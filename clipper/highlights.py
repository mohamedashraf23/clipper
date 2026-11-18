"""Gameplay mode: find highlight moments without relying on speech.

Signals, per half second of the video:
- loudness of the game audio (fights, chases, explosions are loud)
- sudden audio bursts (gunshots, crashes, explosions)
- on-screen motion (frame-to-frame change on a tiny grayscale copy)
- dialogue, if any (cutscenes, a streamer's voice)
Dark or frozen stretches (loading and pause screens) are pushed down.
"""
import json
import re
import subprocess

import numpy as np

from . import config, ff
from .transcribe import all_words

STEP = 0.5          # seconds per analysis bin
MOTION_FPS = 4      # frames sampled per second for motion
SMALL_W, SMALL_H = 64, 36


def _audio_curves(wav_path, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    from scipy.io import wavfile

    sr, data = wavfile.read(str(wav_path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    x = data.astype(np.float32) / 32768.0
    hop = int(sr * STEP)
    frame = int(sr * 0.05)  # 50 ms frames to catch bursts
    n_frames = len(x) // frame
    rms50 = np.sqrt(np.mean(x[: n_frames * frame].reshape(n_frames, frame) ** 2, axis=1) + 1e-10)
    db50 = 20 * np.log10(rms50)
    per_bin = hop // frame
    loud = np.full(n_bins, -90.0, np.float32)
    burst = np.zeros(n_bins, np.float32)
    for b in range(n_bins):
        seg = db50[b * per_bin:(b + 1) * per_bin]
        if len(seg) == 0:
            continue
        loud[b] = 10 * np.log10(np.mean(10 ** (seg / 10)))
        # a burst = a 50 ms frame far above the previous 2 s
        prev = db50[max(0, b * per_bin - 40):b * per_bin]
        base = np.median(prev) if len(prev) else seg.min()
        burst[b] = max(0.0, float(seg.max() - base))
    return loud, burst


def _video_curves(video_path, n_bins: int, log=print) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[float]]:
    """Motion, brightness and letterboxing per bin, plus scene-cut times."""
    cmd = [ff.find_bin("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video_path),
           "-an", "-vf", f"fps={MOTION_FPS},scale={SMALL_W}:{SMALL_H}:flags=area,format=gray",
           "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = SMALL_W * SMALL_H
    diffs, lum, boxed = [], [], []
    prev = None
    bar = max(2, SMALL_H // 9)  # ~11% of the height: where cinematic black bars sit
    while True:
        buf = proc.stdout.read(size * 64)
        if not buf:
            break
        frames = np.frombuffer(buf[: len(buf) // size * size], np.uint8).reshape(-1, SMALL_H, SMALL_W).astype(np.float32)
        for f in frames:
            lum.append(f.mean() / 255.0)
            # letterbox: near-black strips top and bottom with a lit picture between = cutscene framing
            edges = max(f[:bar].mean(), f[-bar:].mean()) / 255.0
            boxed.append(1.0 if edges < 0.035 and f[bar:-bar].mean() / 255.0 > 0.10 else 0.0)
            diffs.append(0.0 if prev is None else float(np.abs(f - prev).mean() / 255.0))
            prev = f
        if len(lum) % (MOTION_FPS * 120) < 64:
            log(f"Scanning motion {len(lum) / MOTION_FPS / 60:.0f} min", transient=True)
    proc.wait()
    diffs, lum, boxed = np.array(diffs, np.float32), np.array(lum, np.float32), np.array(boxed, np.float32)

    per_bin = int(MOTION_FPS * STEP)
    motion = np.zeros(n_bins, np.float32)
    bright = np.zeros(n_bins, np.float32)
    letterbox = np.zeros(n_bins, np.float32)
    for b in range(n_bins):
        seg = slice(b * per_bin, (b + 1) * per_bin)
        if len(diffs[seg]):
            motion[b] = float(np.median(diffs[seg]))
            bright[b] = float(lum[seg].mean())
            letterbox[b] = float(boxed[seg].mean())

    # scene cuts: a single frame change far above its neighbourhood
    cuts = []
    for i in range(1, len(diffs)):
        local = np.median(diffs[max(0, i - 8):i + 8]) + 1e-3
        if diffs[i] > 0.12 and diffs[i] > 4 * local:
            t = i / MOTION_FPS
            if not cuts or t - cuts[-1] > 1.0:
                cuts.append(float(t))
    return motion, bright, letterbox, cuts


def _z(a: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(a, 5), np.percentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-6), 0, 1.5)


def _smooth(a: np.ndarray, seconds: float) -> np.ndarray:
    k = max(1, int(seconds / STEP))
    return np.convolve(a, np.ones(k) / k, mode="same")


ANALYSIS_VERSION = 2  # bump when scoring changes so cached highlights.json files are recomputed


def analyze(video_path, wav_path, duration: float, transcript: dict | None, cache=None, log=print) -> dict:
    if cache and cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("v") == ANALYSIS_VERSION:
            return cached
    n_bins = int(np.ceil(duration / STEP))
    log("Measuring game audio")
    loud, burst = _audio_curves(wav_path, n_bins)
    log("Scanning motion and scene cuts")
    motion, bright, letterbox, cuts = _video_curves(video_path, n_bins, log)

    speech = np.zeros(n_bins, np.float32)
    for w in all_words(transcript or {"segments": []}):
        b = int(w["start"] / STEP)
        if 0 <= b < n_bins:
            speech[b] += 1

    loud_z, burst_z, motion_z = _z(_smooth(loud, 3)), _z(_smooth(burst, 2)), _z(_smooth(motion, 3))
    talking = _smooth(speech, 3) > 0.15  # someone is speaking around this moment

    # Shouting is loud too: while characters talk, loudness counts for much less than action does.
    score = (np.where(talking, 0.15, 0.35) * loud_z
             + np.where(talking, 0.30, 0.40) * burst_z
             + 0.45 * motion_z)

    # Cutscenes: cinematic black bars, or steady dialogue with a calm camera. Gameplay is what people clip.
    boxed = _smooth(letterbox, 2) > 0.6
    calm_dialogue = (_smooth(speech, 8) > 0.5) & (_smooth(motion_z, 8) < 0.45)
    cutscene = boxed | calm_dialogue
    score = np.where(cutscene, score * 0.4, score)

    dead = (_smooth(bright, 2) < 0.06) | (_smooth(motion, 3) < np.percentile(motion, 8))
    score = np.where(dead, score * 0.25, score)
    out = {"v": ANALYSIS_VERSION, "step": STEP, "score": score.round(4).tolist(), "loud": loud_z.round(3).tolist(),
           "burst": burst_z.round(3).tolist(), "motion": motion_z.round(3).tolist(),
           "speech": speech.tolist(), "cutscene": cutscene.astype(np.int8).tolist(), "cuts": cuts}
    log(f"Gameplay scan: {cutscene.mean() * 100:.0f}% of the video looks like cutscenes, {len(cuts)} scene cuts")
    if cache:
        cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def _snap(t: float, cuts: list[float], window: float) -> float:
    near = [c for c in cuts if abs(c - t) <= window]
    return min(near, key=lambda c: abs(c - t)) if near else t


def _word_gap(t: float, words: list[dict], direction: int) -> float:
    """Move t out of the middle of a spoken word/sentence."""
    for w in words:
        if w["start"] < t < w["end"]:
            return w["end"] + 0.1 if direction > 0 else w["start"] - 0.1
    return t


def pick(analysis: dict, n: int, min_len: float, max_len: float, duration: float, transcript: dict | None) -> list[dict]:
    score = np.array(analysis["score"], np.float32)
    cuts, step = analysis["cuts"], analysis["step"]
    words = all_words(transcript or {"segments": []})
    target = (min_len + max_len) / 2
    win = max(1, int(target / step))
    if len(score) <= win:
        return [{"start": 0.0, "end": round(duration, 2), "peak": duration / 2, "strength": 1.0}]

    # rank windows by average intensity plus their single best moment
    csum = np.concatenate([[0], np.cumsum(score)])
    avg = (csum[win:] - csum[:-win]) / win
    peak_in = np.array([score[i:i + win].max() for i in range(len(avg))])
    rank = 0.65 * avg + 0.35 * peak_in

    picks = []
    order = np.argsort(-rank)
    for i in order:
        s, e = i * step, i * step + target
        if any(s < p["end"] + 3 and e > p["start"] - 3 for p in picks):
            continue
        seg = score[i:i + win]
        peak_t = (i + int(np.argmax(seg))) * step
        # build up before the peak, payoff after it
        s = max(0.0, peak_t - target * 0.55)
        e = min(duration, s + target)
        s = _word_gap(_snap(s, cuts, 3.0), words, -1)
        e = _word_gap(_snap(e, cuts, 3.0), words, +1)
        if e - s < min_len:
            e = min(duration, s + min_len)
        if e - s > max_len:
            e = s + max_len
        s, e = max(0.0, s), min(duration, e)
        if any(s < p["end"] and e > p["start"] for p in picks):
            continue
        picks.append({"start": round(float(s), 2), "end": round(float(e), 2), "peak": round(float(peak_t - s), 2),
                      "strength": float(rank[i])})
        if len(picks) >= n:
            break
    top = max((p["strength"] for p in picks), default=1) or 1
    for p in picks:
        p["score"] = int(round(40 + 60 * p["strength"] / top))
    return picks


def _signals(analysis: dict, p: dict) -> dict:
    step = analysis["step"]
    a, b = int(p["start"] / step), int(p["end"] / step)
    seg = lambda k: np.array(analysis[k][a:b] or [0], np.float32)
    return {"loud": float(seg("loud").mean()), "burst": float(seg("burst").max()),
            "motion": float(seg("motion").mean()), "speech": float(seg("speech").sum())}


TEMPLATES = {
    "burst": ("Things get loud", "Wait for it", "intense cinematic action, heavy drums, distorted bass, high energy"),
    "motion": ("Full speed moment", "This went sideways fast", "fast driving electronic beat, aggressive synths, energetic"),
    "loud": ("All out action", "Things escalate fast", "dark trap beat, heavy 808, tense and energetic"),
    "speech": ("Story moment", "This scene changes everything", "moody cinematic ambient, low strings, suspenseful"),
}


def describe(picks: list[dict], analysis: dict, transcript: dict | None, title: str, log=print) -> list[dict]:
    """Titles, hooks and music moods. Uses the local LLM when available, templates otherwise."""
    words = all_words(transcript or {"segments": []})
    for p in picks:
        sig = _signals(analysis, p)
        p["_sig"] = sig
        p["_lines"] = " ".join(w["word"] for w in words if p["start"] <= w["start"] < p["end"]).strip()[:600]
        kind = max(("burst", sig["burst"]), ("motion", sig["motion"] * 1.1), ("loud", sig["loud"] * 0.9),
                   ("speech", min(1.0, sig["speech"] / 40)), key=lambda kv: kv[1])[0]
        t, h, m = TEMPLATES[kind]
        p.update(title=t, hook=h, music_mood=m, reason=f"Strongest signal: {kind}; peak at {p['peak']:.0f}s into the clip")

    try:
        from .picker import _ollama, ollama_status
        st = ollama_status()
        if not (st["running"] and st["installed"]):
            raise RuntimeError("local AI not available")
        log(f"Local AI ({config.OLLAMA_MODEL}) writing hooks for {len(picks)} gameplay clips")
        brief = [{"id": i, "seconds": round(p["end"] - p["start"]),
                  "peak_at_second": p["peak"],
                  "audio_intensity": round(p["_sig"]["loud"], 2), "sudden_loud_sounds": round(p["_sig"]["burst"], 2),
                  "on_screen_motion": round(p["_sig"]["motion"], 2), "dialogue": p["_lines"] or "(no dialogue)"}
                 for i, p in enumerate(picks)]
        schema = {"type": "object", "properties": {"clips": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "title": {"type": "string"}, "hook": {"type": "string"},
            "music_mood": {"type": "string"}}, "required": ["id", "title", "hook", "music_mood"]}}}, "required": ["clips"]}
        prompt = (
            f"Video: {title}\nThese are highlight clips cut from gameplay footage. Signals are 0 to 1.5 "
            "(higher = more intense). Dialogue is what characters say in the clip, it may be empty.\n"
            f"{json.dumps(brief, ensure_ascii=False)}\n\n"
            "For each clip write, in English:\n- title: 3 to 6 words\n"
            "- hook: on screen text for the first seconds, max 7 words, makes a gamer keep watching, "
            "no hashtags, no emojis\n"
            "You cannot see the video. Sudden loud sounds can be a crash, an engine, a gunshot or a slammed door, "
            "so NEVER name a specific event (explosion, shootout, chase, crash, kill) unless the dialogue mentions it. "
            "Without dialogue, write curiosity hooks that stay true whatever happens (for example: 'Wait for the ending', "
            "'This went sideways fast', 'Nobody expected this').\n"
            "- music_mood: 6 to 12 words describing an instrumental background track (genre, instruments, energy). "
            "Never name artists.\nReply with JSON only."
        )
        res = _ollama("/api/chat", {"model": config.OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}],
                                    "format": schema, "stream": False, "options": {"temperature": 0.5, "num_ctx": 8192},
                                    "keep_alive": 0})
        got = {c["id"]: c for c in json.loads(res["message"]["content"]).get("clips", [])}
        for i, p in enumerate(picks):
            c = got.get(i)
            if not c:
                continue
            hook = re.sub(r"[#\U0001F300-\U0001FAFF]", "", c.get("hook", "")).strip()
            if hook and hook.isascii():
                p["hook"] = " ".join(hook.split()[:8])
            if c.get("title", "").isascii() and c["title"].strip():
                p["title"] = c["title"].strip()
            mood = c.get("music_mood", "")
            if mood.isascii() and len(mood.split()) >= 3:
                p["music_mood"] = mood
    except Exception as e:
        log(f"Using template hooks for gameplay ({type(e).__name__}: {e})")
    for p in picks:
        p.pop("_sig", None)
        p.pop("_lines", None)
        p.pop("strength", None)
    return picks
