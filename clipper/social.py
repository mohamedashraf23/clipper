"""Post-ready text for each clip: a caption to paste into TikTok / Reels / Shorts, plus hashtags.

Written by the local AI (Ollama) in the video's language when it's available; otherwise a plain
template from the clip title. Saved next to the clip as post.txt.
"""
import json
import re

from . import config
from .transcribe import all_words

LANG_TAGS = {"ar": ["#اكسبلور", "#ترند"], "es": ["#parati"], "fr": ["#pourtoi"], "de": ["#fürdich"]}
BASE_TAGS = {"talk": ["#shorts", "#podcast", "#reels"], "gameplay": ["#gaming", "#gameplay", "#shorts"]}
MAX_TAGS = 8


def _clean_tag(t: str) -> str:
    t = re.sub(r"[^\w؀-ۿ]+", "", t.strip().lstrip("#"))
    return f"#{t}" if t else ""


def _template(p: dict, content: str, lang: str, video_title: str) -> dict:
    words = [w for w in re.findall(r"[\w؀-ۿ]+", f"{p.get('title', '')} {video_title}") if len(w) > 3]
    tags = [_clean_tag(w) for w in dict.fromkeys(words)][:4]
    tags += BASE_TAGS.get(content, BASE_TAGS["talk"]) + LANG_TAGS.get(lang, [])
    hook = (p.get("hook") or p.get("title") or "").strip()
    return {"caption": hook + (" 👀" if content == "gameplay" else ""), "hashtags": list(dict.fromkeys(t for t in tags if t))[:MAX_TAGS]}


def write_posts(picks: list[dict], transcript: dict | None, video_title: str, content: str, log=print) -> list[dict]:
    """Adds 'post': {'caption', 'hashtags'} to every pick."""
    lang = (transcript or {}).get("language", "en")
    for p in picks:
        p["post"] = _template(p, content, lang, video_title)
    try:
        from .picker import _LANG_NAMES, _ollama, ollama_status
        st = ollama_status()
        if not (st["running"] and st["installed"]):
            return picks
        words = all_words(transcript or {"segments": []})
        brief = [{"id": i, "title": p.get("title", ""), "hook": p.get("hook", ""),
                  "said": " ".join(w["word"] for w in words if p["start"] <= w["start"] < p["end"])[:500]}
                 for i, p in enumerate(picks)]
        lang_name = _LANG_NAMES.get(lang, lang or "English")
        schema = {"type": "object", "properties": {"posts": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}}}, "required": ["id", "caption", "hashtags"]}}},
            "required": ["posts"]}
        prompt = (
            f"Video: {video_title}\nThese are short clips cut from it ({'gameplay' if content == 'gameplay' else 'people talking'}). "
            f"'said' is what is spoken in each clip.\n{json.dumps(brief, ensure_ascii=False)}\n\n"
            f"For each clip write, in {lang_name}:\n"
            "- caption: the text to post with the clip on TikTok, Reels and Shorts. One or two short sentences that make "
            "people watch and comment, at most one emoji, no hashtags inside it. Only claim what the clip actually shows.\n"
            + ("You cannot see the gameplay: NEVER name a specific event (explosion, shootout, chase, crash, kill) "
               "unless 'said' mentions it. Write curiosity captions that stay true whatever happens.\n"
               if content == "gameplay" else "")
            +
            f"- hashtags: 5 to 8 relevant hashtags, mixing broad and specific ones, in {lang_name} or English.\n"
            "Reply with JSON only."
        )
        log(f"Local AI writing post captions for {len(picks)} clips")
        res = _ollama("/api/chat", {"model": config.OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}],
                                    "format": schema, "stream": False, "options": {"temperature": 0.6, "num_ctx": 8192},
                                    "keep_alive": 0}, timeout=300)
        got = {x["id"]: x for x in json.loads(res["message"]["content"]).get("posts", [])}
        cjk = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
        for i, p in enumerate(picks):
            x = got.get(i)
            if not x or (lang not in ("zh", "ja", "ko") and cjk.search(x.get("caption", ""))):
                continue
            caption = re.sub(r"\s*#\S+", "", x.get("caption", "")).strip()
            tags = [_clean_tag(t) for t in x.get("hashtags", [])]
            tags = [t for t in dict.fromkeys(tags) if t and not cjk.search(t)]
            if caption:
                p["post"]["caption"] = caption[:300]
            if len(tags) >= 3:
                p["post"]["hashtags"] = tags[:MAX_TAGS]
    except Exception as e:
        log(f"Using simple post captions ({type(e).__name__}: {e})")
    return picks


def post_text(post: dict) -> str:
    return f"{post['caption']}\n\n{' '.join(post['hashtags'])}\n"
