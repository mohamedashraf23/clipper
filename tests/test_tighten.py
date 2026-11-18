from clipper import tighten
from clipper.transcribe import all_words
from conftest import make_transcript


def words_at(pairs):
    """[(start, end, word)] -> word dicts"""
    return [{"word": w, "start": s, "end": e} for s, e, w in pairs]


def test_no_cuts_when_speech_is_continuous():
    ws = words_at([(0.0, 0.3, "a"), (0.35, 0.6, "b"), (0.7, 1.0, "c")])
    assert tighten.keep_segments(ws, 0.0, 1.5) == [(0.0, 1.35)]


def test_medium_pause_is_shortened():
    ws = words_at([(0.0, 0.5, "hello"), (1.5, 2.0, "world")])  # 1.0 s gap
    segs = tighten.keep_segments(ws, 0.0, 2.5)
    assert len(segs) == 2
    gap_kept = segs[1][0] - 0.0 - (segs[0][1] - segs[0][0])
    assert tighten.total(segs) < 2.5
    # 0.1 s of breathing room on each side of the cut
    assert abs((segs[0][1] - 0.5) - tighten.KEEP_GAP / 2) < 1e-6
    assert abs((1.5 - segs[1][0]) - tighten.KEEP_GAP / 2) < 1e-6
    assert gap_kept >= 0


def test_long_gap_is_kept_because_it_may_be_laughter():
    ws = words_at([(0.0, 0.5, "joke"), (5.0, 5.5, "haha")])  # 4.5 s gap > MAX_CUT
    assert len(tighten.keep_segments(ws, 0.0, 6.0)) == 1


def test_filler_words_are_dropped():
    ws = words_at([(0.0, 0.4, "so"), (0.5, 0.9, "um"), (1.0, 1.4, "yes")])
    # 'um' removed leaves a 0.6 s hole between 'so' and 'yes' -> cut
    segs = tighten.keep_segments(ws, 0.0, 2.0)
    assert len(segs) == 2
    remapped = tighten.remap_words(ws, 0.0, segs)
    assert [w["word"] for w in remapped] == ["so", "yes"]


def test_remap_keeps_words_in_order_and_inside_new_length(transcript):
    words = all_words(transcript)
    segs = tighten.keep_segments(words, 0.0, 50.0)
    new_len = tighten.total(segs)
    remapped = tighten.remap_words(words, 0.0, segs)
    starts = [w["start"] for w in remapped]
    assert starts == sorted(starts)
    assert all(0.0 <= w["start"] <= new_len + 0.01 for w in remapped)
    assert new_len < 50.0


def test_clip_offset_is_respected():
    t = make_transcript([(100.0, "one two three"), (102.5, "four five six")])
    words = all_words(t)
    segs = tighten.keep_segments(words, 100.0, 104.0)
    assert segs[0][0] == 0.0  # relative to the clip start, not the video
    assert all(e <= 4.0 for _, e in segs)
