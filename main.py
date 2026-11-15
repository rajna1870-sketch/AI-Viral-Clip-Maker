
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import imageio_ffmpeg

app = FastAPI(title="AI Viral Clip Maker")

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
