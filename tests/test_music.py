from pathlib import Path

from clipper import music


def _lib(tmp_path: Path, names):
    for n in names:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0")
    return music.library(tmp_path)


def test_library_finds_audio_recursively_and_ignores_other_files(tmp_path):
    tracks = _lib(tmp_path, ["a.mp3", "sub/b.wav", "notes.txt", "cover.jpg", "c.FLAC"])
    assert sorted(t.name for t in tracks) == ["a.mp3", "b.wav", "c.FLAC"]


def test_missing_folder_is_empty(tmp_path):
    assert music.library(tmp_path / "nope") == []


def test_mood_matches_file_and_folder_names(tmp_path):
    tracks = _lib(tmp_path, ["calm-lofi-piano.mp3", "energetic/drive.mp3", "dark-trap-808.mp3"])
    used = {}
    assert music.pick_track("calm lofi hip hop, soft piano", tracks, used).name == "calm-lofi-piano.mp3"
    assert music.pick_track("energetic driving beat", tracks, used).name == "drive.mp3"


def test_batch_spreads_across_tracks_when_nothing_matches(tmp_path):
    tracks = _lib(tmp_path, ["one.mp3", "two.mp3", "three.mp3"])
    used = {}
    picked = [music.pick_track("mysterious ambient", tracks, used, salt=i).name for i in range(3)]
    assert len(set(picked)) == 3
