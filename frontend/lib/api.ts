// Typed client for the FastAPI backend in server.py.
// In production the page is served by that server, so the base is "" (same origin).
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type VerifyStatus = "pass" | "warn" | "fail";
export type JobStatus = "queued" | "running" | "done" | "error" | "interrupted";

export interface Check { name: string; status: VerifyStatus; detail: string }
export interface Output {
  file: string; thumb: string; width: number; height: number;
  verify: { status: VerifyStatus; checks: Check[]; attempts?: number };
}
export interface Clip {
  index: number; slug: string; start: number; end: number; duration: number;
  title: string; hook: string; music_mood: string; score: number; reason: string;
  music_file: string | null; status: "pending" | "rendering" | "done";
  outputs: Record<string, Output>;
}
export interface JobState {
  id: string; source: string; title: string; status: JobStatus; stage: string | null;
  progress: number; message: string; pick_method: string | null; content?: "talk" | "gameplay";
  clips: Clip[]; log: string[]; error: string | null; created: number;
}
export interface JobSummary {
  id: string; title: string; source: string; status: JobStatus; progress: number;
  message: string; created: number; clips: number;
}
export interface Health {
  ffmpeg: boolean; nvenc: boolean; cuda: boolean; gpu?: string | null;
  claude_key: boolean; claude_model: string;
  ollama: { running: boolean; installed: boolean; model: string };
}

export interface Settings {
  n_clips: number; min_len: number; max_len: number; aspects: string[];
  framing: string; facecam: string; content: string;
  captions: boolean; hook_text: boolean; music: boolean; music_volume: number;
  caption_style: string; zoom: string; picker: string; whisper_model: string; language: string;
}

async function json<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail || `The server answered ${res.status}.`);
  return body as T;
}

export const api = {
  health: () => fetch(`${API_BASE}/api/health`).then(json<Health>),
  jobs: () => fetch(`${API_BASE}/api/jobs`).then(json<JobSummary[]>),
  job: (id: string) => fetch(`${API_BASE}/api/jobs/${id}`).then(json<JobState>),
  remove: (id: string) => fetch(`${API_BASE}/api/jobs/${id}`, { method: "DELETE" }).then(json<{ deleted: string }>),
  create: (settings: Settings, source: { url?: string; file?: File }) => {
    const fd = new FormData();
    fd.append("settings", JSON.stringify(settings));
    if (source.file) fd.append("file", source.file);
    else fd.append("url", source.url ?? "");
    return fetch(`${API_BASE}/api/jobs`, { method: "POST", body: fd }).then(json<{ id: string }>);
  },
};

export const fileUrl = (jobId: string, path: string) => `${API_BASE}/files/${jobId}/${path}`;

export const STEPS = [
  { key: "ingest", label: "Import" },
  { key: "transcribe", label: "Transcribe" },
  { key: "pick", label: "Pick" },
  { key: "music", label: "Music" },
  { key: "render", label: "Render" },
  { key: "verify", label: "Verify" },
] as const;

export const isRtl = (s?: string | null) => /[֐-ࣿיִ-﷿ﹰ-﻿]/.test(s || "");
export const fmtTime = (t: number) => {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
