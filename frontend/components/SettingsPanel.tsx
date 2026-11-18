"use client";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowClockwise, CaretDown, FilmStrip, LinkSimple, MusicNotes, Scissors, Subtitles, TextT, Timer, UploadSimple, WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Health, Settings } from "@/lib/api";
import { fast, riseIn, stagger } from "@/lib/motion";
import { InlineError, Segmented, Toggle } from "./controls";

const ASPECTS = [
  { value: "9:16", label: "9:16 Shorts", w: 14, h: 24, m: 0 },
  { value: "1:1", label: "1:1 Square", w: 20, h: 20, m: 2 },
  { value: "16:9", label: "16:9 Wide", w: 28, h: 16, m: 4 },
];

type Source = { url?: string; file?: File };

export function SettingsPanel({ health, onSubmit, rerunTarget, onRerun }: {
  health: Health | null | "offline"; onSubmit: (s: Settings, src: Source) => Promise<void>;
  /** the open job, when it can be re-run with the settings below */
  rerunTarget?: { id: string; title: string } | null;
  onRerun?: (id: string, s: Settings) => Promise<void>;
}) {
  const [mode, setMode] = useState<"url" | "file">("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [content, setContent] = useState("auto");
  const [n, setN] = useState(3);
  const [minLen, setMinLen] = useState(20);
  const [maxLen, setMaxLen] = useState(55);
  const [aspects, setAspects] = useState<string[]>(["9:16", "1:1", "16:9"]);
  const [framing, setFraming] = useState("fit");
  const [facecam, setFacecam] = useState("auto");
  const [captions, setCaptions] = useState(true);
  const [hook, setHook] = useState(true);
  const [music, setMusic] = useState(true);
  const [tighten, setTighten] = useState(true);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [style, setStyle] = useState("bold");
  const [zoom, setZoom] = useState("punch");
  const [vol, setVol] = useState(30);
  const [picker, setPicker] = useState("ollama");
  const [whisper, setWhisper] = useState("small");
  const [lang, setLang] = useState("");
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState<"url" | "len" | null>(null);
  const [busy, setBusy] = useState(false);
  const urlRef = useRef<HTMLInputElement>(null);

  // default picker follows what's available: Claude if a key is set, else local AI, else rules
  useEffect(() => {
    if (health && health !== "offline")
      setPicker(health.claude_key ? "claude" : health.ollama.running && health.ollama.installed ? "ollama" : "rules");
  }, [health]);

  const fail = (msg: string, field: "url" | "len" | null = null) => {
    setError(msg); setInvalid(field);
    if (field === "url") urlRef.current?.focus();
  };

  const collect = (): Settings => ({
    n_clips: n, min_len: minLen, max_len: maxLen, aspects, framing, facecam, content,
    captions, hook_text: hook, music, music_volume: vol / 100, caption_style: style, zoom, picker,
    whisper_model: whisper, language: lang, tighten,
  });

  /** checks shared by a new job and a re-run; returns false after showing the error */
  const settingsOk = () => {
    if (!aspects.length) { fail("Pick at least one aspect ratio."); return false; }
    if (!minLen || !maxLen || minLen >= maxLen) { fail("The shortest length must be below the longest.", "len"); return false; }
    return true;
  };

  const serverError = (err: unknown) => {
    const m = (err as Error).message;
    fail(m === "Failed to fetch" ? "Can't reach the server. Is start.bat running?" : m);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(""); setInvalid(null);
    if (mode === "url") {
      if (!url.trim()) return fail("Paste a video link first.", "url");
      if (!/^https?:\/\//i.test(url.trim())) return fail("The link should start with https://", "url");
    } else if (!file) return fail("Choose a video file first.");
    if (!settingsOk()) return;
    setBusy(true);
    try {
      await onSubmit(collect(), mode === "file" ? { file: file! } : { url: url.trim() });
    } catch (err) { serverError(err); } finally { setBusy(false); }
  }

  async function rerun() {
    if (!rerunTarget || !onRerun) return;
    setError(""); setInvalid(null);
    if (!settingsOk()) return;
    setRerunBusy(true);
    try { await onRerun(rerunTarget.id, collect()); } catch (err) { serverError(err); } finally { setRerunBusy(false); }
  }

  const toggleAspect = (a: string) =>
    setAspects((cur) => (cur.includes(a) ? cur.filter((x) => x !== a) : [...cur, a]));

  return (
    <motion.form className="panel" noValidate onSubmit={submit} variants={stagger(0.07, 0.1)} initial="hidden" animate="show">
      <motion.section className="group" variants={riseIn} aria-labelledby="g1">
        <h2 className="group-h title-3" id="g1"><span className="n caption-3">1</span>Source</h2>
        <Segmented id="src" label="Video source" value={mode} onChange={setMode} options={[
          { value: "url", label: "Video link", icon: <LinkSimple size={16} /> },
          { value: "file", label: "Upload file", icon: <UploadSimple size={16} /> },
        ]} />
        <AnimatePresence mode="wait" initial={false}>
          {mode === "url" ? (
            <motion.div key="url" className="field" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} transition={fast}>
              <label htmlFor="url" className="body-6">Paste a YouTube or video page link</label>
              <input ref={urlRef} id="url" type="text" className={`body-6 ${invalid === "url" ? "invalid" : ""}`} value={url}
                     onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=" autoComplete="off" spellCheck={false} />
            </motion.div>
          ) : (
            <motion.label key="file" className={`drop ${over ? "over" : ""}`} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0, x: -12 }} transition={fast}
                          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                          onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); }}>
              <motion.span animate={over ? { y: -4, scale: 1.1 } : { y: 0, scale: 1 }} transition={fast}><FilmStrip size={24} /></motion.span>
              <b className="body-5">{file ? `${file.name} (${(file.size / 1e6).toFixed(1)} MB)` : "Drop a video here"}</b>
              <span className="caption-5">or click to choose. MP4, MOV, MKV or WEBM.</span>
              <input type="file" accept="video/*" hidden onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])} />
            </motion.label>
          )}
        </AnimatePresence>
        <div className="field">
          <label htmlFor="content" className="body-6">Content type</label>
          <select id="content" className="body-6" value={content} onChange={(e) => setContent(e.target.value)}>
            <option value="auto">Detect from the video</option>
            <option value="talk">Talking: podcast, interview, vlog</option>
            <option value="gameplay">Gameplay: pick by action, not words</option>
          </select>
        </div>
      </motion.section>

      <motion.section className="group" variants={riseIn} aria-labelledby="g2">
        <h2 className="group-h title-3" id="g2"><span className="n caption-3">2</span>Clips</h2>
        <div className="field">
          <label className="lbl body-6" htmlFor="n">How many clips
            <motion.b key={n} className="body-4" initial={{ y: -6, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={fast}>{n}</motion.b>
          </label>
          <input type="range" id="n" min={1} max={10} value={n} onChange={(e) => setN(+e.target.value)} />
        </div>
        <div className="row">
          <div className="field"><label htmlFor="minlen" className="body-6">Shortest (sec)</label>
            <input type="number" id="minlen" className={`body-6 mono ${invalid === "len" ? "invalid" : ""}`} min={5} max={180} value={minLen} onChange={(e) => setMinLen(+e.target.value)} /></div>
          <div className="field"><label htmlFor="maxlen" className="body-6">Longest (sec)</label>
            <input type="number" id="maxlen" className="body-6 mono" min={10} max={180} value={maxLen} onChange={(e) => setMaxLen(+e.target.value)} /></div>
        </div>
      </motion.section>

      <motion.section className="group" variants={riseIn} aria-labelledby="g3">
        <h2 className="group-h title-3" id="g3"><span className="n caption-3">3</span>Format</h2>
        <div className="checks" role="group" aria-label="Aspect ratios">
          {ASPECTS.map((a) => {
            const on = aspects.includes(a.value);
            return (
              <motion.button key={a.value} type="button" className="aspect caption-4" aria-pressed={on} onClick={() => toggleAspect(a.value)}
                             whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }} transition={fast}>
                <motion.i className="frame" style={{ width: a.w, height: a.h, margin: `${a.m}px 0` }}
                          animate={{ scale: on ? 1 : 0.85, opacity: on ? 1 : 0.6 }} transition={{ type: "spring", stiffness: 500, damping: 20 }} />
                {a.label}
              </motion.button>
            );
          })}
        </div>
        <div className="field">
          <label htmlFor="framing" className="body-6">When the shape doesn&apos;t match</label>
          <select id="framing" className="body-6" value={framing} onChange={(e) => setFraming(e.target.value)}>
            <option value="fit">Show the whole video, blurred fill</option>
            <option value="fit_black">Show the whole video, black bars</option>
            <option value="crop">Crop to fill, follow the face</option>
            <option value="stack_cam">Stacked: facecam on top, gameplay below</option>
            <option value="stack_zoom">Stacked: whole frame on top, zoomed action below</option>
          </select>
          <AnimatePresence>
            {framing.startsWith("stack") && (
              <motion.p className="caption-5 muted" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
                Stacked layouts apply to 9:16. Square and wide clips use the whole video.
              </motion.p>
            )}
          </AnimatePresence>
        </div>
        <AnimatePresence>
          {framing === "stack_cam" && (
            <motion.div className="field" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={fast}>
              <label htmlFor="facecam" className="body-6">Where is the facecam</label>
              <select id="facecam" className="body-6" value={facecam} onChange={(e) => setFacecam(e.target.value)}>
                <option value="auto">Find it automatically</option>
                <option value="top-left">Top left</option>
                <option value="top-right">Top right</option>
                <option value="bottom-left">Bottom left</option>
                <option value="bottom-right">Bottom right</option>
              </select>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.section>

      <motion.section className="group" variants={riseIn} aria-labelledby="g4">
        <h2 className="group-h title-3" id="g4"><span className="n caption-3">4</span>Look and sound</h2>
        <div className="toggles">
          <Toggle checked={captions} onChange={setCaptions} icon={<Subtitles size={16} />}>Animated captions</Toggle>
          <Toggle checked={hook} onChange={setHook} icon={<TextT size={16} />}>Hook title, first 3 sec</Toggle>
          <Toggle checked={music} onChange={setMusic} icon={<MusicNotes size={16} />}>AI music</Toggle>
          <Toggle checked={tighten} onChange={setTighten} icon={<Timer size={16} />}>Cut pauses and filler words</Toggle>
        </div>
        <p className="caption-5 muted">Jump cuts apply to talking videos. Gameplay keeps its pauses.</p>
        <div className="row">
          <div className="field"><label htmlFor="style" className="body-6">Caption style</label>
            <select id="style" className="body-6" value={style} onChange={(e) => setStyle(e.target.value)}>
              <option value="bold">Bold yellow</option><option value="clean">Clean green</option><option value="fire">Impact orange</option>
            </select></div>
          <div className="field"><label htmlFor="zoom" className="body-6">Zoom</label>
            <select id="zoom" className="body-6" value={zoom} onChange={(e) => setZoom(e.target.value)}>
              <option value="punch">Punch in</option><option value="slow">Slow push</option><option value="none">None</option>
            </select></div>
        </div>
        <div className="field">
          <label className="lbl body-6" htmlFor="vol">Music volume <b className="body-4">{vol}%</b></label>
          <input type="range" id="vol" min={5} max={80} value={vol} disabled={!music} onChange={(e) => setVol(+e.target.value)} />
        </div>
      </motion.section>

      <motion.section className="group" variants={riseIn} aria-labelledby="g5">
        <h2 className="group-h title-3" id="g5"><span className="n caption-3">5</span>AI engines</h2>
        <div className="field">
          <label htmlFor="picker" className="body-6">Who picks the clips</label>
          <select id="picker" className="body-6" value={picker} onChange={(e) => setPicker(e.target.value)}>
            <option value="ollama">Free local AI (Ollama)</option>
            <option value="claude">Claude (API key, paid)</option>
            <option value="rules">Simple rules, fastest</option>
          </select>
        </div>
        <details className="adv">
          <summary className="body-5">Transcription settings <CaretDown size={16} /></summary>
          <div className="inner">
            <div className="row">
              <div className="field"><label htmlFor="whisper" className="body-6">Whisper model</label>
                <select id="whisper" className="body-6" value={whisper} onChange={(e) => setWhisper(e.target.value)}>
                  {["tiny", "base", "small", "medium", "large-v3"].map((m) => <option key={m}>{m}</option>)}
                </select></div>
              <div className="field"><label htmlFor="lang" className="body-6">Language</label>
                <select id="lang" className="body-6" value={lang} onChange={(e) => setLang(e.target.value)}>
                  <option value="">Detect</option><option value="ar">Arabic</option><option value="en">English</option>
                  <option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option>
                </select></div>
            </div>
            <p className="caption-5 muted">Bigger models are more accurate and slower. Small is a good balance on a 6 GB GPU.</p>
          </div>
        </details>
      </motion.section>

      <motion.button type="submit" className="btn-primary button-md" disabled={busy} variants={riseIn}
                     whileHover={{ y: -1 }} whileTap={{ scale: 0.98 }}>
        <motion.span className="shine" initial={{ x: "-150%" }} animate={{ x: "450%" }}
                     transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1], repeat: Infinity, repeatDelay: 3.5 }} />
        <motion.span animate={busy ? { rotate: [0, -18, 18, 0] } : { rotate: 0 }}
                     transition={busy ? { duration: 0.8, repeat: Infinity, ease: [0.22, 1, 0.36, 1] } : { duration: 0.3 }} style={{ display: "inline-flex" }}>
          <Scissors size={18} weight="bold" />
        </motion.span>
        <span>{busy ? (mode === "file" ? "Uploading" : "Starting") : "Make clips"}</span>
      </motion.button>
      <AnimatePresence>
        {rerunTarget && (
          <motion.button key="rerun" type="button" className="btn btn-secondary button-sm" onClick={rerun} disabled={rerunBusy}
                         initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                         whileHover={{ y: -1 }} whileTap={{ scale: 0.98 }} transition={fast}
                         title="Same video, new settings. Skips the download and, if the Whisper settings are unchanged, the transcription.">
            <motion.span style={{ display: "inline-flex" }} animate={rerunBusy ? { rotate: 360 } : { rotate: 0 }}
                         transition={rerunBusy ? { duration: 0.9, repeat: Infinity, ease: [0.22, 1, 0.36, 1] } : fast}>
              <ArrowClockwise size={16} weight="bold" />
            </motion.span>
            <span className="ti">{rerunBusy ? "Starting" : <>Re-run <b dir="auto">{rerunTarget.title}</b> with these settings</>}</span>
          </motion.button>
        )}
      </AnimatePresence>
      <InlineError message={error} icon={<WarningCircle size={18} />} />
    </motion.form>
  );
}
