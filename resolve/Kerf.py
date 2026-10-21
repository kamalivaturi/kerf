"""Kerf for DaVinci Resolve (Free & Studio). Workspace > Scripts > Kerf.

Reads the current timeline, sends it to the local Kerf engine, and imports the result as a new
timeline (FCP7 XML via MediaPool.ImportTimelineFromFile). Stdlib only: runs on Resolve's Python.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

KERF_HOME = os.environ.get("KERF_HOME", r"C:\Kerf")  # replaced by the installer
ENGINE = "http://127.0.0.1:7878"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".kerf", "token")


# ------------------------------------------------------------------ engine

def call(path, body=None, timeout=3600):
    token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else ""
    req = urllib.request.Request(ENGINE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "X-Kerf-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(json.loads(e.read() or b"{}").get("error", str(e)))


def alive():
    try:
        urllib.request.urlopen(ENGINE + "/health", timeout=2)
        return True
    except Exception:
        return False


def engine_command():
    """Kerf Studio's bundled engine if installed (Windows, macOS, Linux), a portable build, else Python + source."""
    exe = "kerf-engine.exe" if os.name == "nt" else "kerf-engine"
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kerf Studio", "engine"),
              "/Applications/Kerf Studio.app/Contents/Resources/engine", os.path.expanduser("~/Applications/Kerf Studio.app/Contents/Resources/engine"),
              "/usr/lib/kerf-studio/engine", "/usr/lib/Kerf Studio/engine", os.path.join(KERF_HOME, "kerf-engine"), KERF_HOME):
        if os.path.isfile(os.path.join(d, exe)):
            return [os.path.join(d, exe), "serve", "--follow-editors"], d
    return ["python" if os.name == "nt" else "python3", "-m", "kerf", "serve", "--follow-editors"], KERF_HOME


def ensure_engine():
    if alive():
        return True
    cmd, cwd = engine_command()
    subprocess.Popen(cmd, cwd=cwd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(40):
        time.sleep(0.5)
        if alive():
            return True
    return False


# ------------------------------------------------------------------ Resolve timeline <-> dict

def project():
    return resolve.GetProjectManager().GetCurrentProject()  # noqa: F821 (Resolve injects `resolve`)


def read_timeline():
    tl = project().GetCurrentTimeline()
    if not tl:
        raise RuntimeError("Open a timeline first.")
    fps = float(tl.GetSetting("timelineFrameRate"))
    t0 = tl.GetStartFrame()
    out = dict(fps=fps, width=int(tl.GetSetting("timelineResolutionWidth")),
               height=int(tl.GetSetting("timelineResolutionHeight")), name=tl.GetName(), video=[], audio=[])
    for kind in ("video", "audio"):
        for i in range(1, tl.GetTrackCount(kind) + 1):
            clips = []
            for it in tl.GetItemListInTrack(kind, i) or []:
                mpi = it.GetMediaPoolItem()
                path = mpi.GetClipProperty("File Path") if mpi else ""
                if not path:
                    continue  # titles, generators, compound clips
                src_in = it.GetLeftOffset() / fps
                enabled = it.GetClipEnabled() if hasattr(it, "GetClipEnabled") else True
                clip = dict(path=path, start=(it.GetStart() - t0) / fps, src_in=src_in,
                            src_out=src_in + it.GetDuration() / fps, enabled=bool(enabled))
                if kind == "video":  # the clip's own framing, so effects build on it (Zoom is over fit-to-frame)
                    try:
                        sw, sh = (int(v) for v in mpi.GetClipProperty("Resolution").lower().split("x"))
                        fit = min(out["width"] / sw, out["height"] / sh)
                        clip.update(base_scale=float(it.GetProperty("ZoomX")) * fit * 100,
                                    base_center=[float(it.GetProperty("Pan")) / out["width"], -float(it.GetProperty("Tilt")) / out["height"]])
                    except Exception:
                        pass  # unknown resolution or properties: neutral framing
                clips.append(clip)
            out[kind].append(clips)
    try:  # playhead (timecode -> seconds from the timeline start) for the Toolkit tools
        h, m, sec, fr = (int(x) for x in tl.GetCurrentTimecode().replace(";", ":").split(":"))
        start = tl.GetStartTimecode().replace(";", ":").split(":")
        out["playhead"] = max(0.0, (h * 3600 + m * 60 + sec + fr / fps) - (int(start[0]) * 3600 + int(start[1]) * 60 + int(start[2]) + int(start[3]) / fps))
    except Exception:
        out["playhead"] = 0.0
    return out


def heartbeat():
    """Tell the engine which project, timeline and playhead are open (shown live in Kerf Studio)."""
    try:
        p = project()
        tl = p.GetCurrentTimeline() if p else None
        st = dict(project=p.GetName() if p else "")
        if tl:
            st.update(sequence=tl.GetName(), timecode=tl.GetCurrentTimecode(), fps=float(tl.GetSetting("timelineFrameRate")),
                      width=int(tl.GetSetting("timelineResolutionWidth")), height=int(tl.GetSetting("timelineResolutionHeight")))
        call("/host/heartbeat", dict(host="resolve", state=st), timeout=2)
        return st
    except Exception:
        return None  # engine restarting or no project: try again on the next tick


def sort_media_pool(mp, s):
    root = mp.GetRootFolder()
    folders = {f.GetName(): f for f in root.GetSubFolderList()}
    moves = {}
    for clip in root.GetClipList():
        if clip.GetClipProperty("Type") == "Timeline":
            name = s["sequences"]
        else:
            ext = os.path.splitext(clip.GetClipProperty("File Path") or "")[1].lower()
            name = next((b for b, exts in s["bins"].items() if ext in exts), s["other"])
        moves.setdefault(name, []).append(clip)
    for name, clips in moves.items():
        folder = folders.get(name) or mp.AddSubFolder(root, name)
        mp.MoveClips(clips, folder)
    mp.SetCurrentFolder(root)
    return f"Sorted {sum(len(c) for c in moves.values())} item(s) into {len(moves)} folder(s)"


def insert_layer(proj, mp, ins):
    """Generated layer (solid, bars...) onto a new top video track at the playhead of the open timeline."""
    tl = proj.GetCurrentTimeline()
    items = mp.ImportMedia([ins["path"]]) if tl else None
    if not items:
        return None
    fps = float(tl.GetSetting("timelineFrameRate"))
    tl.AddTrack("video")
    ok = mp.AppendToTimeline([{"mediaPoolItem": items[0], "startFrame": 0, "endFrame": int(ins["duration"] * fps) - 1,
                               "trackIndex": tl.GetTrackCount("video"), "recordFrame": tl.GetStartFrame() + int(ins["at"] * fps)}])
    return "Added the layer at the playhead" if ok else None


def apply(res):
    proj, notes = project(), []
    mp = proj.GetMediaPool()
    if res.get("sort"):
        return [sort_media_pool(mp, res["sort"])]
    if res.get("insert"):
        done = insert_layer(proj, mp, res["insert"])
        if done:
            return [done]
    if res.get("imports"):  # downloads etc. go straight into the Media Pool
        mp.ImportMedia(res["imports"])
        notes.append(f"Imported {len(res['imports'])} file(s) into the Media Pool")
    names = res.get("sequence_names") or []
    for i, xml in enumerate(res.get("xml", [])):
        name = names[i] if i < len(names) else os.path.splitext(os.path.basename(xml))[0]
        new = mp.ImportTimelineFromFile(xml, {"timelineName": name, "importSourceClips": True})
        if new:
            proj.SetCurrentTimeline(new)
            notes.append(f"Created timeline '{name}'")
        else:
            notes.append(f"Resolve could not import {xml}")
    if res.get("srt"):
        mp.ImportMedia([res["srt"]])
        notes.append("Caption SRT added to the Media Pool (drag it onto the timeline for a subtitle track)")
    tl = proj.GetCurrentTimeline()
    fps = float(tl.GetSetting("timelineFrameRate")) if tl else 30.0
    for m in res.get("markers", []) if tl else []:
        tl.AddMarker(int(round(m["t"] * fps)), "Blue", m["name"], "Kerf", 1)
    if res.get("markers"):
        notes.append(f"Added {len(res['markers'])} chapter markers")
    if res.get("mogrt"):
        notes.append("MOGRT captions are Premiere-only; in Resolve use output=overlay (animated caption clip)")
    return notes


# ------------------------------------------------------------------ UI (Fusion UIManager)

def main():
    ui = fusion.UIManager  # noqa: F821 (Resolve injects `fusion` and `bmd`)
    disp = bmd.UIDispatcher(ui)  # noqa: F821
    if not ensure_engine():
        print(f"Kerf: engine did not start. Run `python -m kerf serve` in {KERF_HOME}")
        return
    feats = call("/features")["features"]
    names = sorted(feats, key=lambda k: (feats[k]["group"], feats[k]["title"]))

    # Source stays ASCII (\u escapes): Resolve may read this file in the system code page.
    dot, sep, ell = "\u25cf", "  \u00b7  ", "\u2026"
    primary = ("QPushButton { background: #ff6b2c; color: #1a0f08; font-weight: bold; border: none; border-radius: 6px;"
               " min-height: 28px; } QPushButton:hover { background: #ff8a4f; } QPushButton:disabled { background: #5a3a2a; }")
    win = disp.AddWindow({"ID": "KerfWin", "WindowTitle": "Kerf", "Geometry": [120, 120, 520, 720]}, ui.VGroup({"Spacing": 6}, [
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "kerf", "Weight": 0,
                      "StyleSheet": "color: #ff6b2c; font-size: 22px; font-weight: 900; font-style: italic; padding-right: 10px;"}),
            ui.Label({"ID": "Live", "StyleSheet": "color: #57d68d;"})]),
        ui.HGroup({"Weight": 0}, [ui.Label({"Text": "Feature", "Weight": 0}), ui.ComboBox({"ID": "Feature"})]),
        ui.Label({"ID": "Help", "WordWrap": True, "Weight": 0, "MinimumSize": [200, 52], "Alignment": {"AlignTop": True},
                  "StyleSheet": "color: #a59a92;"}),
        ui.HGroup({"Weight": 0}, [ui.ComboBox({"ID": "Preset"}),
                                  ui.LineEdit({"ID": "PresetName", "PlaceholderText": "Save settings as" + ell}),
                                  ui.Button({"ID": "SavePreset", "Text": "Save", "Weight": 0})]),
        ui.Label({"Text": "Settings (JSON, edit any value)", "Weight": 0}),
        ui.TextEdit({"ID": "Params", "Weight": 3, "Font": ui.Font({"Family": "Consolas", "PixelSize": 13})}),
        ui.HGroup({"Weight": 0}, [ui.Button({"ID": "Analyze", "Text": "Analyze"}),
                                  ui.Button({"ID": "Apply", "Text": "Apply", "StyleSheet": primary})]),
        ui.Tree({"ID": "Items", "Weight": 2, "Hidden": True}),  # shown only when there is something to review
        ui.TextEdit({"ID": "Out", "ReadOnly": True, "Weight": 1, "PlaceholderText": "Results appear here."}),
    ]))
    it = win.GetItems()
    it["Items"].SetHeaderLabels(["Review (untick to skip)"])
    for n in names:
        it["Feature"].AddItem(feats[n]["group"] + sep + feats[n]["title"])
    state = {"items": []}

    def cur():
        return names[int(it["Feature"].CurrentIndex)]

    def show_params(p):
        it["Params"].PlainText = json.dumps({k: v for k, v in p.items() if k not in ("items", "preview")}, indent=1)

    def load_feature(ev=None):
        f = feats[cur()]
        it["Help"].Text = f["help"]
        show_params(f["defaults"])
        it["Preset"].Clear()
        it["Preset"].AddItem("Preset" + ell)
        for p in f["presets"]["builtin"] + f["presets"]["user"]:
            it["Preset"].AddItem(p)
        it["Analyze"].Enabled = bool(f["review"])
        it["Items"].Clear()
        it["Items"].Hidden = True
        state["items"] = []

    def load_preset(ev):
        if int(it["Preset"].CurrentIndex) > 0:
            show_params(call(f"/presets?feature={cur()}&name={urllib.parse.quote(it['Preset'].CurrentText)}"))

    def save_preset(ev):
        if it["PresetName"].Text.strip():
            call("/presets", dict(feature=cur(), name=it["PresetName"].Text.strip(), params=json.loads(it["Params"].PlainText)))
            feats.update(call("/features")["features"])
            load_feature()

    def run(analyze):
        try:
            params = json.loads(it["Params"].PlainText)
            if analyze:
                params["plan_only" if cur() == "prompt_edit" else "preview"] = True
            elif state["items"]:
                tree = it["Items"]
                ids = [str(x["id"]) for k, x in enumerate(state["items"]) if tree.TopLevelItem(k).CheckState[0] == "Checked"]
                params["items"] = ",".join(ids) or "-1"
            it["Out"].PlainText = "Working" + ell
            timeline = read_timeline() if feats[cur()].get("needs_timeline", True) else None
            res = call("/run", dict(feature=cur(), timeline=timeline, params=params, host="resolve"))
            if analyze:
                it["Items"].Clear()
                state["items"] = res.get("items", [])
                for x in state["items"]:
                    row = it["Items"].NewItem()
                    row.Text[0] = x["label"]
                    row.CheckState[0] = "Checked"
                    it["Items"].AddTopLevelItem(row)
                it["Items"].Hidden = not state["items"]
                it["Out"].PlainText = json.dumps(res.get("report", {}), indent=1)
                return
            notes = apply(res)
            it["Out"].PlainText = "\n".join(["\u2713 " + n for n in notes] + ([res["text"]] if res.get("text") else [])
                                            + [json.dumps(res.get("report", {}), indent=1)])
            state["items"] = []
            it["Items"].Clear()
            it["Items"].Hidden = True
        except Exception as e:
            it["Out"].PlainText = f"Error: {e}"

    win.On.Feature.CurrentIndexChanged = load_feature
    win.On.Preset.CurrentIndexChanged = load_preset
    win.On.SavePreset.Clicked = save_preset
    win.On.Analyze.Clicked = lambda ev: run(True)
    win.On.Apply.Clicked = lambda ev: run(False)
    win.On.KerfWin.Close = lambda ev: disp.ExitLoop()
    def beat(ev=None):
        s = heartbeat()
        it["Live"].Text = (dot + " " + s["project"] + (sep + s["sequence"] + sep + s["timecode"] if s.get("sequence") else "")) if s \
            else "\u25cb Kerf engine not reachable"

    try:  # live project / timeline / playhead while the Kerf window is open
        timer = ui.Timer({"ID": "KerfBeat", "Interval": 1000})
        disp.On.KerfBeat.Timeout = beat
        timer.Start()
    except Exception:
        timer = None
    beat()
    load_feature()
    win.Show()
    disp.RunLoop()
    if timer:
        timer.Stop()
    win.Hide()


main()
