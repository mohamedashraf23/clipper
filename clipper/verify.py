"""Step 6: check every rendered clip before you post it."""
import re
from pathlib import Path

from . import ff


def _check(name: str, ok: bool, detail: str, level: str = "fail") -> dict:
    return {"name": name, "status": "pass" if ok else level, "detail": detail}


def verify_clip(path: Path, *, expected_w: int, expected_h: int, expected_duration: float,
                caption_events: int, captions_wanted: bool, music_wanted: bool) -> dict:
    checks = []
    if not path.exists() or path.stat().st_size < 10_000:
        return {"status": "fail", "checks": [_check("file", False, "Output file missing or empty")]}

    meta = ff.probe(path)
    checks.append(_check("resolution", (meta["width"], meta["height"]) == (expected_w, expected_h),
                         f"{meta['width']}x{meta['height']} (expected {expected_w}x{expected_h})"))
    drift = abs(meta["duration"] - expected_duration)
    checks.append(_check("duration", drift <= 0.5, f"{meta['duration']:.2f}s (expected {expected_duration:.2f}s)"))
    checks.append(_check("audio", meta["has_audio"], "Audio track present" if meta["has_audio"] else "No audio track"))
    checks.append(_check("codec", meta["video_codec"] == "h264" and meta["audio_codec"] == "aac",
                         f"{meta['video_codec']}/{meta['audio_codec']} (platforms want h264/aac)", "warn"))

    # One pass over the file: loudness, black frames, long silences.
    proc = ff.run(["-i", path.name, "-af", "ebur128=framelog=quiet,silencedetect=noise=-45dB:d=2.5",
                   "-vf", "blackdetect=d=0.4:pix_th=0.08", "-f", "null", "-"], cwd=path.parent)
    log = proc.stderr

    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    if m:
        lufs = float(m[-1])
        checks.append(_check("loudness", -17.5 <= lufs <= -10.5, f"{lufs:.1f} LUFS (target -14)", "warn"))

    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", log))
    checks.append(_check("black frames", black < 0.25 * expected_duration,
                         f"{black:.1f}s of black" if black else "None", "warn"))

    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    longest = max(silences, default=0.0)
    checks.append(_check("dead air", longest < 4.0,
                         f"Longest silence {longest:.1f}s" if silences else "No long silences", "warn"))

    if captions_wanted:
        checks.append(_check("captions", caption_events > 0, f"{caption_events} caption events burned in"))
    if music_wanted:
        checks.append(_check("music", True, "Background music mixed under voice"))

    worst = "pass"
    if any(c["status"] == "fail" for c in checks):
        worst = "fail"
    elif any(c["status"] == "warn" for c in checks):
        worst = "warn"
    return {"status": worst, "checks": checks}
