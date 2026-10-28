// Toolkit: one-click editor tools (anchor, layers, beats, curves, shakes, stabilizer, zoom, quick mask, FX presets).
// Engine tools run through /run like every feature; selection-based ones use host.tools (Premiere).
import { useEffect, useRef, useState } from "react";
import { api, runFeature, store } from "./api";
import { host, IN_EDITOR } from "./host";

export type ToolTab = "tools" | "graphs" | "motion" | "shakes";
type P = Record<string, string | number | boolean>;

const CURVES: [string, string, string][] = [ // [label, bezier, premiere interpolation]
  ["Ease out", "0,0,0.58,1", "bezier"], ["Ease in", "0.42,0,1,1", "bezier"], ["Ease in/out", "0.42,0,0.58,1", "bezier"],
  ["Snappy", "0.2,0.9,0.1,1", "bezier"], ["Linear", "0,0,1,1", "linear"],
];
const SPEEDS: [string, string][] = [["Ease in", "ease_in"], ["Ease out", "ease_out"], ["Speedramp", "speedramp"],
  ["Ease in/out", "ease_in_out"], ["Linear", "linear"]];
const AXES: [string, string][] = [["vertical", "Vertical"], ["horizontal", "Horizontal"], ["hv", "HV Shake"], ["scale", "Scale"],
  ["all", "All"], ["custom", "Custom"]];
const SHAKE: P = { amplitude: 28, rotation: 1.5, frequency: 11, duration: 0.45, decay: 0.7, zoom: 108, flash: 0, chromatic: 0 };
const SLIDERS: [string, string, number, number, number][] = [["amplitude", "Amplitude px", 0, 120, 1], ["rotation", "Rotation °", 0, 10, .1],
  ["frequency", "Frequency Hz", 1, 30, .5], ["duration", "Duration s", .1, 3, .05], ["decay", "Decay", 0, 1, .05],
  ["zoom", "Overscan %", 100, 140, 1], ["flash", "Flash", 0, 100, 1], ["chromatic", "Chromatic px", 0, 20, 1]];
const CARDS = ["anchor", "curves", "shakes", "stabzoom", "mask", "captions", "utils", "scripts"];

// ------------------------------------------------------------------ icons (stroke SVG, inherit color)
const I = {
  curve: (b: string, color = "var(--color-accent)") => {
    const [x1, y1, x2, y2] = b.split(",").map(Number);
    return <svg aria-hidden="true" viewBox="0 0 40 40" width="34" height="34"><path d={`M6 34 C ${6 + x1 * 28} ${34 - y1 * 28}, ${6 + x2 * 28} ${34 - y2 * 28}, 34 6`}
      fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" /></svg>;
  },
  speed: (k: string) => {
    const d = { ease_in: "M5 34 C 20 34, 30 30, 33 6 L33 34", ease_out: "M7 6 L7 34 C 10 10, 20 34, 35 34",
      speedramp: "M5 34 C 14 34, 18 30, 20 6 C 22 30, 26 34, 35 34", ease_in_out: "M5 34 C 16 34, 18 6, 20 6 C 22 6, 24 34, 35 34",
      linear: "M5 34 L35 6" }[k];
    return <svg aria-hidden="true" viewBox="0 0 40 40" width="34" height="34"><path d={d} fill="none" stroke="var(--color-second)" strokeWidth="2.4" strokeLinecap="round" /></svg>;
  },
  axis: (k: string) => {
    const d = { vertical: "M20 5v30M14 11l6-6 6 6M14 29l6 6 6-6", horizontal: "M5 20h30M11 14l-6 6 6 6M29 14l6 6-6 6",
      hv: "M20 5v30M5 20h30M14 11l6-6 6 6M14 29l6 6 6-6M11 14l-6 6 6 6M29 14l6 6-6 6",
      scale: "M20 9v22M15 14l5-5 5 5M15 26l5 5 5-5M10 6h20v28H10z", all: "M20 5v30M5 20h30M14 11l6-6 6 6M14 29l6 6 6-6M11 14l-6 6 6 6M29 14l6 6-6 6M12 12l16 16",
      custom: "M20 5v24M14 11l6-6 6 6M12 33l8-4 8 4" }[k];
    return <svg aria-hidden="true" viewBox="0 0 40 40" width="28" height="28"><path d={d} fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  },
  bolt: <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22"><path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg>,
};

// ------------------------------------------------------------------ shared runner
function useRunner(hasMedia: boolean, onNeedMedia: () => void) {
  const [busy, setBusy] = useState(""), [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const say = (text: string, ok = true) => { setToast({ ok, text }); setTimeout(() => setToast((t) => (t?.text === text ? null : t)), 6000); };
  async function guard(label: string, fn: () => Promise<string | string[] | void>) {
    if (busy) return;
    setBusy(label);
    try { const r = await fn(); if (r) say(Array.isArray(r) ? r.join(" · ") || "Done" : r); }
    catch (e) { say((e as Error).message, false); } finally { setBusy(""); }
  }
  const run = (feature: string, params: P, label = feature) => {
    if (feature !== "project_sort" && !hasMedia) { say(host.pickFile ? "Choose a video first. Opening the picker…" : "Choose a video first: paste its path in the field at the top."); onNeedMedia(); return; }
    return runNow(feature, params, label);
  };
  const runNow = (feature: string, params: P, label: string) => guard(label, async () => {
    const { res, notes } = await runFeature(feature, params, { needsTimeline: feature !== "project_sort" });
    return notes.length ? notes : res.report ? Object.entries(res.report).slice(0, 3).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`) : "Done";
  });
  const tool = (label: string, fn: (t: NonNullable<typeof host.tools>) => Promise<string>, fallback?: () => void) =>
    host.tools ? guard(label, () => fn(host.tools!)) : fallback ? fallback() : say(`${label} works inside the Premiere panel`, false);
  // a tool the editor runs itself (After Effects ExtendScript), else the engine / Premiere path
  const act = (name: string, label: string, p: P, fallback: () => unknown) =>
    host.native?.[name] ? guard(label, () => host.native![name](p)) : fallback();
  return { busy, toast, run, tool, act, say, hasMedia, onNeedMedia };
}
type Runner = ReturnType<typeof useRunner>;

function Stepper({ value, set, min, max, step = 1, fmt = (v: number) => String(v), label }: {
  value: number; set: (v: number) => void; min: number; max: number; step?: number; fmt?: (v: number) => string; label: string;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step));
  return <div className="stepper" aria-label={label} title={label} onWheel={(e) => set(clamp(value - Math.sign(e.deltaY) * step))}>
    <button className="tk-mini" onClick={() => set(clamp(value - step))} aria-label={`Less ${label}`}>−</button>
    <b>{fmt(value)}</b>
    <button className="tk-mini" onClick={() => set(clamp(value + step))} aria-label={`More ${label}`}>+</button>
  </div>;
}

// ------------------------------------------------------------------ bezier editor (speed graph / value graph)
export function Bezier({ value, set, color = "var(--color-accent)" }: { value: string; set: (v: string) => void; color?: string }) {
  const svg = useRef<SVGSVGElement>(null);
  const [x1, y1, x2, y2] = value.split(",").map(Number).concat([0, 0, 1, 1]).slice(0, 4);
  const S = 200, pad = 16, X = (v: number) => pad + v * (S - 2 * pad), Y = (v: number) => S - pad - v * (S - 2 * pad);
  function drag(which: 1 | 2) {
    return (e: React.PointerEvent) => {
      const r = svg.current!.getBoundingClientRect();
      const move = (ev: PointerEvent) => {
        const x = Math.min(1, Math.max(0, ((ev.clientX - r.left) * S / r.width - pad) / (S - 2 * pad)));
        const y = Math.min(1.5, Math.max(-.5, (S - pad - (ev.clientY - r.top) * S / r.height) / (S - 2 * pad)));
        set((which === 1 ? [x, y, x2, y2] : [x1, y1, x, y]).map((n) => +n.toFixed(2)).join(","));
      };
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
      e.preventDefault();
    };
  }
  return <svg ref={svg} viewBox={`0 0 ${S} ${S}`} className="bezier" role="img" aria-label={`Curve ${value}`}>
    {[.25, .5, .75].map((g) => <g key={g}><line x1={X(g)} y1={Y(0)} x2={X(g)} y2={Y(1)} className="grid" /><line x1={X(0)} y1={Y(g)} x2={X(1)} y2={Y(g)} className="grid" /></g>)}
    <rect x={X(0)} y={Y(1)} width={S - 2 * pad} height={S - 2 * pad} className="frame" />
    <line x1={X(0)} y1={Y(0)} x2={X(x1)} y2={Y(y1)} className="handle" /><line x1={X(1)} y1={Y(1)} x2={X(x2)} y2={Y(y2)} className="handle" />
    <path d={`M${X(0)} ${Y(0)} C ${X(x1)} ${Y(y1)}, ${X(x2)} ${Y(y2)}, ${X(1)} ${Y(1)}`} fill="none" stroke={color} strokeWidth="3" />
    <circle cx={X(x1)} cy={Y(y1)} r="7" className="knob" onPointerDown={drag(1)} />
    <circle cx={X(x2)} cy={Y(y2)} r="7" className="knob" onPointerDown={drag(2)} />
  </svg>;
}

// ------------------------------------------------------------------ live shake preview (same maths as the engine)
function ShakePreview({ p, axis }: { p: P; axis: string }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    let raf = 0; const t0 = performance.now();
    const f = () => { setT((performance.now() - t0) / 1000); raf = requestAnimationFrame(f); };
    raf = requestAnimationFrame(f);
    return () => cancelAnimationFrame(raf);
  }, []);
  const d = Number(p.duration), lt = t % (d + .8);
  const env = lt > d ? 0 : (1 - lt / d) ** (1 + 3 * Number(p.decay));
  const w = 2 * Math.PI * Number(p.frequency) * t, n = (ph: number) => (Math.sin(w + ph) + .5 * Math.sin(1.7 * w + ph * 2)) / 1.5;
  const mx = ["vertical", "scale"].includes(axis) ? 0 : 1, my = ["horizontal", "scale"].includes(axis) ? 0 : 1, mr = ["all", "custom"].includes(axis) ? 1 : 0;
  const A = Number(p.amplitude) * env * .35;
  const s = Number(p.zoom) / 100 + (["scale", "all"].includes(axis) ? Number(p.amplitude) / 400 * env * Math.abs(n(4)) : 0);
  const flash = lt < .12 ? Number(p.flash) / 100 * (1 - lt / .12) : 0, ch = Number(p.chromatic) * env * .35;
  return <div className="shake-stage" aria-hidden="true">
    <div className="shake-shot" style={{ transform: `translate(${A * n(0) * mx}px,${A * n(1) * my}px) rotate(${Number(p.rotation) * env * n(2) * mr}deg) scale(${s})`,
      filter: `brightness(${1 + flash})`, boxShadow: ch ? `${ch}px 0 0 rgba(255,0,60,.45) inset, ${-ch}px 0 0 rgba(0,160,255,.45) inset` : undefined }}>
      <span>kerf</span>
    </div>
  </div>;
}

// ------------------------------------------------------------------ quick mask region drawer
function MaskRegion({ r, onDone }: { r: Runner; onDone: () => void }) {
  const [img, setImg] = useState(""), [box, setBox] = useState<number[] | null>(null), [model, setModel] = useState("u2net_human_seg");
  const [output, setOutput] = useState("cutout"), ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!r.hasMedia) return;
    (async () => { try { setImg((await api.post("/frame", { timeline: await host.readTimeline() })).image); } catch (e) { r.say((e as Error).message, false); } })();
  }, [r.hasMedia]);
  function down(e: React.PointerEvent) {
    const rc = ref.current!.getBoundingClientRect();
    const fx = (x: number) => Math.min(1, Math.max(0, (x - rc.left) / rc.width)), fy = (y: number) => Math.min(1, Math.max(0, (y - rc.top) / rc.height));
    const x0 = fx(e.clientX), y0 = fy(e.clientY);
    const move = (ev: PointerEvent) => { const x = fx(ev.clientX), y = fy(ev.clientY); setBox([Math.min(x0, x), Math.min(y0, y), Math.abs(x - x0), Math.abs(y - y0)]); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  }
  const region = box && box[2] > .02 && box[3] > .02 ? box.map((v) => v.toFixed(3)).join(",") : "";
  return <section className="tk-card fade">
    <div className="tk-head"><span className="tk-label">Quick mask: draw around the subject</span><button className="tk-mini" onClick={onDone} aria-label="Close">✕</button></div>
    <div className="mask-canvas" ref={ref} onPointerDown={down}>
      {img ? <img src={img} alt="Current frame" draggable={false} /> : r.hasMedia ? <div className="help">Reading the frame at the playhead…</div>
        : <div className="help">Choose a video first, then draw around the subject. <button className="tk-mini" onClick={r.onNeedMedia}>Choose video…</button></div>}
      {box && <div className="mask-box" style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${box[2] * 100}%`, height: `${box[3] * 100}%` }} />}
    </div>
    <div className="tk-row">
      <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model"><option value="u2net_human_seg">People (best)</option>
        <option value="u2netp">Objects (fast)</option><option value="silueta">Objects (detailed)</option></select>
      <select value={output} onChange={(e) => setOutput(e.target.value)} aria-label="Output"><option value="cutout">Cutout (alpha)</option><option value="matte">Matte</option></select>
      <button className="tk-btn primary" disabled={!!r.busy} onClick={() => r.run("quick_mask", { model, output, region, clips: "playhead" }, "Quick mask")}>
        {region ? "Cut out region" : "Cut out whole frame"}</button>
    </div>
    <p className="help">Runs offline on this computer. The first run downloads the model once.</p>
  </section>;
}

// ------------------------------------------------------------------ scripts hub (After Effects)
type Script = { name: string; path: string; panel: boolean };
function ScriptsHub({ r }: { r: Runner }) {
  const [list, setList] = useState<Script[]>([]), [q, setQ] = useState("");
  const [fav, setFav] = useState<string[]>(store.get("scriptFavs", []));
  useEffect(() => { host.native?.listScripts?.({}).then((t) => setList(JSON.parse(t))).catch(() => {}); }, []);
  const toggle = (p: string) => { const n = fav.includes(p) ? fav.filter((x) => x !== p) : [...fav, p]; setFav(n); store.set("scriptFavs", n); };
  const needle = q.trim().toLowerCase();
  const shown = list.filter((s) => !needle || s.name.toLowerCase().includes(needle))
    .sort((a, b) => Number(fav.includes(b.path)) - Number(fav.includes(a.path)) || a.name.localeCompare(b.name));
  return <section className="tk-card">
    <div className="tk-head"><span className="tk-label">Your scripts</span><small>{list.length} installed · ★ pins to the top</small></div>
    <input className="script-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your scripts and panels" aria-label="Search scripts" />
    <div className="script-list">{shown.map((s) => <div key={s.path} className="script-row">
      <button className="script-run" disabled={!!r.busy} onClick={() => r.act("runScript", s.name, { path: s.path }, () => {})} title={s.path}>
        <span>{s.name}</span>{s.panel && <small>panel</small>}</button>
      <button className={`tk-mini fav${fav.includes(s.path) ? " on" : ""}`} onClick={() => toggle(s.path)} aria-pressed={fav.includes(s.path)}
        aria-label={`${fav.includes(s.path) ? "Unpin" : "Pin"} ${s.name}`}>★</button></div>)}
      {!shown.length && <p className="help">{list.length ? "No script matches that search." : "No scripts found in After Effects' Scripts folders."}</p>}</div>
  </section>;
}

// ------------------------------------------------------------------ the tabs
export default function Toolkit({ tab, projectKey, hasMedia, onNeedMedia }: {
  tab: ToolTab; projectKey: string; hasMedia: boolean; onNeedMedia: () => void;
}) {
  const r = useRunner(hasMedia, onNeedMedia);
  const [s, setS] = useState<P>({ every: 1, smoothing: 50, color: "#000000", axis: "hv", on: IN_EDITOR ? "playhead" : "cuts", output: "keyframes",
    music: "", curve: "0.42,0,0.58,1", min_speed: 30, max_speed: 300, amount: 120, zdur: 0.6, tracks: "2", scale: 35, margin: 4,
    ...SHAKE, ...store.get<P>("toolkit", {}) });
  const set = (k: string, v: string | number | boolean) => setS((x) => { const n = { ...x, [k]: v }; store.set("toolkit", n); return n; });
  const [mask, setMask] = useState(false), [edit, setEdit] = useState(false);
  const [order, setOrder] = useState<string[]>(CARDS), [hidden, setHidden] = useState<string[]>([]);
  const [fx, setFx] = useState<string[]>([]), [fxSel, setFxSel] = useState("");
  useEffect(() => { setOrder(store.get(`layout:${projectKey}`, CARDS)); setHidden(store.get(`hidden:${projectKey}`, [])); }, [projectKey]);
  useEffect(() => { api.get("/fx").then((x) => setFx(x.presets)).catch(() => {}); }, []);
  const saveLayout = (o: string[], h: string[]) => { setOrder(o); setHidden(h); store.set(`layout:${projectKey}`, o); store.set(`hidden:${projectKey}`, h); };
  const move = (c: string, d: number) => { const o = [...order], i = o.indexOf(c), j = i + d; if (j < 0 || j >= o.length) return; [o[i], o[j]] = [o[j], o[i]]; saveLayout(o, hidden); };

  const anchor = (ax: number, ay: number) => {
    const pos = `${["top", "middle", "bottom"][ay * 2]}_${["left", "center", "right"][ax * 2]}`.replace("middle_center", "center");
    r.act("anchor", "Anchor", { ax, ay }, () => r.tool("Anchor", (t) => t.setAnchor(ax, ay), () => r.run("layout", { arrange: pos, tracks: s.tracks, scale: s.scale, margin: s.margin }, "Position")));
  };
  const layer = (kind: string, extra: P = {}) => r.run("add_layer", { kind, color: s.color, ...extra }, `Add ${kind}`);
  const shakeP = { axis: s.axis, ...Object.fromEntries(Object.keys(SHAKE).map((k) => [k, s[k]])) };
  const shake = () => r.act("shake", "Shake", shakeP, () => r.run("camera_shake", { ...shakeP, on: s.on, music: s.music, output: s.output }, "Shake"));
  const zoom = (direction: string, ease: string) => r.act("zoom", `Zoom ${direction}`, { direction, ease, amount: s.amount, duration: s.zdur },
    () => r.run("zoom_move", { direction, ease, amount: s.amount, duration: s.zdur }, `Zoom ${direction}`));
  const has = (a: string) => host.has(a);
  const busy = !!r.busy;
  const axisRow = <div className="icons">{AXES.map(([k, l]) => <button key={k} className={`tk-icon tall${s.axis === k ? " on" : ""}`}
    onClick={() => set("axis", k)} aria-pressed={s.axis === k}>{I.axis(k)}<small>{l}</small></button>)}</div>;

  const cards: Record<string, JSX.Element> = {
    anchor: <section className="tk-card tk-split">
      <div><span className="tk-label">Anchor</span>
        <div className="anchor-grid">{[0, .5, 1].map((ay) => [0, .5, 1].map((ax) =>
          <button key={`${ax}${ay}`} className={`dot${ax === .5 && ay === .5 ? " mid" : ""}`} disabled={busy} onClick={() => anchor(ax, ay)}
            aria-label={`Anchor ${ay === 0 ? "top" : ay === 1 ? "bottom" : "middle"} ${ax === 0 ? "left" : ax === 1 ? "right" : "center"}`}><i /></button>))}</div></div>
      <div><span className="tk-label">Add layer</span>
        <div className="tk-grid2">
          <button className="tk-btn" disabled={busy} onClick={() => r.act("null", "Null", {}, () => layer("transparent"))}>Null</button>
          {has("parentNull") && <button className="tk-btn" disabled={busy} onClick={() => r.act("parentNull", "Null + parent", {}, () => {})} title="Parents the selected layers to a new null">Null + parent</button>}
          {has("bars") && <button className="tk-btn" disabled={busy} onClick={() => layer("letterbox", { aspect: 2.39, duration: 0 })}>Bars</button>}
          {has("adjustment") && <button className="tk-btn green" disabled={busy} onClick={() => r.act("adjustment", "Adjustment", {}, () => r.tool("Adjustment", (t) => t.adjustment()))}>ADJ</button>}
          <div className="tk-btn split"><button disabled={busy} onClick={() => r.act("solid", "Solid", { color: s.color }, () => layer("solid"))}>Solid</button>
            <input type="color" value={String(s.color)} onChange={(e) => set("color", e.target.value)} aria-label="Solid color" /></div>
        </div></div>
      <div><span className="tk-label">Beats</span>
        <button className="tk-btn primary block" disabled={busy} title={host.native ? "Select the music layer" : undefined}
          onClick={() => r.act("beats", "Beats", { every: s.every }, () => r.run("beat_markers", { music: s.music, every: s.every }, "Beats"))}>Place beats</button>
        {has("clearBeats") && <button className="tk-btn block" disabled={busy} onClick={() => r.act("clearBeats", "Clear beats", {}, () => r.tool("Clear", (t) => t.clearMarkers("Beat")))}>Clear</button>}
        <Stepper label="Every N beats" value={Number(s.every)} set={(v) => set("every", v)} min={1} max={16} /></div>
    </section>,
    curves: <section className="tk-card">
      <div className="tk-head"><span className="tk-label">Curves</span><span className="legend"><i className="o" />Value <i className="b" />Speed</span></div>
      <div className="tk-row spread">
        <div className="icons">{CURVES.map(([l, b, m]) => <button key={l} className="tk-icon" title={`Value: ${l} (selected clips' keyframes)`} disabled={busy}
          onClick={() => r.act("valueCurve", l, { name: l }, () => r.tool(l, (t) => t.ease(m as "linear" | "bezier"), () => { set("curve", b); r.say(`Curve set to ${l} for Zoom and the custom speed ramp`); }))}>{I.curve(b)}</button>)}</div>
        <span className="vsep" />
        <div className="icons">{SPEEDS.map(([l, k]) => <button key={k} className="tk-icon" title={`Speed: ${l}`} disabled={busy}
          onClick={() => r.act("speedCurve", `Speed ${l}`, { kind: k }, () => r.run("speed_ramp", { preset: k, min_speed: s.min_speed, max_speed: s.max_speed, clips: IN_EDITOR ? "playhead" : "all" }, `Speed ${l}`))}>{I.speed(k)}</button>)}</div>
      </div>
    </section>,
    shakes: <section className="tk-card">
      <span className="tk-label">Shakes</span>
      {axisRow}
      <button className="tk-btn primary block grow top-gap" disabled={busy} onClick={shake}>{I.bolt} APPLY SHAKE</button>
    </section>,
    stabzoom: <section className="tk-card tk-split two">
      <div><span className="tk-label">Stabilizer</span>
        <div className="tk-row"><button className="tk-btn" disabled={busy} onClick={() => host.native?.stabilize ? r.act("stabilize", "Stabilize", {}, () => {}) : r.run("stabilize", { smoothing: Math.round(Number(s.smoothing) * .6), clips: IN_EDITOR ? "playhead" : "all" }, "Stabilize")}>Stabilize</button>
          {!host.native?.stabilize && <Stepper label="Smoothness" value={Number(s.smoothing)} set={(v) => set("smoothing", v)} min={10} max={100} step={10} fmt={(v) => `${v}%`} />}</div></div>
      <div><span className="tk-label">Zoom</span>
        <div className="tk-stack">{["in", "out"].map((d) => <div key={d} className="seg"><b>Zoom {d}</b>
          {["in", "out"].map((e) => <button key={e} className="seg-btn" disabled={busy} onClick={() => zoom(d, e)} title={`Zoom ${d}, ease ${e}`}>Ease {e}</button>)}</div>)}</div></div>
    </section>,
    mask: host.native?.mask ? <section className="tk-card"><span className="tk-label">Quick mask</span>
        <button className="tk-wide" disabled={busy} onClick={() => r.act("mask", "Quick mask", {}, () => {})}><span className="dash" /> CUT OUT SELECTED LAYER</button>
        <p className="help">Offline AI cutout of the selected footage layer. Draw a mask on the layer first to limit it to a region.</p></section>
      : mask ? <MaskRegion r={r} onDone={() => setMask(false)} />
      : <button className="tk-wide" onClick={() => setMask(true)}><span className="dash" aria-hidden="true" /> Quick mask: draw a region</button>,
    captions: has("captions") ? <section className="tk-card"><span className="tk-label">Captions</span>
        <button className="tk-btn primary block" disabled={busy} onClick={() => r.act("captions", "Captions", {}, () => {})}>Captions for the layer</button>
        <p className="help">Transcribes the selected layer and adds an animated caption layer above it.</p></section> : null as unknown as JSX.Element,
    scripts: has("scripts") ? <ScriptsHub r={r} /> : null as unknown as JSX.Element,
    utils: <section className="tk-card">
      <span className="tk-label">Utilities</span>
      <div className="tk-row wrap">
        <button className="tk-btn" disabled={busy} onClick={() => r.act("frameExport", "Frame export", {}, () => r.run("frame_export", {}, "Frame export"))}>Save frame to Desktop</button>
        <button className="tk-btn" disabled={busy} onClick={() => r.act("sortProject", "Sort project", {}, () => r.run("project_sort", {}, "Sort project"))}>Sort project</button>
        {has("fx") && <><button className="tk-btn" disabled={busy} onClick={() => host.native?.copyFx ? Promise.resolve(r.act("copyFx", "Copy FX", { name: window.prompt?.("Name this effect preset", "My look") || `FX ${new Date().toLocaleTimeString()}` }, () => {})).then(() => api.get("/fx").then((x) => setFx(x.presets))) : r.tool("Copy FX", async (t) => {
          const name = window.prompt?.("Name this effect preset", "My look") || `FX ${new Date().toLocaleTimeString()}`;
          const res = await api.post("/fx/save", { name, chain: await t.copyFx() });
          setFx((await api.get("/fx")).presets); setFxSel(name);
          return `Saved “${name}” (${res.components} effects)`;
        })}>Copy FX</button>
        <select value={fxSel} onChange={(e) => setFxSel(e.target.value)} aria-label="FX preset"><option value="">FX preset…</option>{fx.map((n) => <option key={n}>{n}</option>)}</select>
        <button className="tk-btn primary" disabled={busy || !fxSel} onClick={() => r.act("applyFx", "Apply FX", { name: fxSel }, () => r.tool("Apply FX", async (t) => t.applyFx(await api.post("/fx/get", { name: fxSel }))))}>Apply FX</button></>}
      </div>
    </section>,
  };

  return <div className="toolkit">
    {tab === "tools" && <>
      <div className="tk-toolbar"><button className={`tk-mini${edit ? " on" : ""}`} onClick={() => setEdit(!edit)}>{edit ? "Done" : "Customize layout"}</button>
        {edit && <button className="tk-mini" onClick={() => saveLayout(CARDS, [])}>Reset</button>}</div>
      {[...order, ...CARDS.filter((c) => !order.includes(c))].filter((c) => cards[c] && (edit || !hidden.includes(c))).map((c) => <div key={c} className={`tk-slot${hidden.includes(c) ? " off" : ""}`}>
        {edit && <div className="tk-edit"><button className="tk-mini" onClick={() => move(c, -1)} aria-label="Move up">↑</button>
          <button className="tk-mini" onClick={() => move(c, 1)} aria-label="Move down">↓</button>
          <button className="tk-mini" onClick={() => saveLayout(order, hidden.includes(c) ? hidden.filter((x) => x !== c) : [...hidden, c])}>{hidden.includes(c) ? "Show" : "Hide"}</button></div>}
        {cards[c]}</div>)}
    </>}
    {tab === "graphs" && <section className="tk-card">
      <span className="tk-label">Speed & value graph</span>
      <div className="tk-row spread top"><Bezier value={String(s.curve)} set={(v) => set("curve", v)} />
        <div className="tk-col">
          <div className="icons">{CURVES.map(([l, b]) => <button key={l} className="tk-icon" title={l} onClick={() => set("curve", b)}>{I.curve(b)}</button>)}</div>
          <label className="tk-field">Curve<input value={String(s.curve)} onChange={(e) => set("curve", e.target.value)} /></label>
          <label className="tk-field">Slowest <b>{s.min_speed}%</b><input type="range" min={5} max={100} value={Number(s.min_speed)} onChange={(e) => set("min_speed", +e.target.value)} /></label>
          <label className="tk-field">Fastest <b>{s.max_speed}%</b><input type="range" min={100} max={1000} step={10} value={Number(s.max_speed)} onChange={(e) => set("max_speed", +e.target.value)} /></label>
          <button className="tk-btn primary" disabled={busy} onClick={() => r.run("speed_ramp", { preset: "custom", curve: s.curve, min_speed: s.min_speed, max_speed: s.max_speed, clips: IN_EDITOR ? "playhead" : "all" }, "Speed ramp")}>Ramp clip</button>
          <button className="tk-btn" disabled={busy} onClick={() => r.run("zoom_move", { curve: s.curve, amount: s.amount, duration: s.zdur }, "Zoom")}>Zoom with this curve</button>
          {host.tools && <button className="tk-btn" disabled={busy} onClick={() => r.tool("Ease", (t) => t.ease("bezier"))}>Ease selected keyframes</button>}
        </div></div>
    </section>}
    {tab === "motion" && <>
      <section className="tk-card"><span className="tk-label">Zoom in / out</span>
        <label className="tk-field">Amount <b>{s.amount}%</b><input type="range" min={101} max={200} value={Number(s.amount)} onChange={(e) => set("amount", +e.target.value)} /></label>
        <label className="tk-field">Duration <b>{Number(s.zdur).toFixed(2)} s</b><input type="range" min={.1} max={5} step={.05} value={Number(s.zdur)} onChange={(e) => set("zdur", +e.target.value)} /></label>
        <div className="tk-stack">{["in", "out"].map((d) => <div key={d} className="seg"><b>Zoom {d}</b>
          {(host.native ? ["in", "out"] : ["in", "out", "in_out"]).map((e) => <button key={e} className="seg-btn" disabled={busy} onClick={() => zoom(d, e)}>{e === "in_out" ? "Both" : `Ease ${e}`}</button>)}</div>)}</div>
      </section>
      {has("align") && <section className="tk-card"><span className="tk-label">Align & distribute</span>
        <div className="tk-row wrap">{([["Left", "left"], ["H centre", "hcenter"], ["Right", "right"], ["Top", "top"], ["V centre", "vcenter"], ["Bottom", "bottom"],
          ["Distribute H", "dist_h"], ["Distribute V", "dist_v"]] as [string, string][]).map(([l, m]) =>
          <button key={m} className="tk-btn" disabled={busy} onClick={() => r.act("align", `Align ${l}`, { mode: m }, () => {})}>{l.toUpperCase()}</button>)}</div>
        <p className="help">Aligns the selected layers to the composition (distribute needs three or more).</p></section>}
      {has("layout") && <section className="tk-card"><span className="tk-label">Align & distribute</span>
        <div className="tk-row wrap">
          <label className="tk-field small">Tracks<input value={String(s.tracks)} onChange={(e) => set("tracks", e.target.value)} /></label>
          <label className="tk-field small">Scale %<input type="number" value={Number(s.scale)} onChange={(e) => set("scale", +e.target.value)} /></label>
          <label className="tk-field small">Margin %<input type="number" value={Number(s.margin)} onChange={(e) => set("margin", +e.target.value)} /></label></div>
        <div className="tk-row wrap">{["align_left", "align_right", "align_top", "align_bottom", "distribute_horizontal", "distribute_vertical", "grid"].map((a) =>
          <button key={a} className="tk-btn" disabled={busy} onClick={() => r.run("layout", { arrange: a, tracks: s.tracks, scale: a.startsWith("dist") || a === "grid" ? 0 : s.scale, margin: s.margin }, a)}>{a.replace("_", " ").toUpperCase()}</button>)}</div>
        <p className="help">Anchor (Tools tab) moves the anchor point of the selected clips in Premiere; elsewhere it places the clips on these tracks at that spot.</p>
      </section>}
    </>}
    {tab === "shakes" && <section className="tk-card">
      <span className="tk-label">Camera shake</span>
      <div className="tk-row spread">{axisRow}</div>
      <ShakePreview p={s} axis={String(s.axis)} />
      {SLIDERS.filter(([k]) => has("shakeEngine") || !["zoom", "chromatic"].includes(k)).map(([k, l, mn, mx, st]) => <label key={k} className="tk-field">{l} <b>{Number(s[k]).toFixed(st < 1 ? 2 : 0)}</b>
        <input type="range" min={mn} max={mx} step={st} value={Number(s[k])} onChange={(e) => set(k, +e.target.value)} /></label>)}
      {has("shakeEngine") && <div className="tk-row wrap">
        <label className="tk-field small">Trigger<select value={String(s.on)} onChange={(e) => set("on", e.target.value)}>{["playhead", "cuts", "beats", "whole"].map((o) => <option key={o}>{o}</option>)}</select></label>
        <label className="tk-field small">Output<select value={String(s.output)} onChange={(e) => set("output", e.target.value)}><option value="keyframes">Keyframes (editable)</option><option value="render">Render (flash + RGB)</option></select></label>
        {s.on === "beats" && <label className="tk-field">Music file<input value={String(s.music)} onChange={(e) => set("music", e.target.value)} placeholder="song.mp3" /></label>}
      </div>}
      <div className="tk-row wrap">
        {([["Impact", { axis: "all", amplitude: 40, duration: .35 }], ["Handheld", { on: "whole", axis: "hv", amplitude: 6, frequency: 1.5, rotation: .4, zoom: 104 }],
          ["Earthquake", { axis: "all", amplitude: 70, frequency: 18, duration: 1.2, decay: .3 }], ["Reset", SHAKE]] as [string, P][]).map(([n, v]) =>
          <button key={n} className="tk-mini" onClick={() => Object.entries(v).forEach(([k, x]) => set(k, x))}>{n}</button>)}
        <button className="tk-btn primary grow" disabled={busy} onClick={shake}>{I.bolt} APPLY SHAKE</button>
      </div>
    </section>}
    {(r.busy || r.toast) && <div className={`tk-toast${r.toast && !r.busy && !r.toast.ok ? " bad" : ""}`} role="status">
      {r.busy ? <><span className="spinner" /> {r.busy}…</> : r.toast?.text}</div>}
  </div>;
}
