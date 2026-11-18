"""Step 2: word-level transcript with faster-whisper (GPU when available)."""
import gc
import json
import os
import sys
from pathlib import Path

from . import config


def _expose_cuda_dlls():
    """ctranslate2 on Windows needs cuBLAS/cuDNN DLLs; PyTorch's wheel ships them."""
    if os.name != "nt":
        return
    try:
        import torch  # noqa: F401
        torch_lib = Path(sys.modules["torch"].__file__).parent / "lib"
        if torch_lib.exists():
            os.add_dll_directory(str(torch_lib))
            os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _load_model(name: str, log):
    _expose_cuda_dlls()
    from faster_whisper import WhisperModel

    try:
        import torch
        if torch.cuda.is_available():
            log(f"Loading Whisper '{name}' on GPU")
            return WhisperModel(name, device="cuda", compute_type="float16"), "cuda"
    except Exception as e:  # missing CUDA libs, out of memory, ...
        log(f"GPU Whisper unavailable ({e}); using CPU")
    log(f"Loading Whisper '{name}' on CPU")
    return WhisperModel(name, device="cpu", compute_type="int8"), "cpu"


def transcribe(audio_path: Path, out_path: Path, model_name: str | None = None,
               language: str | None = None, duration: float = 0, log=print) -> dict:
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))

    model, device = _load_model(model_name or config.WHISPER_MODEL, log)
    try:
        result = _run(model, audio_path, language, duration, log)
    except RuntimeError as e:
        if device != "cuda":
            raise
        log(f"GPU transcription failed ({e}); retrying on CPU")
        del model
        _free()
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name or config.WHISPER_MODEL, device="cpu", compute_type="int8")
        result = _run(model, audio_path, language, duration, log)
    finally:
        del model
        _free()

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _load_wav(path) -> "np.ndarray":
    """audio.wav is 16 kHz mono PCM (written by ingest); avoids PyAV version quirks."""
    import numpy as np
    import scipy.io.wavfile

    sr, data = scipy.io.wavfile.read(str(path))
    if sr != 16000:
        raise RuntimeError(f"expected 16 kHz audio, got {sr}")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        return data.astype(np.float32) / 32768.0
    return data.astype(np.float32)


def _run(model, audio_path, language, duration, log):
    segments, info = model.transcribe(
        _load_wav(audio_path),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    out = {"language": info.language, "segments": []}
    for seg in segments:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip(), "prob": round(w.probability, 3)}
            for w in (seg.words or []) if w.word.strip()
        ]
        if not words:
            continue
        out["segments"].append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                                "text": seg.text.strip(), "words": words})
        if duration:
            log(f"Transcribing {min(100, int(seg.end / duration * 100))}%", transient=True, frac=seg.end / duration)
    return out


def _free():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def all_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s["words"]]
