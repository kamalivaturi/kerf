// Client for the local Kerf engine (python -m kerf serve). Every call except /health carries the token.
import { host, IN_CEP, type RunResult } from "./host";

// The engine's port comes from its locator file (kerf/server.py LOCATOR); same origin when the engine serves the page.
const IN_PANEL = __UXP__ || IN_CEP || import.meta.env.DEV;
let base: Promise<string> | null = null;
const BASE = () => base ??= !IN_PANEL ? Promise.resolve("")
  : (host.locate?.() ?? Promise.resolve({ port: undefined })).catch(() => ({ port: undefined }))
      .then((l: { port?: number }) => `http://127.0.0.1:${l.port || 7878}`);
let token = "";

export const store = {
  get<T>(k: string, d: T): T { try { const v = localStorage.getItem(`kerf.${k}`); return v ? (JSON.parse(v) as T) : d; } catch { return d; } },
  set(k: string, v: unknown) { try { localStorage.setItem(`kerf.${k}`, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

async function headers(): Promise<Record<string, string>> {
  if (!token) token = await host.readToken().catch(() => "");
  return { "Content-Type": "application/json", "X-Kerf-Token": token };
}

async function parse(r: Response) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401) { token = ""; base = null; } // engine restarted (new token, maybe a new port): re-read
    throw new Error(j.error || `${r.status} ${r.statusText}`);
  }
  return j;
}

export const api = {
  async get(path: string) {
    return parse(await fetch((await BASE()) + path, { headers: await headers() }));
  },
  async post(path: string, body: unknown) {
    return parse(await fetch((await BASE()) + path, { method: "POST", headers: await headers(), body: JSON.stringify(body) }));
  },
  async mediaUrl(id: string, kind: "gif" | "mp4" | "png") {
    await headers();
    return `${await BASE()}/mogrt/media?id=${encodeURIComponent(id)}&kind=${kind}&token=${encodeURIComponent(token)}`;
  },
  async health(): Promise<{ ok: boolean; version: string } | null> {
    try {
      const r = await fetch((await BASE()) + "/health");
      return r.ok ? r.json() : null;
    } catch {
      return null;
    }
  },
};

export type Stage = "read" | "run" | "apply";
/** The one way the panel runs a feature: read the timeline when it needs one, POST /run, apply the Result's steps. */
export async function runFeature(feature: string, params: Record<string, unknown>,
  { needsTimeline = true, apply = true, onStage }: { needsTimeline?: boolean; apply?: boolean; onStage?: (s: Stage, res?: RunResult) => void } = {}) {
  let timeline = null;
  if (needsTimeline) { onStage?.("read"); timeline = await host.readTimeline(); }
  onStage?.("run");
  const out_dir = store.get<string>("outDir", "") || (await host.outDir());
  const res: RunResult = await api.post("/run", { feature, timeline, params, out_dir });
  if (!apply) return { res, notes: [] as string[] };
  onStage?.("apply", res);
  return { res, notes: await host.apply(res) };
}
