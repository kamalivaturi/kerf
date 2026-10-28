"""resolve/Kerf.py against a stand-in Resolve API: read a timeline, run a real feature, apply every step type.

Resolve can't run in CI, so the fakes below answer the calls the script makes the way Resolve 18/19 does."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kerf import features  # noqa: E402
from kerf.timeline import Timeline  # noqa: E402


class Item:  # a timeline clip
    def __init__(self, path, start, dur, left=0, zoom=1.0, pan=0.0, tilt=0.0):
        self.path, self.start, self.dur, self.left = path, start, dur, left
        self.props = {"ZoomX": zoom, "Pan": pan, "Tilt": tilt}

    def GetMediaPoolItem(self):
        return PoolItem(self.path)

    def GetLeftOffset(self): return self.left
    def GetStart(self): return 86400 + self.start
    def GetDuration(self): return self.dur
    def GetClipEnabled(self): return True
    def GetProperty(self, k): return self.props[k]


class PoolItem:
    def __init__(self, path, kind="Video"):
        self.path, self.kind = path, kind

    def GetClipProperty(self, k):
        return {"File Path": self.path, "Resolution": "3840x2160", "Type": self.kind}[k]


class Tl:
    def __init__(self, name, items=()):
        self.name, self.items, self.markers, self.tracks = name, list(items), [], 1

    def GetName(self): return self.name
    def GetSetting(self, k): return {"timelineFrameRate": "30", "timelineResolutionWidth": "1920", "timelineResolutionHeight": "1080"}[k]
    def GetStartFrame(self): return 86400
    def GetTrackCount(self, kind): return self.tracks if kind == "video" else 1
    def GetItemListInTrack(self, kind, i): return self.items if (kind, i) == ("video", 1) else []
    def GetCurrentTimecode(self): return "01:00:02:00"
    def GetStartTimecode(self): return "01:00:00:00"
    def AddMarker(self, frame, color, name, note, dur): self.markers.append((frame, color, name)); return True
    def AddTrack(self, kind): self.tracks += 1; return True


class Folder:
    def __init__(self, name, clips=()):
        self.name, self.clips, self.subs = name, list(clips), []

    def GetName(self): return self.name
    def GetClipList(self): return self.clips
    def GetSubFolderList(self): return self.subs


class Pool:
    def __init__(self, proj):
        self.proj, self.root, self.imported, self.appended = proj, Folder("Master"), [], []

    def GetRootFolder(self): return self.root
    def ImportMedia(self, paths): self.imported += paths; return [PoolItem(p) for p in paths]
    def AppendToTimeline(self, clips): self.appended += clips; return True
    def AddSubFolder(self, root, name): f = Folder(name); root.subs.append(f); return f
    def MoveClips(self, clips, folder): folder.clips += clips; return True
    def SetCurrentFolder(self, folder): return True

    def ImportTimelineFromFile(self, xml, opts):
        tl = Tl(opts["timelineName"])
        self.proj.timelines.append(tl)
        return tl


class Project:
    def __init__(self, tl):
        self.timelines, self.current = [tl], tl
        self.pool = Pool(self)

    def GetName(self): return "Test project"
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, tl): self.current = tl; return True
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, i): return self.timelines[i - 1]


class Resolve:
    def __init__(self, proj): self.proj = proj
    def GetProjectManager(self): return self
    def GetCurrentProject(self): return self.proj


def load(proj, home):
    """resolve/Kerf.py as a module, without opening its window (the last line calls main())."""
    os.environ["KERF_HOME_DIR"] = str(home)
    src = (ROOT / "resolve" / "Kerf.py").read_text(encoding="utf-8")
    assert src.rstrip().endswith("main()")
    ns = {"__name__": "kerf_resolve", "resolve": Resolve(proj), "fusion": None, "bmd": None}
    exec(compile(src.rstrip()[: -len("main()")], "resolve/Kerf.py", "exec"), ns)
    return ns


def test_resolve_script_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("KERF_HOME_DIR", str(tmp_path))
    video = tmp_path / "talk.mp4"  # tone 2 s, silence 1 s: silences finds cuts
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10", "-f", "lavfi",
                    "-i", "aevalsrc='0.3*sin(2*PI*220*t)*lt(mod(t,3),2)':s=48000:d=10", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    tl = Tl("Edit", [Item(str(video), start=0, dur=300, zoom=1.2, pan=192.0, tilt=108.0)])
    proj = Project(tl)
    k = load(proj, tmp_path)

    # the locator decides the port; defaults before the engine's first start
    assert k["engine"]() == "http://127.0.0.1:7878"
    (tmp_path / "engine.json").write_text(json.dumps(dict(port=7999, token_file=str(tmp_path / "token"), helper="")))
    assert k["engine"]() == "http://127.0.0.1:7999"

    # read: raw framing plus the editor's id; the engine converts it (kerf/units.py)
    d = k["read_timeline"]()
    assert d["editor"] == "resolve" and d["playhead"] == 2.0
    assert d["video"][0][0]["framing"] == dict(zoom=1.2, pan=192.0, tilt=108.0, source=[3840, 2160])
    c = Timeline.from_dict(d).video[0][0]
    assert abs(c.base_scale - 60.0) < 1e-6 and c.base_center == (0.1, -0.1)

    # a real feature on that timeline: the step list creates a new timeline in Resolve
    res = features.run("silences", d, out_dir=str(tmp_path / "out"))
    assert [s["op"] for s in res["steps"]] == ["timeline"]
    notes = k["apply"](res)
    assert proj.current is not tl and any("Created timeline" in n for n in notes), notes

    # every other step type, through the same apply()
    proj.current = tl
    steps = dict(steps=[
        dict(op="import", files=["a.mp4"], what="media"),
        dict(op="import", files=["c.srt"], what="captions"),
        dict(op="insert", path="solid.mov", at=1.0, duration=2.0),
        dict(op="markers", markers=[dict(t=1.0, name="Intro")], kind="chapter"),
        dict(op="timeline", xml=res["xml"][0], name="Edit"),  # a taken name gets a number
        dict(op="mogrt", path="m.mogrt", param="Text", pages=[]),
    ])
    notes = k["apply"](steps)
    assert proj.pool.imported[:2] == ["a.mp4", "c.srt"] and proj.pool.appended[0]["recordFrame"] == 86400 + 30
    assert tl.markers == [(30, "Blue", "Intro")]
    assert any("Edit 2" in n for n in notes) and any("Premiere-only" in n for n in notes), notes
    proj.pool.root.clips = [PoolItem("x.mp4"), PoolItem("y.wav")]
    assert k["apply"](dict(steps=[dict(op="sort", plan=dict(bins={"Video": [".mp4"]}, sequences="Timelines", other="Other"))]))
