import re
from pathlib import Path

from clipper import captions, render
from clipper.reframe import corner_box, crop_box
from clipper.transcribe import all_words
from conftest import make_transcript


def _events(ass: Path):
    text = ass.read_text(encoding="utf-8-sig")
    rows = [l for l in text.splitlines() if l.startswith("Dialogue: 1")]

    def sec(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    return text, [(sec(r.split(",")[1]), sec(r.split(",")[2]), r) for r in rows]


def test_caption_chunks_never_overlap(tmp_path, transcript):
    ass = tmp_path / "c.ass"
    n = captions.build_ass(all_words(transcript), 0.0, 30.0, 1080, 1920, ass, hook="Big hook")
    _, ev = _events(ass)
    assert n == len(ev) > 0
    chunk_starts = {}
    for s, e, row in ev:
        assert e > s
    # consecutive events may touch but never overlap
    ordered = sorted(ev)
    assert all(a[1] <= b[0] + 0.011 for a, b in zip(ordered, ordered[1:]))


def test_arabic_uses_arabic_font_and_no_inline_tags(tmp_path):
    t = make_transcript([(0.0, "عم تسمع هيفا بتغني أغنيتها")], lang="ar")
    ass = tmp_path / "ar.ass"
    captions.build_ass(all_words(t), 0.0, 5.0, 1080, 1920, ass, hook="نقاش حول صوت هيفا")
    text, ev = _events(ass)
    style = next(l for l in text.splitlines() if l.startswith("Style: Cap"))
    assert "Arial Black" not in style and ",Arial," in style
    assert style.split(",")[13] == "0"  # letter spacing 0: spacing breaks Arabic letter joining
    for _, _, row in ev:
        body = row.split(",,", 1)[1]
        assert not re.search(r"\}.*\{", body), "no override tags inside right-to-left text"


def test_seam_moves_hook_to_panel_line(tmp_path, transcript):
    ass = tmp_path / "s.ass"
    captions.build_ass(all_words(transcript), 0.0, 10.0, 1080, 1920, ass, hook="Hook", seam_y=768)
    hook_style = next(l for l in ass.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Style: Hook"))
    margin_v = int(hook_style.split(",")[-2])
    assert 700 < margin_v < 768


def test_stack_geometry_fits_canvas_and_avoids_facecam():
    top_h, (bw, bh, bx, by) = render.stack_geometry("stack_cam", 1920, 1080, 1080, 1920, (344, 246, 1270, 83))
    assert top_h == 768
    assert bx + bw <= 1270  # gameplay crop ends before the webcam on the right
    assert abs(bw / bh - 1080 / (1920 - top_h)) < 0.01
    top_h2, crop2 = render.stack_geometry("stack_zoom", 1920, 1080, 1080, 1920)
    assert top_h2 == 606  # full width 16:9 strip on top
    assert all(v % 2 == 0 for v in crop2)


def test_crop_and_corner_boxes_stay_inside_frame():
    for center in [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5), None]:
        w, h, x, y = crop_box(1920, 1080, 1080, 1920, center)
        assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080
    for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
        w, h, x, y = corner_box(1920, 1080, corner, render.facecam_aspect(1080, 1920))
        assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080
