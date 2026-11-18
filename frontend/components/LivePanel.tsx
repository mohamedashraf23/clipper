"use client";
import { AnimatePresence, motion } from "motion/react";
import { Broadcast, Lightning, Scissors, StopCircle, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { isRtl, type Clip, type LiveClip, type LiveState } from "@/lib/api";
import { EASE, fast, move, stagger } from "@/lib/motion";
import { ClipCard } from "./ClipCard";

const LENGTHS = [30, 45, 60, 90];
const fmtDur = (t: number) => {
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

/** Last five minutes of action intensity, newest on the right. */
function Sparkline({ values }: { values: number[] }) {
  const W = 600, H = 64;
  const path = useMemo(() => {
    if (values.length < 2) return "";
    const step = Math.max(1, Math.floor(values.length / 150)); // ~150 points is plenty
    const pts = values.filter((_, i) => i % step === 0);
    const max = Math.max(1, ...pts);
    return pts.map((v, i) => `${i === 0 ? "M" : "L"}${(i / (pts.length - 1)) * W},${H - (v / max) * (H - 6) - 3}`).join(" ");
  }, [values]);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Action intensity, last five minutes">
      {path && <motion.path d={`${path} L${W},${H} L0,${H} Z`} className="spark-fill" initial={false} animate={{ d: `${path} L${W},${H} L0,${H} Z` }} transition={move} />}
      {path && <motion.path d={path} className="spark-line" initial={false} animate={{ d: path }} transition={move} />}
    </svg>
  );
}

/** Live clips use the same card as normal clips. */
const asClip = (c: LiveClip): Clip => ({
  ...c, status: c.status === "done" ? "done" : c.status === "rendering" ? "rendering" : "pending",
  reason: c.status === "error" ? `Failed: ${c.error ?? "unknown error"}` : c.reason === "auto" ? "Auto clip: an action spike" : "Clipped with the button",
});

export function LivePanel({ live, onClip, onStop }: {
  live: LiveState; onClip: (seconds: number) => Promise<void>; onStop: () => Promise<void>;
}) {
  const recording = live.status === "recording" || live.status === "connecting";
  const [seconds, setSeconds] = useState(live.settings?.clip_seconds ?? 45);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(0);
  const [err, setErr] = useState("");
  const [stopping, setStopping] = useState(false);

  const clip = useCallback(async () => {
    if (!recording || busy || live.recorded < 5) return;
    setBusy(true); setErr("");
    try { await onClip(seconds); setFlash((f) => f + 1); }
    catch (e) { setErr((e as Error).message); }
    finally { setTimeout(() => setBusy(false), 600); }
  }, [recording, busy, live.recorded, onClip, seconds]);

  // C clips, unless you're typing somewhere
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key.toLowerCase() !== "c" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t.closest("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      clip();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clip]);

  const title = live.title || live.url;
  const done = live.clips.filter((c) => c.status === "done").length;
  const working = live.clips.filter((c) => c.status === "queued" || c.status === "rendering").length;

  return (
    <>
      <motion.article className="panel live" layout initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={move}>
        <div className="job-head">
          <div className="live-title">
            <span className={`rec ${recording ? "on" : ""}`}>
              {recording && <motion.span className="rec-ring" animate={{ scale: [1, 2.2], opacity: [0.6, 0] }} transition={{ duration: 1.6, repeat: Infinity, ease: EASE }} />}
              <span className="rec-dot" />
            </span>
            <div>
              <h2 className="heading-6" dir={isRtl(title) ? "rtl" : "auto"}>{title}</h2>
              <span className="caption-5 muted">
                {live.status === "connecting" ? "Connecting" : recording ? "Recording" : live.status === "ended" ? "Stream ended" : live.status === "error" ? "Stopped with an error" : "Stopped"}
                {" · "}<span className="mono">{fmtDur(live.recorded)}</span> recorded
                {" · "}{fmtDur(live.buffered)} in the buffer
                {live.settings?.auto_clips ? " · auto clips on" : ""}
              </span>
            </div>
          </div>
          <AnimatePresence>
            {recording && (
              <motion.button type="button" className="btn button-sm" disabled={stopping} exit={{ opacity: 0 }} whileTap={{ scale: 0.96 }}
                             onClick={async () => { setStopping(true); try { await onStop(); } finally { setStopping(false); } }}>
                <StopCircle size={16} />{stopping ? "Stopping" : "Stop"}
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        <div className="spark-wrap">
          <div className="caption-4 soft spark-label"><Lightning size={14} />Action, last 5 minutes</div>
          <Sparkline values={live.intensity} />
        </div>

        <div className="clip-bar">
          <motion.button type="button" className="btn-primary clip-that button-md" onClick={clip}
                         disabled={!recording || busy || live.recorded < 5}
                         whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }} transition={fast}>
            <AnimatePresence>
              <motion.span key={flash} className="clip-flash" initial={{ scale: 0, opacity: flash ? 0.55 : 0 }}
                           animate={{ scale: 4, opacity: 0 }} transition={{ duration: 0.7, ease: EASE }} />
            </AnimatePresence>
            <Scissors size={20} weight="bold" />
            <span>{busy ? "Clipping" : `Clip that`}</span>
            <kbd className="caption-3">C</kbd>
          </motion.button>
          <div className="seg lengths" role="group" aria-label="Clip length">
            {LENGTHS.map((n) => (
              <button key={n} type="button" className="caption-4" aria-pressed={seconds === n} onClick={() => setSeconds(n)}>
                {seconds === n && <motion.span layoutId="len-bg" className="pill-bg" transition={{ type: "spring", stiffness: 520, damping: 34 }} />}
                <span>last {n}s</span>
              </button>
            ))}
          </div>
        </div>
        <AnimatePresence initial={false}>
          <motion.p key={live.message} className="body-6 soft live-msg" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
            {live.message}{working ? ` · ${working} clip${working > 1 ? "s" : ""} rendering` : ""}{done ? ` · ${done} ready` : ""}
          </motion.p>
        </AnimatePresence>
        <AnimatePresence>
          {(err || live.error) && (
            <motion.div className="job-err body-6" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <WarningCircle size={18} /><span>{err || live.error}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.article>

      {live.clips.length === 0 ? (
        <motion.div className="hist-empty live-empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ ...move, delay: 0.2 }}>
          <Broadcast size={24} />
          <span className="caption-5">Clips show up here. Press <b>Clip that</b> (or C) after a great moment
            {live.settings?.auto_clips ? ", or wait for an auto clip after the first 90 seconds" : ""}.</span>
        </motion.div>
      ) : (
        <motion.div className="grid" variants={stagger(0.08)} initial="hidden" animate="show">
          <AnimatePresence>
            {[...live.clips].reverse().map((c) => <ClipCard key={`${live.id}-${c.index}`} jobId={live.id} clip={asClip(c)} />)}
          </AnimatePresence>
        </motion.div>
      )}
    </>
  );
}
