"use client";
import { motion } from "motion/react";
import { CheckCircle, Cpu, Key, Play, Plugs, Sparkle, Warning } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import type { Health } from "@/lib/api";
import { EASE, riseIn, stagger } from "@/lib/motion";

function Chip({ on, icon, children, keep }: { on: boolean; icon: ReactNode; children: ReactNode; keep?: boolean }) {
  return (
    <motion.span variants={riseIn} className={`chip caption-4 ${on ? "on" : "off"} ${keep ? "key" : ""}`}>
      {on ? icon : <Warning size={16} className="icon" />}{children}
    </motion.span>
  );
}

export function Header({ health }: { health: Health | null | "offline" }) {
  return (
    <motion.header className="topbar" initial={{ opacity: 0, y: -24 }} animate={{ opacity: 1, y: 0 }}
                   transition={{ duration: 0.6, ease: EASE }}>
      <div className="logo">
        <motion.span className="logo-mark" whileHover={{ rotate: -8, scale: 1.08 }} transition={{ type: "spring", stiffness: 400, damping: 15 }}>
          <Play size={14} weight="fill" />
        </motion.span>
        <span className="heading-6">Clipper</span>
      </div>
      {health === null ? (
        <div className="chips"><span className="chip skel" /><span className="chip skel" /><span className="chip skel" /></div>
      ) : health === "offline" ? (
        <div className="chips">
          <span className="chip caption-4 off key"><Plugs size={16} />Server offline. Run start.bat</span>
        </div>
      ) : (
        <motion.div className="chips" variants={stagger(0.05)} initial="hidden" animate="show">
          <Chip on={health.ffmpeg} icon={<CheckCircle size={16} />}>{health.ffmpeg ? "FFmpeg" : "FFmpeg missing"}</Chip>
          <Chip on={health.cuda} icon={<Cpu size={16} />}>
            {health.cuda ? (health.gpu || "GPU").replace("NVIDIA GeForce ", "") : "CPU only"}
          </Chip>
          <Chip on={health.nvenc} icon={<CheckCircle size={16} />}>{health.nvenc ? "NVENC encoder" : "CPU encoder"}</Chip>
          <Chip keep on={health.ollama.running && health.ollama.installed} icon={<Sparkle size={16} />}>
            {!health.ollama.running ? "Ollama not running"
              : health.ollama.installed ? `Local AI ${health.ollama.model}` : `${health.ollama.model} not downloaded`}
          </Chip>
          <Chip on={health.claude_key} icon={<Key size={16} />}>
            {health.claude_key ? `Claude ${health.claude_model}` : "No Claude key"}
          </Chip>
        </motion.div>
      )}
    </motion.header>
  );
}
