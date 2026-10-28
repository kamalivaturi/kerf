// MOGRT gallery + Studio. Previews animate live from the same specs the AE builder uses, so every
// template (built or not) and every Studio tweak shows its motion before After Effects runs.
import { useEffect, useMemo, useState } from "react";
import { api, store } from "./api";
import { host } from "./host";
import { t } from "./i18n";

type Anim = { props: [string, number | number[]][]; ease: string; dur: number; stagger: number; based_on: number };
type Look = Record<string, string | number | boolean>;
export type Spec = {
  id: string; kind: string; anim_name: string; look_name: string; format: string; name: string; w: number; h: number;
  text: string; subtext: string; size: number; pos: [number, number]; duration: number; preview_seconds: number; anim: Anim; look: Look;
};
type Entry = { id: string; name: string; kind: string; anim: string; look: string; format: string; source: string; file: string;
  controls: number | string[]; gif?: string; mp4?: string; png?: string; spec?: Spec };
type Info = { library: Entry[]; catalog: Spec[]; anims: string[]; looks: string[]; kinds: string[]; formats: string[] };

const clamp = (x: number) => Math.max(0, Math.min(1, x));
const EASE: Record<string, (p: number) => number> = {
  cubic: (p) => 1 - (1 - p) ** 3,
  back: (p) => 1 + 2.70158 * (p - 1) ** 3 + 1.70158 * (p - 1) ** 2,
  expo: (p) => (p >= 1 ? 1 : 1 - 2 ** (-10 * p)),
  step: (p) => (p > 0 ? 1 : 0),
  bounce: (p) => { const n = 7.5625, d = 2.75; return p < 1 / d ? n * p * p : p < 2 / d ? n * (p -= 1.5 / d) * p + .75 : p < 2.5 / d ? n * (p -= 2.25 / d) * p + .9375 : n * (p -= 2.625 / d) * p + .984375; },
};
const lerp = (a: number, b: number, e: number) => a + (b - a) * e;
const rgba = (hex: string, a: number) => { const n = parseInt(String(hex).slice(1), 16) || 0; return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };

/** Inline style of one animated unit (char/word/line) at time `tt`. Mirrors the AE expression selector. */
function unitStyle(a: Anim, i: number, tt: number, k: number): React.CSSProperties {
  const lt = tt - i * a.stagger;
  if (a.ease === "wave") {
    const y = (a.props[0][1] as number[])[1];
    return { transform: `translateY(${Math.sin((tt / a.dur) * 2 * Math.PI - i * .6) * y * k}px)` };
  }
  const p = clamp(lt / Math.max(a.dur, .001));
  if (a.ease === "flicker") return { opacity: p >= 1 ? 1 : lt < 0 ? 0 : (Math.floor(lt * 30 + i * 7) % 3 ? 1 : .15) };
  const e = (EASE[a.ease] || EASE.cubic)(p);
  const tf: string[] = [], st: React.CSSProperties = {};
  for (const [name, v] of a.props) {
    const vv = v as any;
    if (name.endsWith("Scale 3D")) tf.push(`scale(${lerp(vv[0] / 100, 1, e)},${lerp(vv[1] / 100, 1, e)})`);
    else if (name.endsWith("Position 3D")) tf.push(`translate(${lerp(vv[0], 0, e) * k}px,${lerp(vv[1], 0, e) * k}px)`);
    else if (name.endsWith("Rotation")) tf.push(`rotate(${lerp(vv, 0, e)}deg)`);
    else if (name.endsWith("Opacity")) st.opacity = lerp(vv / 100, 1, e);
    else if (name.endsWith("Blur")) st.filter = `blur(${lerp(vv[0], 0, e) * k * .5}px)`;
    else if (name.endsWith("Tracking Amount")) st.letterSpacing = `${lerp(vv, 0, e) / 1000}em`;
  }
  if (tf.length) st.transform = tf.join(" ");
  return st;
}

function textShadow(l: Look, k: number) {
  const out: string[] = [];
  const sw = Number(l.stroke_width || 0) * k * .5;
  if (sw > 0) for (let a = 0; a < 360; a += 45) out.push(`${(Math.cos(a * Math.PI / 180) * sw).toFixed(1)}px ${(Math.sin(a * Math.PI / 180) * sw).toFixed(1)}px 0 ${l.stroke}`);
  if (Number(l.glow) > 0) out.push(`0 0 ${Number(l.glow) * k * .4}px ${l.stroke || l.highlight}`, `0 0 ${Number(l.glow) * k * .9}px ${l.stroke || l.highlight}`);
  if (l.shadow) out.push(`${3 * k}px ${4 * k}px ${8 * k}px rgba(0,0,0,.6)`);
  return out.join(",") || undefined;
}

export function LivePreview({ s, width, playing = true }: { s: Spec; width: number; playing?: boolean }) {
  const [tt, setT] = useState(99);
  const units = s.anim.based_on === 2 ? s.text.length : s.anim.based_on === 3 ? s.text.split(/\s+/).length : 1;
  const period = Math.max(s.preview_seconds || 3, units * s.anim.stagger + s.anim.dur + 1.2);
  useEffect(() => {
    if (!playing) { setT(99); return; }
    let raf = 0; const t0 = performance.now();
    const loop = () => { setT(((performance.now() - t0) / 1000) % period); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, period]);
  const k = width / s.w, height = s.h * k, l = s.look;
  const align = String(l.align || (s.kind === "lower_third" ? "left" : "center"));
  const words = s.text.split(/\s+/);
  const active = l.highlight_on ? Math.min(words.length - 1, Math.floor(Math.min(tt, period) / .45)) : -1;
  let ci = 0;
  const line = words.map((w, wi) => {
    const inner = s.anim.based_on === 2
      ? w.split("").map((ch) => <span key={ci} style={{ display: "inline-block", ...unitStyle(s.anim, ci++, tt, k) }}>{ch}</span>)
      : w;
    if (s.anim.based_on === 2) ci++; // the space between words is a character too
    return <span key={wi} style={{ display: "inline-block", color: String(wi === active ? l.highlight : l.fill),
      ...(s.anim.based_on === 3 ? unitStyle(s.anim, wi, tt, k) : {}) }}>{inner}{wi < words.length - 1 ? "\u00a0" : ""}</span>;
  });
  const font = String(l.font || "Arial");
  return (
    <div className="mg-stage" style={{ width, height }}>
      <div className="mg-text" style={{
        left: `${s.pos[0] * 100}%`, top: `${s.pos[1] * 100}%`, textAlign: align as any,
        transform: `translate(${align === "left" ? "0" : align === "right" ? "-100%" : "-50%"},-50%)`,
        fontFamily: `"${font.replace(/-(BoldMT|MT|Bold|Black|Regular)$/i, "")}", "${font}", Arial, sans-serif`,
        fontWeight: /black|bold|impact|heavy/i.test(font) ? 800 : 600, fontSize: s.size * k,
        letterSpacing: l.tracking ? `${Number(l.tracking) / 1000}em` : undefined, lineHeight: l.leading ? `${Number(l.leading) * k}px` : 1.15,
        fontKerning: l.kerning === "none" ? "none" : "normal", textShadow: textShadow(l, k),
        background: l.box ? rgba(String(l.box_color), Number(l.box_opacity) / 100) : undefined,
        padding: l.box ? `${.18 * s.size * k}px ${.4 * s.size * k}px` : undefined, borderRadius: l.box ? 14 * k : undefined,
        ...(s.anim.based_on === 4 ? unitStyle(s.anim, 0, tt, k) : {}),
      }}>
        {line}
        {s.subtext && <div style={{ fontSize: "0.55em", color: String(l.highlight), opacity: clamp((tt - .3) / .4) }}>{s.subtext}</div>}
      </div>
    </div>
  );
}

type FieldType = "text" | "num" | "color" | "bool" | string[];
const FIELDS: [string, string, FieldType][] = [
  ["text", "Text", "text"], ["subtext", "Subtitle", "text"], ["font", "Font (PostScript name)", "text"], ["size", "Size (px @1080p)", "num"],
  ["fill", "Fill color", "color"], ["stroke", "Stroke color", "color"], ["stroke_width", "Stroke width", "num"],
  ["highlight", "Highlight color", "color"], ["highlight_on", "Highlight active word", "bool"],
  ["tracking", "Letter spacing", "num"], ["leading", "Line spacing (0 = auto)", "num"], ["kerning", "Kerning", ["metrics", "optical", "none"]],
  ["align", "Alignment", ["center", "left", "right"]], ["dur", "Animation duration (s), lower = faster", "num"], ["stagger", "Stagger (s)", "num"],
  ["duration", "Template length (s)", "num"], ["box", "Background box", "bool"], ["box_color", "Box color", "color"],
  ["box_opacity", "Box opacity %", "num"], ["shadow", "Drop shadow", "bool"], ["glow", "Glow intensity", "num"],
];
const LOOK_KEYS = new Set(["font", "fill", "stroke", "stroke_width", "highlight", "highlight_on", "box", "box_color", "box_opacity", "shadow", "glow", "tracking", "leading", "kerning", "align"]);
const NUM_LOOK = new Set(["stroke_width", "box_opacity", "glow", "tracking", "leading"]);

function applyOverrides(base: Spec, o: Record<string, any>, info: Info): Spec {
  const pick = (f: (s: Spec) => boolean) => info.catalog.find(f);
  const anim = o.anim && o.anim !== base.anim_name ? pick((x) => x.anim_name === o.anim)?.anim : null;
  const look = o.look && o.look !== base.look_name ? pick((x) => x.look_name === o.look)?.look : null;
  const fmt = o.format && o.format !== base.format ? pick((x) => x.kind === base.kind && x.format === o.format) : null;
  const s: Spec = JSON.parse(JSON.stringify({ ...base, ...(fmt ? { w: fmt.w, h: fmt.h, pos: fmt.pos, size: fmt.size } : {}) }));
  if (anim) { s.anim = JSON.parse(JSON.stringify(anim)); s.anim_name = o.anim; }
  if (look) { s.look = { ...look }; s.look_name = o.look; }
  for (const [key, v] of Object.entries(o)) {
    if (v === "" || v === undefined || ["anim", "look", "format"].includes(key)) continue;
    if (LOOK_KEYS.has(key)) s.look[key] = NUM_LOOK.has(key) ? Number(v) : v;
    else if (key === "dur" || key === "stagger") (s.anim as any)[key] = Number(v);
    else if (key === "size" || key === "duration") (s as any)[key] = Number(v);
    else if (key === "text" || key === "subtext") (s as any)[key] = String(v);
  }
  return s;
}

export default function Graphics({ onCaptions, onClose, vertical }: { onCaptions: (file: string) => void; onClose: () => void; vertical?: boolean }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [q, setQ] = useState(""), [kind, setKind] = useState("caption"), [fmt, setFmt] = useState(vertical ? "9x16" : "16x9");
  useEffect(() => { if (vertical !== undefined) setFmt(vertical ? "9x16" : "16x9"); }, [vertical]); // follow the open sequence
  const [hover, setHover] = useState(""), [sel, setSel] = useState<Spec | null>(null);
  const [o, setO] = useState<Record<string, any>>({}), [saveName, setSaveName] = useState("");
  const [msg, setMsg] = useState(""), [busy, setBusy] = useState(false), [imp, setImp] = useState("");
  const [styles, setStyles] = useState<Record<string, Record<string, any>>>(store.get("mogrtStyles", {}));
  const [urls, setUrls] = useState<Record<string, { png?: string; gif?: string }>>({});
  const load = () => api.get("/mogrt").then(setInfo).catch((e) => setMsg((e as Error).message));
  useEffect(() => { load(); }, []);
  const built = useMemo(() => Object.fromEntries((info?.library || []).map((e) => [e.id, e])), [info]);
  // a still per card, the animated preview only under the pointer: 194 live GIFs at once made the panel crawl.
  // All the URLs land in one update, so the grid renders once, not once per template.
  useEffect(() => {
    const lib = info?.library || [];
    Promise.all(lib.map(async (e) => [e.id, { png: e.png ? await api.mediaUrl(e.id, "png") : undefined,
      gif: e.gif ? await api.mediaUrl(e.id, "gif") : undefined }] as const)).then((all) => setUrls(Object.fromEntries(all)));
  }, [info]);
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const mine = (info?.library || []).filter((e) => e.source !== "pack").map((e) => e.spec || ({ id: e.id, name: e.name, kind: "imported" } as Spec));
    if (kind === "mine" && !needle) return mine;
    return [...mine, ...(info?.catalog || [])].filter((s) => needle ? `${s.name} ${s.id}`.toLowerCase().includes(needle)
      : s.kind === kind && (s.kind !== "caption" || s.format === fmt));
  }, [info, q, kind, fmt]);
  const live = sel?.anim && info ? applyOverrides(sel, o, info) : null;
  const toBuild = list.filter((s) => s.anim && !built[s.id]);

  async function run(label: string, fn: () => Promise<any>) {
    setBusy(true); setMsg(label);
    try {
      const r = await fn();
      setMsg(typeof r === "string" ? r : r?.built !== undefined ? `Built ${r.built}/${r.requested}${r.failed?.length ? `, ${r.failed.length} failed` : ""}` : "Done");
      load();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  function saveStyle() {
    if (!saveName.trim()) return;
    const next = { ...styles, [saveName.trim()]: o };
    setStyles(next); store.set("mogrtStyles", next); setMsg(`Style “${saveName.trim()}” saved: apply it to any template from My styles`);
  }

  if (!info) return <section className="card fade"><h2>{t("graphics")}<button className="ghost close" onClick={onClose} aria-label="Close">✕</button></h2><p className="help">{msg || "…"}</p></section>;
  return (
    <section className="card graphics fade">
      <div className="mg-head"><h2>{t("graphics")}</h2><span className="count">{info.catalog.length} templates, {info.library.length} built</span>
        <button className="ghost close" onClick={onClose} aria-label="Close">✕</button></div>
      {!sel && <>
        <div className="search"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("searchTemplates")} aria-label="Search templates" /></div>
        {!q && <nav className="tabs small">
          {[...info.kinds, "mine"].map((x) => <button key={x} className={kind === x ? "on" : ""} onClick={() => setKind(x)}>{x === "mine" ? "Mine" : x.replace("_", " ")}</button>)}
          {kind === "caption" && <span className="fmt">{info.formats.map((x) => <button key={x} className={fmt === x ? "on" : ""}
            onClick={() => setFmt(x)} aria-label={`Format ${x.replace("x", ":")}`}>{x.replace("x", ":")}</button>)}</span>}
        </nav>}
        <div className="mg-grid">
          {list.map((s) => (
            <button key={s.id} className={`mg-card${s.format === "9x16" ? " tall" : ""}`} onMouseEnter={() => setHover(s.id)}
              onMouseLeave={() => setHover("")} onFocus={() => setHover(s.id)} onBlur={() => setHover("")}
              onClick={() => { setSel(s); setO({}); setSaveName(""); setMsg(""); }} title={s.name}>
              {urls[s.id]?.png ? <span className="mg-thumb"><img src={(hover === s.id && urls[s.id].gif) || urls[s.id].png} alt="" /></span>
                : s.anim ? <LivePreview s={s} width={150} playing={hover === s.id} /> : <div className="mg-stage imported">MOGRT</div>}
              <span className="mg-name">{s.anim_name ? `${s.anim_name}, ${s.look_name}` : s.name}</span>
              {s.anim && !built[s.id] && <em className="tier">not built</em>}
            </button>
          ))}
          {!list.length && <span className="help">No templates here yet.</span>}
        </div>
        <div className="row mg-import"><input value={imp} onChange={(e) => setImp(e.target.value)} placeholder="Import a .mogrt you own: C:\…\template.mogrt" aria-label="MOGRT path" />
          {host.pickFile && <button className="ghost" onClick={async () => { const p = await host.pickFile!(); if (p) setImp(p); }}>…</button>}
          <button className="ghost" disabled={!imp || busy} onClick={() => run("Importing", () => api.post("/mogrt/import", { path: imp }).then((e) => `Imported “${e.name}” with ${e.controls} editable controls`))}>Import</button></div>
        <div className="actions">
          {!info.library.some((e) => e.source === "pack") && <button className="primary" disabled={busy}
            onClick={() => run("Downloading the Kerf MOGRT pack (194 templates with previews)…", () => api.post("/mogrt/install-pack", {}).then((r) => `Installed ${r.installed} templates`))}>Install the Kerf MOGRT pack</button>}
          {toBuild.length > 0 && <button className="ghost" disabled={busy} onClick={() => run("Building in After Effects (save and close any open AE project first)…",
            () => api.post("/mogrt/build", { ids: toBuild.map((s) => s.id) }))}>Build {toBuild.length} in After Effects</button>}
        </div>
      </>}
      {sel && <div className="studio fade">
        <button className="ghost" onClick={() => setSel(null)}>← {t("allTemplates")}</button>
        {live ? <>
          <div className="studio-preview"><LivePreview s={live} width={live.h > live.w ? 200 : 340} /></div>
          <div className="form">
            <label className="row">Animation<select value={live.anim_name} onChange={(e) => setO({ ...o, anim: e.target.value, dur: "", stagger: "" })}>{info.anims.map((a) => <option key={a}>{a}</option>)}</select></label>
            <label className="row">Look<select value={live.look_name} onChange={(e) => setO({ anim: o.anim, format: o.format, text: o.text, look: e.target.value })}>{info.looks.map((a) => <option key={a}>{a}</option>)}</select></label>
            <label className="row">Format<select value={o.format || live.format} onChange={(e) => setO({ ...o, format: e.target.value })}>{info.formats.map((a) => <option key={a}>{a}</option>)}</select></label>
            {FIELDS.filter(([k]) => k !== "subtext" || live.kind === "lower_third").map(([k, l, type]) => {
              const v = o[k] ?? (k in live.look ? live.look[k] : k === "dur" || k === "stagger" ? (live.anim as any)[k] : (live as any)[k]) ?? "";
              const set = (x: any) => setO({ ...o, [k]: x });
              if (type === "bool") return <label key={k} className="row check"><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />{l}</label>;
              if (Array.isArray(type)) return <label key={k} className="row">{l}<select value={String(v || type[0])} onChange={(e) => set(e.target.value)}>{type.map((c) => <option key={c}>{c}</option>)}</select></label>;
              if (type === "color") return <label key={k} className="row">{l}<span className="color"><input type="text" value={String(v)} onChange={(e) => set(e.target.value)} /><i style={{ background: String(v) }} /></span></label>;
              return <label key={k} className="row">{l}<input type={type === "num" ? "number" : "text"} step="any" value={String(v)} onChange={(e) => set(e.target.value)} /></label>;
            })}
          </div>
          <div className="presets">
            <select value="" onChange={(e) => e.target.value && setO(styles[e.target.value])} aria-label="My styles">
              <option value="">My styles…</option>{Object.keys(styles).map((n) => <option key={n}>{n}</option>)}</select>
            <input value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="Name (style or MOGRT)" aria-label="Name" />
            <button className="ghost" onClick={saveStyle} disabled={!saveName.trim()}>Save style</button>
          </div>
        </> : <p className="help">{sel.name}: imported template. Edit its controls in Premiere’s Essential Graphics panel.</p>}
        <div className="actions">
          {live && <button className="ghost" onClick={() => setO({})}>Reset</button>}
          {built[sel.id] && <button className="ghost" onClick={() => run("Inserting", () => host.insertMogrt(built[sel.id].file))}>Insert at playhead</button>}
          {built[sel.id] && (sel.kind === "caption" || sel.kind === "imported") && <button className="ghost" onClick={() => onCaptions(built[sel.id].file)}>Use for captions</button>}
          {live && <button className="primary" disabled={busy || !saveName.trim()} onClick={() => run("Building your MOGRT in After Effects…",
            () => api.post("/mogrt/studio", { base: sel.id, name: saveName.trim(), overrides: Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "")) }))}>Save as my MOGRT</button>}
        </div>
        {live && <p className="help">Every value stays editable later in Premiere’s Essential Graphics panel.</p>}
      </div>}
      {msg && <div className={busy ? "busy" : "note"}>{busy && <span className="spinner" />} {msg}</div>}
    </section>
  );
}
