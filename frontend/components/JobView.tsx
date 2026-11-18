"use client";
import { AnimatePresence, motion } from "motion/react";
import {
  Check, DownloadSimple, FilmStrip, GameController, MusicNotes, SealCheck, Sparkle, StopCircle, TerminalWindow, Waveform, WarningCircle, X,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { isRtl, STEPS, type JobState } from "@/lib/api";
import { EASE, fast, move } from "@/lib/motion";
import { AnimatedNumber } from "./controls";

const STEP_ICON: Record<string, ReactNode> = {
  ingest: <DownloadSimple size={12} />, transcribe: <Waveform size={12} />, pick: <Sparkle size={12} />,
  music: <MusicNotes size={12} />, render: <FilmStrip size={12} />, verify: <SealCheck size={12} />,
};

function Stepper({ job }: { job: JobState }) {
  const idx = STEPS.findIndex((s) => s.key === job.stage);
  return (
    <div className="steps">
      {STEPS.map((s, i) => {
        let state = "";
        if (job.status === "done" || i < idx) state = "done";
        else if (i === idx && job.status === "running") state = "active";
        else if (i === idx && (job.status === "error" || job.status === "interrupted" || job.status === "cancelled")) state = "failed";
        return (
          <motion.div key={s.key} className={`step ${state}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ ...move, delay: i * 0.05 }}>
            <span className="k">
              {state === "active" && (
                <motion.span className="ring" initial={{ scale: 0.8, opacity: 0.7 }} animate={{ scale: 1.5, opacity: 0 }}
                             transition={{ duration: 1.4, repeat: Infinity, ease: EASE }} />
              )}
              <AnimatePresence mode="wait" initial={false}>
                <motion.span key={state} style={{ display: "inline-flex" }}
                             initial={{ scale: 0, rotate: -45 }} animate={{ scale: 1, rotate: 0 }} exit={{ scale: 0 }}
                             transition={{ type: "spring", stiffness: 600, damping: 22 }}>
                  {state === "done" ? <Check size={12} weight="bold" /> : state === "failed" ? <X size={12} weight="bold" /> : STEP_ICON[s.key]}
                </motion.span>
              </AnimatePresence>
            </span>
            <span className="caption-4">{s.label}</span>
          </motion.div>
        );
      })}
    </div>
  );
}

function ProgressBar({ job }: { job: JobState }) {
  const cls = job.status === "error" ? "error" : job.status === "done" ? "done" : "";
  return (
    <div className={`bar ${cls}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)}>
      <motion.div className="fill" initial={{ scaleX: 0 }} animate={{ scaleX: job.progress || 0 }}
                  transition={{ type: "spring", stiffness: 60, damping: 20 }} />
      {job.status === "running" && (
        <motion.div className="sheen" initial={{ x: "-100%" }} animate={{ x: "500%" }}
                    transition={{ duration: 1.8, repeat: Infinity, ease: EASE, repeatDelay: 0.4 }} />
      )}
    </div>
  );
}

export function JobView({ job, onCancel }: { job: JobState; onCancel?: (id: string) => Promise<void> }) {
  const [cancelling, setCancelling] = useState(false);
  const active = job.status === "running" || job.status === "queued";
  useEffect(() => { if (!active) setCancelling(false); }, [active]);
  const logRef = useRef<HTMLPreElement>(null);
  const title = job.title || job.source;
  useEffect(() => {
    const el = logRef.current;
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 40) el.scrollTop = el.scrollHeight;
  }, [job.log.length]);

  return (
    <motion.article className="panel" layout initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={move}>
      <div className="job-head">
        <AnimatePresence mode="wait">
          <motion.h2 key={title} className="heading-6" dir={isRtl(title) ? "rtl" : "auto"}
                     initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
            {title}
          </motion.h2>
        </AnimatePresence>
        <AnimatePresence>
          {job.pick_method && (
            <motion.span className="badge caption-4" initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }}
                         transition={{ type: "spring", stiffness: 500, damping: 25 }}>
              {job.content === "gameplay" ? <GameController size={14} /> : <Sparkle size={14} />}Picked by {job.pick_method}
            </motion.span>
          )}
        </AnimatePresence>
      </div>
      <Stepper job={job} />
      <ProgressBar job={job} />
      <div className="status-line">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={job.message} className="msg body-6 soft" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                       exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.25, ease: EASE }}>
            {job.message}
          </motion.span>
        </AnimatePresence>
        <span className="status-right">
          <span className="body-5 mono">
            {job.status === "running" ? <AnimatedNumber value={Math.round(job.progress * 100)} suffix="%" /> : job.status === "queued" ? "Queued" : job.status === "cancelled" ? "Cancelled" : ""}
          </span>
          <AnimatePresence>
            {active && onCancel && (
              <motion.button type="button" className="btn button-sm" disabled={cancelling}
                             initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9 }}
                             whileTap={{ scale: 0.96 }} transition={fast}
                             onClick={async () => { setCancelling(true); try { await onCancel(job.id); } catch { setCancelling(false); } }}>
                <StopCircle size={16} />{cancelling ? "Cancelling" : "Cancel"}
              </motion.button>
            )}
          </AnimatePresence>
        </span>
      </div>
      <AnimatePresence>
        {job.error && (
          <motion.div className="job-err body-6" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
            <WarningCircle size={18} /><span>{job.error}. The full trace is in the log below.</span>
          </motion.div>
        )}
      </AnimatePresence>
      <details className="log">
        <summary className="caption-4"><TerminalWindow size={14} />Log</summary>
        <pre ref={logRef}>{job.log.join("\n")}</pre>
      </details>
    </motion.article>
  );
}
