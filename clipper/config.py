"""Central settings for the clipper. Values can be overridden in a .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

def _default_jobs_dir() -> Path:
    """Videos are big. Inside a synced folder (OneDrive, Dropbox...) the sync client uploads every render
    and locks files mid-write, so keep jobs in the home folder there instead."""
    synced = any(s in str(ROOT).lower() for s in ("onedrive", "dropbox", "icloud", "google drive", "googledrive"))
    return Path.home() / "clipper-jobs" if synced else ROOT / "jobs"


JOBS_DIR = Path(os.getenv("CLIPPER_JOBS_DIR") or _default_jobs_dir())
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Output canvases per aspect ratio (width, height).
ASPECTS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny | base | small | medium | large-v3
MUSICGEN_MODEL = os.getenv("MUSICGEN_MODEL", "facebook/musicgen-small")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")  # free local model; qwen2.5:3b if VRAM is tight
MUSIC_MAX_SECONDS = 30  # MusicGen is trained on 30 s pieces; longer clips loop the track

HOST = os.getenv("CLIPPER_HOST", "127.0.0.1")
PORT = int(os.getenv("CLIPPER_PORT", "8765"))


def has_claude_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
