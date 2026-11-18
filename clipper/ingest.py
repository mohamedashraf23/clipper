"""Step 1: bring a video URL or local MP4 into the job folder."""
import os
import re
import shutil
from pathlib import Path

from . import ff

URL_RE = re.compile(r"^https?://", re.I)


def is_url(source: str) -> bool:
    return bool(URL_RE.match(source.strip()))


def download(url: str, job_dir: Path, log=print) -> tuple[Path, str]:
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading" and d.get("_percent_str"):
            log(f"downloading {d['_percent_str'].strip()}", transient=True)

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(job_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "ffmpeg_location": ff.ffmpeg_dir(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title") or "video"
    files = sorted(job_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix not in (".part", ".ytdl")]
    if not files:
        raise RuntimeError("Download finished but no video file was found")
    return files[0], title


def ingest(source: str, job_dir: Path, log=print) -> dict:
    """Returns {path, title, duration, width, height, fps, has_audio} and writes audio.wav for Whisper."""
    if is_url(source):
        log("Downloading video")
        path, title = download(source, job_dir, log)
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(source)
        path = job_dir / ("source" + src.suffix.lower())
        if src.resolve() != path.resolve():
            if src.resolve().parent == job_dir.resolve():
                src.replace(path)  # uploaded (or linked) into the job folder: just rename
            else:
                try:
                    os.link(src, path)  # same drive: instant, no extra space
                except OSError:
                    shutil.copyfile(src, path)
        title = src.stem

    meta = ff.probe(path)
    if meta["width"] == 0:
        raise RuntimeError("That file has no video stream")
    if not meta["has_audio"]:
        raise RuntimeError("That video has no audio track, so there is nothing to transcribe")

    log("Extracting audio")
    ff.run(["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", job_dir / "audio.wav"])
    return {"path": str(path), "title": title, **meta}
