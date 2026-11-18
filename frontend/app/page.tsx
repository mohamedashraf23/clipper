"use client";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ClipCard } from "@/components/ClipCard";
import { EmptyState } from "@/components/EmptyState";
import { Header } from "@/components/Header";
import { History } from "@/components/History";
import { JobView } from "@/components/JobView";
import { LivePanel } from "@/components/LivePanel";
import { SettingsPanel } from "@/components/SettingsPanel";
import { api, type Health, type JobState, type JobSummary, type LiveSettings, type LiveState, type LiveSummary, type Settings } from "@/lib/api";

const isLive = (id: string | null) => !!id && id.startsWith("live-");
const LIVE_AS_JOB: Record<string, JobSummary["status"]> = { connecting: "running", recording: "running", stopped: "done", ended: "done", error: "error" };
/** History shows live sessions next to normal jobs. */
const liveRow = (l: LiveSummary): JobSummary => ({
  id: l.id, title: `● ${l.title || "Live stream"}`, source: l.url, status: LIVE_AS_JOB[l.status] ?? "done",
  progress: 0, message: "", created: l.started, clips: l.clips,
});
import { fast, stagger } from "@/lib/motion";

export default function Page() {
  const [health, setHealth] = useState<Health | null | "offline">(null);
  const [jobs, setJobs] = useState<JobSummary[] | null | "error">(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const [pollKey, setPollKey] = useState(0); // bump to start polling again (a trim re-renders inside the same job)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const loadJobs = useCallback(() => Promise.all([api.jobs(), api.live.list().catch(() => [] as LiveSummary[])])
    .then(([j, l]) => setJobs([...l.map(liveRow), ...j].sort((a, b) => b.created - a.created)))
    .catch(() => setJobs("error")), []);

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
        if (isLive(current)) {
          const ls = await api.live.get(current);
          if (!alive) return;
          setLive(ls);
          const busy = ls.status === "recording" || ls.status === "connecting" ||
                       ls.clips.some((c) => c.status === "queued" || c.status === "rendering");
          if (busy) timer.current = setTimeout(tick, 2000); else loadJobs();
          return;
        }
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
  }, [current, loadJobs, pollKey]);

  const open = (id: string) => { if (id !== current) { setJob(null); setLive(null); setCurrent(id); } };

  async function startLive(url: string, settings: LiveSettings) {
    const { id } = await api.live.start(url, settings);
    open(id);
    loadJobs();
  }
  async function clipLive(seconds: number) {
    if (!live) return;
    await api.live.clip(live.id, seconds);
    setPollKey((k) => k + 1);
  }
  async function stopLive() {
    if (!live) return;
    await api.live.stop(live.id);
    setPollKey((k) => k + 1);
    loadJobs();
  }
  const liveRunning = Array.isArray(jobs) && jobs.some((j) => isLive(j.id) && j.status === "running");

  async function create(settings: Settings, src: { url?: string; file?: File }) {
    const { id } = await api.create(settings, src);
    open(id);
    loadJobs();
  }

  async function rerun(id: string, settings: Settings) {
    const { id: newId } = await api.rerun(id, settings);
    open(newId);
    loadJobs();
  }

  async function cancel(id: string) {
    await api.cancel(id);
    setPollKey((k) => k + 1);
  }

  async function trim(index: number, start: number, end: number) {
    if (!job) return;
    await api.trim(job.id, index, start, end);
    setPollKey((k) => k + 1);
    loadJobs();
  }

  const jobBusy = !!job && (job.status === "running" || job.status === "queued");

  const rerunTarget = job && job.status !== "running" && job.status !== "queued"
    ? { id: job.id, title: job.title || job.origin || job.source } : null;

  async function remove(id: string) {
    await (isLive(id) ? api.live.remove(id) : api.remove(id)).catch(() => undefined);
    if (id === current) { setCurrent(null); setJob(null); setLive(null); }
    loadJobs();
  }

  return (
    <MotionConfig reducedMotion="user">
      <a className="skip button-sm" href="#workspace">Skip to clips</a>
      <Header health={health} />
      <main className="layout">
        <aside className="side">
          <SettingsPanel health={health} onSubmit={create} rerunTarget={rerunTarget} onRerun={rerun}
                         onStartLive={startLive} liveRunning={liveRunning} />
          <History jobs={jobs} current={current} onOpen={open} onDelete={remove} />
        </aside>
        <section id="workspace" tabIndex={-1} aria-live="polite">
          <AnimatePresence mode="wait">
            {current ? (
              <motion.div key={current} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: fast }}>
                {isLive(current) ? (live ? <LivePanel live={live} onClip={clipLive} onStop={stopLive} /> : (
                  <div className="panel"><div className="skel line" style={{ width: "40%" }} /></div>
                )) : job ? (
                  <>
                    <JobView job={job} onCancel={cancel} />
                    <motion.div className="grid" variants={stagger(0.08)} initial="hidden" animate="show">
                      <AnimatePresence>
                        {job.clips.map((c) => (
                          <ClipCard key={`${job.id}-${c.index}`} jobId={job.id} clip={c} busy={jobBusy}
                                    sourceDuration={job.source_meta?.duration} onTrim={trim} />
                        ))}
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
