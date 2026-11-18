"""Live mode: watch a live stream, keep a rolling buffer, and turn moments into clips while it runs.

    stream link --yt-dlp--> ffmpeg --> 10 s .ts segments (last BUFFER_MINUTES kept)
                                          |
                     analyzer thread: motion / loudness / bursts per 0.5 s, scored like gameplay mode
                                          |
          auto trigger (a big spike)  or  "Clip that" button (the last N seconds)
                                          |
                     clip worker: join segments -> captions (optional) -> render every aspect -> verify

One live session runs at a time. Clips render on a separate worker so recording never pauses.
"""
import csv
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import numpy as np

from . import captions, config, ff, highlights, render, social, verify

SEGMENT_SECONDS = 10
BUFFER_MINUTES = 30
WARMUP_SECONDS = 90      # learn what "normal" looks like before auto-clipping
COOLDOWN_SECONDS = 120   # at most one auto clip per two minutes
STEP = highlights.STEP

LIVE_DEFAULTS = {
    "clip_seconds": 45,
    "auto_clips": True,
    "aspects": ["9:16"],
    "framing": "stack_zoom",
    "facecam": "auto",
    "captions": True,
    "hook_text": True,
    "caption_style": "bold",
    "zoom": "none",
    "whisper_model": "base",   # small and fast: clips should be ready within a minute
    "language": "",
}

_sessions: dict[str, "LiveSession"] = {}
_lock = threading.Lock()


class LiveError(RuntimeError):
    pass


def _z_hist(values: np.ndarray, history: np.ndarray) -> np.ndarray:
    """Scale against what this stream has shown so far, so a quiet stream and a loud one both work."""
    if len(history) < 20:
        return np.clip(values, 0, 1.5)
    lo, hi = np.percentile(history, 5), np.percentile(history, 95)
    return np.clip((values - lo) / (hi - lo + 1e-6), 0, 1.5)


class LiveSession:
    def __init__(self, url: str, settings: dict, session_id: str | None = None):
        self.id = session_id or "live-" + time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.dir = config.JOBS_DIR / self.id
        self.seg_dir = self.dir / "segments"
        self.seg_dir.mkdir(parents=True, exist_ok=True)
        self.url = url
        self.s = {**LIVE_DEFAULTS, **settings}
        self.s["clip_seconds"] = max(15, min(120, int(self.s.get("clip_seconds") or 45)))
        self.state = {
            "id": self.id, "kind": "live", "url": url, "title": "", "status": "connecting",
            "message": "Connecting to the stream", "started": time.time(), "finished": None,
            "buffered": 0.0, "recorded": 0.0, "intensity": [], "clips": [], "log": [], "error": None,
            "settings": self.s,
        }
        self._procs: list[subprocess.Popen] = []
        self._stop = threading.Event()
        self._segments: list[dict] = []          # {"file", "start", "end"} in stream seconds
        self._seen = 0
        self._raw = {"loud": [], "burst": [], "motion": [], "bright": []}
        self._score: list[float] = []
        self._last_auto = -1e9
        self._pending_auto: list[float] = []      # peak times waiting for their footage to arrive
        self._clips_q: queue.Queue = queue.Queue()
        self._save_lock = threading.Lock()
        self.save()

    # ---- state -----------------------------------------------------------
    def save(self):
        with self._save_lock:
            tmp = self.dir / "live.json.tmp"
            data = json.dumps(self.state, indent=1, ensure_ascii=False)
            for attempt in range(6):
                try:
                    tmp.write_text(data, encoding="utf-8")
                    tmp.replace(self.dir / "live.json")
                    return
                except PermissionError:
                    time.sleep(0.1 * (attempt + 1))

    def log(self, msg: str):
        self.state["message"] = msg
        self.state["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        try:
            print(f"[{self.id}] {msg}", flush=True)
        except (UnicodeEncodeError, OSError):
            pass
        self.save()

    # ---- recording -------------------------------------------------------
    def _recorder_cmds(self) -> tuple[list[str] | None, list[str]]:
        """(downloader, segmenter). A local file path simulates a live stream (used by tests and demos)."""
        # Matroska pieces: unlike .ts they hold any codec (H.264 from Twitch, but also AV1/VP9) with a plain copy
        out = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-f", "segment", "-segment_format", "matroska",
               "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1",
               "-segment_list", str(self.seg_dir / "segments.csv"), "-segment_list_type", "csv",
               str(self.seg_dir / "seg_%06d.mkv")]
        ffmpeg = [ff.find_bin("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        if Path(self.url).exists():
            return None, [*ffmpeg, "-re", "-i", self.url, *out]
        dl = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--no-part",
              "--ffmpeg-location", ff.ffmpeg_dir(), "-f", "b[height<=1080]/best", "-o", "-", self.url]
        return dl, [*ffmpeg, "-i", "pipe:0", *out]

    def _probe_stream(self):
        if Path(self.url).exists():
            self.state["title"] = Path(self.url).stem
            return
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(self.url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise LiveError(f"Couldn't open that stream: {str(e).replace('ERROR: ', '')[:240]}") from None
        if not (info.get("is_live") or info.get("live_status") == "is_live"):
            raise LiveError("That link isn't live right now. For a finished video, use Video link instead.")
        self.state["title"] = info.get("title") or info.get("uploader") or "Live stream"
        self.state["channel"] = info.get("uploader") or info.get("channel") or ""

    def start(self):
        threading.Thread(target=self._run, daemon=True, name=f"{self.id}-rec").start()
        threading.Thread(target=self._clip_worker, daemon=True, name=f"{self.id}-clips").start()
        return self

    def _run(self):
        try:
            self._probe_stream()
            dl, seg = self._recorder_cmds()
            if dl:
                p_dl = subprocess.Popen(dl, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p_seg = subprocess.Popen(seg, stdin=p_dl.stdout, stderr=subprocess.PIPE)
                p_dl.stdout.close()
                self._procs = [p_dl, p_seg]
            else:
                p_seg = subprocess.Popen(seg, stderr=subprocess.PIPE)
                self._procs = [p_seg]
            self.state["status"] = "recording"
            self.log(f"Recording '{self.state['title']}'. Clips need about {SEGMENT_SECONDS} seconds of delay.")
            while not self._stop.is_set():
                self._ingest_new_segments()
                if p_seg.poll() is not None:  # the stream ended or the connection dropped
                    self._ingest_new_segments()
                    if not self._stop.is_set():
                        err = (p_seg.stderr.read() or b"").decode("utf-8", "replace").strip()[-300:]
                        self.state["status"] = "ended"
                        self.log("The stream ended or the connection dropped." + (f" ({err})" if err else ""))
                    break
                time.sleep(1.0)
        except LiveError as e:
            self.state.update(status="error", error=str(e))
            self.log(str(e))
        except Exception as e:
            self.state.update(status="error", error=f"{type(e).__name__}: {e}")
            self.log(traceback.format_exc())
        finally:
            self._kill()
            if self.state["status"] in ("connecting", "recording"):
                self.state["status"] = "stopped"
            self._clips_q.put(None)  # let the worker finish what's queued, then exit
            self.save()

    def _kill(self):
        for p in self._procs:
            try:
                p.kill()
            except OSError:
                pass

    def stop(self):
        if self.state["status"] in ("connecting", "recording"):
            self._stop.set()
            self.state["status"] = "stopped"
            self.log("Stopped. Clips already queued will still finish.")
            self._kill()

    # ---- segments and live scoring ----------------------------------------
    def _ingest_new_segments(self):
        lst = self.seg_dir / "segments.csv"
        if not lst.exists():
            return
        rows = list(csv.reader(lst.read_text(encoding="utf-8", errors="replace").splitlines()))
        for row in rows[self._seen:]:
            if len(row) < 3:
                continue
            seg = {"file": row[0], "start": float(row[1]), "end": float(row[2])}
            self._seen += 1
            self._segments.append(seg)
            try:
                self._analyze(seg)
            except Exception as e:  # a corrupt piece shouldn't stop the session
                self.state["log"].append(f"{time.strftime('%H:%M:%S')}  Skipped analysing {seg['file']} ({e})")
            self.state["recorded"] = round(seg["end"], 1)
        self._trim_buffer()
        self.state["buffered"] = round(sum(s["end"] - s["start"] for s in self._segments), 1)
        self._check_triggers()
        self.save()

    def _analyze(self, seg: dict):
        path = self.seg_dir / seg["file"]
        dur = seg["end"] - seg["start"]
        n = max(1, int(round(dur / STEP)))  # round, not ceil: keeps bins aligned with stream time over hours
        wav = path.with_suffix(".wav")
        ff.run(["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
        loud, burst = highlights._audio_curves(wav, n)
        motion, bright, _, _ = highlights._video_curves(path, n, log=lambda *a, **k: None)
        wav.unlink(missing_ok=True)
        for k, v in (("loud", loud), ("burst", burst), ("motion", motion), ("bright", bright)):
            self._raw[k].extend(float(x) for x in v)
        r = {k: np.array(v, np.float32) for k, v in self._raw.items()}
        new = slice(len(self._score), len(r["loud"]))
        score = (0.35 * _z_hist(highlights._smooth(r["loud"], 3), r["loud"])
                 + 0.40 * _z_hist(highlights._smooth(r["burst"], 2), r["burst"])
                 + 0.45 * _z_hist(highlights._smooth(r["motion"], 3), r["motion"]))
        score = np.where(highlights._smooth(r["bright"], 2) < 0.06, score * 0.25, score)
        self._score.extend(float(x) for x in score[new])
        # the page draws the last 5 minutes as a sparkline
        self.state["intensity"] = [round(x, 3) for x in self._score[-int(300 / STEP):]]

    def _trim_buffer(self):
        keep_from = self.state["recorded"] - BUFFER_MINUTES * 60
        busy = {f for c in self.state["clips"] if c["status"] in ("queued", "rendering") for f in c.get("_files", [])}
        while self._segments and self._segments[0]["end"] < keep_from and self._segments[0]["file"] not in busy:
            old = self._segments.pop(0)
            (self.seg_dir / old["file"]).unlink(missing_ok=True)

    def _check_triggers(self):
        recorded = self.state["recorded"]
        clip_len = self.s["clip_seconds"]
        if self.s.get("auto_clips") and recorded >= WARMUP_SECONDS and len(self._score) > 40:
            sc = np.array(self._score, np.float32)
            win = max(2, int(10 / STEP))
            means = np.convolve(sc, np.ones(win) / win, mode="valid")
            recent_from = max(0, len(means) - int(SEGMENT_SECONDS / STEP) - win)
            recent = means[recent_from:]
            if len(recent):
                i = recent_from + int(np.argmax(recent))
                peak_t = (i + win / 2) * STEP
                threshold = max(0.75, float(np.percentile(means, 95)))
                if means[i] >= threshold and peak_t - self._last_auto >= COOLDOWN_SECONDS:
                    self._last_auto = peak_t
                    self._pending_auto.append(peak_t)
                    self.log(f"Big moment at {_fmt(peak_t)} (intensity {means[i]:.2f}). Making a clip.")
        # an auto clip waits until the footage after its peak has been recorded
        for peak_t in list(self._pending_auto):
            start = max(0.0, peak_t - clip_len * 0.6)
            if recorded >= start + clip_len or self.state["status"] != "recording":
                self._pending_auto.remove(peak_t)
                self.queue_clip(start, min(recorded, start + clip_len), reason="auto", peak=peak_t - start)

    # ---- clips -------------------------------------------------------------
    def clip_last(self, seconds: float | None = None) -> dict:
        """The 'Clip that' button: the last N seconds that have been recorded."""
        if not self._segments:
            raise LiveError("Nothing recorded yet. Give it a few seconds.")
        seconds = max(10, min(120, float(seconds or self.s["clip_seconds"])))
        end = self.state["recorded"]
        start = max(self._segments[0]["start"], end - seconds)
        return self.queue_clip(start, end, reason="button", peak=(end - start) * 0.8)

    def queue_clip(self, start: float, end: float, reason: str, peak: float) -> dict:
        files = [s["file"] for s in self._segments if s["end"] > start and s["start"] < end]
        if not files:
            raise LiveError("That moment is no longer in the buffer")
        index = len(self.state["clips"]) + 1
        clip = {"index": index, "slug": f"{index:02d}-{reason}-{int(start)}", "start": round(start, 2),
                "end": round(end, 2), "duration": round(end - start, 2), "reason": reason, "peak": round(peak, 2),
                "title": "Clip that" if reason == "button" else "Big moment", "hook": "", "music_mood": "",
                "music_file": None, "score": 0, "outputs": {}, "status": "queued", "_files": files,
                "created": time.time()}
        self.state["clips"].append(clip)
        self.save()
        self._clips_q.put(clip)
        return clip

    def _clip_worker(self):
        while True:
            clip = self._clips_q.get()
            if clip is None:
                if self._stop.is_set() or self.state["status"] != "recording":
                    break
                continue
            try:
                self._render_clip(clip)
            except Exception as e:
                clip["status"] = "error"
                clip["error"] = f"{type(e).__name__}: {e}"
                self.log(f"Clip {clip['index']} failed: {clip['error']}")
            finally:
                self.save()
        self.state["finished"] = self.state["finished"] or time.time()
        self.save()

    def _render_clip(self, clip: dict):
        clip["status"] = "rendering"
        self.save()
        cdir = self.dir / clip["slug"]
        cdir.mkdir(exist_ok=True)
        segs = [s for s in self._segments if s["file"] in clip["_files"]] or \
               [{"file": f, "start": 0, "end": 0} for f in clip["_files"]]
        # 1. join the buffered pieces (stream copy, instant)
        listing = cdir / "pieces.txt"
        listing.write_text("".join(f"file '{(self.seg_dir / s['file']).as_posix()}'\n" for s in segs), encoding="utf-8")
        joined = cdir / "source.mp4"
        ff.run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-movflags", "+faststart", joined])
        offset = clip["start"] - segs[0]["start"]
        src = {**ff.probe(joined), "path": str(joined)}
        if not src["width"] or not src["height"]:
            raise LiveError("The recorded pieces have no picture (the stream's video format couldn't be saved)")
        rel_start, rel_end = max(0.0, offset), min(src["duration"], offset + clip["duration"])
        clip["duration"] = round(rel_end - rel_start, 2)

        # 2. hook and post text from the live signals (local AI if it's running, safe templates otherwise)
        a0, a1 = int(clip["start"] / STEP), int(clip["end"] / STEP)
        r = {k: np.array(v[a0:a1] or [0], np.float32) for k, v in self._raw.items()}
        mini = {"step": STEP, "loud": highlights._z(r["loud"]).tolist(), "burst": highlights._z(r["burst"]).tolist(),
                "motion": highlights._z(r["motion"]).tolist(), "speech": [0.0] * len(r["loud"])}
        words, tr = [], None
        if self.s.get("captions"):
            wav = cdir / "audio.wav"
            ff.run(["-ss", f"{rel_start:.3f}", "-t", f"{clip['duration']:.3f}", "-i", joined,
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
            from . import transcribe
            tr = transcribe.transcribe(wav, cdir / "transcript.json", model_name=self.s["whisper_model"],
                                       language=self.s["language"] or None, duration=clip["duration"],
                                       log=lambda *a, **k: None)
            # transcript times start at 0 = the clip start; captions want times in the joined file
            words = [{**w, "start": w["start"] + rel_start, "end": w["end"] + rel_start} for w in transcribe.all_words(tr)]
        pick = {"start": 0.0, "end": clip["duration"], "peak": clip["peak"], "strength": 1.0}
        described = highlights.describe([pick], mini, tr, self.state["title"], log=lambda *a, **k: None)[0]
        if clip["reason"] == "auto":
            clip["title"] = described["title"]
        clip["hook"] = described["hook"]
        post_pick = {"start": 0.0, "end": clip["duration"], "title": clip["title"], "hook": clip["hook"]}
        clip["post"] = social.write_posts([post_pick], tr, self.state["title"], "gameplay", log=lambda *a, **k: None)[0]["post"]

        # 3. render every aspect and verify
        framing = self.s.get("framing", "stack_zoom")
        facecam = None
        if framing == "stack_cam":
            from .reframe import corner_box, find_facecam
            asp = render.facecam_aspect(*config.ASPECTS["9:16"])
            facecam = (find_facecam(str(joined), rel_start, rel_end, asp) if self.s.get("facecam", "auto") == "auto"
                       else corner_box(src["width"], src["height"], self.s["facecam"], asp))
        for aspect in [a for a in self.s["aspects"] if a in config.ASPECTS] or ["9:16"]:
            w, h = config.ASPECTS[aspect]
            tag = aspect.replace(":", "x")
            seam = None
            if framing in ("stack_cam", "stack_zoom") and h > w * 1.2 and src["width"] > src["height"]:
                seam = render.stack_geometry("stack_cam" if facecam else "stack_zoom", src["width"], src["height"], w, h)[0]
            ass = cdir / f"captions_{tag}.ass"
            events = captions.build_ass(words, rel_start, rel_end, w, h, ass,
                                        hook=clip["hook"] if self.s["hook_text"] else "",
                                        style=self.s["caption_style"], captions=self.s["captions"], seam_y=seam)
            out = cdir / f"{clip['slug']}_{tag}.mp4"
            render.render_clip(source=str(joined), src_meta=src, start=rel_start, end=rel_end, out_w=w, out_h=h,
                               face=None, ass_file=ass if (self.s["captions"] or self.s["hook_text"]) else None,
                               music_file=None, music_volume=0.0, zoom=self.s["zoom"], out_path=out,
                               framing=framing, facecam=tuple(facecam) if facecam else None)
            spoken = any(rel_start <= wd["start"] < rel_end for wd in words)
            result = verify.verify_clip(out, expected_w=w, expected_h=h, expected_duration=clip["duration"],
                                        caption_events=events, captions_wanted=self.s["captions"] and spoken,
                                        music_wanted=False)
            clip["outputs"][aspect] = {"file": f"{clip['slug']}/{out.name}",
                                       "thumb": f"{clip['slug']}/{out.with_suffix('.jpg').name}",
                                       "width": w, "height": h, "verify": result}
            self.save()
        (cdir / "post.txt").write_text(social.post_text(clip["post"]), encoding="utf-8")
        joined.unlink(missing_ok=True)  # the rendered clips are what matter; the buffer copy is big
        clip["status"] = "done"
        self.log(f"Clip {clip['index']} ready ({clip['duration']:.0f}s, {'auto' if clip['reason'] == 'auto' else 'your button'})")


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# ---- registry used by the web server ---------------------------------------
def start(url: str, settings: dict) -> LiveSession:
    with _lock:
        active = [s for s in _sessions.values() if s.state["status"] in ("connecting", "recording")]
        if active:
            raise LiveError("A live session is already running. Stop it first.")
        sess = LiveSession(url, settings)
        _sessions[sess.id] = sess
    return sess.start()


def get(session_id: str) -> LiveSession | None:
    return _sessions.get(session_id)


def public_state(session_id: str) -> dict | None:
    """State for the page (internal fields stripped). Falls back to live.json for past sessions."""
    if session_id in _sessions:
        st = _sessions[session_id].state
    else:
        p = config.JOBS_DIR / session_id / "live.json"
        if not p.exists():
            return None
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("status") in ("connecting", "recording"):
            st["status"] = "stopped"  # the app was closed while it ran
    out = {**st, "clips": [{k: v for k, v in c.items() if not k.startswith("_")} for c in st.get("clips", [])]}
    return out


def list_sessions() -> list[dict]:
    out = []
    for p in sorted(config.JOBS_DIR.glob("live-*/live.json"), reverse=True):
        st = public_state(p.parent.name)
        if st:
            out.append({k: st.get(k) for k in ("id", "title", "url", "status", "started", "recorded")}
                       | {"clips": len(st.get("clips", []))})
    return out


def delete(session_id: str):
    sess = _sessions.get(session_id)
    if sess and sess.state["status"] in ("connecting", "recording"):
        raise LiveError("Stop the session first")
    _sessions.pop(session_id, None)
    shutil.rmtree(config.JOBS_DIR / session_id, ignore_errors=True)
