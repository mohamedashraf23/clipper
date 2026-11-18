"use client";
import { AnimatePresence, motion } from "motion/react";
import { ClockCounterClockwise, Plugs, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { isRtl, type JobSummary } from "@/lib/api";
import { fast, move } from "@/lib/motion";

const DOT: Record<string, string> = { done: "pass", error: "fail", interrupted: "fail" };

function DeleteButton({ onConfirm }: { onConfirm: () => void }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <motion.button type="button" layout className={`btn ${armed ? "danger" : "icon"}`} aria-label={armed ? "Confirm delete" : "Delete job"}
                   onClick={(e) => { e.stopPropagation(); if (armed) onConfirm(); else setArmed(true); }}
                   whileTap={{ scale: 0.94 }} transition={fast}>
      <Trash size={16} />
      <AnimatePresence>{armed && (
        <motion.span className="button-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>Delete</motion.span>
      )}</AnimatePresence>
    </motion.button>
  );
}

export function History({ jobs, current, onOpen, onDelete }: {
  jobs: JobSummary[] | null | "error"; current: string | null;
  onOpen: (id: string) => void; onDelete: (id: string) => void;
}) {
  const list = Array.isArray(jobs) ? jobs : [];
  return (
    <motion.nav className="panel" aria-labelledby="histh" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
                transition={{ ...move, delay: 0.5 }}>
      <div className="hist-h">
        <h2 className="title-3" id="histh">History</h2>
        {list.length > 0 && <span className="caption-5 muted">{list.length} {list.length === 1 ? "job" : "jobs"}</span>}
      </div>
      {jobs === null ? (
        <div className="hlist"><div className="skel line" /><div className="skel line" /></div>
      ) : jobs === "error" ? (
        <div className="hist-empty"><Plugs size={24} /><span className="caption-5">History couldn&apos;t load. Check that the server is running.</span></div>
      ) : list.length === 0 ? (
        <div className="hist-empty"><ClockCounterClockwise size={24} />
          <span className="caption-5">Finished jobs show up here so you can reopen and download them later.</span></div>
      ) : (
        <motion.div className="hlist" layout>
          <AnimatePresence initial={false}>
            {list.map((j, i) => {
              const t = j.title || j.source;
              return (
                <motion.div key={j.id} layout role="button" tabIndex={0} className={`hitem ${j.id === current ? "sel" : ""}`}
                            initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0, transition: { ...move, delay: Math.min(i, 8) * 0.04 } }}
                            exit={{ opacity: 0, x: 24, transition: fast }}
                            onClick={() => onOpen(j.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(j.id); } }}>
                  <div className="l">
                    <span className="ti body-5" dir={isRtl(t) ? "rtl" : undefined}>{t}</span>
                    <span className="caption-5 muted">
                      {new Date(j.created * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {j.clips} clips
                    </span>
                  </div>
                  <div className="r">
                    {j.status === "running" || j.status === "queued" ? (
                      <motion.span className="dot warn" animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 1.4, repeat: Infinity, ease: [0.22, 1, 0.36, 1] }} />
                    ) : (
                      <>
                        <span className={`dot ${DOT[j.status] || "warn"}`} title={j.status} />
                        <DeleteButton onConfirm={() => onDelete(j.id)} />
                      </>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </motion.div>
      )}
    </motion.nav>
  );
}
