// Host adapters. Premiere Pro (UXP) reads/writes the real timeline; "standalone" (browser at /app)
// works on media files. Both talk to the same local Kerf engine.
import type { premierepro, Sequence, Project } from "@adobe/premierepro";

export type Clip = { path: string; src_in: number; src_out: number; start: number; enabled: boolean;
                     base_scale?: number; base_center?: [number, number] }; // the clip's own Scale / Position
export type TimelineDict = { fps: number; width: number; height: number; name: string; video: Clip[][]; audio: Clip[][]; playhead?: number };
export type Live = { project?: string; sequence?: string; timecode?: string; playhead?: number; fps?: number; width?: number; height?: number };
export const timecode = (s: number, fps: number) => {
  const r = Math.round(fps) || 30, f = Math.round(s * fps), p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(f / r / 3600))}:${p(Math.floor(f / r / 60) % 60)}:${p(Math.floor(f / r) % 60)}:${p(f % r)}`;
};
/** The open editor sequence/comp/timeline with a known frame size, if any editor reports one. */
export const liveSequence = (live?: Record<string, Live>) =>
  Object.entries(live || {}).map(([host, s]) => ({ host, ...s })).find((s) => s.width && s.height && s.fps);
export type RunResult = {
  xml?: string[]; sequence_names?: string[]; files?: string[]; imports?: string[]; srt?: string; text?: string;
  markers?: { t: number; name: string }[]; report?: Record<string, unknown>;
  items?: { id: number; label: string }[];
  mogrt?: { path: string; param: string; pages: { start: number; end: number; text: string }[] };
  insert?: { path: string; at: number; duration: number };
  sort?: { bins: Record<string, string[]>; sequences: string; other: string };
  error?: string;
};

// What each editor can do; the UI only shows tabs, cards and buttons whose action the editor supports.
const ALL = ["anchor", "null", "bars", "adjustment", "solid", "beats", "clearBeats", "valueCurve", "speedCurve", "speedGraph", "shake",
  "shakeEngine", "stabilize", "zoom", "layout", "mask", "frameExport", "sortProject", "fx", "graphs", "edit", "graphics"];
const CAPS: Record<string, Set<string>> = {
  premiere: new Set(ALL),
  standalone: new Set(ALL.filter((a) => !["adjustment", "clearBeats", "fx"].includes(a))),
  aftereffects: new Set(["anchor", "null", "parentNull", "adjustment", "solid", "beats", "clearBeats", "valueCurve", "speedCurve", "shake",
    "stabilize", "zoom", "alignAE", "mask", "frameExport", "sortProject", "fx", "captions"]),
};
export const EDITOR_NAME: Record<string, string> = { premiere: "Premiere", aftereffects: "After Effects", standalone: "Studio" };

export interface Host {
  name: "premiere" | "aftereffects" | "standalone";
  has(action: string): boolean; // capability: hide what this editor can't do
  native?: Record<string, (p: Record<string, any>) => Promise<string>>; // tools that run inside the editor itself
  readTimeline(): Promise<TimelineDict>;
  apply(res: RunResult): Promise<string[]>; // returns human-readable notes
  outDir(): Promise<string | undefined>;
  readToken(): Promise<string>;
  insertMogrt(path: string): Promise<string>; // at the playhead, on a new top track
  tools?: HostTools;
  projectKey?(): Promise<string>; // per-project UI layouts // NLE-side actions (Premiere): selection-based tools the engine can't do from files
  pickFile?(): Promise<string | undefined>;
  onFileDrop?(cb: (paths: string[]) => void): void; // files dropped on the window (Kerf Studio)
  launchEngine?(kerfHome: string): Promise<void>;
  live?(): Promise<Live>; // project / sequence / playhead right now (Premiere), sent to the engine as a heartbeat
}

export interface HostTools {
  setAnchor(ax: number, ay: number): Promise<string>;
  ease(mode: "linear" | "bezier" | "hold"): Promise<string>;
  clearMarkers(prefix: string): Promise<string>;
  copyFx(): Promise<{ components: unknown[] }>;
  applyFx(chain: { components: any[] }): Promise<string>;
  adjustment(): Promise<string>;
}

const req: ((m: string) => any) | undefined = (globalThis as any).require;
export const IN_UXP: boolean = __UXP__ && typeof req === "function";
export const IN_CEP: boolean = !__UXP__ && typeof (globalThis as any).__adobe_cep__ !== "undefined"; // After Effects HTML panel
export const IN_EDITOR = IN_UXP || IN_CEP;

// ------------------------------------------------------------------ Premiere Pro (UXP)

function premiere(): Host {
  const ppro = req!("premierepro") as premierepro;
  const uxp = req!("uxp");
  const TICKS = 254016000000;

  async function active(): Promise<[Project, Sequence]> {
    const project = await ppro.Project.getActiveProject();
    const seq = project && (await project.getActiveSequence());
    if (!project || !seq) throw new Error("Open a sequence in Premiere Pro first.");
    return [project, seq];
  }

  // Scale and Position of a clip as the editor shows them, so effects build on the existing framing
  async function framing(it: any, W: number, H: number): Promise<Partial<Clip>> {
    try {
      const motion = (await components(it)).out.find((c) => c.match === "AE.ADBE Motion")?.comp;
      if (!motion) return {};
      const prm: Record<string, any> = {};
      for (let i = 0; i < motion.getParamCount(); i++) prm[motion.getParam(i).displayName] = motion.getParam(i);
      const pos = plain((await prm["Position"].getStartValue()).value.value) as number[];
      const n = Math.abs(pos[0]) > 2 || Math.abs(pos[1]) > 2 ? [pos[0] / W, pos[1] / H] : pos; // pixels or 0..1
      return { base_scale: Number((await prm["Scale"].getStartValue()).value.value) || 100, base_center: [n[0] - 0.5, n[1] - 0.5] };
    } catch { return {}; } // no Motion (audio, graphics) or an unreadable value: neutral framing
  }

  async function trackClips(track: any, frame?: [number, number]): Promise<Clip[]> {
    const items = track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false) || [];
    const out: Clip[] = [];
    for (const it of Array.from(items) as any[]) {
      const proj = await it.getProjectItem();
      const clip = proj && (await ppro.ClipProjectItem.cast(proj));
      const path = clip && (await clip.getMediaFilePath());
      if (!path) continue; // graphics, adjustment layers, nested sequences: not media files
      const [s, e, i] = await Promise.all([it.getStartTime(), it.getEndTime(), it.getInPoint()]);
      out.push({ path, start: s.seconds, src_in: i.seconds, src_out: i.seconds + (e.seconds - s.seconds),
                 enabled: !(await it.isDisabled()), ...(frame ? await framing(it, ...frame) : {}) });
    }
    return out;
  }

  function transact(project: Project, label: string, build: (add: (a: any) => void) => void) {
    let ok = false;
    project.lockedAccess(() => {
      ok = project.executeTransaction((ca) => build((a) => ca.addAction(a)), label);
    });
    return ok;
  }

  async function allItems(folder: any, out: any[] = []): Promise<any[]> {
    for (const it of await ppro.FolderItem.cast(folder).getItems()) {
      out.push(it);
      if (it.type === ppro.Constants.ProjectItemType.BIN) await allItems(it, out);
    }
    return out;
  }
  async function mediaPath(it: any) {
    try { return (await ppro.ClipProjectItem.cast(it).getMediaFilePath()) || ""; } catch { return ""; }
  }
  const norm = (x: string) => x.replace(/\\/g, "/").toLowerCase();

  async function insertAt(project: Project, seq: Sequence, item: any, seconds: number, label: string) {
    const editor = ppro.SequenceEditor.getEditor(seq);
    const vt = await seq.getVideoTrackCount();
    transact(project, label, (add) => add(editor.createOverwriteItemAction(item, ppro.TickTime.createWithSeconds(seconds), vt, 0)));
  }

  async function sortProject(project: Project, s: NonNullable<RunResult["sort"]>) {
    const root = await project.getRootItem();
    const folder = ppro.FolderItem.cast(root as any);
    const top = (await folder.getItems()) as any[];
    const isBin = (x: any) => x.type === ppro.Constants.ProjectItemType.BIN;
    const plan: [any, string][] = [];
    for (const it of top.filter((x) => !isBin(x))) {
      let bin = s.other;
      try { if (await ppro.ClipProjectItem.cast(it).isSequence()) bin = s.sequences; } catch { /* not a clip */ }
      if (bin === s.other) {
        const ext = ((await mediaPath(it)).match(/\.[^.\\/]+$/)?.[0] || "").toLowerCase();
        bin = Object.entries(s.bins).find(([, exts]) => exts.includes(ext))?.[0] || s.other;
      }
      plan.push([it, bin]);
    }
    const names = new Set(plan.map(([, b]) => b));
    const have = new Set(top.filter(isBin).map((x) => x.name));
    transact(project, "Kerf bins", (add) => [...names].filter((n) => !have.has(n)).forEach((n) => add(folder.createBinAction(n, false))));
    const bins = Object.fromEntries(((await folder.getItems()) as any[]).filter(isBin).map((x) => [x.name, ppro.FolderItem.cast(x)]));
    transact(project, "Kerf project sort", (add) => plan.forEach(([it, b]) => bins[b] && add(folder.createMoveItemAction(it, bins[b] as any))));
    return `Sorted ${plan.length} item(s) into ${names.size} bin(s)`;
  }

  async function selectedVideo(): Promise<[Project, Sequence, any[]]> {
    const [project, seq] = await active();
    const items = await (await seq.getSelection()).getTrackItems();
    const video = [];
    for (const it of items as any[]) if ((await components(it)).out.some((c) => c.match === "AE.ADBE Motion")) video.push(it);
    if (!video.length) throw new Error("Select one or more video clips in the timeline first.");
    return [project, seq, video];
  }
  async function components(item: any) {
    const chain = await item.getComponentChain();
    const out: { comp: any; match: string }[] = [];
    for (let i = 0; i < chain.getComponentCount(); i++) {
      const comp = chain.getComponentAtIndex(i);
      out.push({ comp, match: await comp.getMatchName() });
    }
    return { chain, out };
  }
  const INTRINSIC = new Set(["AE.ADBE Motion", "AE.ADBE Opacity", "AE.ADBE Time Remapping"]);
  const plain = (v: any) => (v && typeof v === "object" && "x" in v && "y" in v ? [v.x, v.y] : v);
  const typed = (v: any) => (Array.isArray(v) && v.length === 2 ? new (ppro as any).PointF(v[0], v[1]) : v);

  const tools: HostTools = {
    async setAnchor(ax, ay) {
      // ponytail: assumes the clip fills the frame (normalized Motion coordinates); off-size media lands approximately
      const [project, , items] = await selectedVideo();
      const actions: any[] = [];
      for (const it of items) {
        const motion = (await components(it)).out.find((c) => c.match === "AE.ADBE Motion")!.comp;
        const prm: Record<string, any> = {};
        for (let i = 0; i < motion.getParamCount(); i++) prm[motion.getParam(i).displayName] = motion.getParam(i);
        const pos = plain((await prm["Position"].getStartValue()).value.value);
        const anc = plain((await prm["Anchor Point"].getStartValue()).value.value);
        const sc = Number((await prm["Scale"].getStartValue()).value.value) / 100 || 1;
        const np = [pos[0] + (ax - anc[0]) * sc, pos[1] + (ay - anc[1]) * sc];
        actions.push(prm["Anchor Point"].createSetValueAction(prm["Anchor Point"].createKeyframe(typed([ax, ay])), true),
                     prm["Position"].createSetValueAction(prm["Position"].createKeyframe(typed(np)), true));
      }
      transact(project, "Kerf anchor", (add) => actions.forEach(add));
      return `Anchor moved on ${items.length} clip(s); the picture stays in place`;
    },
    async ease(mode) {
      const [project, , items] = await selectedVideo();
      const m = { linear: ppro.Keyframe.INTERPOLATION_MODE_LINEAR, bezier: ppro.Keyframe.INTERPOLATION_MODE_BEZIER,
                  hold: ppro.Keyframe.INTERPOLATION_MODE_HOLD }[mode];
      const actions: any[] = [];
      for (const it of items) for (const { comp } of (await components(it)).out) {
        for (let i = 0; i < comp.getParamCount(); i++) {
          const prm = comp.getParam(i);
          if (prm.isTimeVarying()) prm.getKeyframeListAsTickTimes().forEach((t: any) => actions.push(prm.createSetInterpolationAtKeyframeAction(t, m, true)));
        }
      }
      transact(project, "Kerf keyframe ease", (add) => actions.forEach(add));
      return actions.length ? `Set ${actions.length} keyframe(s) to ${mode}` : "The selected clips have no keyframes";
    },
    async clearMarkers(prefix) {
      const [project, seq] = await active();
      const markers = await ppro.Markers.getMarkers(seq);
      const hit = markers.getMarkers().filter((m: any) => m.getName().startsWith(prefix));
      transact(project, "Kerf clear markers", (add) => hit.forEach((m: any) => add(markers.createRemoveMarkerAction(m))));
      return `Removed ${hit.length} “${prefix}” marker(s)`;
    },
    async copyFx() {
      // ponytail: keyframe times are stored as Premiere reports them (clip-relative); retimed clips may need a nudge
      const [, , items] = await selectedVideo();
      const out = [];
      for (const { comp, match } of (await components(items[0])).out) {
        const params = [];
        for (let i = 0; i < comp.getParamCount(); i++) {
          const prm = comp.getParam(i);
          try {
            const keys = prm.isTimeVarying()
              ? prm.getKeyframeListAsTickTimes().map((t: any) => ({ t: t.seconds, v: plain(prm.getKeyframePtr(t).value.value) })) : [];
            params.push({ i, name: prm.displayName, value: plain((await prm.getStartValue()).value.value), keys });
          } catch { /* colours and other opaque values are skipped */ }
        }
        out.push({ match, name: await comp.getDisplayName(), params });
      }
      return { components: out };
    },
    async applyFx(preset) {
      const [project, , items] = await selectedVideo();
      for (const it of items) {
        const { chain } = await components(it);
        const add: any[] = [];
        for (const c of preset.components)
          if (!INTRINSIC.has(c.match)) add.push(chain.createAppendComponentAction(await ppro.VideoFilterFactory.createComponent(c.match)));
        transact(project, "Kerf apply effects", (a) => add.forEach(a));
        const now = (await components(it)).out, used = new Set<number>(), actions: any[] = [];
        for (const c of preset.components) {
          const k = now.findIndex((x, j) => x.match === c.match && !used.has(j) && (INTRINSIC.has(c.match) || j >= now.length - add.length));
          if (k < 0) continue;
          used.add(k);
          const comp = now[k].comp;
          for (const p of c.params) {
            try {
              const prm = comp.getParam(p.i);
              if (p.keys.length) {
                actions.push(prm.createSetTimeVaryingAction(true));
                for (const kf of p.keys) {
                  const f = prm.createKeyframe(typed(kf.v));
                  f.position = ppro.TickTime.createWithSeconds(kf.t);
                  actions.push(prm.createAddKeyframeAction(f));
                }
              } else actions.push(prm.createSetValueAction(prm.createKeyframe(typed(p.value)), true));
            } catch { /* a param type that can't be set this way */ }
          }
        }
        transact(project, "Kerf effect values", (a) => actions.forEach(a));
      }
      return `Applied ${preset.components.length} effect(s) to ${items.length} clip(s)`;
    },
    async adjustment() {
      const [project, seq] = await active();
      const adj = (await allItems(await project.getRootItem())).find((x) => /adjustment layer/i.test(x.name) && x.type !== ppro.Constants.ProjectItemType.BIN);
      if (!adj) return "Premiere has no scripting call to create adjustment layers: make one once (File › New › Adjustment Layer) and Kerf will reuse it";
      await insertAt(project, seq, adj, (await seq.getPlayerPosition()).seconds, "Kerf adjustment layer");
      return `Placed “${adj.name}” at the playhead`;
    },
  };

  // AE-authored MOGRT text params hold JSON ({"textEditValue": ...} plus style); plain strings elsewhere.
  async function textValue(prm: any, text: string) {
    try {
      const cur = (await prm.getStartValue())?.value;
      const v = typeof cur === "string" && cur.startsWith("{") ? JSON.parse(cur) : null;
      if (v && "textEditValue" in v) return JSON.stringify({ ...v, textEditValue: text });
    } catch { /* fall through to plain text */ }
    return text;
  }

  // One MOGRT instance per caption page; the page text goes into the template's text parameter.
  async function placeMogrt(project: Project, seq: Sequence, m: NonNullable<RunResult["mogrt"]>) {
    const editor = ppro.SequenceEditor.getEditor(seq);
    const vTrack = await seq.getVideoTrackCount(); // new track above everything
    let placed = 0, textSet = 0;
    for (const pg of m.pages) {
      const items = Array.from((await editor.insertMogrtFromPath(m.path, ppro.TickTime.createWithSeconds(pg.start), vTrack, 0)) || []);
      const video = items.find((x: any) => typeof x.getComponentChain === "function") as any;
      if (!video) continue;
      placed++;
      const chain = await video.getComponentChain();
      const actions: any[] = [video.createSetEndAction(ppro.TickTime.createWithSeconds(pg.end))];
      for (let c = 0; c < chain.getComponentCount(); c++) {
        const comp = chain.getComponentAtIndex(c);
        for (let p = 0; p < comp.getParamCount(); p++) {
          const prm = comp.getParam(p);
          if (prm.displayName === m.param) {
            try { actions.push(prm.createSetValueAction(prm.createKeyframe(await textValue(prm, pg.text)), true)); textSet++; } catch { /* not a text param */ }
          }
        }
      }
      transact(project, "Kerf MOGRT caption", (add) => actions.forEach(add));
    }
    return textSet ? `Placed ${placed} MOGRT captions`
      : `Placed ${placed} MOGRT captions, but no parameter named “${m.param}” was found: set mogrt_param to your template's text field name`;
  }

  return {
    name: "premiere",
    has: (a) => CAPS.premiere.has(a),
    tools,
    async projectKey() { return (await ppro.Project.getActiveProject())?.path || "untitled"; },
    async live() {
      const project = await ppro.Project.getActiveProject();
      const seq = project && (await project.getActiveSequence());
      if (!seq) return { project: project?.name };
      const fps = TICKS / Number(await seq.getTimebase());
      const playhead = (await seq.getPlayerPosition()).seconds;
      const rect = await (await seq.getSettings()).getVideoFrameRect();
      return { project: project.name, sequence: seq.name, playhead, fps, width: Math.round(rect.width), height: Math.round(rect.height),
               timecode: timecode(playhead, fps) };
    },
    async readTimeline() {
      const [, seq] = await active();
      const fps = TICKS / Number(await seq.getTimebase());
      const rect = await (await seq.getSettings()).getVideoFrameRect();
      const video: Clip[][] = [], audio: Clip[][] = [];
      const frame: [number, number] = [Math.round(rect.width), Math.round(rect.height)];
      for (let i = 0; i < (await seq.getVideoTrackCount()); i++) video.push(await trackClips(await seq.getVideoTrack(i), frame));
      for (let i = 0; i < (await seq.getAudioTrackCount()); i++) audio.push(await trackClips(await seq.getAudioTrack(i)));
      const playhead = (await seq.getPlayerPosition()).seconds;
      return { fps, width: Math.round(rect.width), height: Math.round(rect.height), name: seq.name, video, audio, playhead };
    },
    async apply(res) {
      const notes: string[] = [];
      if (res.sort) return [await sortProject(await ppro.Project.getActiveProject(), res.sort)];
      if (res.insert) { // a generated layer goes onto the open sequence instead of into a new one
        const [project, seq] = await active();
        const root = await project.getRootItem();
        await project.importFiles([res.insert.path], true, root as any, false);
        let item = null;
        for (const it of (await allItems(root)).reverse()) if (norm(await mediaPath(it)) === norm(res.insert.path)) { item = it; break; }
        if (item) { await insertAt(project, seq, item, res.insert.at, "Kerf layer"); return [`Added ${res.insert.path.split(/[\\/]/).pop()} at the playhead`]; }
      }
      if (res.imports?.length) { // downloads etc.: into the project bin, no open sequence required
        const project = await ppro.Project.getActiveProject();
        await project.importFiles(res.imports, true, (await project.getRootItem()) as any, false);
        notes.push(`Imported ${res.imports.length} file(s) into the project`);
        if (!res.xml?.length && !res.markers?.length) return notes;
      }
      const [project, seq] = await active();
      const root = await project.getRootItem();
      for (const [i, xml] of (res.xml || []).entries()) {
        const before = new Set((await project.getSequences()).map((s) => s.guid.toString()));
        await project.importFiles([xml], true, root as any, false);
        const created = (await project.getSequences()).filter((s) => !before.has(s.guid.toString()));
        const target = created.find((s) => s.name === res.sequence_names?.[i]) || created[created.length - 1];
        if (target) { await project.openSequence(target); notes.push(`Opened sequence “${target.name}”`); }
      }
      if (res.srt) { await project.importFiles([res.srt], true, root as any, false); notes.push("Caption SRT imported into the project bin"); }
      if (res.markers?.length) {
        const markers = await ppro.Markers.getMarkers(seq);
        transact(project, "Kerf markers", (add) => res.markers!.forEach((m) =>
          add(markers.createAddMarkerAction(m.name, "Chapter", ppro.TickTime.createWithSeconds(m.t),
                                            ppro.TickTime.createWithSeconds(0), "Kerf"))));
        notes.push(`Added ${res.markers.length} chapter markers`);
      }
      if (res.mogrt) notes.push(await placeMogrt(project, seq, res.mogrt));
      return notes;
    },
    async insertMogrt(path) {
      const [, seq] = await active();
      const at = await seq.getPlayerPosition();
      const items = await ppro.SequenceEditor.getEditor(seq).insertMogrtFromPath(path, at, await seq.getVideoTrackCount(), 0);
      return items?.length ? `Inserted ${path.split(/[\/]/).pop()} at the playhead (edit it in Essential Graphics)` : "Premiere did not insert the template";
    },
    async outDir() {
      const [project] = await active();
      return project.path ? project.path.replace(/[\\/][^\\/]+$/, "") + "/Kerf" : undefined;
    },
    async readToken() {
      const os = req!("os"), fs = req!("fs");
      const sep = os.platform?.() === "win32" ? "\\" : "/";
      return String(await fs.readFile(`${os.homedir()}${sep}.kerf${sep}token`, { encoding: "utf-8" })).trim();
    },
    async pickFile() {
      const f = await uxp.storage.localFileSystem.getFileForOpening();
      return f?.nativePath;
    },
    async launchEngine(kerfHome) {
      const os = req!("os"), win = os.platform?.() === "win32";
      // the Kerf helper (set up by the Kerf installer) starts the engine; else a source checkout's start script
      const helper = win ? `${os.homedir()}\\AppData\\Local\\Kerf\\kerf.exe` : "/Applications/Kerf.app";
      if (await uxp.shell.openPath(helper).then((r: unknown) => !r, () => false)) return;
      await uxp.shell.openPath(win ? `${kerfHome}\\start-kerf.cmd` : `${kerfHome}/start-kerf.command`);
    },
  };
}

// ------------------------------------------------------------------ Standalone (browser)

let mediaPaths: string[] = [];
export const setStandaloneMedia = (paths: string[]) => { mediaPaths = paths; };
export const standaloneMedia = () => mediaPaths;

export const NO_MEDIA = "Choose a video first: click “Choose video…” at the top, drag a file into the window, or paste its path.";

function standalone(): Host {
  const tauri = (globalThis as any).__TAURI__; // Kerf Studio exposes the native file picker and file drops
  return {
    name: "standalone",
    has: (a) => CAPS.standalone.has(a),
    ...(tauri?.dialog && {
      async pickFile() {
        const p = await tauri.dialog.open({ multiple: false, filters: [{ name: "Video, audio or image",
          extensions: ["mp4", "mov", "mkv", "m4v", "avi", "webm", "mxf", "mts", "wav", "mp3", "m4a", "aac", "flac", "png", "jpg", "jpeg", "mogrt"] }] });
        return typeof p === "string" ? p : undefined;
      },
    }),
    ...(tauri?.webview && {
      onFileDrop(cb: (paths: string[]) => void) {
        tauri.webview.getCurrentWebview().onDragDropEvent((e: any) => { if (e.payload?.type === "drop" && e.payload.paths?.length) cb(e.payload.paths); });
      },
    }),
    async readTimeline() {
      if (!mediaPaths[0]) throw new Error(NO_MEDIA);
      const { api } = await import("./api");
      const tl: TimelineDict = (await api.post("/media", { path: mediaPaths[0] })).timeline;
      const seq = liveSequence((await api.get("/host").catch(() => null))?.live);
      return seq ? { ...tl, width: seq.width!, height: seq.height!, fps: seq.fps! } : tl;
    },
    async apply(res) {
      return [...(res.xml || []).map((x) => `Timeline XML: ${x} (import into Premiere or Resolve)`), ...(res.files || [])];
    },
    async insertMogrt(path) { return `Drag ${path} into Premiere (Essential Graphics) - inserting needs the Premiere panel`; },
    async outDir() { return undefined; },
    async readToken() { return (window as any).KERF_TOKEN || ""; },
  };
}

// ------------------------------------------------------------------ After Effects (CEP panel; tools run in ExtendScript, aftereffects/Kerf.jsx)

function aftereffects(): Host {
  const cep = (globalThis as any).__adobe_cep__;
  const es = (script: string) => new Promise<string>((ok) => cep.evalScript(script, (r: string) => ok(r)));
  const call = async (name: string, settings: object = {}, args: unknown[] = []) => {
    const out = await es(`KerfAE.call(${JSON.stringify(name)}, ${JSON.stringify(settings)}, ${JSON.stringify(args)})`);
    let r: { ok?: boolean; text?: string } = {};
    try { r = JSON.parse(out); } catch { throw new Error(out && out !== "EvalScript error." ? out : "After Effects didn't answer: open a composition and try again"); }
    if (!r.ok) throw new Error(r.text || `${name} failed`);
    return r.text || "Done";
  };
  // Engine work runs here, asynchronously, so After Effects never freezes; ExtendScript only adds the result.
  const engine = async (feature: string, params: Record<string, unknown>, timeline: unknown) => {
    const { api } = await import("./api");
    return (await api.post("/run", { feature, timeline, params })) as RunResult & { files?: string[] };
  };
  const clip = async () => JSON.parse(await call("clipInfo")) as { timeline: TimelineDict; path: string; name: string; region: string };
  return {
    name: "aftereffects",
    has: (a) => CAPS.aftereffects.has(a),
    native: {
      anchor: (p) => call("anchor", {}, [p.ax, p.ay]), null: () => call("null"), parentNull: () => call("parentNull"),
      adjustment: () => call("adjustment"), solid: (p) => call("solid", {}, [p.color]),
      beats: async (p) => {
        const c = await clip();
        const res = await engine("beat_markers", { music: c.path, every: p.every }, c.path);
        return call("addMarkers", {}, [res.markers || []]);
      },
      clearBeats: () => call("clearBeats"),
      valueCurve: (p) => call("valueCurve", {}, [p.name]), speedCurve: (p) => call("speedCurve", {}, [p.kind]),
      shake: (p) => call("shake", { axis: p.axis, amp: p.amplitude, freq: p.frequency, rot: p.rotation, dur: p.duration, decay: p.decay, flash: Number(p.flash) > 0 }),
      stabilize: () => call("stabilize"),
      zoom: (p) => call("zoom", { amount: p.amount, zdur: p.duration }, [p.direction, p.ease === "out" ? "out" : "in"]),
      align: (p) => call("align", {}, [p.mode]),
      mask: async () => {
        const c = await clip();
        const res = await engine("quick_mask", { clips: "all", region: c.region, model: "u2net_human_seg" }, c.timeline);
        if (!res.files?.length) throw new Error("No cutout was made: is the selected layer a video?");
        return call("addLayer", {}, [res.files[0], `${c.name} (Kerf cutout)`]);
      },
      frameExport: () => call("frameExport"),
      sortProject: () => call("sortProject"), copyFx: (p) => call("copyFx", {}, [p.name]), applyFx: (p) => call("applyFx", {}, [p.name]),
      captions: async () => {
        const c = await clip();
        const res = await engine("captions", { output: "overlay" }, { ...c.timeline, audio: c.timeline.video });
        const mov = (res.files || []).find((f) => /\.mov$/i.test(f));
        if (!mov) return "No speech found in the selected layer";
        return call("addLayer", {}, [mov, "Kerf captions", 0]);
      },
    },
    async live() { try { return JSON.parse(await es("KerfAE.live()")); } catch { return {}; } },
    async projectKey() { return (await this.live!()).project || "untitled"; },
    async readTimeline() { throw new Error("After Effects tools work on the selected layers of the open composition."); },
    async apply() { return []; },
    async outDir() { return undefined; },
    readToken: () => es("KerfAE.token()"),
    async insertMogrt() { return "MOGRTs are for Premiere Pro"; },
    async launchEngine() { await es("KerfAE.launch()"); },
  };
}

export const host: Host = IN_UXP ? premiere() : IN_CEP ? aftereffects() : standalone();
