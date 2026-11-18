"""Cancelling jobs: while queued, mid-step (progress callbacks), and with FFmpeg running."""
import threading
import time

from clipper import ff, pipeline


def test_final_status_is_saved_before_gpu_cleanup(monkeypatch):
    """If the app closes while the GPU is being freed, the job must already be saved as done."""
    import json

    monkeypatch.setattr(pipeline.Job, "_run", lambda self: None)
    seen = {}

    def slow_unload():
        seen["on_disk"] = json.loads((job.dir / "job.json").read_text(encoding="utf-8"))["status"]

    monkeypatch.setattr(pipeline.music, "unload", slow_unload)
    job = pipeline.Job("https://example.com/v", {})
    job.run()
    assert seen["on_disk"] == "done"


def test_cancel_while_queued_never_starts(monkeypatch):
    ran = []
    monkeypatch.setattr(pipeline.Job, "_run", lambda self: ran.append(1))
    job = pipeline.Job("https://example.com/v", {})
    job.cancel()
    job.run()
    assert ran == []
    assert job.state["status"] == "cancelled"


def test_cancel_mid_step_stops_at_next_progress_update(monkeypatch):
    def slow_run(self):
        self.state["clips"] = [{"status": "done"}]
        for i in range(200):  # like Whisper reporting progress
            self.log(f"working {i}", transient=True)
            time.sleep(0.01)
        raise AssertionError("should have been cancelled")

    monkeypatch.setattr(pipeline.Job, "_run", slow_run)
    job = pipeline.Job("https://example.com/v", {})
    t = threading.Thread(target=job.run)
    t.start()
    time.sleep(0.2)
    job.cancel()
    t.join(5)
    assert not t.is_alive()
    assert job.state["status"] == "cancelled"
    assert "1 finished clips were kept" in job.state["log"][-1]


def test_kill_all_stops_a_running_ffmpeg(ffmpeg):
    errors = []

    def long_encode():
        try:  # 10 minutes of test pattern: would take far longer than the test allows
            ff.run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=600", "-f", "null", "-"])
        except ff.FFmpegError as e:
            errors.append(e)

    t = threading.Thread(target=long_encode)
    t.start()
    time.sleep(1.0)
    ff.kill_all()
    t.join(10)
    assert not t.is_alive()
    assert errors, "a killed ffmpeg reports a failure the pipeline can turn into 'cancelled'"


def test_cancel_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    c = TestClient(server.app)
    assert c.post("/api/jobs/nope/cancel").status_code == 404
    job = pipeline.Job("https://example.com/v", {})
    pipeline._jobs[job.id] = job
    assert c.post(f"/api/jobs/{job.id}/cancel").status_code == 200
    assert job.cancelled
    job.state["status"] = "done"
    assert c.post(f"/api/jobs/{job.id}/cancel").status_code == 409
