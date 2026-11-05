"""Kerf for DaVinci Resolve (Free & Studio): Workspace > Scripts > Kerf.

Removes silences from the open timeline: reads it, sends it to the local Kerf engine, and imports the result as a
new timeline (FCP7 XML via MediaPool.ImportTimelineFromFile). The looks (captions, zooms, shakes) are Kerf FX,
under Effects > OpenFX > Kerf. Stdlib only: runs on Resolve's Python.
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
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kerf", "engine"), os.path.join(KERF_HOME, "kerf-engine"), KERF_HOME):
        if os.path.isfile(os.path.join(d, exe)):
            return [os.path.join(d, exe), "serve", "--follow-editors"], d
    return ["python" if os.name == "nt" else "python3", "-m", "kerf", "serve", "--follow-editors"], KERF_HOME


def ensure_engine():
    """Resolve runs scripts without asking, so the window starts Kerf itself when the login watcher hasn't yet."""
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
    try:  # playhead (timecode -> seconds from the timeline start)
        h, m, sec, fr = (int(x) for x in tl.GetCurrentTimecode().replace(";", ":").split(":"))
        start = tl.GetStartTimecode().replace(";", ":").split(":")
        out["playhead"] = max(0.0, (h * 3600 + m * 60 + sec + fr / fps) - (int(start[0]) * 3600 + int(start[1]) * 60 + int(start[2]) + int(start[3]) / fps))
    except Exception:
        out["playhead"] = 0.0
    return out


def heartbeat():
    """Tell the engine which project and timeline are open (keeps it running while Resolve is)."""
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


def apply(res):
    """Performs the Result's timeline steps (kerf/features.py) with Resolve's API: the edit lands as a new timeline."""
    proj, notes = project(), []
    mp = proj.GetMediaPool()
    for st in res.get("steps") or []:
        if st["op"] != "timeline":
            notes.append(f"Skipped a '{st['op']}' step: this window only edits timelines")
            continue
        taken = {proj.GetTimelineByIndex(i + 1).GetName() for i in range(proj.GetTimelineCount())}
        name = next(n for n in [st["name"]] + [f"{st['name']} {k}" for k in range(2, 999)] if n not in taken)  # Resolve rejects duplicates
        new = import_timeline(mp, st["xml"], name)
        if new:
            proj.SetCurrentTimeline(new)
            notes.append(f"Created timeline '{name}'")
        else:
            notes.append(f"Resolve could not import {st['xml']}")
    return notes


# ------------------------------------------------------------------ UI (Fusion UIManager), styled like the Kerf panel

# The Kerf panel's tokens (ui/src/styles.scss), so the Resolve window reads as the same product.
INK, MUTED, ACCENT, ACCENT_HOVER, ACCENT_INK = "#f3ece7", "#a59a92", "#ff6b2c", "#ff8a4c", "#1a0f08"
PAPER, PAPER2, PAPER3, RULE, RULE_STRONG, HOVER, PRESS = "#121110", "#1a1817", "#242120", "#2e2a28", "#403a36", "#2c2826", "#34302d"
STYLE = (
    f"QWidget {{ color: {INK}; font-size: 13px; }}"
    f"QWidget#KerfWin {{ background: {PAPER}; }}"
    f"QPushButton {{ background: {ACCENT}; color: {ACCENT_INK}; border: 1px solid {ACCENT}; border-radius: 6px; padding: 8px 12px; font-weight: 600; }}"
    f"QPushButton:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }} QPushButton:pressed {{ background: {PRESS}; }}"
    f"QPushButton:disabled {{ color: {MUTED}; background: {PAPER2}; border-color: {RULE}; }}"
    f"QComboBox, QTextEdit {{ background: {PAPER}; border: 1px solid {RULE_STRONG}; border-radius: 6px; padding: 5px 8px;"
    f" selection-background-color: {ACCENT}; selection-color: {ACCENT_INK}; }}"
    f"QComboBox:hover {{ background: {HOVER}; }} QComboBox:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}"
    f"QComboBox QAbstractItemView {{ background: {PAPER2}; border: 1px solid {RULE_STRONG}; }}"
    f"QTextEdit#Out {{ background: {PAPER3}; border-color: {RULE}; }}"
)


def geometry(w=380, h=380):
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


def label(v):
    return v.replace("_", " ").capitalize()


def main():
    ui = fusion.UIManager  # noqa: F821 (Resolve injects `fusion` and `bmd`)
    disp = bmd.UIDispatcher(ui)  # noqa: F821
    if not ensure_engine():
        print("Kerf: engine did not start. Reinstall Kerf (it sets up the engine), then try again.")
        return
    f = call("/features")["features"]["silences"]
    choices, defaults = f["choices"], f["defaults"]
    keys = {"Preset": "preset", "Detection": "detection", "Mode": "mode"}

    def pick(id_, text):
        return ui.HGroup({"Weight": 0, "Spacing": 6}, [ui.Label({"Text": text, "Weight": 0, "MinimumSize": [80, 0]}),
                                                       ui.ComboBox({"ID": id_})])

    geom = geometry()
    win = disp.AddWindow({"ID": "KerfWin", "WindowTitle": "Kerf", "Geometry": geom, "StyleSheet": STYLE},
                         ui.VGroup({"Spacing": 8}, [
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "kerf", "Weight": 0,
                      "StyleSheet": f"color: {ACCENT}; font-size: 24px; font-weight: 900; font-style: italic; padding-right: 10px;"}),
            ui.Label({"ID": "Live", "StyleSheet": f"color: {MUTED};"})]),
        ui.Label({"Text": "Remove silences", "Weight": 0, "StyleSheet": f"color: {INK}; font-size: 14px; font-weight: 700; padding-top: 6px;"}),
        ui.Label({"Text": "Cuts the quiet parts of the open timeline into a new timeline. The original stays as it is.",
                  "WordWrap": True, "Weight": 0, "StyleSheet": f"color: {MUTED};"}),
        pick("Preset", "Pace"), pick("Detection", "Detect by"), pick("Mode", "Then"),
        ui.Button({"ID": "Run", "Text": "Remove silences", "Weight": 0}),
        ui.TextEdit({"ID": "Out", "ReadOnly": True, "MinimumSize": [200, 64], "PlaceholderText": "Results appear here."}),
    ]))
    it = win.GetItems()
    for id_, key in keys.items():
        for v in choices[key]:
            it[id_].AddItem(label(v))
        it[id_].CurrentText = label(defaults[key])

    def say(text):
        it["Out"].PlainText = text

    def run(ev):
        params = {key: choices[key][int(it[id_].CurrentIndex)] for id_, key in keys.items()}
        it["Run"].Enabled = False
        try:
            say("Removing silences\u2026")
            res = call("/run", dict(feature="silences", timeline=read_timeline(), params=params, host="resolve"))
            report = res.get("report") or {}
            say("\n".join(["\u2713 " + n for n in apply(res)] + [f"{label(k)}: {v}" for k, v in list(report.items())[:4]]))
        except Exception as e:
            say(f"\u26a0 {e}")
        it["Run"].Enabled = True

    def beat(ev=None):
        s = heartbeat()
        it["Live"].Text = ", ".join([s["project"]] + ([s["sequence"]] if s.get("sequence") else [])) if s \
            else "Kerf engine not reachable"

    win.On.Run.Clicked = run
    win.On.KerfWin.Close = lambda ev: disp.ExitLoop()
    try:  # live project / timeline while the Kerf window is open
        timer = ui.Timer({"ID": "KerfBeat", "Interval": 1000})
        disp.On.KerfBeat.Timeout = beat
        timer.Start()
    except Exception:
        timer = None
    beat()
    win.RecalcLayout()
    win.Resize(geom[2:])  # Fusion restores the last size per window ID; start from one that fits
    win.Show()
    disp.RunLoop()
    if timer:
        timer.Stop()
    win.Hide()


main()
