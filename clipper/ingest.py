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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "video"
    except yt_dlp.utils.DownloadError as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
        hint = ""
        if re.search(r"private|sign in|login|age", msg, re.I):
            hint = " The video needs a login or is private: download it yourself and upload the file instead."
        elif re.search(r"unsupported url|no video", msg, re.I):
            hint = " That page doesn't contain a video yt-dlp can read."
        elif re.search(r"http error 4\d\d|unable to download", msg, re.I):
            hint = " If downloads from this site worked before, update yt-dlp: .venv\\Scripts\\python -m pip install -U yt-dlp"
        raise RuntimeError(f"Couldn't download that link: {msg[:300]}.{hint}") from None
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
