"use client";
import { AnimatePresence, motion } from "motion/react";
import { CaretDown, ChartBar, Clock, DownloadSimple, FilmStrip, MusicNotes } from "@phosphor-icons/react";
import { useState } from "react";
import { fileUrl, fmtTime, isRtl, type Clip } from "@/lib/api";
import { EASE, fast, riseIn, spring } from "@/lib/motion";

const LABEL = { pass: "All checks passed", warn: "Passed with warnings", fail: "Failed checks" } as const;

function SkeletonBody({ clip }: { clip: Clip }) {
  return (
    <>
      <div className="vid skel">
        <motion.div className="scan" initial={{ y: "-120%" }} animate={{ y: "420%" }}
                    transition={{ duration: 2.2, repeat: Infinity, ease: EASE }} style={{ top: 0 }} />
        <motion.span animate={{ opacity: [0.5, 1, 0.5] }} transition={{ duration: 1.6, repeat: Infinity, ease: EASE }}>
          <FilmStrip size={24} />
        </motion.span>
        <span className="caption-4">{clip.status === "rendering" ? "Rendering" : "Waiting to render"}</span>
      </div>
      <div className="body">
        <span className="title-3" dir={isRtl(clip.title) ? "rtl" : undefined}>{clip.index}. {clip.title}</span>
        {[70, 45].map((w, i) => (
          <motion.div key={i} className="skel line" style={{ width: `${w}%` }}
                      animate={{ opacity: [1, 0.45, 1] }} transition={{ duration: 1.6, repeat: Infinity, ease: EASE, delay: i * 0.2 }} />
        ))}
      </div>
    </>
  );
}

export function ClipCard({ jobId, clip }: { jobId: string; clip: Clip }) {
  const aspects = Object.keys(clip.outputs);
  const [picked, setPicked] = useState<string | null>(null);
  const aspect = picked && clip.outputs[picked] ? picked : aspects[0];
  const out = aspect ? clip.outputs[aspect] : null;
  const vs = out?.verify.status ?? "pass";
  const [openChecks, setOpenChecks] = useState<boolean | null>(null);
  const showChecks = openChecks ?? vs !== "pass";
  const key = `${jobId}-${clip.index}`;

  return (
    <motion.article className="card" layout variants={riseIn} whileHover={{ y: -4 }} transition={{ layout: { duration: 0.5, ease: EASE } }}>
      {!out ? <SkeletonBody clip={clip} /> : (
        <>
          <div className="atabs" role="group" aria-label="Aspect ratio">
            {aspects.map((a) => (
              <button key={a} type="button" className="caption-4" aria-pressed={a === aspect} onClick={() => setPicked(a)}>
                {a === aspect && <motion.span layoutId={`tab-${key}`} className="tab-bg" transition={spring} />}
                <span><span className={`dot ${clip.outputs[a].verify.status}`} />{a}</span>
              </button>
            ))}
          </div>
          <div className="vid">
            <AnimatePresence mode="wait" initial={false}>
              <motion.video key={aspect} controls preload="metadata" playsInline
                            poster={fileUrl(jobId, out.thumb)} src={fileUrl(jobId, out.file)}
                            initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }}
                            transition={fast} />
            </AnimatePresence>
          </div>
          <div className="body">
            <h3 className="title-3" dir={isRtl(clip.title) ? "rtl" : undefined}>{clip.index}. {clip.title}</h3>
            <p className="body-4 hook" dir={isRtl(clip.hook) ? "rtl" : undefined}>{clip.hook}</p>
            <div className="meta caption-5">
              <span><Clock size={14} /><span className="mono">{fmtTime(clip.start)} to {fmtTime(clip.end)}</span></span>
              <span className="mono">{clip.duration.toFixed(1)}s</span>
              <span><ChartBar size={14} />Score {clip.score}</span>
              {clip.music_file && <span><MusicNotes size={14} />{clip.music_mood}</span>}
            </div>
            {clip.reason && <p className="caption-5 muted">{clip.reason}</p>}
            <div className="verify">
              <button type="button" className="caption-4" aria-expanded={showChecks} onClick={() => setOpenChecks(!showChecks)}>
                <span className={`dot ${vs}`} />{LABEL[vs]}
                {out.verify.attempts && out.verify.attempts > 1 ? `, after ${out.verify.attempts} tries` : ""}
                <motion.span className="chev" style={{ marginLeft: "auto", display: "inline-flex" }} animate={{ rotate: showChecks ? 180 : 0 }} transition={fast}>
                  <CaretDown size={14} />
                </motion.span>
              </button>
              <AnimatePresence initial={false}>
                {showChecks && (
                  <motion.ul className="vlist" initial="hidden" animate="show" exit={{ opacity: 0, transition: fast }}
                             variants={{ hidden: {}, show: { transition: { staggerChildren: 0.03 } } }}>
                    {out.verify.checks.map((c) => (
                      <motion.li key={c.name} className="caption-5" variants={{ hidden: { opacity: 0, x: -8 }, show: { opacity: 1, x: 0, transition: fast } }}>
                        <span className={`dot ${c.status}`} /><span className="k">{c.name}</span><span className="soft">{c.detail}</span>
                      </motion.li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>
            <div className="actions">
              <motion.a className="btn button-sm" href={fileUrl(jobId, out.file)} download whileHover={{ y: -1 }} whileTap={{ scale: 0.97 }} transition={fast}>
                <DownloadSimple size={16} />Download {aspect}
              </motion.a>
            </div>
          </div>
        </>
      )}
    </motion.article>
  );
}
