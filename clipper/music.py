"""Step 4b: AI background music with MusicGen (runs locally on the GPU)."""
import gc
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


def unload():
    global _model, _processor
    _model = _processor = None
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
