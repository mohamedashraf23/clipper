"""Shared test setup. Tests never touch your real jobs folder, GPU or network."""
import os
import shutil
import tempfile

import pytest

# must happen before clipper.config is imported anywhere
os.environ["CLIPPER_JOBS_DIR"] = tempfile.mkdtemp(prefix="clipper-test-jobs-")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"  # nothing listens here: local AI is "not running"


def make_transcript(sentences: list[tuple[float, str]], wps: float = 2.5, lang: str = "en") -> dict:
    """Build a faster-whisper style transcript: one segment per sentence, evenly timed words.
    sentences: (start_time, text) pairs."""
    segs = []
    for start, text in sentences:
        words, t = [], start
        for w in text.split():
            words.append({"word": w, "start": round(t, 3), "end": round(t + 1 / wps * 0.85, 3), "probability": 0.9})
            t += 1 / wps
        segs.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
    return {"language": lang, "segments": segs}


@pytest.fixture
def transcript():
    # ~60 s of speech, sentences every 5 s, with a few pauses and fillers
    lines = [
        (0.0, "Welcome back to the show everyone."),
        (5.0, "Today we talk about something huge."),
        (10.0, "Have you ever wondered why this happens?"),
        (15.5, "um so the answer is simple."),
        (21.0, "It changed everything for me!"),
        (26.0, "Let me explain how it works."),
        (31.0, "First you need the right setup."),
        (36.0, "Then you practise every single day."),
        (41.0, "That is the whole secret really."),
        (46.0, "Thanks for watching and see you soon."),
    ]
    return make_transcript(lines)


@pytest.fixture
def ffmpeg():
    from clipper import ff
    try:
        return ff.find_bin("ffmpeg")
    except ff.FFmpegError:
        pytest.skip("FFmpeg not installed")


@pytest.fixture
def tmpdir_clean():
    d = tempfile.mkdtemp(prefix="clipper-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)
