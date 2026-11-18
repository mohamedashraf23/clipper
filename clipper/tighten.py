"""Jump cuts for talking clips: shrink long pauses and drop filler words, using the word timestamps.

Everything here works in seconds relative to the clip start, so the renderer can trim the already
seeked input and captions can be shifted onto the shortened timeline.
"""
import re

MAX_GAP = 0.45   # pauses longer than this get shortened
KEEP_GAP = 0.20  # ...down to this much breathing room
MIN_PIECE = 0.12  # never keep slivers shorter than this
MAX_CUT = 2.5     # gaps longer than this are probably laughter, a reaction or music: keep them
FILLERS = {
    # English
    "um", "umm", "uh", "uhh", "uhm", "erm", "er", "ah", "ahh", "hmm", "hm", "mm", "mmm",
    # Arabic hesitations Whisper writes out
    "اه", "آه", "امم", "إمم", "ممم", "اممم", "ايه ايه",
}


def _norm(word: str) -> str:
    return re.sub(r"[^\w؀-ۿ]+", "", word.lower())


def keep_segments(words: list[dict], clip_start: float, clip_end: float,
                  drop_fillers: bool = True) -> list[tuple[float, float]]:
    """Ranges (relative to clip_start) to keep, in order."""
    dur = clip_end - clip_start
    ws = [{"s": max(0.0, w["start"] - clip_start), "e": min(dur, w["end"] - clip_start), "w": w["word"]}
          for w in words if w["end"] > clip_start and w["start"] < clip_end]
    if not ws:
        return [(0.0, dur)]
    if drop_fillers:
        ws = [w for w in ws if _norm(w["w"]) not in FILLERS] or ws

    pad = KEEP_GAP / 2
    keeps = []
    cur_s = max(0.0, ws[0]["s"] - pad) if MAX_GAP < ws[0]["s"] <= MAX_CUT else 0.0
    cur_e = ws[0]["e"]
    for w in ws[1:]:
        gap = w["s"] - cur_e
        if MAX_GAP < gap <= MAX_CUT:  # a pause (or a removed filler): cut it down
            keeps.append((cur_s, min(dur, cur_e + pad)))
            cur_s = max(0.0, w["s"] - pad)
        cur_e = max(cur_e, w["e"])
    keeps.append((cur_s, min(dur, cur_e + 0.35)))  # let the last word ring out

    merged = []
    for s, e in keeps:
        if e - s < MIN_PIECE:
            continue
        if merged and s - merged[-1][1] < 0.05:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(round(s, 3), round(e, 3)) for s, e in merged] or [(0.0, dur)]


def total(segments: list[tuple[float, float]]) -> float:
    return round(sum(e - s for s, e in segments), 3)


def remap_words(words: list[dict], clip_start: float, segments: list[tuple[float, float]]) -> list[dict]:
    """Words moved onto the shortened timeline (absolute times, so captions can keep using clip_start).
    Words that fall in a removed stretch are dropped."""
    out = []
    for w in words:
        rs, re_ = w["start"] - clip_start, w["end"] - clip_start
        offset = 0.0
        for s, e in segments:
            if s - 0.05 <= rs < e:
                ns = offset + max(0.0, rs - s)
                ne = offset + min(e, re_) - s
                out.append({**w, "start": clip_start + ns, "end": clip_start + max(ns + 0.05, ne)})
                break
            offset += e - s
    return out
