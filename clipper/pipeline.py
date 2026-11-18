"""Runs the six steps for one job and keeps job.json up to date for the web page."""
import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import captions, config, ff, highlights, ingest, music, picker, render, tighten, transcribe, verify
from .reframe import corner_box, face_center, find_facecam

DEFAULTS = {
    "n_clips": 3,
    "min_len": 20,
    "max_len": 55,
    "aspects": ["9:16", "1:1", "16:9"],
    "captions": True,
    "caption_style": "bold",
    "hook_text": True,
    "music": True,
    "music_volume": 0.30,
    "zoom": "punch",          # punch | slow | none
    "framing": "fit",         # fit (blurred fill, nothing cut) | fit_black | crop (fill, face-centred)
                              # | stack_cam (facecam over gameplay) | stack_zoom (whole frame over zoomed action)
    "facecam": "auto",        # auto | top-left | top-right | bottom-left | bottom-right
    "whisper_model": config.WHISPER_MODEL,
    "language": "",
    "picker": "auto",         # auto | claude | ollama | rules
    "content": "auto",        # auto | talk | gameplay
    "tighten": True,          # jump cuts: shorten pauses, drop filler words (talking videos only)
}
GAMEPLAY_WPM = 60  # fewer spoken words per minute than this = treat as gameplay when content is "auto"
GAME_TITLE_RE = re.compile(
    r"\b(gameplay|walkthrough|playthrough|let'?s play|no commentary|speedrun|ps[45]|xbox|"
    r"gta|grand theft auto|fortnite|minecraft|valorant|warzone|call of duty|cod|apex|cs2|csgo|counter.strike|"
    r"rocket league|fifa|ea fc|elden ring|red dead|rdr2|roblox|league of legends|overwatch|pubg|free fire)\b", re.I)

STAGES = [  # (key, label, start fraction, end fraction)
    ("ingest", "Import", 0.00, 0.08),
    ("transcribe", "Transcribe", 0.08, 0.35),
    ("pick", "Pick clips", 0.35, 0.40),
    ("music", "AI music", 0.40, 0.55),
    ("render", "Render clips", 0.55, 0.97),
    ("verify", "Verify", 0.97, 1.00),
]
_STAGE = {k: (label, a, b) for k, label, a, b in STAGES}

_queue_lock = threading.Lock()  # one job at a time: the GPU only has 6 GB


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "clip"


class Job:
    def __init__(self, source: str, settings: dict, job_id: str | None = None):
        self.id = job_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.dir = config.JOBS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = {
            "id": self.id, "source": source, "settings": {**DEFAULTS, **settings},
            "status": "queued", "stage": None, "progress": 0.0, "message": "Waiting in queue",
            "title": "", "pick_method": None, "clips": [], "log": [], "error": None,
            "created": time.time(), "finished": None,
        }
        self.save()

    # --- state helpers -------------------------------------------------
    def save(self, force: bool = True):
        """Persist job.json. The web page reads live state from memory, so the disk copy can lag;
        OneDrive (or antivirus) may briefly lock the file, so retry and never let a save kill the job."""
        now = time.time()
        if not force and now - getattr(self, "_last_save", 0) < 2.0:
            return
        self._last_save = now
        data = json.dumps(self.state, indent=1, ensure_ascii=False)
        target = self.dir / "job.json"
        for attempt in range(8):
            try:
                tmp = self.dir / "job.json.tmp"
                tmp.write_text(data, encoding="utf-8")
                tmp.replace(target)
                return
            except PermissionError:
                time.sleep(0.15 * (attempt + 1))
        try:
            target.write_text(data, encoding="utf-8")
        except OSError as e:
            print(f"[{self.id}] could not save job.json: {e}", flush=True)

    def stage(self, key: str, frac: float = 0.0, message: str | None = None, force: bool = True):
        label, a, b = _STAGE[key]
        self.state["stage"] = key
        self.state["progress"] = round(a + (b - a) * max(0.0, min(1.0, frac)), 4)
        if message:
            self.state["message"] = message
        self.save(force)

    def log(self, msg: str, transient: bool = False, frac: float | None = None):
        self.state["message"] = msg
        if frac is not None and self.state["stage"]:
            self.stage(self.state["stage"], frac, force=False)
        if not transient:
            self.state["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
            try:  # Windows consoles default to cp1252 and choke on Arabic etc.; never let logging kill a job
                print(f"[{self.id}] {msg}", flush=True)
            except (UnicodeEncodeError, OSError):
                pass
        self.save(force=not transient)

    # --- the pipeline --------------------------------------------------
    def run(self):
        with _queue_lock:
            self.state["status"] = "running"
            try:
                self._run()
                self.state["status"] = "done"
                self.state["progress"] = 1.0
                n = len(self.state["clips"])
                outs = [o["verify"]["status"] for c in self.state["clips"] for o in c["outputs"].values()]
                bad, warn = outs.count("fail"), outs.count("warn")
                summary = (f"{bad} failed checks" if bad else
                           f"{warn} have warnings" if warn else "All checks passed")
                self.state["message"] = f"Finished {n} clips and {len(outs)} renders. {summary}."
            except Exception as e:
                self.state["status"] = "error"
                self.state["error"] = f"{type(e).__name__}: {e}"
                self.log(traceback.format_exc())
                self.state["message"] = "Failed"  # keep the long traceback in the log, not the headline
            finally:
                music.unload()
                self.state["finished"] = time.time()
                self.save()

    def _run(self):
        s = self.state["settings"]
        aspects = [a for a in s["aspects"] if a in config.ASPECTS] or ["9:16"]

        # 1. import
        self.stage("ingest", 0, "Importing video")
        src = ingest.ingest(self.state["source"], self.dir, log=self.log)
        src["title"] = s.get("title") or src["title"]
        self.state["title"] = src["title"]
        self.state["source_meta"] = {k: src[k] for k in ("duration", "width", "height", "fps")}
        self.log(f"Imported '{src['title']}' — {src['duration']:.0f}s, {src['width']}x{src['height']} @ {src['fps']:.0f}fps")

        # 2. transcribe
        self.stage("transcribe", 0, "Transcribing")
        tr = transcribe.transcribe(self.dir / "audio.wav", self.dir / "transcript.json",
                                   model_name=s["whisper_model"], language=s["language"] or None,
                                   duration=src["duration"], log=self.log)
        words = transcribe.all_words(tr)
        wpm = len(words) / max(src["duration"] / 60, 0.1)
        self.log(f"Transcript: {len(words)} words ({wpm:.0f} per minute), language '{tr['language']}'")
        content = s.get("content", "auto")
        if content == "auto":
            # story games are full of cutscene dialogue, so the title is a stronger clue than word count
            titled = bool(GAME_TITLE_RE.search(f"{src['title']} {self.state['source']}"))
            content = "gameplay" if titled or wpm < GAMEPLAY_WPM else "talk"
            why = "the title says it's gameplay" if titled else f"only {wpm:.0f} words a minute" if content == "gameplay" else f"{wpm:.0f} words a minute"
            self.log(f"Content looks like {content} ({why})"
                     + (", so clips are picked from action instead of speech" if content == "gameplay" else ""))
        if content == "talk" and len(words) < 10:
            raise RuntimeError("Hardly any speech was found. Set Content type to Gameplay to clip by action instead")
        self.state["content"] = content

        # 3. pick clips
        self.stage("pick", 0, "Picking the best moments")
        max_len = min(float(s["max_len"]), src["duration"])
        min_len = min(float(s["min_len"]), max_len)
        if content == "gameplay":
            analysis = highlights.analyze(src["path"], self.dir / "audio.wav", src["duration"], tr,
                                          cache=self.dir / "highlights.json", log=self.log)
            self.stage("pick", 0.7, "Writing hooks")
            picks = highlights.describe(highlights.pick(analysis, int(s["n_clips"]), min_len, max_len, src["duration"], tr),
                                        analysis, tr, src["title"], log=self.log)
            method = "gameplay highlights"
        else:
            picks, method = picker.pick_clips(tr, int(s["n_clips"]), min_len, max_len, src["duration"],
                                              title=src["title"], picker=s.get("picker") or ("auto" if s.get("use_claude", True) else "rules"),
                                              log=self.log)
        if not picks:
            raise RuntimeError("Could not find any clip-able segment")
        self.state["pick_method"] = method
        self.log(f"Picked {len(picks)} clips (picked by {method})")
        for i, p in enumerate(picks):
            self.state["clips"].append({
                "index": i + 1, "slug": f"{i + 1:02d}-{_slug(p['title'])}", **p,
                "duration": round(p["end"] - p["start"], 2), "music_file": None, "face": None,
                "outputs": {}, "status": "pending",
            })
        # jump cuts: shorten pauses and drop filler words (talking only; pauses in gameplay are action)
        if s.get("tighten", True) and content == "talk":
            saved = 0.0
            for clip in self.state["clips"]:
                segs = tighten.keep_segments(words, clip["start"], clip["end"])
                if len(segs) > 1:
                    clip["segments"] = segs
                    clip["cut_seconds"] = round(clip["duration"] - tighten.total(segs), 2)
                    clip["duration"] = tighten.total(segs)
                    saved += clip["cut_seconds"]
            if saved:
                self.log(f"Jump cuts removed {saved:.1f}s of pauses and filler words")
        self.save()
        total = len(self.state["clips"])

        # 4b. AI music (all clips first, then free the GPU)
        if s["music"]:
            for i, clip in enumerate(self.state["clips"]):
                self.stage("music", i / total, f"Composing music {i + 1} of {total}: {clip['music_mood']}")
                out = self.dir / f"music_{clip['index']:02d}.wav"
                for attempt in (1, 2):
                    try:
                        music.generate(clip["music_mood"], clip["duration"], out, log=self.log)
                        clip["music_file"] = out.name
                        break
                    except Exception as e:
                        if attempt == 2:
                            self.log(f"Music for clip {clip['index']} failed ({e}); rendering without music")
                        else:
                            self.log(f"Music for clip {clip['index']} failed, retrying ({type(e).__name__})")
                            music.unload()
            music.unload()

        # 3b/4/5/6. reframe + captions + render + verify, clip i of N
        jobs = total * len(aspects)
        done = 0
        for clip in self.state["clips"]:
            clip["status"] = "rendering"
            clip_dir = self.dir / clip["slug"]
            clip_dir.mkdir(exist_ok=True)
            framing = s.get("framing", "fit")
            clip["face"] = face_center(src["path"], clip["start"], clip["end"]) if framing == "crop" else None
            clip["facecam"] = None
            if framing == "stack_cam":
                cam_aspect = render.facecam_aspect(*config.ASPECTS["9:16"])
                where = s.get("facecam", "auto")
                if where == "auto":
                    box = find_facecam(src["path"], clip["start"], clip["end"], cam_aspect)
                    self.log(f"Clip {clip['index']}: facecam found at {box[2]},{box[3]}" if box else
                             f"Clip {clip['index']}: no facecam found, using whole frame plus zoom")
                else:
                    box = corner_box(src["width"], src["height"], where, cam_aspect)
                clip["facecam"] = list(box) if box else None
            for aspect in aspects:
                w, h = config.ASPECTS[aspect]
                tag = aspect.replace(":", "x")
                self.stage("render", done / jobs, f"Rendering clip {clip['index']} of {total}, {aspect}")
                seam = None
                if framing in ("stack_cam", "stack_zoom") and h > w * 1.2 and src["width"] > src["height"]:
                    layout = "stack_cam" if (framing == "stack_cam" and clip["facecam"]) else "stack_zoom"
                    seam = render.stack_geometry(layout, src["width"], src["height"], w, h)[0]
                ass = clip_dir / f"captions_{tag}.ass"
                segs = clip.get("segments")
                cap_words = tighten.remap_words(words, clip["start"], segs) if segs else words
                cap_end = clip["start"] + clip["duration"] if segs else clip["end"]
                events = captions.build_ass(cap_words, clip["start"], cap_end, w, h, ass,
                                            hook=clip["hook"] if s["hook_text"] else "",
                                            style=s["caption_style"], captions=s["captions"], seam_y=seam)
                use_ass = s["captions"] or s["hook_text"]
                out = clip_dir / f"{clip['slug']}_{tag}.mp4"
                music_path = (self.dir / clip["music_file"]) if clip["music_file"] else None
                spoken = any(clip["start"] <= wd["start"] < clip["end"] for wd in words)
                result = self._render_and_verify(src, clip, w, h, ass if use_ass else None, music_path,
                                                 out, events, s, captions_wanted=s["captions"] and spoken)
                clip["outputs"][aspect] = {
                    "file": f"{clip['slug']}/{out.name}", "thumb": f"{clip['slug']}/{out.with_suffix('.jpg').name}",
                    "width": w, "height": h, "verify": result,
                }
                done += 1
                self.save()
            clip["status"] = "done"
            self.save()
        self.stage("verify", 1.0, "Verifying")

    def _render_and_verify(self, src, clip, w, h, ass, music_path, out, events, s, captions_wanted=True) -> dict:
        """Render, verify, and retry once with safer settings if a hard check fails."""
        attempts = [None, "libx264"]  # 2nd attempt: CPU encoder
        result = {"status": "fail", "checks": []}
        for n, encoder in enumerate(attempts):
            try:
                render.render_clip(source=str(Path(src["path"]).resolve()), src_meta=src, start=clip["start"],
                                   end=clip["end"], out_w=w, out_h=h, face=clip["face"], ass_file=ass,
                                   music_file=music_path,
                                   # game audio is already full; keep the music bed further back
                                   music_volume=float(s["music_volume"]) * (0.6 if self.state.get("content") == "gameplay" else 1.0),
                                   zoom=s["zoom"], out_path=out, encoder=encoder,
                                   framing=s.get("framing", "fit"),
                                   facecam=tuple(clip["facecam"]) if clip.get("facecam") else None,
                                   segments=[tuple(x) for x in clip["segments"]] if clip.get("segments") else None)
                result = verify.verify_clip(out, expected_w=w, expected_h=h, expected_duration=clip["duration"],
                                            caption_events=events, captions_wanted=captions_wanted,
                                            music_wanted=bool(music_path))
            except ff.FFmpegError as e:
                self.log(f"Render attempt {n + 1} failed: {e}")
                result = {"status": "fail", "checks": [{"name": "render", "status": "fail", "detail": str(e)[-400:]}]}
            if result["status"] != "fail":
                break
            self.log(f"Clip {clip['index']} {w}x{h} failed verification; retrying")
        result["attempts"] = n + 1
        return result


# --- registry used by the web server ------------------------------------
_jobs: dict[str, Job] = {}


def start_job(source: str, settings: dict, job_id: str | None = None) -> Job:
    job = Job(source, settings, job_id)
    _jobs[job.id] = job
    threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
    return job


def rerun_job(old_id: str, settings: dict) -> Job:
    """New job on the same video with new settings: no download, and no transcription when the
    Whisper model and language are unchanged. The video is hard-linked, so it costs no extra space."""
    old_dir = config.JOBS_DIR / old_id
    old = get_state(old_id)
    if not old:
        raise FileNotFoundError(old_id)
    src = next((p for p in sorted(old_dir.glob("source.*")) if p.suffix not in (".part", ".ytdl", ".wav")), None)
    if not src:
        raise FileNotFoundError("The original video is no longer in that job's folder")

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    new_dir = config.JOBS_DIR / job_id
    new_dir.mkdir(parents=True)
    linked = new_dir / f"upload{src.suffix}"
    try:
        os.link(src, linked)
    except OSError:
        shutil.copyfile(src, linked)

    merged = {**DEFAULTS, **settings, "title": old.get("title") or src.stem}
    prev = {**DEFAULTS, **old.get("settings", {})}
    if (merged["whisper_model"], merged["language"]) == (prev["whisper_model"], prev["language"]):
        for name in ("transcript.json", "highlights.json"):
            if (old_dir / name).exists():
                shutil.copy2(old_dir / name, new_dir / name)

    job = Job(str(linked), merged, job_id=job_id)
    job.state["origin"] = old.get("origin") or old.get("source")  # the original link, for display
    job.state["rerun_of"] = old_id
    job.save()
    _jobs[job.id] = job
    threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
    return job


def get_state(job_id: str) -> dict | None:
    if job_id in _jobs:
        return _jobs[job_id].state
    p = config.JOBS_DIR / job_id / "job.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def list_jobs() -> list[dict]:
    out = []
    for p in sorted(config.JOBS_DIR.glob("*/job.json"), reverse=True):
        try:
            st = _jobs[p.parent.name].state if p.parent.name in _jobs else json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if st.get("status") in ("queued", "running") and p.parent.name not in _jobs:
            st["status"] = "interrupted"
        out.append({k: st.get(k) for k in ("id", "title", "status", "progress", "message", "created", "rerun_of")}
                   | {"source": st.get("origin") or st.get("source"), "clips": len(st.get("clips", []))})
    return out
