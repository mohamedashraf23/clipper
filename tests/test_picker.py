from clipper import picker


def test_rules_picker_returns_non_overlapping_clips_in_range(transcript):
    picks = picker.pick_with_rules(transcript, 3, 10, 20)
    assert picks
    for p in picks:
        assert 10 <= p["end"] - p["start"] <= 20 + 1e-6
    spans = sorted((p["start"], p["end"]) for p in picks)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_snap_moves_to_word_boundaries_and_extends_short_clips(transcript):
    raw = [{"start": 10.3, "end": 13.0, "title": "t", "hook": "h", "music_mood": "m", "score": 50, "reason": ""}]
    out = picker._snap(raw, transcript, 50.0, min_len=8, max_len=20)
    assert out, "a too-short pick should be extended, not dropped"
    s, e = out[0]["start"], out[0]["end"]
    assert e - s >= 8
    assert s <= 10.0  # snapped back to the first word of the sentence


def test_clean_fixes_local_model_drift(transcript):
    picks = [{"start": 0.0, "end": 9.0, "title": "关于喜欢的人", "hook": "非常感谢",
              "music_mood": "平静", "score": 455, "reason": ""}]
    out = picker._clean(picks, transcript)[0]
    assert out["title"].isascii() and out["hook"].isascii()
    assert out["music_mood"] == picker.DEFAULT_MOOD
    assert out["score"] == 100


def test_language_problem_is_detected():
    plan = picker.ClipPlan(clips=[picker.ClipPick(start=0, end=10, title="关于", hook="ok", music_mood="平静",
                                                  score=455, reason="")])
    problem = picker._language_problem(plan, "ar", "Arabic")
    assert "Chinese" in problem and "English" in problem and "1 to 100" in problem
    good = picker.ClipPlan(clips=[picker.ClipPick(start=0, end=10, title="صوت هيفا", hook="بتحبها",
                                                  music_mood="calm lofi beat, soft piano", score=80, reason="")])
    assert picker._language_problem(good, "ar", "Arabic") == ""


def test_dedupe_drops_clips_on_the_same_topic():
    from conftest import make_transcript
    t = make_transcript([
        (0.0, "Training discipline consistency practice routine habits matter"),
        (10.0, "Training discipline consistency practice routine habits again"),
        (20.0, "Cooking pasta tomatoes garlic basil dinner tonight"),
    ])
    picks = [{"start": 0.0, "end": 9.0, "score": 90}, {"start": 10.0, "end": 19.0, "score": 70},
             {"start": 20.0, "end": 29.0, "score": 60}]
    kept = picker._dedupe(picks, t)
    assert [p["start"] for p in kept] == [0.0, 20.0]


def test_auto_picker_falls_back_to_rules_without_ai(transcript):
    # conftest points Ollama at a dead port and removes the Claude key
    picks, method = picker.pick_clips(transcript, 2, 10, 20, 50.0, title="t", picker="auto", log=lambda *a, **k: None)
    assert method == "rules"
    assert len(picks) == 2
