"""API tests with FastAPI's in-process client: no server is started and no job actually runs."""
import json

import pytest
from fastapi.testclient import TestClient

import server
from clipper import config, pipeline


@pytest.fixture
def client(monkeypatch):
    started = []

    class FakeJob:
        def __init__(self, source, settings, job_id=None):
            self.id = job_id or "fake"
            started.append((source, settings))

    monkeypatch.setattr(pipeline, "start_job", lambda source, settings, job_id=None: FakeJob(source, settings, job_id))
    c = TestClient(server.app)
    c.started = started
    return c


def test_health_reports_tools(client):
    h = client.get("/api/health").json()
    for key in ("ffmpeg", "cuda", "claude_key", "ollama", "aspects"):
        assert key in h
    assert h["ollama"]["running"] is False  # conftest points it at a dead port


def test_create_needs_a_source(client):
    r = client.post("/api/jobs", data={"settings": "{}"})
    assert r.status_code == 400


def test_create_rejects_non_http_urls(client):
    r = client.post("/api/jobs", data={"url": "file:///etc/passwd", "settings": "{}"})
    assert r.status_code == 400


def test_create_clamps_clip_count(client):
    r = client.post("/api/jobs", data={"url": "https://example.com/v", "settings": json.dumps({"n_clips": 999})})
    assert r.status_code == 200
    assert client.started[-1][1]["n_clips"] == 20


def test_upload_rejects_unknown_file_types(client):
    r = client.post("/api/jobs", data={"settings": "{}"}, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_GB", 1 / 1024 ** 3 * 1000)  # 1000 bytes
    r = client.post("/api/jobs", data={"settings": "{}"}, files={"file": ("big.mp4", b"x" * 5000, "video/mp4")})
    assert r.status_code == 413
    r = client.post("/api/jobs", data={"settings": "{}"}, files={"file": ("empty.mp4", b"", "video/mp4")})
    assert r.status_code == 400


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/rerun", json={}).status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 404


def test_trim_validation(client):
    d = config.JOBS_DIR / "t2"
    d.mkdir(exist_ok=True)
    (d / "source.mp4").write_bytes(b"\0")
    clip = {"index": 1, "start": 10.0, "end": 40.0, "duration": 30.0, "outputs": {}, "status": "done"}
    (d / "job.json").write_text(json.dumps({"id": "t2", "status": "running", "clips": [clip], "created": 0,
                                            "settings": {}, "source_meta": {"duration": 100.0}}), encoding="utf-8")
    pipeline._jobs.pop("t2", None)
    assert client.post("/api/jobs/nope/clips/1/trim", json={"start": 0, "end": 10}).status_code == 404
    assert client.post("/api/jobs/t2/clips/1/trim", json={"start": 0, "end": 10}).status_code == 409  # running
    pipeline._jobs["t2"].state["status"] = "done"
    assert client.post("/api/jobs/t2/clips/1/trim", json={}).status_code == 400
    assert client.post("/api/jobs/t2/clips/1/trim", json={"start": 10, "end": 11}).status_code == 400  # too short
    assert client.post("/api/jobs/t2/clips/7/trim", json={"start": 10, "end": 30}).status_code == 404


def test_job_files_are_served_from_jobs_dir(client):
    d = config.JOBS_DIR / "t1"
    d.mkdir(exist_ok=True)
    (d / "job.json").write_text(json.dumps({"id": "t1", "status": "done", "clips": [], "created": 0}), encoding="utf-8")
    assert client.get("/api/jobs/t1").json()["status"] == "done"
    assert client.get("/files/t1/job.json").status_code == 200
    assert client.get("/files/../server.py").status_code == 404
