
import os
import re
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import imageio_ffmpeg

app = FastAPI(title="AI Viral Clip Maker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rajna1870-sketch.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

JOB_ROOT = "/tmp/viral_clip_jobs"
os.makedirs(JOB_ROOT, exist_ok=True)

MAX_SIZE = 200 * 1024 * 1024
MAX_CLIPS = 10


@app.get("/")
def home():
    return {"status": "success", "message": "AI Viral Clip Maker Running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def run_command(command, timeout=600):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1500:])
    return result


def clean_old_jobs():
    now = datetime.now().timestamp()
    for name in os.listdir(JOB_ROOT):
        path = os.path.join(JOB_ROOT, name)
        try:
            if os.path.isdir(path):
                if now - os.path.getmtime(path) > 3600:
                    shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def make_title(text, number):
    words = re.findall(r"[\w\u0900-\u097F]+", text)
    title = " ".join(words[:7]).strip()
    if not title:
        title = "AI Viral Short"
    return f"{number}. {title}"


def seconds_to_srt(seconds):
    milliseconds = int(seconds * 1000)
    hours = milliseconds // 3600000
    milliseconds %= 3600000
    minutes = milliseconds // 60000
    milliseconds %= 60000
    secs = milliseconds // 1000
    milliseconds %= 1000
    return (
        f"{hours:02}:{minutes:02}:{secs:02},"
        f"{milliseconds:03}"
    )


def create_srt(segments, start_time, end_time, path):
    lines = []
    index = 1

    for segment in segments:
        start = max(segment.start, start_time)
        end = min(segment.end, end_time)

        if end <= start:
            continue

        text = segment.text.strip()
        if not text:
            continue

        lines.append(str(index))
        lines.append(
            seconds_to_srt(start - start_time)
            + " --> "
            + seconds_to_srt(end - start_time)
        )
        lines.append(text)
        lines.append("")
        index += 1

    with open(path, "w", encoding="utf-8-sig") as file:
        file.write("\n".join(lines))


@app.post("/make-best-clips")
async def make_best_clips(video: UploadFile = File(...)):
    suffix = Path(video.filename or "").suffix.lower()

    if suffix not in [".mp4", ".mov", ".mkv", ".webm"]:
        raise HTTPException(
            status_code=400,
            detail="MP4, MOV, MKV ya WEBM video upload karein"
        )

    clean_old_jobs()

    job_id = uuid4().hex
    folder = os.path.join(JOB_ROOT, job_id)
    os.makedirs(folder)

    input_path = os.path.join(folder, "input" + suffix)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    try:
        size = 0

        with open(input_path, "wb") as output:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break

                size += len(chunk)

                if size > MAX_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Video 200 MB se chhoti honi chahiye"
                    )

                output.write(chunk)

        if size == 0:
            raise HTTPException(
                status_code=400,
                detail="Khali video upload hui hai"
            )

        # Audio transcription
        from faster_whisper import WhisperModel

        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8"
        )

        transcription, info = model.transcribe(
            input_path,
            beam_size=1,
            vad_filter=True
        )

        transcript = list(transcription)

        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="Video mein awaaz ya dialogue nahi mila"
            )

        # Scene detection
        from scenedetect import detect, ContentDetector

        scenes = detect(
            input_path,
            ContentDetector(
                threshold=18.0,
                min_scene_len=15
            ),
            show_progress=False
        )

        # Candidate scenes
        candidates = []

        for start, end in scenes:
            scene_start = start.get_seconds()
            scene_end = end.get_seconds()
            duration = scene_end - scene_start

            if duration < 10:
                continue

            if duration > 45:
                scene_end = scene_start + 45
                duration = 45

            words = []
            for segment in transcript:
                overlap = (
                    segment.start < scene_end
                    and segment.end > scene_start
                )
                if overlap:
                    words.extend(segment.text.split())

            if len(words) < 5:
                continue

            score = len(words) / max(duration, 1)

            candidates.append({
                "start": scene_start,
                "end": scene_end,
                "duration": duration,
                "score": score,
                "text": " ".join(words)
            })

        # If scene detection found no usable candidates,
        # divide the video into 30-second speech sections.
        if not candidates:
            video_end = max(
                (segment.end for segment in transcript),
                default=0
            )

            start = 0
            while start < video_end:
                end = min(start + 30, video_end)

                words = []
                for segment in transcript:
                    if segment.start < end and segment.end > start:
                        words.extend(segment.text.split())

                if len(words) >= 5:
                    candidates.append({
                        "start": start,
                        "end": end,
                        "duration": end - start,
                        "score": len(words) / max(end - start, 1),
                        "text": " ".join(words)
                    })

                start += 20

        if not candidates:
            raise HTTPException(
                status_code=400,
                detail="Koi upyogi dialogue wala scene nahi mila"
            )

        # Rank candidates and remove overlapping clips
        candidates.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        selected = []

        for candidate in candidates:
            overlaps = False

            for existing in selected:
                if (
                    candidate["start"] < existing["end"]
                    and candidate["end"] > existing["start"]
                ):
                    overlaps = True
                    break

            if not overlaps:
                selected.append(candidate)

            if len(selected) >= MAX_CLIPS:
                break

        clips = []

        for number, candidate in enumerate(selected, start=1):
            start = candidate["start"]
            end = candidate["end"]
            duration = end - start

            clip_name = f"viral_clip_{number}.mp4"
            clip_path = os.path.join(folder, clip_name)

            srt_path = os.path.join(
                folder,
                f"viral_clip_{number}.srt"
            )

            create_srt(
                transcript,
                start,
                end,
                srt_path
            )

            command = [
                ffmpeg, "-y",
                "-ss", str(start),
                "-i", input_path,
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-vf",
                "scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                clip_path
            ]

            run_command(command, timeout=300)

            clips.append({
                "title": make_title(candidate["text"], number),
                "filename": clip_name,
                "duration": round(duration, 1),
                "download_url": (
                    f"/download/{job_id}/{clip_name}"
                ),
                "subtitle_file": f"viral_clip_{number}.srt"
            })

        return {
            "status": "success",
            "job_id": job_id,
            "total_clips": len(clips),
            "clips": clips,
            "message": "Aapki clips taiyar hain"
        }

    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    except subprocess.TimeoutExpired:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=504,
            detail="Video processing mein bahut samay laga"
        )

    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Video process nahi hui: " + str(error)[:500]
        )

    finally:
        await video.close()


@app.get("/download/{job_id}/{filename}")
def download_clip(job_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not re.fullmatch(r"viral_clip_[0-9]+\.mp4", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(JOB_ROOT, job_id, filename)

    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail="Clip nahi mili. Dobara video process karein."
        )

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename
    )


@app.get("/download-subtitle/{job_id}/{filename}")
def download_subtitle(job_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not re.fullmatch(r"viral_clip_[0-9]+\.srt", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(JOB_ROOT, job_id, filename)

    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail="Subtitle file nahi mili"
        )

    return FileResponse(
        path,
        media_type="application/x-subrip",
        filename=filename
    )
