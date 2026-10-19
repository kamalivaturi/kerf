// Client for the local Kerf engine (python -m kerf serve). Every call except /health carries the token.
import { host } from "./host";

const BASE = __UXP__ || import.meta.env.DEV ? "http://127.0.0.1:7878" : "";
let token = "";

async function headers(): Promise<Record<string, string>> {
  if (!token) token = await host.readToken().catch(() => "");
  return { "Content-Type": "application/json", "X-Kerf-Token": token };
}

async function parse(r: Response) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401) token = ""; // engine restarted with a new token: re-read next time
    throw new Error(j.error || `${r.status} ${r.statusText}`);
  }
  return j;
}

export const api = {
  async get(path: string) {
    return parse(await fetch(BASE + path, { headers: await headers() }));
  },
  async post(path: string, body: unknown) {
    return parse(await fetch(BASE + path, { method: "POST", headers: await headers(), body: JSON.stringify(body) }));
  },
  async health(): Promise<{ ok: boolean; version: string } | null> {
    try {
      const r = await fetch(BASE + "/health");
      return r.ok ? r.json() : null;
    } catch {
      return null;
    }
  },
};
