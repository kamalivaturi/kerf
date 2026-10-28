"""Kerf for DaVinci Resolve (Free & Studio). Workspace > Scripts > Kerf.

Reads the current timeline, sends it to the local Kerf engine, and imports the result as a new
timeline (FCP7 XML via MediaPool.ImportTimelineFromFile). Stdlib only: runs on Resolve's Python.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KERF_HOME = os.environ.get("KERF_HOME", r"C:\Kerf")  # replaced by the installer
HOME = os.environ.get("KERF_HOME_DIR") or os.path.join(os.path.expanduser("~"), ".kerf")


def locator():
    """The engine's locator (kerf/server.py LOCATOR): port, token file, helper. Defaults before the first start."""
    try:
        with open(os.path.join(HOME, "engine.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def engine():
    return f"http://127.0.0.1:{locator().get('port', 7878)}"


# ------------------------------------------------------------------ engine

def call(path, body=None, timeout=3600):
    token_file = locator().get("token_file") or os.path.join(HOME, "token")
    token = open(token_file).read().strip() if os.path.exists(token_file) else ""
    req = urllib.request.Request(engine() + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "X-Kerf-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(json.loads(e.read() or b"{}").get("error", str(e)))


def alive():
    try:
        urllib.request.urlopen(engine() + "/health", timeout=2)
        return True
    except Exception:
        return False


def engine_command():
    """The Kerf helper if installed (runs the engine, keeps Kerf updated), a bundled engine, else Python + source."""
    app = locator().get("helper") or (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kerf", "kerf.exe") if os.name == "nt"
                                      else "/Applications/Kerf.app" if sys.platform == "darwin" else "/usr/bin/kerf")
    if os.path.exists(app):
        return (["open", "-g", app] if app.endswith(".app") else [app]), os.path.dirname(app) or "/"
    exe = "kerf-engine.exe" if os.name == "nt" else "kerf-engine"
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kerf", "engine"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kerf Studio", "engine"),
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
               height=int(tl.GetSetting("timelineResolutionHeight")), name=tl.GetName(), video=[], audio=[], editor="resolve")
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
                if kind == "video":  # the clip's framing as Resolve reports it; kerf/units.py converts it
                    try:
                        sw, sh = (int(v) for v in mpi.GetClipProperty("Resolution").lower().split("x"))
                        clip["framing"] = dict(zoom=float(it.GetProperty("ZoomX")), pan=float(it.GetProperty("Pan")),
                                               tilt=float(it.GetProperty("Tilt")), source=[sw, sh])
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
    """Tell the engine which project, timeline and playhead are open (shown live in the Kerf panels)."""
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


def pool_paths(folder):
    paths = {os.path.normcase(os.path.normpath(c.GetClipProperty("File Path") or ".")) for c in folder.GetClipList()}
    for sub in folder.GetSubFolderList():
        paths |= pool_paths(sub)
    return paths


def import_timeline(mp, xml, name):
    """Resolve refuses an XML whose source clips are already in the Media Pool when asked to import them, so add
    only the missing files first, then build the timeline from the pool."""
    text = open(xml, encoding="utf-8").read()
    files = {os.path.normpath(re.sub(r"^/(?=[A-Za-z]:)", "", urllib.parse.unquote(u)))
             for u in re.findall(r"<pathurl>file://localhost(/.*?)</pathurl>", text)}
    pool = pool_paths(mp.GetRootFolder())
    missing = [f for f in files if os.path.normcase(f) not in pool and os.path.exists(f)]
    if missing:
        mp.ImportMedia(missing)
    return (mp.ImportTimelineFromFile(xml, {"timelineName": name, "importSourceClips": False})
            or mp.ImportTimelineFromFile(xml, {"timelineName": name, "importSourceClips": True}))


def export_still(proj):
    """The composited frame at the playhead (every track, color and effects), straight from Resolve."""
    tl = proj.GetCurrentTimeline()
    if not tl or not hasattr(proj, "ExportCurrentFrameAsStill"):
        return None
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    folder = desk if os.path.isdir(desk) else os.path.join(os.path.expanduser("~"), ".kerf", "output")
    f = os.path.join(folder, f"{tl.GetName()} {tl.GetCurrentTimecode().replace(':', '-')}.png")
    return f if proj.ExportCurrentFrameAsStill(f) else None


def apply(res):
    """Performs the Result's steps (kerf/features.py steps) with Resolve's API."""
    proj, notes = project(), []
    mp = proj.GetMediaPool()
    for st in res.get("steps") or []:
        op = st["op"]
        if op == "sort":
            notes.append(sort_media_pool(mp, st["plan"]))
        elif op == "insert":
            notes.append(insert_layer(proj, mp, st) or "Resolve could not add the layer")
        elif op == "import":
            mp.ImportMedia(st["files"])
            notes.append("Caption SRT added to the Media Pool (drag it onto the timeline for a subtitle track)"
                         if st["what"] == "captions" else f"Imported {len(st['files'])} file(s) into the Media Pool")
        elif op == "timeline":
            taken = {proj.GetTimelineByIndex(i + 1).GetName() for i in range(proj.GetTimelineCount())}
            name = next(n for n in [st["name"]] + [f"{st['name']} {k}" for k in range(2, 999)] if n not in taken)  # Resolve rejects duplicates
            new = import_timeline(mp, st["xml"], name)
            if new:
                proj.SetCurrentTimeline(new)
                notes.append(f"Created timeline '{name}'")
            else:
                notes.append(f"Resolve could not import {st['xml']}")
        elif op == "markers":
            tl = proj.GetCurrentTimeline()
            fps = float(tl.GetSetting("timelineFrameRate")) if tl else 30.0
            for m in st["markers"] if tl else []:
                tl.AddMarker(int(round(m["t"] * fps)), "Blue", m["name"], "Kerf", 1)
            notes.append(f"Added {len(st['markers'])} chapter markers" if tl else "Open a timeline to add markers")
        elif op == "mogrt":
            notes.append("MOGRT captions are Premiere-only; in Resolve use output=overlay (animated caption clip)")
    return notes


# ------------------------------------------------------------------ UI (Fusion UIManager), styled like the Kerf panel

COLORS = [("Black", "#000000"), ("White", "#FFFFFF"), ("Kerf orange", "#FF6B2C"), ("Blue", "#3D7CFF"), ("Green", "#13B07A")]
FORM_ROWS = 7  # settings shown as controls; the rest are under "More settings"
# The Kerf panel's tokens (ui/src/styles.scss), so the Resolve window reads as the same product.
INK, MUTED, ACCENT, ACCENT_HOVER, ACCENT_INK = "#f3ece7", "#a59a92", "#ff6b2c", "#ff8a4c", "#1a0f08"
PAPER, PAPER2, PAPER3, RULE, RULE_STRONG, HOVER, PRESS = "#121110", "#1a1817", "#242120", "#2e2a28", "#403a36", "#2c2826", "#34302d"
STYLE = (
    f"QWidget {{ color: {INK}; font-size: 13px; }}"
    f"QWidget#KerfWin {{ background: {PAPER}; }}"
    f"QPushButton {{ background: {PAPER3}; border: 1px solid {RULE}; border-radius: 6px; padding: 8px 12px; font-weight: 600; }}"
    f"QPushButton:hover {{ background: {HOVER}; }} QPushButton:pressed {{ background: {PRESS}; }}"
    f"QPushButton:focus {{ border-color: {ACCENT}; }}"
    f"QPushButton:disabled {{ color: {MUTED}; background: {PAPER2}; border-color: {RULE}; }}"
    f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QTreeWidget {{ background: {PAPER}; border: 1px solid {RULE};"
    f" border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; selection-color: {ACCENT_INK}; }}"
    f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}"
    f"QComboBox QAbstractItemView {{ background: {PAPER2}; border: 1px solid {RULE_STRONG}; }}"
    f"QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 14px; font-weight: 600; border-bottom: 2px solid transparent; }}"
    f"QTabBar::tab:hover {{ color: {INK}; }}"
    f"QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; }}"
    f"QSlider::groove:horizontal {{ height: 4px; background: {RULE_STRONG}; border-radius: 2px; }}"
    f"QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}"
    f"QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -5px 0; border-radius: 7px; }}"
    f"QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {RULE_STRONG}; border-radius: 3px; background: {PAPER}; }}"
    f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}"
    f"QScrollBar:vertical {{ background: {PAPER}; width: 10px; }} QScrollBar::handle:vertical {{ background: {RULE_STRONG}; border-radius: 4px; }}"
)
PRIMARY = (f"QPushButton {{ background: {ACCENT}; color: {ACCENT_INK}; border: 1px solid {ACCENT}; border-radius: 6px; padding: 8px 12px;"
           f" font-weight: 600; }} QPushButton:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}"
           f" QPushButton:disabled {{ background: {PAPER3}; color: {MUTED}; }}")


def geometry(w=480, h=820):
    """Window rect in logical pixels (Resolve applies display scaling itself), capped to the screen's work area."""
    try:
        import ctypes
        dc = ctypes.windll.user32.GetDC(0)
        k = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
        screen_h = ctypes.windll.gdi32.GetDeviceCaps(dc, 117) / k  # DESKTOPVERTRES (physical) -> logical
        ctypes.windll.user32.ReleaseDC(0, dc)
    except Exception:  # macOS / Linux
        screen_h = 10_000
    return [60, 30, w, int(min(h, screen_h - 110))]  # leaves room for the title bar and taskbar


def main():
    ui = fusion.UIManager  # noqa: F821 (Resolve injects `fusion` and `bmd`)
    disp = bmd.UIDispatcher(ui)  # noqa: F821
    if not ensure_engine():
        print("Kerf: engine did not start. Reinstall Kerf (it sets up the engine), then try again.")
        return
    feats = call("/features")["features"]
    edit_names = sorted((n for n in feats if not feats[n].get("toolkit")),  # the toolkit ones have their own tabs
                         key=lambda k: (feats[k]["group"], feats[k]["title"]))
    ell = "\u2026"

    def head(text):
        return ui.Label({"Text": text, "Weight": 0,  # the panel's card heads: sentence case, one step up
                         "StyleSheet": f"color: {INK}; font-size: 14px; font-weight: 700; padding-top: 10px;"})

    def btn(id_, text, primary=False, tip=""):
        return ui.Button({"ID": id_, "Text": text, "ToolTip": tip, **({"StyleSheet": PRIMARY} if primary else {})})

    def slider(id_, label, lo, hi, val):
        return ui.HGroup({"Weight": 0}, [ui.Label({"Text": label, "Weight": 0, "MinimumSize": [110, 0]}),
                                         ui.Slider({"ID": id_, "Minimum": lo, "Maximum": hi, "Value": val, "Orientation": "Horizontal"}),
                                         ui.Label({"ID": id_ + "V", "Weight": 0, "MinimumSize": [48, 0], "Alignment": {"AlignRight": True}})])

    def row(*items):
        return ui.HGroup({"Weight": 0, "Spacing": 6}, list(items))

    tools = ui.VGroup({"Spacing": 6}, [
        head("Add layer"),
        row(btn("LNull", "Null", tip="Transparent placeholder layer at the playhead"), btn("LSolid", "Solid"),
            ui.ComboBox({"ID": "LColor", "Weight": 0})),
        row(btn("LBars", "Bars 2.39"), btn("LVig", "Vignette")),
        head("Beats"),
        row(btn("Beats", "Place beat markers", True), ui.Label({"Text": "every", "Weight": 0}),
            ui.SpinBox({"ID": "Every", "Minimum": 1, "Maximum": 16, "Value": 1, "Weight": 0})),
        head("Speed ramp (clip under the playhead)"),
        row(btn("SpIn", "Ease in"), btn("SpOut", "Ease out")),
        row(btn("SpRamp", "Speed ramp"), btn("SpBoth", "In and out")),
        head("Stabilizer"),
        row(btn("Stab", "Stabilize clip"), ui.Label({"Text": "Smoothness", "Weight": 0}),
            ui.Slider({"ID": "Smooth", "Minimum": 10, "Maximum": 100, "Value": 50, "Orientation": "Horizontal"}),
            ui.Label({"ID": "SmoothV", "Weight": 0, "MinimumSize": [40, 0]})),
        head("Quick mask (offline AI cutout)"),
        row(btn("Mask", "Cut out subject", True), ui.ComboBox({"ID": "MaskModel", "Weight": 0})),
        head("Utilities"),
        row(btn("Frame", "Save frame to Desktop"), btn("Sort", "Sort media pool")),
        ui.VGap(0, 1),
    ])
    motion = ui.VGroup({"Spacing": 6}, [
        head("Zoom (eased, at the playhead)"),
        slider("ZAmt", "Amount %", 101, 200, 120), slider("ZDur", "Duration s", 10, 500, 60),
        row(btn("ZInIn", "Zoom in, ease in"), btn("ZInOut", "Zoom in, ease out", True)),
        row(btn("ZOutIn", "Zoom out, ease in"), btn("ZOutOut", "Zoom out, ease out")),
        head("Place & align clips"),
        row(ui.Label({"Text": "Arrange", "Weight": 0}), ui.ComboBox({"ID": "Arrange"})),
        row(ui.Label({"Text": "Tracks", "Weight": 0}), ui.LineEdit({"ID": "LTracks", "Text": "2"})),
        row(ui.Label({"Text": "Scale %", "Weight": 0}), ui.SpinBox({"ID": "LScale", "Minimum": 0, "Maximum": 400, "Value": 35}),
            ui.Label({"Text": "Margin %", "Weight": 0}), ui.SpinBox({"ID": "LMargin", "Minimum": 0, "Maximum": 40, "Value": 4})),
        row(btn("Layout", "Apply layout", True,
                "Picture-in-picture, grids and alignment build a new timeline; Scale 0 = fit")),
        ui.VGap(0, 1),
    ])
    shakes = ui.VGroup({"Spacing": 6}, [
        head("Camera shake"),
        row(ui.Label({"Text": "Axis", "Weight": 0}), ui.ComboBox({"ID": "Axis"}), ui.Label({"Text": "On", "Weight": 0}), ui.ComboBox({"ID": "On"})),
        row(ui.Label({"Text": "Output", "Weight": 0}), ui.ComboBox({"ID": "Output"})),
        slider("SAmp", "Amplitude px", 0, 120, 28), slider("SFreq", "Frequency Hz", 1, 30, 11),
        slider("SRot", "Rotation \u00b0", 0, 100, 15), slider("SDur", "Duration s", 10, 300, 45),
        slider("SDecay", "Decay", 0, 100, 70),
        row(btn("PImpact", "Impact"), btn("PHand", "Handheld"), btn("PQuake", "Earthquake")),
        row(btn("Shake", "Apply shake", True)),
        ui.Label({"Text": "Live, keyframeable shake, zoom, RGB split, vignette and bars on any clip: Edit page, Effects, OpenFX, Kerf.", "WordWrap": True, "Weight": 0, "StyleSheet": f"color: {MUTED};"}),
        ui.VGap(0, 1),
    ])
    form = []
    for i in range(FORM_ROWS):
        form.append(row(ui.Label({"ID": f"FL{i}", "Weight": 0, "MinimumSize": [150, 0]}), ui.LineEdit({"ID": f"FE{i}"}),
                        ui.ComboBox({"ID": f"FC{i}"}), ui.CheckBox({"ID": f"FK{i}", "Text": ""})))
    edit = ui.VGroup({"Spacing": 6}, [
        row(ui.Label({"Text": "Feature", "Weight": 0}), ui.ComboBox({"ID": "Feature"})),
        ui.Label({"ID": "Help", "WordWrap": True, "Weight": 0, "MinimumSize": [200, 56], "Alignment": {"AlignTop": True},
                  "StyleSheet": f"color: {MUTED};"}),
        row(ui.ComboBox({"ID": "Preset"}), ui.LineEdit({"ID": "PresetName", "PlaceholderText": "Save settings as" + ell}),
            ui.Button({"ID": "SavePreset", "Text": "Save", "Weight": 0})),
        *form,
        ui.CheckBox({"ID": "More", "Text": "More settings (all values)", "Weight": 0}),
        ui.TextEdit({"ID": "Params", "Weight": 2, "Hidden": True, "Font": ui.Font({"Family": "Consolas", "PixelSize": 13})}),
        row(btn("Analyze", "Analyze"), btn("Apply", "Apply", True)),
        ui.Tree({"ID": "Items", "Weight": 2, "Hidden": True}),  # shown only when there is something to review
        ui.VGap(0, 1),
    ])
    geom = geometry()
    win = disp.AddWindow({"ID": "KerfWin", "WindowTitle": "Kerf", "Geometry": geom, "StyleSheet": STYLE},
                         ui.VGroup({"Spacing": 8}, [
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "kerf", "Weight": 0,
                      "StyleSheet": f"color: {ACCENT}; font-size: 24px; font-weight: 900; font-style: italic; padding-right: 10px;"}),
            ui.Label({"ID": "Live", "StyleSheet": f"color: {MUTED};"})]),
        ui.TabBar({"ID": "Tabs", "Weight": 0}),
        ui.Stack({"ID": "Pages"}, [tools, motion, shakes, edit]),
        ui.TextEdit({"ID": "Out", "ReadOnly": True, "Weight": 0, "MinimumSize": [200, 64], "PlaceholderText": "Results appear here."}),
    ]))
    it = win.GetItems()
    for t in ("Tools", "Motion", "Shakes", "Edit"):
        it["Tabs"].AddTab(t)
    it["Items"].SetHeaderLabels(["Review (untick to skip)"])
    for name, _ in COLORS:
        it["LColor"].AddItem(name)
    for label in ("People (best)", "Objects (fast)", "Objects (detailed)"):
        it["MaskModel"].AddItem(label)
    for a in feats["layout"]["choices"]["arrange"]:
        it["Arrange"].AddItem(a.replace("_", " "))
    for combo, key in (("Axis", "axis"), ("On", "on"), ("Output", "output")):
        for v in feats["camera_shake"]["choices"][key]:
            if not (key == "on" and v == "times"):
                it[combo].AddItem(v)
    it["Axis"].CurrentText, it["On"].CurrentText = "hv", "playhead"
    for n in edit_names:
        it["Feature"].AddItem(feats[n]["group"] + ": " + feats[n]["title"])
    state = {"items": [], "params": {}, "keys": [], "loading": False}

    # ---------------------------------------------------------------- running a feature
    def say(text):
        it["Out"].PlainText = text

    def run(name, params, label, analyze=False):
        try:
            say(label + ell)
            timeline = read_timeline() if feats[name].get("needs_timeline", True) else None
            res = call("/run", dict(feature=name, timeline=timeline, params=params, host="resolve"))
            if analyze:
                return res
            notes = apply(res)
            report = res.get("report") or {}
            say("\n".join(["\u2713 " + n for n in notes] + ([res["text"]] if res.get("text") else [])
                          + [f"{k}: {v}" for k, v in list(report.items())[:6]]) or "\u2713 " + label + " done")
        except Exception as e:
            say(f"\u26a0 {label}: {e}")
        return None

    def val(id_, k=1.0):
        return round(it[id_].Value * k, 3)

    def show_vals(ev=None):
        for id_, k, fmt in (("ZAmt", 1, "{:.0f}%"), ("ZDur", .01, "{:.2f}s"), ("SAmp", 1, "{:.0f}"), ("SFreq", 1, "{:.0f}"),
                            ("SRot", .1, "{:.1f}\u00b0"), ("SDur", .01, "{:.2f}s"), ("SDecay", .01, "{:.2f}"), ("Smooth", 1, "{:.0f}%")):
            it[id_ + "V"].Text = fmt.format(it[id_].Value * k)

    def shake_params():
        return dict(axis=it["Axis"].CurrentText, on=it["On"].CurrentText, output=it["Output"].CurrentText,
                    amplitude=val("SAmp"), frequency=val("SFreq"), rotation=val("SRot", .1), duration=val("SDur", .01),
                    decay=val("SDecay", .01), clips="playhead")

    def preset(values):
        for id_, v in values.items():
            it[id_].Value = v
        show_vals()

    def color():
        return COLORS[int(it["LColor"].CurrentIndex)][1]

    on = win.On
    on.LNull.Clicked = lambda ev: run("add_layer", dict(kind="transparent"), "Null")
    on.LSolid.Clicked = lambda ev: run("add_layer", dict(kind="solid", color=color()), "Solid")
    on.LBars.Clicked = lambda ev: run("add_layer", dict(kind="letterbox", aspect=2.39, duration=0), "Bars")
    on.LVig.Clicked = lambda ev: run("add_layer", dict(kind="vignette"), "Vignette")
    on.Beats.Clicked = lambda ev: run("beat_markers", dict(every=it["Every"].Value), "Beat markers")
    for id_, preset_name in (("SpIn", "ease_in"), ("SpOut", "ease_out"), ("SpRamp", "speedramp"), ("SpBoth", "ease_in_out")):
        setattr(getattr(on, id_), "Clicked", lambda ev, p=preset_name: run("speed_ramp", dict(preset=p, clips="playhead"), "Speed ramp"))
    on.Stab.Clicked = lambda ev: run("stabilize", dict(smoothing=round(it["Smooth"].Value * .6), clips="playhead"), "Stabilize")
    on.Mask.Clicked = lambda ev: run("quick_mask", dict(model=["u2net_human_seg", "u2netp", "silueta"][int(it["MaskModel"].CurrentIndex)],
                                                         output="cutout", clips="playhead"), "Quick mask")
    def frame(ev):
        f = export_still(project())
        say("\u2713 Saved " + f) if f else run("frame_export", {}, "Frame export")
    on.Frame.Clicked = frame
    on.Sort.Clicked = lambda ev: run("project_sort", {}, "Sort media pool")
    for id_, d, e in (("ZInIn", "in", "in"), ("ZInOut", "in", "out"), ("ZOutIn", "out", "in"), ("ZOutOut", "out", "out")):
        setattr(getattr(on, id_), "Clicked", lambda ev, d=d, e=e: run("zoom_move", dict(direction=d, ease=e, amount=val("ZAmt"),
                                                                                         duration=val("ZDur", .01)), f"Zoom {d}"))
    on.Layout.Clicked = lambda ev: run("layout", dict(arrange=it["Arrange"].CurrentText.replace(" ", "_"), tracks=it["LTracks"].Text,
                                                      scale=it["LScale"].Value, margin=it["LMargin"].Value), "Layout")
    on.Shake.Clicked = lambda ev: run("camera_shake", shake_params(), "Camera shake")
    on.PImpact.Clicked = lambda ev: preset(dict(SAmp=40, SFreq=11, SRot=15, SDur=35, SDecay=70))
    on.PHand.Clicked = lambda ev: (preset(dict(SAmp=6, SFreq=2, SRot=4, SDur=300, SDecay=0)), setattr(it["On"], "CurrentText", "whole"))
    on.PQuake.Clicked = lambda ev: preset(dict(SAmp=70, SFreq=18, SRot=30, SDur=120, SDecay=30))
    for id_ in ("ZAmt", "ZDur", "SAmp", "SFreq", "SRot", "SDur", "SDecay", "Smooth"):
        setattr(getattr(on, id_), "ValueChanged", show_vals)
    on.Tabs.CurrentChanged = lambda ev: setattr(it["Pages"], "CurrentIndex", int(it["Tabs"].CurrentIndex))

    # ---------------------------------------------------------------- Edit tab: settings form
    def cur():
        return edit_names[int(it["Feature"].CurrentIndex)]

    def choices_for(key):
        ch = feats[cur()]["choices"].get(key) or []
        return [c for c in ch if c != "mogrt"]  # MOGRTs are Premiere-only

    def show_json():
        it["Params"].PlainText = json.dumps(state["params"], indent=1)

    def fill(params):
        state["loading"], state["params"] = True, {k: v for k, v in params.items() if k not in ("items", "preview", "plan_only")}
        state["keys"] = list(state["params"])[:FORM_ROWS]
        for i in range(FORM_ROWS):
            key = state["keys"][i] if i < len(state["keys"]) else None
            v = state["params"].get(key)
            ch = choices_for(key) if key else []
            it[f"FL{i}"].Text = key.replace("_", " ").capitalize() if key else ""
            it[f"FE{i}"].Hidden = not key or isinstance(v, bool) or bool(ch)
            it[f"FC{i}"].Hidden = not key or not ch
            it[f"FK{i}"].Hidden = not key or not isinstance(v, bool)
            it[f"FL{i}"].Hidden = not key
            if key and ch:
                it[f"FC{i}"].Clear()
                for c in ch:
                    it[f"FC{i}"].AddItem(c)
                it[f"FC{i}"].CurrentText = str(v)
            elif key and isinstance(v, bool):
                it[f"FK{i}"].Checked = v
            elif key:
                it[f"FE{i}"].Text = "" if v is None else str(v)
        show_json()
        state["loading"] = False

    def form_changed(i, value):
        if state["loading"] or i >= len(state["keys"]):
            return
        state["params"][state["keys"][i]] = value
        show_json()

    for i in range(FORM_ROWS):
        setattr(getattr(on, f"FE{i}"), "TextChanged", lambda ev, i=i: form_changed(i, it[f"FE{i}"].Text))
        setattr(getattr(on, f"FC{i}"), "CurrentIndexChanged", lambda ev, i=i: form_changed(i, it[f"FC{i}"].CurrentText))
        setattr(getattr(on, f"FK{i}"), "Clicked", lambda ev, i=i: form_changed(i, bool(it[f"FK{i}"].Checked)))

    def json_changed(ev):
        if state["loading"]:
            return
        try:
            state["params"] = json.loads(it["Params"].PlainText)
        except ValueError:
            pass  # still typing

    def load_feature(ev=None):
        f = feats[cur()]
        h = f["help"]  # the label shows what fits in three lines; hover it for the rest
        it["Help"].Text = h if len(h) <= 150 else h[:h.rfind(" ", 0, 148)] + ell
        it["Help"].ToolTip = h
        it["Preset"].Clear()
        it["Preset"].AddItem("Preset" + ell)
        for p in f["presets"]["builtin"] + f["presets"]["user"]:
            it["Preset"].AddItem(p)
        it["Analyze"].Enabled = bool(f["review"])
        it["Items"].Clear()
        it["Items"].Hidden = True
        state["items"] = []
        fill(f["defaults"])

    def load_preset(ev):
        if int(it["Preset"].CurrentIndex) > 0:
            fill(call(f"/presets?feature={cur()}&name={urllib.parse.quote(it['Preset'].CurrentText)}"))

    def save_preset(ev):
        name = it["PresetName"].Text.strip()
        if name:
            call("/presets", dict(feature=cur(), name=name, params=state["params"]))
            feats.update(call("/features")["features"])
            load_feature()
            say("\u2713 Saved preset " + name)

    def run_edit(analyze):
        params = dict(state["params"])
        if analyze:
            params["plan_only" if cur() == "prompt_edit" else "preview"] = True
        elif state["items"]:
            tree = it["Items"]
            ids = [str(x["id"]) for k, x in enumerate(state["items"]) if tree.TopLevelItem(k).CheckState[0] == "Checked"]
            params["items"] = ",".join(ids) or "-1"
        res = run(cur(), params, feats[cur()]["title"], analyze)
        if analyze and res is not None:
            it["Items"].Clear()
            state["items"] = res.get("items", [])
            for x in state["items"]:
                r = it["Items"].NewItem()
                r.Text[0] = x["label"]
                r.CheckState[0] = "Checked"
                it["Items"].AddTopLevelItem(r)
            it["Items"].Hidden = not state["items"]
            say(f"{len(state['items'])} item(s) to review. Untick any to skip, then Apply." if state["items"]
                else json.dumps(res.get("report", {}), indent=1))
        elif not analyze:
            state["items"] = []
            it["Items"].Clear()
            it["Items"].Hidden = True

    on.Feature.CurrentIndexChanged = load_feature
    on.Preset.CurrentIndexChanged = load_preset
    on.SavePreset.Clicked = save_preset
    on.More.Clicked = lambda ev: setattr(it["Params"], "Hidden", not it["More"].Checked)
    on.Params.TextChanged = json_changed
    on.Analyze.Clicked = lambda ev: run_edit(True)
    on.Apply.Clicked = lambda ev: run_edit(False)
    on.KerfWin.Close = lambda ev: disp.ExitLoop()

    def beat(ev=None):
        s = heartbeat()
        it["Live"].Text = ", ".join([s["project"]] + ([s["sequence"], s["timecode"]] if s.get("sequence") else [])) if s \
            else "Kerf engine not reachable"

    try:  # live project / timeline / playhead while the Kerf window is open
        timer = ui.Timer({"ID": "KerfBeat", "Interval": 1000})
        disp.On.KerfBeat.Timeout = beat
        timer.Start()
    except Exception:
        timer = None
    beat()
    show_vals()
    load_feature()
    it["Params"].Hidden = it["Items"].Hidden = True  # hidden at creation, Qt still reserves their height
    win.RecalcLayout()
    win.Resize(geom[2:])  # Fusion restores the last size per window ID; start from one that fits
    win.Show()
    disp.RunLoop()
    if timer:
        timer.Stop()
    win.Hide()


main()
