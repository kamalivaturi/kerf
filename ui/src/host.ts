// Host adapters. Premiere Pro (UXP) reads/writes the real timeline; "standalone" (browser at /app)
// works on media files. Both talk to the same local Kerf engine.
import type { premierepro, Sequence, Project } from "@adobe/premierepro";

export type Clip = { path: string; src_in: number; src_out: number; start: number; enabled: boolean };
export type TimelineDict = { fps: number; width: number; height: number; name: string; video: Clip[][]; audio: Clip[][] };
export type RunResult = {
  xml?: string[]; sequence_names?: string[]; files?: string[]; imports?: string[]; srt?: string; text?: string;
  markers?: { t: number; name: string }[]; report?: Record<string, unknown>;
  items?: { id: number; label: string }[];
  mogrt?: { path: string; param: string; pages: { start: number; end: number; text: string }[] };
  error?: string;
};

export interface Host {
  name: "premiere" | "standalone";
  readTimeline(): Promise<TimelineDict>;
  apply(res: RunResult): Promise<string[]>; // returns human-readable notes
  outDir(): Promise<string | undefined>;
  readToken(): Promise<string>;
  insertMogrt(path: string): Promise<string>; // at the playhead, on a new top track
  pickFile?(): Promise<string | undefined>;
  launchEngine?(kerfHome: string): Promise<void>;
}

const req: ((m: string) => any) | undefined = (globalThis as any).require;
export const IN_UXP: boolean = __UXP__ && typeof req === "function";

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

  async function trackClips(track: any): Promise<Clip[]> {
    const items = track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false) || [];
    const out: Clip[] = [];
    for (const it of Array.from(items) as any[]) {
      const proj = await it.getProjectItem();
      const clip = proj && (await ppro.ClipProjectItem.cast(proj));
      const path = clip && (await clip.getMediaFilePath());
      if (!path) continue; // graphics, adjustment layers, nested sequences: not media files
      const [s, e, i] = await Promise.all([it.getStartTime(), it.getEndTime(), it.getInPoint()]);
      out.push({ path, start: s.seconds, src_in: i.seconds, src_out: i.seconds + (e.seconds - s.seconds),
                 enabled: !(await it.isDisabled()) });
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
    async readTimeline() {
      const [, seq] = await active();
      const fps = TICKS / Number(await seq.getTimebase());
      const rect = await (await seq.getSettings()).getVideoFrameRect();
      const video: Clip[][] = [], audio: Clip[][] = [];
      for (let i = 0; i < (await seq.getVideoTrackCount()); i++) video.push(await trackClips(await seq.getVideoTrack(i)));
      for (let i = 0; i < (await seq.getAudioTrackCount()); i++) audio.push(await trackClips(await seq.getAudioTrack(i)));
      return { fps, width: Math.round(rect.width), height: Math.round(rect.height), name: seq.name, video, audio };
    },
    async apply(res) {
      const notes: string[] = [];
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
      const os = req!("os");
      const script = os.platform?.() === "win32" ? `${kerfHome}\\start-kerf.cmd` : `${kerfHome}/start-kerf.command`;
      await uxp.shell.openPath(script);
    },
  };
}

// ------------------------------------------------------------------ Standalone (browser)

let mediaPaths: string[] = [];
export const setStandaloneMedia = (paths: string[]) => { mediaPaths = paths; };
export const standaloneMedia = () => mediaPaths;

function standalone(): Host {
  return {
    name: "standalone",
    async readTimeline() {
      if (!mediaPaths[0]) throw new Error("Enter a media file path first.");
      const { api } = await import("./api");
      return (await api.post("/media", { path: mediaPaths[0] })).timeline;
    },
    async apply(res) {
      return [...(res.xml || []).map((x) => `Timeline XML: ${x} (import into Premiere or Resolve)`), ...(res.files || [])];
    },
    async insertMogrt(path) { return `Drag ${path} into Premiere (Essential Graphics) - inserting needs the Premiere panel`; },
    async outDir() { return undefined; },
    async readToken() { return (window as any).KERF_TOKEN || ""; },
  };
}

export const host: Host = IN_UXP ? premiere() : standalone();
