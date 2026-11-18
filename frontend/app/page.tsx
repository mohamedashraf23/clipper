"use client";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ClipCard } from "@/components/ClipCard";
import { EmptyState } from "@/components/EmptyState";
import { Header } from "@/components/Header";
import { History } from "@/components/History";
import { JobView } from "@/components/JobView";
import { SettingsPanel } from "@/components/SettingsPanel";
import { api, type Health, type JobState, type JobSummary, type Settings } from "@/lib/api";
import { fast, stagger } from "@/lib/motion";

export default function Page() {
  const [health, setHealth] = useState<Health | null | "offline">(null);
  const [jobs, setJobs] = useState<JobSummary[] | null | "error">(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const loadJobs = useCallback(() => api.jobs().then(setJobs).catch(() => setJobs("error")), []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth("offline"));
    loadJobs();
  }, [loadJobs]);

  // poll the open job while it runs
  useEffect(() => {
    if (!current) return;
    let alive = true;
    const tick = async () => {
      try {
        const st = await api.job(current);
        if (!alive) return;
        setJob(st);
        if (st.status === "running" || st.status === "queued") timer.current = setTimeout(tick, 1500);
        else loadJobs();
      } catch {
        if (alive) timer.current = setTimeout(tick, 3000);
      }
    };
    tick();
    return () => { alive = false; clearTimeout(timer.current); };
  }, [current, loadJobs]);

  const open = (id: string) => { if (id !== current) { setJob(null); setCurrent(id); } };

  async function create(settings: Settings, src: { url?: string; file?: File }) {
    const { id } = await api.create(settings, src);
    open(id);
    loadJobs();
  }

  async function remove(id: string) {
    await api.remove(id).catch(() => undefined);
    if (id === current) { setCurrent(null); setJob(null); }
    loadJobs();
  }

  return (
    <MotionConfig reducedMotion="user">
      <a className="skip button-sm" href="#workspace">Skip to clips</a>
      <Header health={health} />
      <main className="layout">
        <aside className="side">
          <SettingsPanel health={health} onSubmit={create} />
          <History jobs={jobs} current={current} onOpen={open} onDelete={remove} />
        </aside>
        <section id="workspace" tabIndex={-1} aria-live="polite">
          <AnimatePresence mode="wait">
            {current ? (
              <motion.div key={current} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: fast }}>
                {job ? (
                  <>
                    <JobView job={job} />
                    <motion.div className="grid" variants={stagger(0.08)} initial="hidden" animate="show">
                      <AnimatePresence>
                        {job.clips.map((c) => <ClipCard key={`${job.id}-${c.index}`} jobId={job.id} clip={c} />)}
                      </AnimatePresence>
                    </motion.div>
                  </>
                ) : (
                  <div className="panel"><div className="skel line" style={{ width: "40%" }} />
                    <div className="steps">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skel" style={{ height: 38 }} />)}</div></div>
                )}
              </motion.div>
            ) : (
              <motion.div key="empty" exit={{ opacity: 0, y: -12, transition: fast }}>
                <EmptyState />
              </motion.div>
            )}
          </AnimatePresence>
        </section>
      </main>
    </MotionConfig>
  );
}
