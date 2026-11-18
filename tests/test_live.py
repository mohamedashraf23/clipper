"""Live mode end to end with a simulated stream: a generated video played at real-time speed."""
import time

import pytest

from clipper import ff, live


@pytest.fixture
def fake_stream(tmp_path, ffmpeg):
    """25 s of moving test pattern with a tone, like a small live stream."""
    out = tmp_path / "stream.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=25",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=25:sample_rate=48000",
            "-shortest", "-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out


def _wait(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.5)
    return False


def test_record_and_clip_button(fake_stream):
    sess = live.start(str(fake_stream), {"auto_clips": False, "captions": False, "aspects": ["9:16"],
                                         "framing": "stack_zoom", "clip_seconds": 15})
    try:
        assert _wait(lambda: sess.state["recorded"] >= 12, 40), sess.state["log"]
        assert sess.state["status"] == "recording"
        assert len(sess.state["intensity"]) > 0  # the live action graph is filling in
        clip = sess.clip_last(10)
        assert clip["reason"] == "button" and 9 <= clip["duration"] <= 10.5
        assert _wait(lambda: clip["status"] in ("done", "error"), 120), clip
        assert clip["status"] == "done", clip.get("error")
        out = clip["outputs"]["9:16"]
        assert out["verify"]["status"] != "fail", out["verify"]["checks"]
        assert (sess.dir / out["file"]).exists()
        assert (sess.dir / clip["slug"] / "post.txt").exists()
        # internal bookkeeping never reaches the page
        assert all(not k.startswith("_") for c in live.public_state(sess.id)["clips"] for k in c)
    finally:
        sess.stop()
    assert sess.state["status"] in ("stopped", "ended")  # the 25 s stream may finish while the clip renders


def test_stream_end_is_reported(fake_stream):
    sess = live.start(str(fake_stream), {"auto_clips": False, "captions": False})
    assert _wait(lambda: sess.state["status"] in ("ended", "error"), 60), sess.state["status"]
    assert sess.state["status"] == "ended"
    assert 20 <= sess.state["recorded"] <= 26
    assert live.list_sessions()[0]["id"] == sess.id


def test_only_one_session_and_api_rules(fake_stream):
    from fastapi.testclient import TestClient
    import server

    c = TestClient(server.app)
    assert c.post("/api/live", json={"url": "file:///x"}).status_code == 400  # local paths only via code, not the API
    sess = live.start(str(fake_stream), {"auto_clips": False, "captions": False})
    try:
        with pytest.raises(live.LiveError):
            live.start(str(fake_stream), {})
        assert c.get(f"/api/live/{sess.id}").json()["kind"] == "live"
        assert c.delete(f"/api/live/{sess.id}").status_code == 409  # can't delete while recording
    finally:
        sess.stop()
    assert c.post(f"/api/live/{sess.id}/clip", json={}).status_code == 409  # not recording any more
    assert c.get("/api/live/nope").status_code == 404


def test_auto_trigger_needs_a_real_spike():
    """Flat streams never auto clip; a spike after the warm-up does, once, then the cooldown applies."""
    s = live.LiveSession.__new__(live.LiveSession)
    s.s = {**live.LIVE_DEFAULTS, "auto_clips": True}
    s.state = {"recorded": 0.0, "status": "recording", "clips": [], "log": [], "message": ""}
    s._last_auto, s._pending_auto, s._score = -1e9, [], []
    s.save = lambda: None
    s.log = lambda m: s.state["log"].append(m)
    queued = []
    s.queue_clip = lambda start, end, reason, peak: queued.append((start, end, reason)) or {}
    flat = [0.3] * int(120 / live.STEP)
    s._score, s.state["recorded"] = list(flat), 120.0
    s._check_triggers()
    assert not s._pending_auto
    s._score += [1.4] * int(10 / live.STEP)  # ten seconds of chaos
    s.state["recorded"] = 130.0
    s._check_triggers()
    assert len(s._pending_auto) == 1
    s.state["recorded"] = 160.0          # footage after the peak has arrived
    s._score += [0.3] * int(30 / live.STEP)
    s._check_triggers()
    assert queued and queued[0][2] == "auto"
    s._score += [1.4] * int(10 / live.STEP)  # another spike inside the cooldown
    s.state["recorded"] = 170.0
    s._check_triggers()
    assert len(queued) == 1 and not s._pending_auto
