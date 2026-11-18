"""Step 3a: choose the best moments. Claude reads the transcript; a rule-based picker is the fallback."""
import json
import re
import urllib.request

from pydantic import BaseModel, Field

from . import config
from .transcribe import all_words

SYSTEM = """You are a senior short-form video editor. You pick the moments of a long video that will \
perform best as standalone vertical clips (TikTok, Reels, Shorts).

A great clip:
- opens with a hook in its first 3 seconds (a bold claim, a question, a surprising fact, tension)
- is self-contained: a viewer with no context understands it
- has a payoff or a clean ending; it never stops mid-sentence
- starts at the beginning of a sentence and ends at the end of one

For every clip also write:
- title: 3-7 words, for the file name and the editor
- hook: on-screen hook text shown for the first seconds, max 8 words, punchy, no hashtags, no emojis
- music_mood: a short text-to-music prompt for an instrumental background bed that fits the clip's \
energy, e.g. "calm lofi hip hop, soft piano, warm vinyl" or "driving electronic beat, energetic, modern". \
Never name artists or songs.
- score: 1-100, your estimate of how well it will perform
- reason: one sentence on why it works"""


class ClipPick(BaseModel):
    start: float = Field(description="Clip start time in seconds, taken from the transcript timestamps")
    end: float = Field(description="Clip end time in seconds")
    title: str
    hook: str
    music_mood: str
    score: int
    reason: str


class ClipPlan(BaseModel):
    clips: list[ClipPick]


def _transcript_lines(transcript: dict) -> str:
    return "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in transcript["segments"])


def pick_with_claude(transcript: dict, n: int, min_len: float, max_len: float, title: str, log=print) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        f"Video title: {title}\n\n"
        f"Transcript (each line is [start-end seconds] text):\n<transcript>\n{_transcript_lines(transcript)}\n</transcript>\n\n"
        f"Pick the {n} best clips. Each clip must be between {min_len:.0f} and {max_len:.0f} seconds long. "
        "Clips must not overlap. Use the transcript timestamps for start and end. "
        "Order them from best to worst."
    )
    log(f"Asking Claude ({config.CLAUDE_MODEL}) to pick {n} clips")
    response = client.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ClipPlan,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"Claude returned no clip plan (stop_reason={response.stop_reason})")
    return [c.model_dump() for c in response.parsed_output.clips]


def pick_with_rules(transcript: dict, n: int, min_len: float, max_len: float) -> list[dict]:
    """Slide over sentence-aligned windows and favour dense, punchy speech."""
    segs = transcript["segments"]
    target = (min_len + max_len) / 2
    candidates = []
    for i, first in enumerate(segs):
        text, words = [], 0
        for j in range(i, len(segs)):
            text.append(segs[j]["text"])
            words += len(segs[j]["words"])
            length = segs[j]["end"] - first["start"]
            if length > max_len:
                break
            if length >= min_len:
                joined = " ".join(text)
                wps = words / length
                punch = joined.count("?") * 0.6 + joined.count("!") * 0.4
                ends_clean = 1.0 if re.search(r"[.!?]$", segs[j]["text"]) else 0.0
                closeness = 1 - abs(length - target) / max_len
                score = wps + punch + ends_clean + closeness
                candidates.append((score, first["start"], segs[j]["end"], joined))
    candidates.sort(reverse=True)
    picks = []
    for score, start, end, text in candidates:
        if any(start < p["end"] and end > p["start"] for p in picks):
            continue
        first_sentence = re.split(r"(?<=[.!?])\s", text)[0]
        hook = " ".join(first_sentence.split()[:8])
        picks.append({
            "start": start, "end": end, "title": " ".join(text.split()[:6]), "hook": hook,
            "music_mood": "modern upbeat background music, light percussion, warm synths",
            "score": 50, "reason": "Dense speech, clean sentence boundaries",
        })
        if len(picks) >= n:
            break
    return picks


def _snap(picks: list[dict], transcript: dict, duration: float, min_len: float, max_len: float) -> list[dict]:
    """Snap to real word boundaries, enforce length, remove overlaps."""
    words = all_words(transcript)
    if not words:
        return []
    out = []
    for p in picks:
        start = max(0.0, float(p["start"]))
        end = min(duration, float(p["end"]))
        # first word that starts at/after start (with a little slack), last word ending by end
        sw = next((w for w in words if w["start"] >= start - 0.4), None)
        ew = next((w for w in reversed(words) if w["end"] <= end + 0.4), None)
        if not sw or not ew or ew["end"] <= sw["start"]:
            continue
        s = max(0.0, sw["start"] - 0.15)
        e = min(duration, ew["end"] + 0.35)
        if e - s > max_len + 5:
            e = s + max_len
        if e - s < min_len:
            # too short (small models often do this): extend to the next sentence end past min_len
            after = [w for w in words if w["start"] >= e - 0.35 and w["end"] <= s + max_len]
            for w in after:
                e = min(duration, w["end"] + 0.35)
                if e - s >= min_len and re.search(r"[.!?]$", w["word"]):
                    break
        if e - s < min(min_len, 5):
            continue
        if any(s < q["end"] and e > q["start"] for q in out):
            continue
        out.append({**p, "start": round(s, 2), "end": round(e, 2)})
    return out


def _ollama(path: str, payload: dict | None = None, timeout: float = 600):
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + path,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ollama_status() -> dict:
    """{'running': bool, 'model': name, 'installed': bool} for the health check."""
    try:
        tags = _ollama("/api/tags", timeout=2)
    except Exception:
        return {"running": False, "model": config.OLLAMA_MODEL, "installed": False}
    names = [m.get("name", "") for m in tags.get("models", [])]
    want = config.OLLAMA_MODEL if ":" in config.OLLAMA_MODEL else config.OLLAMA_MODEL + ":latest"
    return {"running": True, "model": config.OLLAMA_MODEL, "installed": want in names}


def _language_problem(plan: "ClipPlan", lang_code: str, lang_name: str) -> str:
    """Describe what's wrong with a small model's answer, or '' when it's fine."""
    issues = []
    cjk_ok = lang_code in ("zh", "ja", "ko")
    if not cjk_ok and any(_CJK.search(c.title + c.hook) for c in plan.clips):
        issues.append(f"titles or hooks in Chinese instead of {lang_name}")
    if any(not c.music_mood.isascii() or len(c.music_mood.split()) < 3 for c in plan.clips):
        issues.append("music_mood not written as an English description")
    if any(not 1 <= c.score <= 100 for c in plan.clips):
        issues.append("scores outside 1 to 100")
    return " and ".join(issues)


def _dedupe(picks: list[dict], transcript: dict, limit: float = 0.5) -> list[dict]:
    """Drop clips that say mostly the same thing as a better clip (shared vocabulary above `limit`)."""
    words = all_words(transcript)

    def vocab(p):
        return {re.sub(r"\W+", "", w["word"].lower()) for w in words
                if p["start"] <= w["start"] < p["end"] and len(re.sub(r"\W+", "", w["word"])) > 3}
    kept, sets = [], []
    for p in sorted(picks, key=lambda q: q.get("score", 0), reverse=True):
        v = vocab(p)
        if v and any(len(v & s) / max(1, min(len(v), len(s))) > limit for s in sets):
            continue
        kept.append(p)
        sets.append(v)
    return sorted(kept, key=lambda q: q.get("score", 0), reverse=True)


def pick_with_ollama(transcript: dict, n: int, min_len: float, max_len: float, title: str, log=print) -> list[dict]:
    """Free, local LLM. Long transcripts are split into windows the small model can read well."""
    segs = transcript["segments"]
    window_chars = 24000  # ~7k tokens per request
    windows, cur, size = [], [], 0
    for s in segs:
        line = f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}"
        if cur and size + len(line) > window_chars:
            windows.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        windows.append(cur)

    lang = _LANG_NAMES.get(transcript.get("language", ""), transcript.get("language") or "the same language")
    per_window = max(1,-(-n * 3 // (2 * len(windows))) + 1) if len(windows) > 1 else n
    schema = ClipPlan.model_json_schema()
    picks = []
    for i, lines in enumerate(windows):
        log(f"Local AI ({config.OLLAMA_MODEL}) reading part {i + 1} of {len(windows)}")
        prompt = (
            f"Video title: {title}\n\nTranscript (each line is [start-end seconds] text):\n"
            + "\n".join(lines)
            + f"\n\nPick the {per_window} best clips from this transcript. Each clip must be between "
            f"{min_len:.0f} and {max_len:.0f} seconds long (end minus start). Clips must not overlap. "
            "Copy start and end times from the transcript timestamps. "
            f"Write title and hook in the transcript's language ({lang}). "
            "Write music_mood in ENGLISH as 5-12 words describing genre, instruments and energy. "
            "score is an integer from 1 to 100. Reply with JSON only."
        )
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        plan = None
        for attempt in (1, 2):
            last = i == len(windows) - 1 and attempt == 2
            res = _ollama("/api/chat", {
                "model": config.OLLAMA_MODEL, "messages": messages, "format": schema, "stream": False,
                "options": {"temperature": 0.3 if attempt == 1 else 0.1, "num_ctx": 12288},
                "keep_alive": 0 if last else "5m",  # free the GPU for MusicGen when done
            })
            reply = res["message"]["content"]
            try:
                plan = ClipPlan.model_validate_json(reply)
            except Exception as e:
                log(f"Local AI returned unusable JSON for part {i + 1} ({type(e).__name__})")
                plan = None
                break
            problem = _language_problem(plan, transcript.get("language", ""), lang)
            if not problem or attempt == 2:
                break
            log(f"Local AI answer had {problem}; asking it to fix that")
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"Your answer has {problem}. Keep the same clips and times, "
                                                     f"write title and hook in {lang} and music_mood in English, "
                                                     "score between 1 and 100. Reply with the full JSON again."}]
        if plan is None:
            continue
        picks += [c.model_dump() for c in plan.clips]
    picks.sort(key=lambda p: p.get("score", 0), reverse=True)
    return picks


_LANG_NAMES = {"ar": "Arabic", "en": "English", "fr": "French", "es": "Spanish", "de": "German",
               "tr": "Turkish", "hi": "Hindi", "ur": "Urdu", "pt": "Portuguese", "it": "Italian"}
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
DEFAULT_MOOD = "modern upbeat background music, light percussion, warm synths"


def _clean(picks: list[dict], transcript: dict) -> list[dict]:
    """Small local models drift: Chinese titles, non-English music prompts, scores of 455. Repair those."""
    words = all_words(transcript)
    cjk_ok = transcript.get("language") in ("zh", "ja", "ko")
    for p in picks:
        clip_text = " ".join(w["word"] for w in words if p["start"] <= w["start"] < p["end"]).strip()
        first = re.split(r"(?<=[.!?؟])\s", clip_text)[0] if clip_text else ""
        if not cjk_ok and _CJK.search(p.get("hook", "")) or not p.get("hook", "").strip():
            p["hook"] = " ".join(first.split()[:8])
        if not cjk_ok and _CJK.search(p.get("title", "")) or not p.get("title", "").strip():
            p["title"] = " ".join(clip_text.split()[:6]) or "clip"
        mood = p.get("music_mood", "")
        if not mood.isascii() or len(mood.split()) < 3:
            p["music_mood"] = DEFAULT_MOOD
        try:
            p["score"] = max(1, min(100, int(p.get("score", 50))))
        except (TypeError, ValueError):
            p["score"] = 50
    return picks


def pick_clips(transcript: dict, n: int, min_len: float, max_len: float, duration: float,
               title: str = "", picker: str = "auto", log=print) -> tuple[list[dict], str]:
    """picker: 'claude' | 'ollama' | 'rules' | 'auto' (Claude if a key is set, else local AI, else rules)."""
    if picker == "auto":
        picker = "claude" if config.has_claude_key() else "ollama"
    picks, method = [], "rules"
    if picker == "claude" and not config.has_claude_key():
        log("No ANTHROPIC_API_KEY in .env; trying the free local AI instead")
        picker = "ollama"

    if picker == "claude":
        try:
            picks = _snap(pick_with_claude(transcript, n, min_len, max_len, title, log), transcript, duration, min_len, max_len)
            method = "claude"
        except Exception as e:
            log(f"Claude picking failed ({type(e).__name__}: {e}); using the rule-based picker")
    elif picker == "ollama":
        st = ollama_status()
        if not st["running"]:
            log("Ollama isn't running (start the Ollama app); using the rule-based picker")
        elif not st["installed"]:
            log(f"Ollama model '{config.OLLAMA_MODEL}' isn't downloaded (run: ollama pull {config.OLLAMA_MODEL}); using the rule-based picker")
        else:
            try:
                picks = _snap(pick_with_ollama(transcript, n, min_len, max_len, title, log), transcript, duration, min_len, max_len)
                method = "local AI"
            except Exception as e:
                log(f"Local AI picking failed ({type(e).__name__}: {e}); using the rule-based picker")

    picks = _dedupe(picks, transcript)
    if len(picks) < n:  # top up with rule-based picks that don't overlap (or repeat a topic)
        extra = _snap(pick_with_rules(transcript, n * 3, min_len, max_len), transcript, duration, min_len, max_len)
        for e in extra:
            if len(picks) >= n:
                break
            if not any(e["start"] < p["end"] and e["end"] > p["start"] for p in picks):
                picks.append(e)
        picks = _dedupe(picks, transcript)
    return _clean(picks[:n], transcript), method
