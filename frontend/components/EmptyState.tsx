"use client";
import { motion } from "motion/react";
import { FilmSlate, SealCheck, Sparkle, Waveform } from "@phosphor-icons/react";
import { EASE, riseIn, stagger } from "@/lib/motion";

const LINES = ["Turn one long video", "into clips ready to post"];

const STEPS = [
  { icon: <Waveform size={20} />, title: "Transcribe", text: "Word level timing on your GPU, any language." },
  { icon: <Sparkle size={20} />, title: "Pick moments", text: "Local AI reads the transcript, or the action in gameplay, and writes a hook." },
  { icon: <SealCheck size={20} />, title: "Render and verify", text: "Captions, music, loudness and length checked on every file." },
];

export function EmptyState() {
  let w = 0;
  return (
    <motion.div className="empty" initial="hidden" animate="show" variants={stagger(0.08, 0.2)}>
      <motion.div className="mark" variants={riseIn}>
        <motion.span style={{ display: "inline-flex" }} animate={{ y: [0, -4, 0], rotate: [0, -6, 0] }}
                     transition={{ duration: 3.2, repeat: Infinity, ease: EASE }}>
          <FilmSlate size={24} />
        </motion.span>
      </motion.div>
      {/* words light up one at a time, from muted to full colour */}
      <h1 className="heading-4" aria-label={LINES.join(" ")}>
        {LINES.map((line, li) => (
          <span key={li} style={{ display: "block" }} aria-hidden>
            {line.split(" ").map((word, i, arr) => {
              const d = 0.35 + w++ * 0.07;
              return (
                <motion.span key={i} className="w" initial={{ opacity: 0.25, y: 10 }} animate={{ opacity: 1, y: 0 }}
                             transition={{ duration: 0.6, ease: EASE, delay: d }}>
                  {word}{i < arr.length - 1 ? " " : ""}
                </motion.span>
              );
            })}
          </span>
        ))}
      </h1>
      <motion.p className="body-3" variants={riseIn}>
        Paste a link or drop a file on the left. Clipper finds the strongest moments, adds captions and music, renders every aspect
        ratio and checks each file before you download it.
      </motion.p>
      <motion.div className="flow" variants={stagger(0.1, 0.9)}>
        {STEPS.map((s) => (
          <motion.div key={s.title} variants={riseIn} whileHover={{ y: -4, borderColor: "#4a4a44" }}>
            {s.icon}<span className="title-4">{s.title}</span><span className="caption-5 muted">{s.text}</span>
          </motion.div>
        ))}
      </motion.div>
    </motion.div>
  );
}
