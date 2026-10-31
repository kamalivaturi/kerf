"""Timeline model, record-time edit operations, and FCP7 XML (xmeml v4) export.

All times are seconds. A Clip plays source [src_in, src_out) at record time `start`.
Keyframes are tuples (t, *values) with t relative to the clip's record start.
"""
from __future__ import annotations

import bisect
import copy
import os
from dataclasses import dataclass, field
from urllib.parse import quote
from xml.sax.saxutils import escape

from . import units

# Basic Motion units, measured by importing scripts/calibrate_xml.py output (Premiere 25, Resolve 21):
# Clip.center is a fraction of the sequence frame (±0.5 = edge, +y down) and Clip.scale is % of native source pixels,
# both relative to the clip's own framing in the editor (base_scale %, base_center) so effects build on it.
# Premiere reads `center` as a fraction of the *source* size and scale as % of native pixels.
# Resolve reads `center` as a fraction of the *timeline* size and applies scale on top of its fit-to-frame.
# Keyframe <when> is media-start based (F(src_in) + F(t)) in both.
EPS = 1e-4
STILL = 5.0  # seconds a still image lasts when it is the whole timeline (Premiere's default still duration)


def interp(kf, t):
    """Linear interpolation of keyframes [(t, *vals)] at t. Returns the value tuple."""
    if not kf:
        return None
    if t <= kf[0][0]:
        return kf[0][1:]
    for (t0, *v0), (t1, *v1) in zip(kf, kf[1:]):
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return tuple(a + (b - a) * f for a, b in zip(v0, v1))
    return kf[-1][1:]


def slice_kf(kf, a, b):
    """Record-time keyframes → keyframes relative to a clip spanning [a, b]."""
    if not kf:
        return []
    inner = [(t - a, *v) for t, *v in kf if a + EPS < t < b - EPS]
    pts = [(0.0, *interp(kf, a))] + inner + [(b - a, *interp(kf, b))]
    if all(p[1:] == pts[0][1:] for p in pts):
        return [pts[0]]  # constant: no keyframes
    return pts


@dataclass
class Clip:
    path: str
    src_in: float
    src_out: float
    start: float
    enabled: bool = True
    scale: list = field(default_factory=list)   # [(t, pct)]
    center: list = field(default_factory=list)  # [(t, x, y)]
    rotation: list = field(default_factory=list)  # [(t, degrees)]
    base_scale: float = 100.0      # the clip's Scale in the editor (% of native pixels)
    base_center: tuple = (0.0, 0.0)  # its Position, as an offset from frame centre in frame fractions

    @property
    def dur(self):
        return self.src_out - self.src_in

    @property
    def end(self):
        return self.start + self.dur

    def sub(self, a, b):
        """Piece of this clip covering record time [a, b]."""
        c = copy.copy(self)
        c.src_in = self.src_in + (a - self.start)
        c.src_out = c.src_in + (b - a)
        c.start = a
        c.scale = slice_kf([(self.start + t, *v) for t, *v in self.scale], a, b) if self.scale else []
        c.center = slice_kf([(self.start + t, *v) for t, *v in self.center], a, b) if self.center else []
        c.rotation = slice_kf([(self.start + t, *v) for t, *v in self.rotation], a, b) if self.rotation else []
        return c


@dataclass
class Timeline:
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    name: str = "Kerf"
    video: list = field(default_factory=lambda: [[]])
    audio: list = field(default_factory=lambda: [[]])
    markers: list = field(default_factory=list)      # [(t, name, note)]
    transitions: list = field(default_factory=list)  # record times of audio crossfades
    transition_dur: float = 0.1
    playhead: float = 0.0  # record time of the NLE playhead when read from a host
    editor: str = ""  # the editor the timeline was read from: picks the XML flavour when none is asked for

    @property
    def duration(self):
        return max((c.end for tr in self.video + self.audio for c in tr), default=0.0)

    def tracks(self, kind):
        return self.video if kind == "video" else self.audio

    @classmethod
    def from_dict(cls, d):
        editor, frame = d.get("editor") or "", (int(d.get("width", 1920)), int(d.get("height", 1080)))

        def source_of(path):  # the clip's native size, when the editor didn't report it
            from .media import probe
            info = probe(path)
            return info["width"] or frame[0], info["height"] or frame[1]

        def clip(c):
            bs, bc = units.clip_framing(c, editor, frame, source_of)
            return Clip(c["path"], float(c["src_in"]), float(c["src_out"]), float(c["start"]), bool(c.get("enabled", True)),
                        base_scale=bs, base_center=bc)

        def clips(tracks):
            return [[clip(c) for c in tr] for tr in tracks]
        video = clips(d.get("video") or [[]])
        audio = clips(d["audio"]) if d.get("audio") else copy.deepcopy(video)
        return cls(float(d.get("fps", 30)), int(d.get("width", 1920)), int(d.get("height", 1080)),
                   d.get("name", "Kerf"), video, audio, playhead=float(d.get("playhead") or 0.0), editor=editor)

    def to_dict(self):
        clip = lambda c: dict(path=c.path, src_in=c.src_in, src_out=c.src_out, start=c.start, enabled=c.enabled,
                              base_scale=c.base_scale, base_center=list(c.base_center))
        return dict(fps=self.fps, width=self.width, height=self.height, name=self.name, editor=self.editor,
                    video=[[clip(c) for c in tr] for tr in self.video], audio=[[clip(c) for c in tr] for tr in self.audio])

    @classmethod
    def from_media(cls, path, probe):
        info = probe(path)
        still = not info["fps"] and info["width"]  # an image: give it an editor's default still length
        c = Clip(path, 0.0, info["duration"] or (STILL if still else 0.0), 0.0)
        return cls(info["fps"] or 30.0, info["width"] or 1920, info["height"] or 1080,
                   os.path.splitext(os.path.basename(path))[0], [[c] if info["width"] else []],  # audio-only: no picture
                   [[copy.copy(c)]])


# ---------------------------------------------------------------- edit operations

def merge(ranges, gap=0.0):
    out = []
    for a, b in sorted(ranges):
        if b - a <= EPS:
            continue
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(r) for r in out]


def invert(ranges, total):
    out, t = [], 0.0
    for a, b in merge(ranges):
        if a > t:
            out.append((t, a))
        t = max(t, b)
    if t < total:
        out.append((t, total))
    return out


def keep(tl, ranges, ripple=True, kinds=("video", "audio")):
    """Keep only record-time `ranges` on the given track kinds. Ripple closes the gaps."""
    ranges = merge(ranges)
    starts = [a for a, _ in ranges]
    offs, acc = [], 0.0
    for a, b in ranges:
        offs.append(acc)
        acc += b - a

    def remap(t):
        i = bisect.bisect_right(starts, t + EPS) - 1
        if i < 0:
            return 0.0
        a, b = ranges[i]
        return offs[i] + min(t, b) - a

    out = copy.deepcopy(tl)
    for kind in kinds:
        for tr in out.tracks(kind):
            new = []
            for c in tr:
                for a, b in ranges:
                    s, e = max(a, c.start), min(b, c.end)
                    if e - s > EPS:
                        p = c.sub(s, e)
                        if ripple:
                            p.start = remap(s)
                        new.append(p)
            tr[:] = new
    if ripple:
        inside = lambda t: any(a - EPS <= t <= b + EPS for a, b in ranges)
        out.markers = [(remap(t), n, note) for t, n, note in out.markers if inside(t)]
        out.transitions = [remap(t) for t in out.transitions if inside(t)]
    return out


def split(tl, times, kinds=("video", "audio"), tracks=None):
    """Cut clips at record `times` without removing anything. `tracks` limits indices per kind."""
    times = sorted(set(times))
    out = copy.deepcopy(tl)
    for kind in kinds:
        for ti, tr in enumerate(out.tracks(kind)):
            if tracks is not None and ti not in tracks:
                continue
            new = []
            for c in tr:
                pts = [c.start] + [t for t in times if c.start + EPS < t < c.end - EPS] + [c.end]
                new += [c.sub(a, b) for a, b in zip(pts, pts[1:])]
            tr[:] = new
    return out


def set_keyframes(tl, tracks, scale=None, center=None, rotation=None):
    """Apply record-time keyframes [(t, *v)] to every clip on video `tracks`."""
    for ti in tracks:
        for c in tl.video[ti]:
            if rotation is not None:
                c.rotation = slice_kf(rotation, c.start, c.end)
            if scale is not None:
                c.scale = slice_kf(scale, c.start, c.end)
            if center is not None:
                c.center = slice_kf(center, c.start, c.end)


def parse_tracks(s):
    """'1, 3' (1-based, as editors show them) → [0, 2]."""
    return [int(x) - 1 for x in str(s).replace(";", ",").split(",") if x.strip()]


def fmt_time(t):
    t = int(round(t))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def add_track(tl, kind, clips):
    tl.tracks(kind).append(sorted(clips, key=lambda c: c.start))
    return len(tl.tracks(kind)) - 1


# ---------------------------------------------------------------- FCP7 XML export

def _rate(fps):
    tb = int(round(fps))
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if abs(fps - tb) > 0.01 else 'FALSE'}</ntsc></rate>"


def _pathurl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "file://localhost/" + quote(p.lstrip("/"), safe="/:")


def to_xmeml(tl, probe, host="premiere"):
    F = lambda s: int(round(s * tl.fps))
    rate = _rate(tl.fps)
    files, n = {}, [0]

    def file_el(path):
        if path in files:
            return f'<file id="{files[path]}"/>'
        fid = files[path] = f"file-{len(files) + 1}"
        info = probe(path)
        dur = F(info["duration"]) if info["duration"] else F(3600)
        media = ""
        if info["width"]:
            media += (f"<video><samplecharacteristics>{_rate(info['fps'] or tl.fps)}<width>{info['width']}</width>"
                      f"<height>{info['height']}</height></samplecharacteristics></video>")
        if info["channels"]:
            media += (f"<audio><samplecharacteristics><depth>16</depth><samplerate>{info['sample_rate']}</samplerate>"
                      f"</samplecharacteristics><channelcount>{info['channels']}</channelcount></audio>")
        return (f'<file id="{fid}"><name>{escape(os.path.basename(path))}</name><pathurl>{escape(_pathurl(path))}</pathurl>'
                f"{rate}<duration>{dur}</duration><media>{media}</media></file>")

    def motion(c):
        framed = c.base_scale != 100.0 or any(c.base_center)
        if not c.scale and not c.center and not c.rotation and not framed:
            return ""
        bs, (bx, by) = c.base_scale / 100, c.base_center
        base = F(c.src_in)
        info = probe(c.path)
        sw, sh = info["width"] or tl.width, info["height"] or tl.height
        fit, kx, ky = units.xml_motion(host, (tl.width, tl.height), (sw, sh))

        def param(pid, name, kf, fmt):
            if not kf:
                return ""
            body = f"<value>{fmt(kf[0][1:])}</value>"
            if len(kf) > 1:
                body += "".join(f"<keyframe><when>{base + F(t)}</when><value>{fmt(v)}</value></keyframe>" for t, *v in kf)
            return f"<parameter><parameterid>{pid}</parameterid><name>{name}</name>{body}</parameter>"

        sc = param("scale", "Scale", c.scale or [(0.0, 100.0)] * framed, lambda v: f"{v[0] * bs / fit:.3f}")
        ce = param("center", "Center", c.center or [(0.0, 0.0, 0.0)] * framed,
                   lambda v: f"<horiz>{(v[0] + bx) * kx:.5f}</horiz><vert>{(v[1] + by) * ky:.5f}</vert>")
        ro = param("rotation", "Rotation", c.rotation, lambda v: f"{v[0]:.3f}")
        return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>"
                f"<effecttype>motion</effecttype><mediatype>video</mediatype>{sc}{ro}{ce}</effect></filter>")

    def clipitem(c, kind, ch=1):
        fs, fe, fi = F(c.start), F(c.end), F(c.src_in)
        if fe <= fs:
            return ""
        n[0] += 1
        info = probe(c.path)
        extra = motion(c) if kind == "video" else (
            f"<sourcetrack><mediatype>audio</mediatype><trackindex>{ch}</trackindex></sourcetrack>")
        return (f'<clipitem id="clipitem-{n[0]}"><name>{escape(os.path.basename(c.path))}</name>'
                f"<enabled>{'TRUE' if c.enabled else 'FALSE'}</enabled>"
                f"<duration>{F(info['duration']) if info['duration'] else F(3600)}</duration>{rate}"
                f"<start>{fs}</start><end>{fe}</end><in>{fi}</in><out>{fi + fe - fs}</out>"
                f"{file_el(c.path)}{extra}</clipitem>")

    def transitions(tr):
        d = tl.transition_dur
        cuts = [t for t in tl.transitions if any(abs(c.start - t) < 1e-3 for c in tr)]
        return "".join(
            f"<transitionitem><start>{F(t - d / 2)}</start><end>{F(t + d / 2)}</end><alignment>center</alignment>"
            f"{rate}<effect><name>Cross Fade (+3dB)</name><effectid>KGAudioTransCrossFade3dB</effectid>"
            "<effectcategory>audio</effectcategory><effecttype>transition</effecttype><mediatype>audio</mediatype>"
            "</effect></transitionitem>" for t in cuts)

    video = "".join("<track>" + "".join(clipitem(c, "video") for c in tr) + "</track>" for tr in tl.video)
    audio = ""
    for tr in tl.audio:
        chans = min(2, max((probe(c.path)["channels"] or 1 for c in tr), default=1))
        for ch in range(1, chans + 1):
            audio += "<track>" + "".join(clipitem(c, "audio", ch) for c in tr) + transitions(tr) + "</track>"
    markers = "".join(f"<marker><name>{escape(name)}</name><comment>{escape(note or '')}</comment>"
                      f"<in>{F(t)}</in><out>-1</out></marker>" for t, name, note in tl.markers)
    fmt = (f"<format><samplecharacteristics>{rate}<width>{tl.width}</width><height>{tl.height}</height>"
           "<anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>"
           "<fielddominance>none</fielddominance></samplecharacteristics></format>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="sequence-1"><name>{escape(tl.name)}</name><duration>{F(tl.duration)}</duration>{rate}'
            f"<media><video>{fmt}{video}</video><audio><numOutputChannels>2</numOutputChannels>"
            "<format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>"
            f"{audio}</audio></media>"
            f"<timecode>{rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>"
            f"{markers}</sequence></xmeml>\n")
