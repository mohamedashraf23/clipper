"""Thin helpers around the ffmpeg / ffprobe binaries."""
import glob
import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def find_bin(name: str) -> str:
    """Locate ffmpeg/ffprobe: FFMPEG_DIR, PATH, then the winget install folder."""
    exe = name + (".exe" if os.name == "nt" else "")
    custom = os.getenv("FFMPEG_DIR")
    if custom and (Path(custom) / exe).exists():
        return str(Path(custom) / exe)
    found = shutil.which(name)
    if found:
        return found
    local = os.getenv("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", exe),
        os.path.join(local, "Microsoft", "WinGet", "Links", exe),
        r"C:\ffmpeg\bin\\" + exe,
    ]
    for pat in patterns:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    raise FFmpegError(f"{name} not found. Install it (winget install Gyan.FFmpeg) or set FFMPEG_DIR in .env")


def ffmpeg_dir() -> str:
    return str(Path(find_bin("ffmpeg")).parent)


def run(args: list[str], cwd: str | Path | None = None, binary: str = "ffmpeg") -> subprocess.CompletedProcess:
    cmd = [find_bin(binary), *map(str, args)]
    if binary == "ffmpeg":
        cmd[1:1] = ["-hide_banner", "-nostdin", "-y"]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"{binary} failed ({proc.returncode}):\n{tail}")
    return proc


def probe(path: str | Path) -> dict:
    proc = run(["-v", "error", "-print_format", "json", "-show_streams", "-show_format", path], binary="ffprobe")
    data = json.loads(proc.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    fps = 30.0
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    # Phones record rotated video; swap dimensions when rotated 90/270.
    width, height = (int(video["width"]), int(video["height"])) if video else (0, 0)
    rotation = 0
    if video:
        for sd in video.get("side_data_list", []):
            if "rotation" in sd:
                rotation = int(sd["rotation"])
        rotation = int(video.get("tags", {}).get("rotate", rotation))
    if abs(rotation) in (90, 270):
        width, height = height, width
    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
    }


@lru_cache(maxsize=None)
def has_encoder(name: str) -> bool:
    try:
        out = run(["-encoders"]).stdout
    except FFmpegError:
        return False
    return f" {name} " in out


@lru_cache(maxsize=None)
def nvenc_works() -> bool:
    """h264_nvenc can be listed but still fail (old driver); try a one-frame encode."""
    if not has_encoder("h264_nvenc"):
        return False
    try:
        run(["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"])
        return True
    except FFmpegError:
        return False
