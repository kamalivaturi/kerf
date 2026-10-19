import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { host, IN_UXP, RunResult, setStandaloneMedia } from "./host";

type Params = Record<string, string | number | boolean>;
type Feature = {
  title: string; group: string; defaults: Params; choices: Record<string, string[]>; help: string; tier: string;
  review: boolean; entitled: boolean; needs_timeline: boolean; presets: { builtin: string[]; user: string[] };
};
type Theme = "auto" | "light" | "dark";
type Item = { id: number; label: string };
type Prefs = { theme: Theme; accent: string; density: "compact" | "comfortable"; fontSize: number; favorites: string[]; showHelp: boolean };
type HistoryEntry = { feature: string; title: string; at: number; notes: string[]; params: Params; ok: boolean };

const GROUP_ORDER = ["★", "AI", "Import", "Cut", "Style", "Audio", "Multicam", "Repurpose", "Export"];
const HIDDEN = new Set(["preview", "items", "plan_only"]);
const LONG = new Set(["prompt", "steps", "extra_words", "urls"]);
const FILES = new Set(["srt_import", "mogrt", "sound", "watermark", "folder", "output"]);
const ACCENTS = ["#ff5a36", "#3d7cff", "#13b07a", "#a64dff", "#ff3d7f", "#f5a623"];
const DEFAULT_PREFS: Prefs = { theme: "auto", accent: ACCENTS[0], density: "comfortable", fontSize: 12, favorites: [], showHelp: true };

const store = {
  get<T>(k: string, d: T): T { try { const v = localStorage.getItem(`kerf.${k}`); return v ? (JSON.parse(v) as T) : d; } catch { return d; } },
  set(k: string, v: unknown) { try { localStorage.setItem(`kerf.${k}`, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
const label = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const rank = (g: string) => { const i = GROUP_ORDER.indexOf(g); return i < 0 ? 99 : i; };
const ago = (t: number) => { const s = Math.round((Date.now() - t) / 1000); return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : new Date(t).toLocaleString(); };

function usePrefs(): [Prefs, (p: Partial<Prefs>) => void] {
  const [prefs, setPrefs] = useState<Prefs>({ ...DEFAULT_PREFS, ...store.get<Partial<Prefs>>("prefs", {}) });
  useEffect(() => {
    const apply = () => {
      let dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
      const uxpTheme = (document as any).theme?.getCurrent?.(); // UXP host theme: darkest|dark|medium|light|lightest
      if (uxpTheme) dark = !String(uxpTheme).includes("light");
      const root = document.documentElement;
      root.dataset.theme = prefs.theme === "auto" ? (dark ? "dark" : "light") : prefs.theme;
      root.dataset.density = prefs.density;
      root.style.setProperty("--accent", prefs.accent);
      root.style.setProperty("--fs", `${prefs.fontSize}px`);
    };
    apply();
    store.set("prefs", prefs);
    document.addEventListener("uxpthemechange", apply);
    return () => document.removeEventListener("uxpthemechange", apply);
  }, [prefs]);
  return [prefs, (p) => setPrefs((cur) => ({ ...cur, ...p }))];
}

function ThemePicker({ prefs, set }: { prefs: Prefs; set: (p: Partial<Prefs>) => void }) {
  return (
    <select className="theme" value={prefs.theme} onChange={(e) => set({ theme: e.target.value as Theme })} aria-label="Theme">
      <option value="auto">◐ Auto</option><option value="light">☀ Light</option><option value="dark">☾ Dark</option>
    </select>
  );
}

export default function App() {
  const [prefs, setPrefs] = usePrefs();
  const [engine, setEngine] = useState<string | null>(null);
  const [features, setFeatures] = useState<Record<string, Feature>>({});
  const [group, setGroup] = useState(store.get("group", "Cut"));
  const [name, setName] = useState(store.get("feature", "silences"));
  const [query, setQuery] = useState("");
  const [params, setParams] = useState<Params>({});
  const [items, setItems] = useState<Item[] | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<RunResult | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [started, setStarted] = useState(0);
  const [, tick] = useState(0);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState<"" | "settings" | "history">("");
  const [history, setHistory] = useState<HistoryEntry[]>(store.get("history", []));
  const [update, setUpdate] = useState<{ latest: string; url: string } | null>(null);
  const [media, setMedia] = useState(store.get("media", ""));
  const applyRef = useRef<() => void>(() => {});

  const f = features[name];
  const fav = (k: string) => prefs.favorites.includes(k);
  const groups = useMemo(() => {
    const gs = Array.from(new Set(Object.values(features).map((x) => x.group)));
    if (prefs.favorites.length) gs.push("★");
    return gs.sort((a, b) => rank(a) - rank(b));
  }, [features, prefs.favorites.length]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.entries(features).filter(([k, x]) => q
      ? `${x.title} ${x.help} ${k}`.toLowerCase().includes(q)
      : group === "★" ? fav(k) : x.group === group);
  }, [features, group, query, prefs.favorites]);

  async function connect() {
    const h = await api.health();
    setEngine(h ? h.version : null);
    if (!h) return;
    try {
      setFeatures((await api.get("/features")).features);
      api.get("/update").then((u) => u.update_available && setUpdate(u)).catch(() => {});
    } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => {
    connect();
    const t = setInterval(() => { if (!engine) connect(); }, 4000);
    return () => clearInterval(t);
  }, [engine]);
  useEffect(() => { if (f) { setParams({ ...f.defaults }); reset(); } store.set("feature", name); }, [name, !!f]);
  useEffect(() => { store.set("group", group); }, [group]);
  useEffect(() => { store.set("media", media); setStandaloneMedia(paths()); }, [media]);
  useEffect(() => { if (!busy) return; const t = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(t); }, [busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") applyRef.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const paths = () => media.split("\n").map((s) => s.trim()).filter(Boolean);
  function reset() { setItems(null); setResult(null); setNotes([]); setError(""); }
  function pickGroup(g: string) {
    setGroup(g);
    setQuery("");
    const inGroup = (k: string) => (g === "★" ? fav(k) : features[k]?.group === g);
    if (!inGroup(name)) { const first = Object.keys(features).find(inGroup); if (first) setName(first); }
  }
  function toggleFav(k: string) {
    setPrefs({ favorites: fav(k) ? prefs.favorites.filter((x) => x !== k) : [...prefs.favorites, k] });
  }
  function remember(entry: HistoryEntry) {
    const next = [entry, ...history].slice(0, 30);
    setHistory(next);
    store.set("history", next);
  }

  async function run(analyze: boolean) {
    if (!f || busy) return;
    reset();
    const p: Params = { ...params };
    if (analyze) p[name === "prompt_edit" ? "plan_only" : "preview"] = true;
    else if (items) p.items = [...checked].join(",") || "-1";
    setStarted(Date.now());
    try {
      if (!IN_UXP && f.needs_timeline && paths().length > 1 && !analyze) {
        setBusy(`Batch: ${paths().length} files`);
        setResult({ report: await api.post("/batch", { feature: name, paths: paths(), params: p }) });
        return;
      }
      let timeline = null;
      if (f.needs_timeline) { setBusy("Reading timeline"); timeline = await host.readTimeline(); }
      setBusy(analyze ? "Analyzing" : name === "download" ? "Downloading" : `Running ${f.title}`);
      const out_dir = store.get<string>("outDir", "") || (await host.outDir());
      const res: RunResult = await api.post("/run", { feature: name, timeline, params: p, out_dir });
      if (analyze) {
        setItems(res.items || []);
        setChecked(new Set((res.items || []).map((i) => i.id)));
        setResult({ report: res.report });
        return;
      }
      setBusy("Applying");
      setResult(res);
      const n = await host.apply(res);
      setNotes(n);
      setItems(null);
      remember({ feature: name, title: f.title, at: Date.now(), notes: n, params: { ...params }, ok: true });
    } catch (e) {
      setError((e as Error).message);
      if (!analyze) remember({ feature: name, title: f.title, at: Date.now(), notes: [(e as Error).message], params: { ...params }, ok: false });
    } finally {
      setBusy("");
    }
  }
  applyRef.current = () => run(false);

  if (!engine) return <Offline onRetry={connect} prefs={prefs} setPrefs={setPrefs} />;

  return (
    <div className="app">
      <header className="top">
        <div className="brand"><span className="logo">K</span> Kerf</div>
        <span className="status ok" title={`Engine ${engine}`}>● {engine}</span>
        <ThemePicker prefs={prefs} set={setPrefs} />
        <button className={`ghost icon ${panel === "history" ? "on" : ""}`} onClick={() => setPanel(panel === "history" ? "" : "history")} aria-label="History" title="History">⟲</button>
        <button className={`ghost icon ${panel === "settings" ? "on" : ""}`} onClick={() => setPanel(panel === "settings" ? "" : "settings")} aria-label="Settings" title="Settings">⚙</button>
      </header>

      {update && <div className="banner">Kerf {update.latest} is available. <a href={update.url} target="_blank" rel="noreferrer">Get update</a></div>}
      {panel === "settings" && <Settings prefs={prefs} setPrefs={setPrefs} onClose={() => setPanel("")} />}
      {panel === "history" && <History entries={history} onLoad={(h) => { setName(h.feature); setGroup(features[h.feature]?.group || group); setTimeout(() => setParams(h.params), 0); setPanel(""); }}
        onClear={() => { setHistory([]); store.set("history", []); }} onClose={() => setPanel("")} />}

      {!IN_UXP && f?.needs_timeline !== false && (
        <section className="card source">
          <label htmlFor="media">Media file(s) <small>one path per line; several = batch</small></label>
          <textarea id="media" rows={2} value={media} onChange={(e) => setMedia(e.target.value)} placeholder="C:\Videos\interview.mp4" />
        </section>
      )}

      <div className="search">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search features…  (Ctrl+Enter applies)" aria-label="Search features" />
      </div>
      {!query && (
        <nav className="tabs">
          {groups.map((g) => <button key={g} className={g === group ? "on" : ""} onClick={() => pickGroup(g)}>{g}</button>)}
        </nav>
      )}
      <div className="chips">
        {visible.map(([k, x]) => (
          <button key={k} className={k === name ? "chip on" : "chip"} onClick={() => setName(k)}>
            {fav(k) && <span className="star">★</span>}{x.title}{x.tier !== "free" && <em className="tier">{x.tier}</em>}
          </button>
        ))}
        {!visible.length && <span className="help">No features match.</span>}
      </div>

      {f && (
        <main className="card fade" key={name}>
          <h2>
            {f.title}
            <button className={`ghost icon fav ${fav(name) ? "on" : ""}`} onClick={() => toggleFav(name)}
              aria-label={fav(name) ? "Remove from favorites" : "Add to favorites"} title="Favorite">{fav(name) ? "★" : "☆"}</button>
          </h2>
          {prefs.showHelp && <p className="help">{f.help}</p>}
          <Presets feature={name} f={f} params={params} setParams={setParams} reload={connect} />
          <Form f={f} params={params} setParams={setParams} />
          <div className="actions">
            <button className="ghost" onClick={() => setParams({ ...f.defaults })} title="Reset to defaults">Reset</button>
            {f.review && <button disabled={!!busy} onClick={() => run(true)}>{name === "prompt_edit" ? "Plan" : "Analyze"}</button>}
            <button className="primary" disabled={!!busy || !f.entitled} onClick={() => run(false)}>
              {f.entitled ? (items ? `Apply ${checked.size} selected` : name === "download" ? "Download" : "Apply") : `Requires ${f.tier}`}
            </button>
          </div>
          {busy && <div className="busy"><span className="spinner" /> {busy}… <span className="elapsed">{Math.round((Date.now() - started) / 1000)}s</span></div>}
          {error && <div className="error">{error}</div>}
          {items && <Review items={items} checked={checked} setChecked={setChecked} />}
          {result && <Result res={result} notes={notes} onUse={!IN_UXP ? (p) => { setMedia(p); pickGroup("Cut"); } : undefined} />}
        </main>
      )}
    </div>
  );
}

function Form({ f, params, setParams }: { f: Feature; params: Params; setParams: (p: Params) => void }) {
  const set = (k: string, v: string | number | boolean) => setParams({ ...params, [k]: v });
  return (
    <div className="form">
      {Object.keys(f.defaults).filter((k) => !HIDDEN.has(k)).map((k) => {
        const d = f.defaults[k], v = params[k] ?? d;
        const changed = String(v) !== String(d);
        const cls = `row${changed ? " changed" : ""}`;
        if (typeof d === "boolean")
          return <label key={k} className={`${cls} check`}><input type="checkbox" checked={!!v} onChange={(e) => set(k, e.target.checked)} />{label(k)}</label>;
        if (f.choices[k])
          return <label key={k} className={cls}>{label(k)}<select value={String(v)} onChange={(e) => set(k, e.target.value)}>
            {f.choices[k].map((c) => <option key={c} value={c}>{c || "—"}</option>)}</select></label>;
        if (LONG.has(k))
          return <label key={k} className={`${cls} col`}>{label(k)}<textarea rows={k === "prompt" || k === "urls" ? 4 : 3} value={String(v)} onChange={(e) => set(k, e.target.value)}
            placeholder={k === "prompt" ? "e.g. Cut the dead air, add bold yellow captions, punch-in zooms, and make a vertical Short"
              : k === "urls" ? "https://… (one link per line: videos, playlists, channels)" : ""} /></label>;
        if (typeof d === "number")
          return <label key={k} className={cls}>{label(k)}<input type="number" step="any" value={String(v)} onChange={(e) => set(k, e.target.value)} /></label>;
        if (/color/.test(k))
          return <label key={k} className={cls}>{label(k)}<span className="color"><input type="text" value={String(v)} onChange={(e) => set(k, e.target.value)} />
            <i style={{ background: String(v).split(",")[0] }} /></span></label>;
        return <label key={k} className={cls}>{label(k)}<span className="file"><input type="text" value={String(v)} onChange={(e) => set(k, e.target.value)} />
          {FILES.has(k) && host.pickFile && <button className="ghost" onClick={async () => { const p = await host.pickFile!(); if (p) set(k, p); }}>…</button>}</span></label>;
      })}
    </div>
  );
}

function Presets({ feature, f, params, setParams, reload }: {
  feature: string; f: Feature; params: Params; setParams: (p: Params) => void; reload: () => void;
}) {
  const [sel, setSel] = useState("");
  const [saveAs, setSaveAs] = useState("");
  async function load(n: string) { setSel(n); if (n) setParams(await api.get(`/presets?feature=${feature}&name=${encodeURIComponent(n)}`)); }
  async function save() { if (!saveAs.trim()) return; await api.post("/presets", { feature, name: saveAs.trim(), params }); setSel(saveAs.trim()); setSaveAs(""); reload(); }
  async function del() { await api.post("/presets/delete", { feature, name: sel }); setSel(""); reload(); }
  return (
    <div className="presets">
      <select value={sel} onChange={(e) => load(e.target.value)} aria-label="Preset">
        <option value="">Preset…</option>
        {f.presets.builtin.length > 0 && <optgroup label="Built-in">{f.presets.builtin.map((p) => <option key={p}>{p}</option>)}</optgroup>}
        {f.presets.user.length > 0 && <optgroup label="Mine">{f.presets.user.map((p) => <option key={p}>{p}</option>)}</optgroup>}
      </select>
      {f.presets.user.includes(sel) && <button className="ghost" onClick={del} title="Delete preset" aria-label="Delete preset">✕</button>}
      <input value={saveAs} onChange={(e) => setSaveAs(e.target.value)} placeholder="Save current as…" aria-label="New preset name"
        onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
      <button className="ghost" onClick={save} disabled={!saveAs.trim()}>Save</button>
    </div>
  );
}

function Review({ items, checked, setChecked }: { items: Item[]; checked: Set<number>; setChecked: (s: Set<number>) => void }) {
  const [filter, setFilter] = useState("");
  const toggle = (id: number) => { const s = new Set(checked); if (s.has(id)) s.delete(id); else s.add(id); setChecked(s); };
  const shown = items.filter((i) => i.label.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="review fade">
      <div className="review-head">
        <b>{checked.size}/{items.length} selected</b>
        {items.length > 8 && <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" aria-label="Filter results" />}
        <button className="ghost" onClick={() => setChecked(new Set(items.map((i) => i.id)))}>All</button>
        <button className="ghost" onClick={() => setChecked(new Set())}>None</button>
      </div>
      <ul>{shown.map((i) => (
        <li key={i.id} className={checked.has(i.id) ? "" : "off"}><label><input type="checkbox" checked={checked.has(i.id)} onChange={() => toggle(i.id)} /> {i.label}</label></li>
      ))}</ul>
    </div>
  );
}

function Result({ res, notes, onUse }: { res: RunResult; notes: string[]; onUse?: (path: string) => void }) {
  return (
    <div className="result fade">
      {notes.map((n) => <div key={n} className="note">✓ {n}</div>)}
      {onUse && res.imports?.map((p) => (
        <div key={p} className="use"><span>{p.split(/[\\/]/).pop()}</span><button className="ghost" onClick={() => onUse(p)}>Use in Kerf →</button></div>
      ))}
      {res.text && <div className="textout"><pre>{res.text}</pre>
        <button className="ghost" onClick={() => navigator.clipboard?.writeText(res.text!)}>Copy</button></div>}
      {res.report && <details open><summary>Report</summary><pre>{JSON.stringify(res.report, null, 1)}</pre></details>}
      {!!res.files?.length && <details><summary>Files ({res.files.length})</summary><pre>{res.files.join("\n")}</pre></details>}
    </div>
  );
}

function History({ entries, onLoad, onClear, onClose }: {
  entries: HistoryEntry[]; onLoad: (h: HistoryEntry) => void; onClear: () => void; onClose: () => void;
}) {
  return (
    <section className="card fade">
      <h2>History <button className="ghost" onClick={onClear} disabled={!entries.length}>Clear</button>
        <button className="ghost close" onClick={onClose} aria-label="Close history">✕</button></h2>
      {!entries.length && <p className="help">Runs you apply show up here so you can repeat them with the same settings.</p>}
      <ul className="history">{entries.map((h, i) => (
        <li key={i} className={h.ok ? "" : "failed"}>
          <div><b>{h.title}</b> <small>{ago(h.at)}</small><div className="help">{h.notes[0] || ""}</div></div>
          <button className="ghost" onClick={() => onLoad(h)}>Load settings</button>
        </li>
      ))}</ul>
    </section>
  );
}

const SETTING_FIELDS: [string, string, string[]?][] = [
  ["ai_provider", "AI provider", ["claude", "openai", "gemini", "local"]],
  ["claude_model", "Claude model"], ["anthropic_api_key", "Anthropic API key"],
  ["openai_model", "OpenAI / Codex model"], ["openai_api_key", "OpenAI API key"],
  ["gemini_model", "Gemini model"], ["gemini_api_key", "Gemini API key"],
  ["local_llm_url", "Local LLM URL (Ollama…)"], ["local_llm_model", "Local model"],
  ["elevenlabs_api_key", "ElevenLabs API key"], ["pexels_api_key", "Pexels API key"],
  ["whisper_model", "Whisper model or fine-tuned path"], ["whisper_device", "Whisper device", ["auto", "cuda", "cpu"]],
];

function Settings({ prefs, setPrefs, onClose }: { prefs: Prefs; setPrefs: (p: Partial<Prefs>) => void; onClose: () => void }) {
  const [s, setS] = useState<Record<string, string>>({});
  const [lic, setLic] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);
  const [tab, setTab] = useState<"look" | "ai" | "paths">("look");
  useEffect(() => { api.get("/settings").then(setS); api.get("/license").then(setLic); }, []);
  async function save() { setS(await api.post("/settings", s)); setSaved(true); setTimeout(() => setSaved(false), 1500); }
  return (
    <section className="card settings fade">
      <h2>Settings <button className="ghost close" onClick={onClose} aria-label="Close settings">✕</button></h2>
      <nav className="tabs small">
        {(["look", "ai", "paths"] as const).map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
          {t === "look" ? "Appearance" : t === "ai" ? "AI & keys" : "Folders"}</button>)}
      </nav>
      {tab === "look" && <>
        <label className="row">Theme<ThemePicker prefs={prefs} set={setPrefs} /></label>
        <div className="row">Accent<span className="swatches">
          {ACCENTS.map((c) => <button key={c} className={`swatch ${prefs.accent === c ? "on" : ""}`} style={{ background: c }} onClick={() => setPrefs({ accent: c })} aria-label={`Accent ${c}`} />)}
          <input type="text" value={prefs.accent} onChange={(e) => /^#[0-9a-f]{6}$/i.test(e.target.value) && setPrefs({ accent: e.target.value })} aria-label="Custom accent hex" />
        </span></div>
        <label className="row">Density<select value={prefs.density} onChange={(e) => setPrefs({ density: e.target.value as Prefs["density"] })}>
          <option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
        <label className="row">Text size <b>{prefs.fontSize}px</b><input type="range" min={10} max={16} value={prefs.fontSize} onChange={(e) => setPrefs({ fontSize: Number(e.target.value) })} /></label>
        <label className="row check"><input type="checkbox" checked={prefs.showHelp} onChange={(e) => setPrefs({ showHelp: e.target.checked })} />Show feature descriptions</label>
        <div className="actions"><button className="ghost" onClick={() => setPrefs({ ...DEFAULT_PREFS, favorites: prefs.favorites })}>Reset appearance</button></div>
      </>}
      {tab === "ai" && <>
        {SETTING_FIELDS.map(([k, l, ch]) => (
          <label key={k} className="row">{l}
            {ch ? <select value={s[k] || ""} onChange={(e) => setS({ ...s, [k]: e.target.value })}>{ch.map((c) => <option key={c}>{c}</option>)}</select>
              : <input type={k.endsWith("_key") ? "password" : "text"} value={s[k] || ""} onChange={(e) => setS({ ...s, [k]: e.target.value })} />}
          </label>
        ))}
        <div className="actions"><button className="primary" onClick={save}>{saved ? "Saved ✓" : "Save settings"}</button></div>
        <p className="help">Keys stay on this computer (~/.kerf/settings.json). Edition: {String(lic.edition ?? "…")} · plan {String(lic.plan ?? "…")}</p>
      </>}
      {tab === "paths" && <>
        <label className="row">Output folder<input defaultValue={store.get("outDir", "")} onChange={(e) => store.set("outDir", e.target.value)} placeholder="next to the project" /></label>
        {IN_UXP && <label className="row">Kerf folder<input defaultValue={store.get("kerfHome", "C:\\Kerf")} onChange={(e) => store.set("kerfHome", e.target.value)} /></label>}
      </>}
    </section>
  );
}

function Offline({ onRetry, prefs, setPrefs }: { onRetry: () => void; prefs: Prefs; setPrefs: (p: Partial<Prefs>) => void }) {
  return (
    <div className="app offline">
      <header className="top"><div className="brand"><span className="logo">K</span> Kerf</div>
        <span className="status bad">● engine offline</span><ThemePicker prefs={prefs} set={setPrefs} /></header>
      <main className="card fade">
        <h2>Start the Kerf engine</h2>
        <p className="help">Kerf does its work in a small local engine (Python + FFmpeg). Nothing leaves your computer unless you turn on an AI provider or download something.</p>
        {host.launchEngine
          ? <button className="primary" onClick={() => host.launchEngine!(store.get("kerfHome", "C:\\Kerf")).then(() => setTimeout(onRetry, 3000))}>Start engine</button>
          : <pre>python -m kerf serve</pre>}
        <div className="actions"><button className="ghost" onClick={onRetry}>Retry</button></div>
      </main>
    </div>
  );
}
