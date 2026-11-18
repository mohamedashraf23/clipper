"""Step 4b: AI background music with MusicGen (runs locally on the GPU)."""
import gc
import zlib
from pathlib import Path

import numpy as np

from . import config

_model = None
_processor = None
_device = "cpu"


def _load(log):
    global _model, _processor, _device
    if _model is not None:
        return
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if _device == "cuda" else torch.float32
    log(f"Loading MusicGen ({config.MUSICGEN_MODEL}) on {_device.upper()} — first run downloads ~1 GB")
    _processor = AutoProcessor.from_pretrained(config.MUSICGEN_MODEL)
    _model = MusicgenForConditionalGeneration.from_pretrained(config.MUSICGEN_MODEL, torch_dtype=dtype).to(_device)
    _model.eval()


def generate(prompt: str, seconds: float, out_path: Path, log=print) -> Path:
    import scipy.io.wavfile
    import torch

    _load(log)
    seconds = max(4.0, min(seconds, config.MUSIC_MAX_SECONDS))
    frame_rate = _model.config.audio_encoder.frame_rate  # tokens per second (50 for musicgen)
    inputs = _processor(text=[f"{prompt}, instrumental, no vocals, background music"],
                        padding=True, return_tensors="pt").to(_device)
    with torch.inference_mode():
        audio = _model.generate(**inputs, do_sample=True, guidance_scale=3.0,
                                max_new_tokens=int(seconds * frame_rate) + 8)
    wav = audio[0, 0].float().cpu().numpy()
    if not np.isfinite(wav).all() or np.abs(wav).max() < 1e-4:
        raise RuntimeError("MusicGen produced silent/invalid audio")
    wav = wav / max(1e-6, np.abs(wav).max()) * 0.9
    sr = _model.config.audio_encoder.sampling_rate
    scipy.io.wavfile.write(out_path, sr, wav.astype(np.float32))
    return out_path


AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def library(folder: str | Path) -> list[Path]:
    """Your own tracks (any common audio format), sorted, from a folder and its subfolders."""
    p = Path(folder).expanduser()
    if not p.is_dir():
        return []
    return sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT and f.is_file())


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def pick_track(mood: str, tracks: list[Path], used: dict[Path, int], salt: int = 0) -> Path:
    """Best file-name match for the clip's mood ('calm-lofi-piano.mp3' for 'calm lofi, soft piano'),
    preferring tracks not used yet in this job, so a batch doesn't all share one song."""
    want = _tokens(mood)

    def score(t: Path):
        name = _tokens(t.stem) | _tokens(t.parent.name)  # folder names count too: music/energetic/track1.mp3
        return (len(want & name), -used.get(t, 0), -((zlib.crc32(t.name.encode()) + salt) % 997))
    best = max(tracks, key=score)
    used[best] = used.get(best, 0) + 1
    return best


def unload():
    global _model, _processor
    if _model is None and _processor is None:
        return  # never loaded (music off, or your own folder): nothing to free, and no slow torch import
    _model = _processor = None
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
