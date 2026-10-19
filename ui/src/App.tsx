import { useEffect, useMemo, useRef, useState } from "react";
import { api, store } from "./api";
import Graphics from "./Graphics";
import Toolkit, { ToolTab } from "./Toolkit";
import { host, IN_UXP, RunResult, setStandaloneMedia } from "./host";
import { LANGS, setLang, t } from "./i18n";

const HELP_URL = "https://github.com/kamalivaturi/kerf#readme";

type Params = Record<string, string | number | boolean>;
type Feature = {
  title: string; group: string; defaults: Params; choices: Record<string, string[]>; help: string; tier: string;
  review: boolean; entitled: boolean; needs_timeline: boolean; presets: { builtin: string[]; user: string[] };
};
type Theme = "auto" | "light" | "dark";
type View = ToolTab | "edit" | "graphics";
type Item = { id: number; label: string; text?: string; editable?: boolean };
type Prefs = { theme: Theme; accent: string; density: "compact" | "comfortable"; fontSize: number; favorites: string[]; showHelp: boolean; lang: string };
type HistoryEntry = { feature: string; title: string; at: number; notes: string[]; params: Params; ok: boolean };

const GROUP_ORDER = ["★", "AI", "Import", "Cut", "Style", "Audio", "Multicam", "Repurpose", "Export"];
const HIDDEN = new Set(["preview", "items", "plan_only"]);
const LONG = new Set(["prompt", "steps", "extra_words", "urls"]);
const FILES = new Set(["srt_import", "mogrt", "sound", "watermark", "folder", "output"]);
const ACCENTS = ["#ff6b2c", "#3d7cff", "#13b07a", "#a64dff", "#ff3d7f", "#f5a623"];
const DEFAULT_PREFS: Prefs = { theme: "auto", accent: ACCENTS[0], density: "comfortable", fontSize: 12, favorites: [], showHelp: true, lang: "auto" };

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
      setLang(prefs.lang);
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
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [result, setResult] = useState<RunResult | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [started, setStarted] = useState(0);
  const [, tick] = useState(0);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState<"" | "settings" | "history" | "news">("");
  const [view, setView] = useState<View>(store.get("view", "tools"));
  const goView = (v: View) => { setView(v); store.set("view", v); };
  const [projectKey, setProjectKey] = useState("standalone");
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
    host.projectKey?.().then(setProjectKey).catch(() => {});
    if (store.get("seenVersion", "") !== h.version) { setPanel("news"); store.set("seenVersion", h.version); }
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
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") applyRef.current();
      if (e.key === "F1") { e.preventDefault(); openHelp(); }
    };
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
    else if (items?.some((i) => i.editable)) p.edits = JSON.stringify(edits);
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
        setEdits({});
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

  const NAV: [View, string, JSX.Element][] = [
    ["tools", "Tools", <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></svg>],
    ["graphs", "Graphs", <svg viewBox="0 0 24 24"><path d="M3 20c4 0 5-16 9-16s5 16 9 16" /></svg>],
    ["motion", "Motion", <svg viewBox="0 0 24 24"><path d="M4 8h12l-3-3M20 16H8l3 3" /><circle cx="4" cy="16" r="1.5" /></svg>],
    ["shakes", "Shakes", <svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z" /></svg>],
    ["edit", "Edit", <svg viewBox="0 0 24 24"><path d="M12 3l1.8 4.6L18.5 9l-4.7 1.6L12 15l-1.8-4.4L5.5 9l4.7-1.4zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" /></svg>],
    ["graphics", "Graphics", <svg viewBox="0 0 24 24"><path d="M12 3 3 8l9 5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5" /></svg>],
  ];
  const needsMedia = !IN_UXP && view !== "graphics" && (view !== "edit" || f?.needs_timeline !== false);

  return (
    <div className="app">
      <header className="top">
        <div className="brand"><span className="wordmark">kerf</span></div>
        <span className="pill status ok" title={`Engine ${engine}`}><i />{IN_UXP ? "Premiere" : "Studio"}</span>
        {([["news", "✦", t("whatsNew")], ["history", "⟲", t("history")], ["settings", "⚙", t("settings")]] as const).map(([k, icon, tip]) =>
          <button key={k} className={`pill icon ${panel === k ? "on" : ""}`} onClick={() => setPanel(panel === k ? "" : k)} aria-label={tip} title={tip}>{icon}</button>)}
        <button className="pill icon" onClick={openHelp} aria-label={t("help")} title={t("help")}>?</button>
        <span className="pill ver">v{engine}</span>
      </header>

      <nav className="mainnav" role="tablist">
        {NAV.map(([k, label, icon]) => <button key={k} role="tab" aria-selected={view === k} className={view === k ? "on" : ""} onClick={() => goView(k)}>
          {icon}<span>{label}</span></button>)}
      </nav>

      {update && <div className="banner">Kerf {update.latest} is available. <a href={update.url} target="_blank" rel="noreferrer">Get update</a></div>}
      {panel === "news" && <News onClose={() => setPanel("")} />}
      {panel === "settings" && <Settings prefs={prefs} setPrefs={setPrefs} onClose={() => setPanel("")} />}
      {panel === "history" && <History entries={history} onLoad={(h) => { goView("edit"); setName(h.feature); setGroup(features[h.feature]?.group || group); setTimeout(() => setParams(h.params), 0); setPanel(""); }}
        onClear={() => { setHistory([]); store.set("history", []); }} onClose={() => setPanel("")} />}

      {needsMedia && (
        <section className="card source">
          <label htmlFor="media">{t("media")} <small>{t("mediaHint")}</small></label>
          <textarea id="media" rows={1} value={media} onChange={(e) => setMedia(e.target.value)} placeholder="C:\Videos\interview.mp4" />
        </section>
      )}

      {view === "graphics" && <Graphics onClose={() => goView("tools")} onCaptions={(file) => {
        goView("edit"); setName("captions"); setGroup(features.captions?.group || group);
        setTimeout(() => setParams({ ...features.captions?.defaults, output: "mogrt", mogrt: file, mogrt_param: "Text" }), 0);
      }} />}
      {(view === "tools" || view === "graphs" || view === "motion" || view === "shakes") && <Toolkit tab={view} projectKey={projectKey} />}

      {view === "edit" && <>
        <div className="search">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} aria-label="Search features" />
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
          {!visible.length && <span className="help">{t("noMatch")}</span>}
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
            {name === "captions" && params.output !== "srt_only" && <CaptionPreview params={params} media={IN_UXP ? "" : paths()[0] || ""} />}
            <div className="actions">
              <button className="ghost" onClick={() => setParams({ ...f.defaults })} title="Reset to defaults">{t("reset")}</button>
              {f.review && <button disabled={!!busy} onClick={() => run(true)}>{name === "prompt_edit" ? t("plan") : t("analyze")}</button>}
              <button className="primary" disabled={!!busy || !f.entitled} onClick={() => run(false)}>
                {f.entitled ? (items ? t("applySelected", { n: checked.size }) : name === "download" ? t("download") : t("apply")) : t("requires", { tier: f.tier })}
              </button>
            </div>
            {busy && <div className="busy"><span className="spinner" /> {busy}… <span className="elapsed">{Math.round((Date.now() - started) / 1000)}s</span></div>}
            {error && <div className="error">{error}</div>}
            {items && <Review items={items} checked={checked} setChecked={setChecked} edits={edits} setEdits={setEdits} />}
            {result && <Result res={result} notes={notes} onUse={!IN_UXP ? (p) => { setMedia(p); pickGroup("Cut"); } : undefined} />}
          </main>
        )}
      </>}
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
        <option value="">{t("preset")}</option>
        {f.presets.builtin.length > 0 && <optgroup label="Built-in">{f.presets.builtin.map((p) => <option key={p}>{p}</option>)}</optgroup>}
        {f.presets.user.length > 0 && <optgroup label="Mine">{f.presets.user.map((p) => <option key={p}>{p}</option>)}</optgroup>}
      </select>
      {f.presets.user.includes(sel) && <button className="ghost" onClick={del} title="Delete preset" aria-label="Delete preset">✕</button>}
      <input value={saveAs} onChange={(e) => setSaveAs(e.target.value)} placeholder={t("saveAs")} aria-label="New preset name"
        onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
      <button className="ghost" onClick={save} disabled={!saveAs.trim()}>{t("save")}</button>
    </div>
  );
}

function Review({ items, checked, setChecked, edits, setEdits }: {
  items: Item[]; checked: Set<number>; setChecked: (s: Set<number>) => void;
  edits: Record<number, string>; setEdits: (e: Record<number, string>) => void;
}) {
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
        i.editable
          ? <li key={i.id} className={`editrow${edits[i.id] !== undefined ? " edited" : ""}`}><span className="tc">{i.label.split("  ")[0]}</span>
              <input value={edits[i.id] ?? i.text ?? ""} aria-label={`Sentence ${i.id + 1}`} onChange={(e) => setEdits({ ...edits, [i.id]: e.target.value })} /></li>
          : <li key={i.id} className={checked.has(i.id) ? "" : "off"}><label><input type="checkbox" checked={checked.has(i.id)} onChange={() => toggle(i.id)} /> {i.label}</label></li>
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
  const [lic, setLic] = useState<Record<string, any>>({});
  const [licKey, setLicKey] = useState(""), [licMsg, setLicMsg] = useState("");
  const [saved, setSaved] = useState(false);
  const [tab, setTab] = useState<"look" | "ai" | "paths" | "share">("look");
  const [bundle, setBundle] = useState(""), [shareMsg, setShareMsg] = useState("");
  useEffect(() => { api.get("/settings").then(setS); api.get("/license").then(setLic); }, []);
  async function save() { setS(await api.post("/settings", s)); setSaved(true); setTimeout(() => setSaved(false), 1500); }
  return (
    <section className="card settings fade">
      <h2>Settings <button className="ghost close" onClick={onClose} aria-label="Close settings">✕</button></h2>
      <nav className="tabs small">
        {(["look", "ai", "paths", "share"] as const).map((k) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
          {k === "look" ? "Appearance" : k === "ai" ? "AI & keys" : k === "paths" ? "Folders" : t("share")}</button>)}
      </nav>
      {tab === "look" && <>
        <label className="row">Theme<ThemePicker prefs={prefs} set={setPrefs} /></label>
        <label className="row">{t("language")}<select value={prefs.lang} onChange={(e) => setPrefs({ lang: e.target.value })}>
          {Object.entries(LANGS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
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
        <p className="help">Keys stay on this computer (~/.kerf/settings.json).</p>
        <h2>Licence</h2>
        <p className="help">{String(lic.edition ?? "…")} · {String(lic.plan ?? "…")}{lic.expires ? ` · renews ${String(lic.expires).slice(0, 10)}` : ""}{lic.key ? ` · ${lic.key}` : ""}</p>
        <div className="presets">
          <input value={licKey} onChange={(e) => setLicKey(e.target.value)} placeholder="Licence key" aria-label="Licence key" />
          <button className="primary" disabled={!licKey.trim()} onClick={async () => { try { setLic(await api.post("/license/activate", { key: licKey })); setLicKey(""); setLicMsg("Activated ✓"); } catch (e) { setLicMsg((e as Error).message); } }}>Activate</button>
          {lic.key && <button className="ghost" onClick={async () => setLic(await api.post("/license/deactivate", {}))}>Deactivate</button>}
        </div>
        {licMsg && <div className="note">{licMsg}</div>}
      </>}
      {tab === "share" && <>
        <p className="help">Copy all your presets (every feature) as one block of text to share or back up; paste a block to import.</p>
        <textarea rows={6} value={bundle} onChange={(e) => setBundle(e.target.value)} placeholder='{"kerf_presets": 1, "features": {}}' aria-label="Preset bundle" />
        <div className="actions">
          <button className="ghost" onClick={async () => { const b = JSON.stringify(await api.post("/presets/export", {}), null, 1); setBundle(b); navigator.clipboard?.writeText(b).catch(() => {}); setShareMsg("Copied to clipboard"); }}>{t("exportPresets")}</button>
          <button className="primary" disabled={!bundle.trim()} onClick={async () => { try { setShareMsg(`Imported ${(await api.post("/presets/import", { bundle })).imported.length} preset(s)`); } catch (e) { setShareMsg((e as Error).message); } }}>{t("importPresets")}</button>
        </div>
        {shareMsg && <div className="note">{shareMsg}</div>}
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
          ? <button className="primary" onClick={() => host.launchEngine!(store.get("kerfHome", "C:\\Kerf")).then(() => setTimeout(onRetry, 3000))}>{t("startEngine")}</button>
          : <pre>python -m kerf serve</pre>}
        <div className="actions"><button className="ghost" onClick={onRetry}>{t("retry")}</button></div>
      </main>
    </div>
  );
}

function openHelp() {
  if (IN_UXP) (globalThis as any).require?.("uxp")?.shell?.openExternal(HELP_URL);
  else window.open(HELP_URL, "_blank", "noopener");
}

function News({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  useEffect(() => { api.get("/changelog").then((r) => setText(r.text)).catch((e) => setText((e as Error).message)); }, []);
  return (
    <section className="card fade">
      <h2>{t("whatsNew")} <button className="ghost close" onClick={onClose} aria-label="Close">✕</button></h2>
      <pre className="news">{text.replace(/^# .*\n+/, "") || "…"}</pre>
    </section>
  );
}

function CaptionPreview({ params, media }: { params: Params; media: string }) {
  const [aspect, setAspect] = useState(store.get("capAspect", "9:16"));
  const [safe, setSafe] = useState(true);
  const [img, setImg] = useState(""), [err, setErr] = useState("");
  useEffect(() => {
    store.set("capAspect", aspect);
    const id = setTimeout(() => api.post("/captions/preview", { path: media, params, t: 1.2, aspect, safe })
      .then((r) => { setImg(r.image); setErr(""); }).catch((e) => setErr((e as Error).message)), 350); // debounce typing
    return () => clearTimeout(id);
  }, [JSON.stringify(params), media, aspect, safe]);
  return (
    <div className="cap-preview">
      <div className="row">{t("captionPreview")}
        <span><select value={aspect} onChange={(e) => setAspect(e.target.value)} aria-label="Aspect">{["9:16", "1:1", "16:9"].map((a) => <option key={a}>{a}</option>)}</select>
          <label className="check"><input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />{t("safeZones")}</label></span></div>
      {img && <img src={img} alt="Caption preview" />}
      {err && <div className="error">{err}</div>}
    </div>
  );
}
