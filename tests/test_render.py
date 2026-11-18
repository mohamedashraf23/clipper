"""End to end: render a real (tiny) clip with FFmpeg, then run the verifier on it. Skipped without FFmpeg."""
from pathlib import Path

import pytest

from clipper import captions, ff, render, verify
from clipper.transcribe import all_words
from conftest import make_transcript


@pytest.fixture
def source(tmp_path, ffmpeg):
    """8 s 640x360 test pattern with a tone, like a small landscape video."""
    out = tmp_path / "src.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8:sample_rate=48000",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out


@pytest.mark.parametrize("framing", ["fit", "stack_zoom", "crop"])
def test_render_vertical_clip_passes_checks(tmp_path, source, framing):
    meta = ff.probe(source)
    words = all_words(make_transcript([(0.5, "this is a test clip"), (3.0, "with some captions on it")]))
    ass = tmp_path / "c.ass"
    events = captions.build_ass(words, 1.0, 7.0, 360, 640, ass, hook="Test hook")
    out = tmp_path / f"out_{framing}.mp4"
    render.render_clip(source=str(source), src_meta=meta, start=1.0, end=7.0, out_w=360, out_h=640, face=None,
                       ass_file=ass, music_file=None, music_volume=0.3, zoom="none", out_path=out,
                       encoder="libx264", framing=framing)
    res = verify.verify_clip(out, expected_w=360, expected_h=640, expected_duration=6.0,
                             caption_events=events, captions_wanted=True, music_wanted=False)
    hard = [c for c in res["checks"] if c["status"] == "fail"]
    assert not hard, hard
    assert out.with_suffix(".jpg").exists()


def test_jump_cuts_shorten_the_render(tmp_path, source):
    meta = ff.probe(source)
    out = tmp_path / "cut.mp4"
    segments = [(0.0, 2.0), (3.0, 6.0)]  # drop one second
    render.render_clip(source=str(source), src_meta=meta, start=1.0, end=7.0, out_w=360, out_h=640, face=None,
                       ass_file=None, music_file=None, music_volume=0.3, zoom="none", out_path=out,
                       encoder="libx264", framing="fit", segments=segments)
    assert abs(ff.probe(out)["duration"] - 5.0) < 0.15
