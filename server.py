"""Local web app for the clipper.  Run:  .venv\\Scripts\\python server.py  then open http://127.0.0.1:8765"""
import json
import shutil
import sys
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clipper import config, ff, pipeline

for _stream in (sys.stdout, sys.stderr):  # print non-English titles/transcripts without crashing
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(title="Clipper")
WEB = config.ROOT / "web"
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    from clipper.picker import ollama_status
    info = {"claude_key": config.has_claude_key(), "claude_model": config.CLAUDE_MODEL,
            "ollama": ollama_status(),
            "whisper_model": config.WHISPER_MODEL, "aspects": list(config.ASPECTS)}
    try:
        ff.find_bin("ffmpeg")
        info["ffmpeg"] = True
        info["nvenc"] = ff.nvenc_works()
    except ff.FFmpegError:
        info["ffmpeg"] = False
        info["nvenc"] = False
    try:
        import torch
        info["cuda"] = torch.cuda.is_available()
        info["gpu"] = torch.cuda.get_device_name(0) if info["cuda"] else None
    except Exception:
        info["cuda"] = False
    return info


@app.post("/api/jobs")
async def create_job(url: str = Form(""), settings: str = Form("{}"), file: UploadFile | None = File(None)):
    try:
        opts = json.loads(settings or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "settings must be JSON")
    opts["n_clips"] = max(1, min(20, int(opts.get("n_clips", 3))))

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED:
            raise HTTPException(400, f"Unsupported file type {ext}")
        job_dir = config.JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = job_dir / f"upload{ext}"
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh, length=8 * 1024 * 1024)
        source = str(dest)
        opts.setdefault("title", Path(file.filename).stem)
    elif url.strip():
        source = url.strip()
        if not source.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "URL must start with http:// or https://")
    else:
        raise HTTPException(400, "Give a video URL or upload a file")

    job = pipeline.start_job(source, opts, job_id=job_id)
    return {"id": job.id}


@app.get("/api/jobs")
def jobs():
    return pipeline.list_jobs()


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    st = pipeline.get_state(job_id)
    if not st:
        raise HTTPException(404, "No such job")
    return st


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    st = pipeline.get_state(job_id)
    if not st:
        raise HTTPException(404, "No such job")
    if st["status"] in ("queued", "running"):
        raise HTTPException(409, "Job is still running")
    shutil.rmtree(config.JOBS_DIR / job_id, ignore_errors=True)
    pipeline._jobs.pop(job_id, None)
    return {"deleted": job_id}


app.mount("/files", StaticFiles(directory=config.JOBS_DIR), name="files")
app.mount("/static", StaticFiles(directory=WEB), name="static")

if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"Clipper running at {url}")
    try:
        if "--no-browser" not in __import__("sys").argv:
            webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
