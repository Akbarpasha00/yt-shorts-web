# YouTube → Shorts (web app)

Paste a YouTube link, get 9:16 clips. Clip length is chosen from the video length
(≤1 min: 1 clip, ≤5 min: ~30 s, ≤15 min: ~45 s, ≤60 min: ~60 s, longer: ~90 s) and the
video is split into equal parts so there is no tiny last clip.

## Run locally
    pip install -r requirements.txt     # also install ffmpeg
    uvicorn app:app --reload
    # open http://localhost:8000

## Run with Docker
    docker build -t yt-shorts .
    docker run -p 8000:8000 yt-shorts

## Deploy online
Any host that runs Docker works (Render, Railway, Fly.io, a VPS).
Pick a plan with at least 1 GB RAM and a few GB of disk; video conversion is CPU-heavy.

Environment variables:
- MAX_MINUTES (default 60)  longest video accepted
- KEEP_HOURS  (default 2)   how long results are kept before auto-delete
- MAX_PARALLEL (default 1)  simultaneous conversions

## Notes
- YouTube often blocks downloads from cloud/datacenter IPs. If that happens, run it on a
  home server/VPS with a residential connection, or give yt-dlp a cookies file.
- Keep yt-dlp updated (`pip install -U yt-dlp`); YouTube changes break old versions.
- Downloading may violate YouTube's Terms, and you need rights to the content.
  Use it only for your own videos or with permission. Add login/rate limits before
  making it public.
