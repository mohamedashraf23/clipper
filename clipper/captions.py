"""Step 4a: animated word-by-word captions (ASS subtitles burned in by ffmpeg)."""
import re
from pathlib import Path

CAPTION_STYLES = {
    # name: (font, active word colour &HBBGGRR, base colour)
    "bold": ("Arial Black", "&H0000E5FF", "&H00FFFFFF"),   # yellow highlight
    "clean": ("Segoe UI Semibold", "&H0060FF6A", "&H00FFFFFF"),  # green highlight
    "fire": ("Impact", "&H00326BFF", "&H00FFFFFF"),         # orange highlight
}


# Arabic, Hebrew, Persian, Urdu... These need a font with those letters, and no inline override
# tags inside the line: ffmpeg's libass lays out right-to-left text per tag run, so per-word
# highlighting scrambles the word order.
_RTL = re.compile(r"[֐-ࣿיִ-﷿ﹰ-﻿]")
RTL_FONTS = {"bold": "Arial", "clean": "Segoe UI Semibold", "fire": "Arial"}


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _chunks(words: list[dict], max_words: int = 3, max_span: float = 1.4) -> list[list[dict]]:
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["end"] - cur[0]["start"] > max_span or w["start"] - cur[-1]["end"] > 0.6):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?,;:]$", w["word"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], clip_start: float, clip_end: float, width: int, height: int,
              out_path: Path, hook: str = "", style: str = "bold", captions: bool = True,
              uppercase: bool = True, seam_y: int | None = None) -> int:
    """Writes an .ass file; returns the number of caption events written.
    seam_y: for stacked layouts, the y of the line between the panels; the hook sits on it."""
    hook_top = None
    if seam_y is not None:
        hook_top = max(0, seam_y - round(min(width, height) * 0.058 * 0.9))
    font, hi, base = CAPTION_STYLES.get(style, CAPTION_STYLES["bold"])
    clip_words = [
        {**w, "start": w["start"] - clip_start, "end": w["end"] - clip_start}
        for w in words if w["end"] > clip_start and w["start"] < clip_end
    ]
    rtl = bool(_RTL.search(hook) or any(_RTL.search(w["word"]) for w in clip_words))
    if rtl:
        font = RTL_FONTS.get(style, "Arial")
    short = min(width, height)
    size = round(short * 0.075)
    vertical = height > width
    margin_v = round(height * (0.24 if vertical else 0.10))
    hook_size = round(short * 0.058)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{base},{base},&H00000000,&H80000000,-1,0,0,0,100,100,{0 if rtl else 1},0,1,{max(3, size // 14)},{max(1, size // 30)},2,{round(width*0.08)},{round(width*0.08)},{margin_v},1
Style: Hook,{font},{hook_size},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,{max(8, hook_size // 3)},0,8,{round(width*0.1)},{round(width*0.1)},{hook_top if hook_top is not None else round(height*0.09)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    dur = clip_end - clip_start

    if hook:
        hook_text = _esc(hook.upper() if uppercase else hook)
        hook_end = min(3.2, dur)
        # drop in from slightly above with a fade
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,"
                     f"{{\\fad(180,250)\\t(0,180,\\fscx100\\fscy100)\\fscx85\\fscy85}}{hook_text}")

    count = 0
    if captions:
        chunks = _chunks(clip_words)
        for n, chunk in enumerate(chunks):
            texts = [_esc(w["word"].upper() if uppercase else w["word"]) for w in chunk]
            chunk_end = chunk[-1]["end"] + 0.08
            if n + 1 < len(chunks):  # never overlap the next chunk, or two lines draw on top of each other
                chunk_end = min(chunk_end, chunks[n + 1][0]["start"])
            if rtl:
                # whole chunk in the highlight colour with a pop; no tags inside the text
                start = max(0.0, chunk[0]["start"])
                if chunk_end > start:
                    lines.append(f"Dialogue: 1,{_ts(start)},{_ts(min(chunk_end, dur))},Cap,,0,0,0,,"
                                 f"{{\\fad(60,0)\\c{hi}\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}}{' '.join(texts)}")
                    count += 1
                continue
            for i, w in enumerate(chunk):
                start = max(0.0, w["start"])
                end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end
                if end <= start:
                    continue
                parts = []
                for j, t in enumerate(texts):
                    if j == i:
                        # active word: highlight colour + quick pop
                        parts.append(f"{{\\c{hi}\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}}{t}{{\\r}}")
                    else:
                        parts.append(t)
                intro = "{\\fad(60,0)}" if i == 0 else ""
                lines.append(f"Dialogue: 1,{_ts(start)},{_ts(min(end, dur))},Cap,,0,0,0,,{intro}{' '.join(parts)}")
                count += 1

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8-sig")
    return count
