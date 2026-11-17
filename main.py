import json
import urllib.request
from urllib.parse import urlparse
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import imageio_ffmpeg

app = FastAPI(title="AI Viral Clip Maker")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rajna1870-sketch.github.io"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "AI Viral Clip Maker Server is running"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/make-clip")
async def make_clip(video: UploadFile = File(...), duration: int = Form(30)):
    if duration not in (15, 30, 45, 60):
        raise HTTPException(status_code=400, detail="15, 30, 45 ya 60 seconds chunein")
    allowed = {".mp4", ".mov", ".mkv", ".webm"}
    suffix = Path(video.filename or "").suffix.lower()

    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail="MP4, MOV, MKV ya WEBM video upload karein"
        )

    folder = tempfile.mkdtemp(prefix="clipmaker_")
    input_path = os.path.join(folder, "input" + suffix)
    output_path = os.path.join(folder, "viral_clip.mp4")

    try:
        size = 0
        with open(input_path, "wb") as f:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 200 * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail="Video 200 MB se chhota hona chahiye"
                    )
                f.write(chunk)

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        command = [
            ffmpeg, "-y",
            "-i", input_path,
            "-t", str(duration),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=240
        )

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename="viral_clip.mp4",
            background=BackgroundTask(
                shutil.rmtree, folder, ignore_errors=True
            )
        )

    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except subprocess.TimeoutExpired:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=504,
            detail="Video processing mein samay adhik lag gaya"
        )
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Video process nahi ho paya"
        )
    finally:
        await video.close()

@app.post("/youtube-info")
async def youtube_info(url: str = Form(...)):
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()

    if host not in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtube.com"
    ):
        raise HTTPException(
            status_code=400,
            detail="Sahi YouTube link dalein"
        )

    request_url = (
        "https://www.youtube.com/oembed?url="
        + urllib.parse.quote(url.strip(), safe="")
        + "&format=json"
    )

    try:
        request = urllib.request.Request(
            request_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        return {
            "status": "success",
            "title": data.get("title"),
            "channel": data.get("author_name"),
            "thumbnail": data.get("thumbnail_url")
        }

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Video ki jankari nahi mil saki. Link check karein."
        )

@app.post("/make-best-clip")
async def make_best_clip(video: UploadFile = File(...)):
    from scenedetect import detect, ContentDetector

    suffix = Path(video.filename or "").suffix.lower()

    if suffix not in [".mp4", ".mov", ".mkv", ".webm"]:
        raise HTTPException(
            status_code=400,
            detail="MP4, MOV, MKV ya WEBM video upload karein"
        )

    folder = tempfile.mkdtemp(prefix="best_clip_")
    input_path = os.path.join(folder, "input" + suffix)
    output_path = os.path.join(folder, "best_clip.mp4")

    try:
        with open(input_path, "wb") as f:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        scenes = detect(
    input_path,
    ContentDetector(threshold=15.0, min_scene_len=15),
    show_progress=False
)

        if scenes:
            start, end = max(
                scenes,
                key=lambda scene: scene[1].get_seconds()
                - scene[0].get_seconds()
            )

            start_time = start.get_seconds()
            duration = min(
                end.get_seconds() - start_time,
                60
            )
        else:
            start_time = 0
            duration = 30

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        command = [
            ffmpeg, "-y",
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(duration),
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path
        ]

        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=240
        )

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename="best_clip.mp4",
            background=BackgroundTask(
                shutil.rmtree,
                folder,
                ignore_errors=True
            )
        )

    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Clip nahi ban payi: " + str(e)[:300]
        )
    finally:
        await video.close()



