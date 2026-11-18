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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from clipper import config, ff, pipeline

for _stream in (sys.stdout, sys.stderr):  # print non-English titles/transcripts without crashing
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(title="Clipper")
FRONTEND = config.ROOT / "frontend" / "out"   # built by `npm run build` in frontend/
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}

# the Next.js dev server (npm run dev) runs on :3000 and calls this API directly
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])

NOT_BUILT = """<!doctype html><meta charset=utf-8><title>Clipper</title>
<body style="background:#000;color:#F4F4F2;font:16px/24px system-ui;display:grid;place-items:center;min-height:100vh;margin:0">
<div style="max-width:560px;padding:24px"><h1 style="font-size:24px">The interface isn't built yet</h1>
<p>Run <code>start.bat</code> again (it builds the page when Node.js is installed), or build it yourself:</p>
<pre style="background:#181818;padding:12px;border-radius:8px">cd frontend
npm ci
npm run build</pre></div>"""


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

if (FRONTEND / "index.html").exists():
    # mounted last so /api and /files win; html=True serves index.html for "/"
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def not_built():
        return NOT_BUILT

if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"Clipper running at {url}")
    try:
        if "--no-browser" not in __import__("sys").argv:
            webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
