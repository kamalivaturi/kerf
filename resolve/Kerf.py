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


def ensure_engine():
    if alive():
        return True
    subprocess.Popen(["python", "-m", "kerf", "serve"], cwd=KERF_HOME,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
                clips.append(dict(path=path, start=(it.GetStart() - t0) / fps, src_in=src_in,
                                  src_out=src_in + it.GetDuration() / fps, enabled=bool(enabled)))
            out[kind].append(clips)
    return out


def apply(res):
    proj, notes = project(), []
    mp = proj.GetMediaPool()
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

    win = disp.AddWindow({"ID": "KerfWin", "WindowTitle": "Kerf", "Geometry": [120, 120, 560, 780]}, ui.VGroup([
        ui.HGroup({"Weight": 0}, [ui.Label({"Text": "Feature", "Weight": 0}), ui.ComboBox({"ID": "Feature"})]),
        ui.Label({"ID": "Help", "WordWrap": True, "Weight": 0}),
        ui.HGroup({"Weight": 0}, [ui.ComboBox({"ID": "Preset"}),
                                  ui.LineEdit({"ID": "PresetName", "PlaceholderText": "Save settings as…"}),
                                  ui.Button({"ID": "SavePreset", "Text": "Save", "Weight": 0})]),
        ui.Label({"Text": "Settings (JSON, edit any value)", "Weight": 0}),
        ui.TextEdit({"ID": "Params", "Weight": 2}),
        ui.HGroup({"Weight": 0}, [ui.Button({"ID": "Analyze", "Text": "Analyze"}), ui.Button({"ID": "Apply", "Text": "Apply"})]),
        ui.Tree({"ID": "Items", "Weight": 2}),
        ui.TextEdit({"ID": "Out", "ReadOnly": True, "Weight": 1}),
    ]))
    it = win.GetItems()
    it["Items"].SetHeaderLabels(["Review (untick to skip)"])
    for n in names:
        it["Feature"].AddItem(f"{feats[n]['group']} · {feats[n]['title']}")
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
        it["Preset"].AddItem("Preset…")
        for p in f["presets"]["builtin"] + f["presets"]["user"]:
            it["Preset"].AddItem(p)
        it["Analyze"].Enabled = bool(f["review"])
        it["Items"].Clear()
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
            it["Out"].PlainText = "Working…"
            timeline = read_timeline() if feats[cur()].get("needs_timeline", True) else None
            res = call("/run", dict(feature=cur(), timeline=timeline, params=params))
            if analyze:
                it["Items"].Clear()
                state["items"] = res.get("items", [])
                for x in state["items"]:
                    row = it["Items"].NewItem()
                    row.Text[0] = x["label"]
                    row.CheckState[0] = "Checked"
                    it["Items"].AddTopLevelItem(row)
                it["Out"].PlainText = json.dumps(res.get("report", {}), indent=1)
                return
            notes = apply(res)
            it["Out"].PlainText = "\n".join(["✓ " + n for n in notes] + ([res["text"]] if res.get("text") else [])
                                            + [json.dumps(res.get("report", {}), indent=1)])
            state["items"] = []
            it["Items"].Clear()
        except Exception as e:
            it["Out"].PlainText = f"Error: {e}"

    win.On.Feature.CurrentIndexChanged = load_feature
    win.On.Preset.CurrentIndexChanged = load_preset
    win.On.SavePreset.Clicked = save_preset
    win.On.Analyze.Clicked = lambda ev: run(True)
    win.On.Apply.Clicked = lambda ev: run(False)
    win.On.KerfWin.Close = lambda ev: disp.ExitLoop()
    load_feature()
    win.Show()
    disp.RunLoop()
    win.Hide()


main()
