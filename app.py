"""YouTube -> 9:16 Shorts web service (FastAPI + yt-dlp + ffmpeg)."""
import os, re, shutil, subprocess, threading, time, uuid, zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
WORK = Path(os.getenv("WORK_DIR", BASE / "jobs"))
MAX_MINUTES = int(os.getenv("MAX_MINUTES", "60"))   # reject longer videos
KEEP_HOURS = float(os.getenv("KEEP_HOURS", "2"))    # auto-delete old jobs
W, H = 1080, 1920
YT_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)

WORK.mkdir(parents=True, exist_ok=True)
jobs: dict = {}
app = FastAPI(title="YT Shorts Maker")


class JobIn(BaseModel):
    url: str
    mode: str = "blur"          # blur | crop
    length: float | None = None  # optional forced seconds per short


# ---------- helpers ----------
def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        tail = (r.stderr.strip().splitlines() or ["command failed"])[-1]
        raise RuntimeError(tail)
    return r.stdout.strip()


def auto_length(total):
    if total <= 60: return total
    if total <= 300: return 30
    if total <= 900: return 45
    if total <= 3600: return 60
    return 90


def plan(total, target, max_len=180):
    n = max(1, round(total / target))
    while total / n > max_len:
        n += 1
    return n, total / n


def vfilter(mode):
    if mode == "crop":
        return ["-vf", f"crop=ih*9/16:ih,scale={W}:{H}"]
    return ["-filter_complex",
            f"split=2[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},boxblur=25:5[b];[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[f];"
            f"[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1"]


def process(job_id, url, mode, length):
    job = jobs[job_id]
    d = WORK / job_id
    try:
        d.mkdir(parents=True, exist_ok=True)
        job["status"] = "checking"
        dur = int(float(sh(["yt-dlp", "--no-playlist", "--print", "duration", url])))
        if dur > MAX_MINUTES * 60:
            raise RuntimeError(f"Video is longer than {MAX_MINUTES} minutes.")

        job["status"] = "downloading"
        src = d / "source.mp4"
        sh(["yt-dlp", "--no-playlist", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "--merge-output-format", "mp4", "-o", str(src), url])

        total = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(src)]))
        n, seg = plan(total, length or auto_length(total))
        job.update(status="converting", total=n, seg_seconds=round(seg, 1), done=0)

        for i in range(n):
            out = d / f"short_{i+1:02d}.mp4"
            sh(["ffmpeg", "-y", "-ss", f"{i*seg:.3f}", "-t", f"{seg:.3f}", "-i", str(src),
                *vfilter(mode), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", str(out)])
            job["done"] = i + 1
            job["files"].append(out.name)

        src.unlink(missing_ok=True)
        with zipfile.ZipFile(d / "all_shorts.zip", "w") as z:
            for f in job["files"]:
                z.write(d / f, f)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def cleaner():
    while True:
        time.sleep(600)
        cutoff = time.time() - KEEP_HOURS * 3600
        for p in WORK.iterdir():
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                jobs.pop(p.name, None)


threading.Thread(target=cleaner, daemon=True).start()
# one conversion at a time keeps small servers from falling over
slot = threading.Semaphore(int(os.getenv("MAX_PARALLEL", "1")))


def guarded(*a):
    jobs[a[0]]["status"] = "queued"
    with slot:
        process(*a)


# ---------- API ----------
@app.post("/api/jobs")
def create(body: JobIn):
    if not YT_RE.match(body.url.strip()):
        raise HTTPException(400, "Please enter a valid YouTube link.")
    if body.mode not in ("blur", "crop"):
        raise HTTPException(400, "Invalid mode.")
    if body.length is not None and not (5 <= body.length <= 180):
        raise HTTPException(400, "Length must be 5-180 seconds.")
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"id": job_id, "status": "queued", "files": [], "done": 0, "total": 0}
    threading.Thread(target=guarded, args=(job_id, body.url.strip(), body.mode, body.length),
                     daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found (it may have expired).")
    return jobs[job_id]


@app.get("/files/{job_id}/{name}")
def get_file(job_id: str, name: str):
    p = (WORK / job_id / name).resolve()
    if WORK.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, filename=name)


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
