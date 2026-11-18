import numpy as np

from clipper import highlights


def fake_analysis(n_bins: int, hot: list[tuple[int, int]], cutscene: list[tuple[int, int]] = ()) -> dict:
    """An analysis dict with flat low scores and 'hot' stretches of action (bin ranges)."""
    score = np.full(n_bins, 0.1, np.float32)
    for a, b in hot:
        score[a:b] = 1.0
    cs = np.zeros(n_bins, np.int8)
    for a, b in cutscene:
        cs[a:b] = 1
    z = np.zeros(n_bins).tolist()
    return {"v": highlights.ANALYSIS_VERSION, "step": highlights.STEP, "score": score.tolist(),
            "loud": z, "burst": z, "motion": z, "speech": z, "cutscene": cs.tolist(), "cuts": []}


def test_pick_finds_the_action_and_respects_lengths():
    # 10 minutes, action at 120-150 s and 400-430 s
    a = fake_analysis(1200, hot=[(240, 300), (800, 860)])
    picks = highlights.pick(a, 2, 20, 40, 600.0, None)
    assert len(picks) == 2
    centres = sorted((p["start"] + p["end"]) / 2 for p in picks)
    assert 110 < centres[0] < 170 and 390 < centres[1] < 450
    for p in picks:
        assert 20 <= p["end"] - p["start"] <= 40 + 1e-6
        assert isinstance(p["start"], float)  # plain floats, so job.json can be saved


def test_picks_do_not_overlap():
    a = fake_analysis(1200, hot=[(240, 300)])
    picks = highlights.pick(a, 3, 20, 40, 600.0, None)
    spans = sorted((p["start"], p["end"]) for p in picks)
    assert all(x[1] <= y[0] for x, y in zip(spans, spans[1:]))


def test_describe_uses_safe_templates_without_ai():
    a = fake_analysis(400, hot=[(100, 160)])
    picks = highlights.pick(a, 1, 20, 40, 200.0, None)
    out = highlights.describe(picks, a, None, "Some Game", log=lambda *x, **k: None)
    hook = out[0]["hook"].lower()
    for banned in ("explosion", "shootout", "kill"):
        assert banned not in hook
    assert out[0]["music_mood"]


def test_short_video_returns_whole_thing():
    a = fake_analysis(20, hot=[])
    picks = highlights.pick(a, 3, 20, 40, 10.0, None)
    assert picks == [{"start": 0.0, "end": 10.0, "peak": 5.0, "strength": 1.0}]
