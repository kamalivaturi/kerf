"""Editor toolkit: speed ramp, camera shake, stabilize, layout (anchor/align/distribute), add layer, frame export,
beat markers, quick mask (offline AI cutout), project sorter, FX presets.

Everything that changes pixels is rendered by FFmpeg into a new clip that replaces the original on the timeline
(source media is never touched). Motion-only tools (layout, shake keyframes) stay editable as Basic Motion keyframes.
"""
from __future__ import annotations

import copy
import json
import math
import random
import re
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from . import media, render
from .timeline import EPS, Clip, add_track, invert, keep, parse_tracks, set_keyframes

# ---------------------------------------------------------------- curves (speed graph / value graph)

CURVES = {"linear": (0, 0, 1, 1), "ease_in": (.42, 0, 1, 1), "ease_out": (0, 0, .58, 1), "ease_in_out": (.42, 0, .58, 1),
          "snappy": (.2, .9, .1, 1), "slow_start": (.7, 0, .84, 0)}


def curve_fn(spec):
    """'ease_in' | 'x1,y1,x2,y2' (CSS cubic-bezier) → f: [0,1] → [0,1]."""
    x1, y1, x2, y2 = CURVES.get(str(spec).strip()) or [float(v) for v in str(spec).split(",")]
    bx = lambda t: 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3
    by = lambda t: 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3

    def f(x):
        lo, hi = 0.0, 1.0
        for _ in range(40):  # x(t) is monotonic for x1, x2 in [0, 1]: bisection is exact enough
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if bx(mid) < x else (lo, mid)
        return by((lo + hi) / 2)
    return f


def _clips(tl, p, track):
    """Clips the tool works on: 'playhead' (clip under the playhead), 'all', or 1-based numbers '1,3'."""
    tr = [c for c in tl.video[track] if c.enabled] if track < len(tl.video) else []
    sel = str(p.get("clips", "all")).strip().lower()
    if sel == "playhead":
        hit = [c for c in tr if c.start - EPS <= tl.playhead < c.end]
        return hit or tr[:1]
    if sel in ("", "all"):
        return tr
    idx = {int(x) - 1 for x in sel.split(",") if x.strip().isdigit()}
    return [c for i, c in enumerate(tr) if i in idx]


def _encode(out, alpha=False, tl=None):
    if alpha:
        return ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(out)]
    enc = render.candidates("h264", False)[0]
    if tl is None:
        return [*render.video_args(enc, "high", 1920, 1080, 30), str(out)]
    return [*render.video_args(enc, "high", tl.width, tl.height, tl.fps), "-r", f"{tl.fps:.3f}", str(out)]


def _bake(c, vf, out, tl, cwd=None):
    """Render the clip's source range through `vf` at the timeline's frame rate (video only; audio stays put)."""
    media.ffmpeg("-ss", f"{c.src_in:.3f}", "-t", f"{c.dur:.3f}", "-i", c.path, "-vf", vf, "-an", *_encode(out, tl=tl), cwd=cwd)
    return Clip(str(out), 0.0, media.probe(str(out))["duration"] or c.dur, c.start)


def _out(ctx, c, tag, ext="mp4"):
    return ctx.out_dir / f"{Path(c.path).stem} {tag} {c.start:.2f}.{ext}"


def _replace(tl, track, old, new):
    tr = tl.video[track]
    tr[tr.index(old)] = new


def _shift_after(tl, t, d):
    for tr in tl.video + tl.audio:
        for c in tr:
            if c.start >= t - EPS:
                c.start += d


# ---------------------------------------------------------------- speed ramp

RAMP_DEFAULTS = dict(preset="speedramp", curve="0.42,0,0.58,1", min_speed=30, max_speed=300, track="1", clips="playhead",
                     frame_blend=False, keep_audio=False)
RAMP_CHOICES = dict(preset=["speedramp", "ease_in", "ease_out", "ease_in_out", "linear", "custom"])
RAMP_HELP = ("Speed graph for clips: speedramp = fast→slow→fast, ease_in = accelerate, ease_out = decelerate, "
             "ease_in_out = slow→fast→slow, custom = your bezier `curve` (x1,y1,x2,y2) from min to max speed. Speeds in %. "
             "clips: playhead | all | 1,3. The ramped shot replaces the original and the edit ripples. Audio under "
             "ramped shots is removed unless keep_audio.")


def speed_profile(preset, curve, lo, hi):
    """u (source progress 0-1) → speed %."""
    c = curve_fn(curve if preset == "custom" else "ease_in_out" if preset in ("speedramp", "ease_in_out") else
                 preset if preset in CURVES else "linear")
    bump = lambda u: c(2 * u) if u < .5 else c(2 - 2 * u)
    return {"speedramp": lambda u: hi - (hi - lo) * bump(u), "ease_in_out": lambda u: lo + (hi - lo) * bump(u),
            "ease_out": lambda u: hi - (hi - lo) * c(u)}.get(preset, lambda u: lo + (hi - lo) * c(u))


def ramp_expr(dur, speed, n=32):
    """setpts expression mapping input time T → output time for a piecewise-constant speed, and the output length."""
    b = [dur * k / n for k in range(n + 1)]
    s = [max(1.0, speed((k + .5) / n)) / 100 for k in range(n)]
    o = [0.0]
    for k in range(n):
        o.append(o[-1] + (b[k + 1] - b[k]) / s[k])
    e = f"{o[n - 1]:.5f}+(T-{b[n - 1]:.5f})/{s[n - 1]:.5f}"
    for k in range(n - 2, -1, -1):
        e = f"if(lt(T,{b[k + 1]:.5f}),{o[k]:.5f}+(T-{b[k]:.5f})/{s[k]:.5f},{e})"
    return e, o[n]


def speed_ramp(tl, p, ctx):
    track = parse_tracks(p["track"])[0]
    out = copy.deepcopy(tl)
    targets = _clips(out, p, track)
    speed = speed_profile(p["preset"], p["curve"], float(p["min_speed"]), float(p["max_speed"]))
    if not p["keep_audio"]:
        out = keep(out, invert([(c.start, c.end) for c in targets], out.duration), ripple=False, kinds=("audio",))
        targets = _clips(out, p, track)
    done = []
    for c in sorted(targets, key=lambda c: -c.start):  # last first, so ripple shifts never move a pending clip
        expr, _ = ramp_expr(c.dur, speed)
        smooth = f",minterpolate=fps={tl.fps:.3f}:mi_mode=blend" if p["frame_blend"] else ""
        vf = f"setpts=PTS-STARTPTS,setpts='({expr})/TB',fps={tl.fps:.3f}{smooth}"
        new = _bake(c, vf, _out(ctx, c, "ramp"), tl)
        end = c.end
        _replace(out, track, c, new)
        _shift_after(out, end, new.dur - c.dur)
        done.append(dict(clip=Path(c.path).name, before=round(c.dur, 2), after=round(new.dur, 2)))
    out.name = f"{tl.name} - Speed ramp"
    return dict(timeline=out, report=dict(ramped=done))


# ---------------------------------------------------------------- camera shake

SHAKE_DEFAULTS = dict(axis="hv", on="cuts", times="", music="", every=1, track="1", output="keyframes", amplitude=28.0,
                      rotation=1.5, frequency=11.0, duration=0.45, decay=0.7, zoom=108, flash=0, chromatic=0, seed=7)
SHAKE_CHOICES = dict(axis=["vertical", "horizontal", "hv", "scale", "all", "custom"], on=["cuts", "beats", "times", "playhead", "whole"], output=["keyframes", "render"])
SHAKE_HELP = ("axis: vertical, horizontal, hv (both), scale (zoom pulse), all (position + rotation + scale), "
              "custom (your amplitude/rotation mix). Camera shake on cuts, music beats (`music` file, every N), given `times` (s, comma list), at the "
              "playhead, or the whole clip. amplitude px (at 1080p; scaled to your frame size), rotation °, frequency Hz, duration s, decay 0-1, zoom % "
              "overscan. output=keyframes keeps it editable (Basic Motion); output=render bakes it with flash "
              "(0-100) and chromatic shift (px).")


def shake_events(tl, p, track):
    on, d = p["on"], float(p["duration"])
    if on == "whole":
        return [(0.0, tl.duration)]
    if on == "cuts":
        ts = sorted({c.start for c in tl.video[track] if c.start > EPS})
    elif on == "beats":
        from .sound import beats
        if not p["music"]:
            raise ValueError("on=beats needs `music` (the song file)")
        ts = beats(p["music"])[0][::max(1, int(p["every"]))]
    elif on == "playhead":
        ts = [tl.playhead]
    else:
        ts = sorted(float(x) for x in str(p["times"]).replace(";", ",").split(",") if x.strip())
    return [(t, min(t + d, tl.duration)) for t in ts if t < tl.duration]


def shake_offsets(t, a, b, p, ph):
    """(dx px, dy px, rotation °) at record time t for an event [a, b]; long spans shake at full strength."""
    if not a <= t <= b:
        return 0.0, 0.0, 0.0
    env = 1.0 if b - a > 5 else (1 - (t - a) / (b - a)) ** (1 + 3 * float(p["decay"]))
    f, A, R = float(p["frequency"]), float(p["amplitude"]), float(p["rotation"])
    w = 2 * math.pi * f * t
    n = lambda k: (math.sin(w + ph[k]) + .5 * math.sin(1.7 * w + ph[k + 3])) / 1.5
    ax = p.get("axis", "custom")
    mx, my = (0, 1) if ax == "vertical" else (1, 0) if ax == "horizontal" else (0, 0) if ax == "scale" else (1, 1)
    mr = 1 if ax in ("all", "custom") else 0
    return A * env * n(0) * mx, A * env * n(1) * my, R * env * n(2) * mr


def shake_scale(t, a, b, p, ph, z):
    """Scale % at t: overscan, plus a zoom pulse for the scale/all axes."""
    if p.get("axis") not in ("scale", "all") or not a <= t <= b:
        return z
    env = 1.0 if b - a > 5 else (1 - (t - a) / (b - a)) ** (1 + 3 * float(p["decay"]))
    return z + float(p["amplitude"]) / 4 * env * math.sin(2 * math.pi * float(p["frequency"]) * t + ph[5])


def camera_shake(tl, p, ctx):
    track = parse_tracks(p["track"])[0]
    evs = shake_events(tl, p, track)
    rnd = random.Random(int(p["seed"]))
    phases = [[rnd.uniform(0, 6.28) for _ in range(8)] for _ in evs]
    out = copy.deepcopy(tl)
    W, H, z = tl.width, tl.height, float(p["zoom"])
    k = min(W, H) / 1080  # amplitude / chromatic are px at 1080p: the same look at 720p, 4K or 9:16
    if p["output"] == "keyframes":
        step = max(1 / tl.fps, 1 / (2 * float(p["frequency"])))
        f1 = 1 / tl.fps
        sk, ck, rk = [(0.0, 100.0)], [(0.0, 0.0, 0.0)], [(0.0, 0.0)]
        for (a, b), ph in zip(evs, phases):
            pre = max(0.0, a - f1)
            sk += [(pre, 100.0), (a, z), (b, z), (b + f1, 100.0)]
            ck.append((pre, 0.0, 0.0))
            rk.append((pre, 0.0))
            for t in np.arange(a, b + step / 2, step):
                dx, dy, r = shake_offsets(float(t), a, b, p, ph)
                sk.append((float(t), shake_scale(float(t), a, b, p, ph, z)))
                ck.append((float(t), dx * k / W, dy * k / H))
                rk.append((float(t), r))
            ck.append((b + f1, 0.0, 0.0))
            rk.append((b + f1, 0.0))
        srt = lambda k: sorted({x[0]: x for x in k}.values())
        set_keyframes(out, [track], scale=srt(sk), center=srt(ck), rotation=srt(rk))
    else:
        for c in list(out.video[track]):
            local = [(a - c.start, b - c.start, ph) for (a, b), ph in zip(evs, phases) if b > c.start and a < c.end]
            if not local or not c.enabled:
                continue
            f = float(p["frequency"])
            info = media.probe(c.path)
            ks = min(info["width"] or W, info["height"] or H) / 1080  # source pixels
            ax = p.get("axis", "custom")
            mx = 0 if ax in ("vertical", "scale") else 1
            my = 0 if ax in ("horizontal", "scale") else 1
            mr = 1 if ax in ("all", "custom") else 0
            env = "+".join(f"between(t,{a:.3f},{b:.3f})*pow(max(0,1-(t-{a:.3f})/{max(b - a, .01):.3f}),{1 + 3 * float(p['decay']):.2f})"
                           if b - a <= 5 else f"between(t,{a:.3f},{b:.3f})" for a, b, _ in local)
            ph = local[0][2]
            wob = lambda k, amp: f"{amp}*({env})*(sin(2*PI*{f}*t+{ph[k]:.2f})+0.5*sin(2*PI*{f * 1.7:.2f}*t+{ph[k + 3]:.2f}))/1.5"
            vf = (f"scale=trunc(iw*{z / 100:.3f}/2)*2:trunc(ih*{z / 100:.3f}/2)*2,"
                  f"rotate='({wob(2, float(p['rotation']) * mr)})*PI/180',"
                  f"crop=trunc(in_w*{100 / z:.4f}/2)*2:trunc(in_h*{100 / z:.4f}/2)*2:"
                  f"'(in_w-out_w)/2+{wob(0, float(p['amplitude']) * ks * mx)}':'(in_h-out_h)/2+{wob(1, float(p['amplitude']) * ks * my)}'")
            if ax in ("scale", "all"):  # zoom pulse via zoompan (per-frame zoom at a fixed output size)
                pulse = re.sub(r"\bt\b", "it", wob(4, float(p["amplitude"]) / 400))
                vf += (f",zoompan=z='1+abs({pulse})':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:"
                       f"s={info['width'] // 2 * 2}x{info['height'] // 2 * 2}:fps={info['fps'] or tl.fps:.3f}")
            if float(p["flash"]) > 0:
                fl = "+".join(f"between(t,{a:.3f},{a + .12:.3f})*(1-(t-{a:.3f})/0.12)" for a, _, _ in local)
                vf += f",eq=brightness='{float(p['flash']) / 100:.2f}*({fl})':eval=frame"
            if float(p["chromatic"]) > 0:
                cpx = max(1, round(float(p["chromatic"]) * ks))
                vf += f",rgbashift=rh={cpx}:bh={-cpx}:enable='gt({env},0.05)'"
            _replace(out, track, c, _bake(c, vf, _out(ctx, c, "shake"), tl))
    out.name = f"{tl.name} - Shake"
    return dict(timeline=out, report=dict(shakes=len(evs), output=p["output"]))


# ---------------------------------------------------------------- stabilize

STAB_DEFAULTS = dict(track="1", clips="playhead", method="auto", smoothing=15, shakiness=5, zoom=0, crop_black=True)
STAB_CHOICES = dict(method=["auto", "vidstab", "deshake"])
STAB_HELP = ("One-click stabilizer: renders a stabilized copy of each clip (vidstab two-pass when FFmpeg has it, "
             "else deshake) and swaps it into the edit. smoothing = frames to average (higher = calmer), zoom % "
             "extra (0 = automatic, to hide moving borders).")


def stabilize(tl, p, ctx):
    track = parse_tracks(p["track"])[0]
    out = copy.deepcopy(tl)
    has_vs = " vidstabdetect " in subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    method = ("vidstab" if has_vs else "deshake") if p["method"] == "auto" else p["method"]
    n = 0
    for c in _clips(out, p, track):
        dest = _out(ctx, c, "stab")
        if method == "vidstab":  # relative names + cwd: Windows drive colons break filter arguments
            trf = dest.with_suffix(".trf").name
            media.ffmpeg("-ss", f"{c.src_in:.3f}", "-t", f"{c.dur:.3f}", "-i", c.path, "-vf",
                         f"vidstabdetect=shakiness={int(p['shakiness'])}:accuracy=15:result={trf}", "-f", "null", "-",
                         cwd=ctx.out_dir)
            zoom = f"optzoom=0:zoom={float(p['zoom'])}" if float(p["zoom"]) else "optzoom=1"
            vf = (f"vidstabtransform=input={trf}:smoothing={int(p['smoothing'])}:{zoom}:"
                  f"crop={'black' if p['crop_black'] else 'keep'},unsharp=5:5:0.6:3:3:0.3")
            new = _bake(c, vf, dest, tl, cwd=ctx.out_dir)
        else:
            new = _bake(c, f"deshake=rx=64:ry=64:edge={'blank' if p['crop_black'] else 'mirror'}", dest, tl)
        _replace(out, track, c, new)
        n += 1
    out.name = f"{tl.name} - Stabilized"
    return dict(timeline=out, report=dict(stabilized=n, method=method))


# ---------------------------------------------------------------- layout: anchor / align / distribute

POSITIONS = ["top_left", "top_center", "top_right", "middle_left", "center", "middle_right",
             "bottom_left", "bottom_center", "bottom_right"]
LAYOUT_DEFAULTS = dict(arrange="bottom_right", tracks="2", scale=35.0, margin=4.0)
LAYOUT_CHOICES = dict(arrange=[*POSITIONS, "align_left", "align_right", "align_top", "align_bottom",
                               "distribute_horizontal", "distribute_vertical", "grid"])
LAYOUT_HELP = ("Places clips on `tracks` (e.g. picture-in-picture on V2): one of 9 anchor positions, align to a frame "
               "edge, or distribute / grid the clips that play at the same time. scale % (0 = fit), margin % of frame. "
               "Written as editable Motion values.")


def _pos(name, w, h, W, H, m):
    col = 0 if name.endswith("left") else 2 if name.endswith("right") else 1
    row = 0 if name.startswith("top") else 2 if name.startswith("bottom") else 1
    x = [m + w / 2, W / 2, W - m - w / 2][col]
    y = [m + h / 2, H / 2, H - m - h / 2][row]
    return (x - W / 2) / W, (y - H / 2) / H


def layout(tl, p, ctx):
    out = copy.deepcopy(tl)
    W, H = tl.width, tl.height
    m = float(p["margin"]) / 100 * min(W, H)
    tracks = [t for t in parse_tracks(p["tracks"]) if t < len(out.video)]
    arr, n_set = p["arrange"], 0
    items = sorted(((ti, c) for ti in tracks for c in out.video[ti] if c.enabled), key=lambda x: (x[1].start, x[0]))
    for ti, c in items:
        info = media.probe(c.path)
        iw, ih = info["width"] or W, info["height"] or H
        group = [g for _, g in items if g.start < c.end - EPS and c.start < g.end - EPS]
        k, n = group.index(c), len(group)
        if arr in ("distribute_horizontal", "distribute_vertical", "grid"):
            cols = n if arr == "distribute_horizontal" else 1 if arr == "distribute_vertical" else math.ceil(math.sqrt(n))
            rows = math.ceil(n / cols)
            cw, ch = (W - m * (cols + 1)) / cols, (H - m * (rows + 1)) / rows
            s = float(p["scale"]) or 100 * min(cw / iw, ch / ih)
            x = m + (k % cols) * (cw + m) + cw / 2
            y = m + (k // cols) * (ch + m) + ch / 2
            cx, cy = (x - W / 2) / W, (y - H / 2) / H
        else:
            s = float(p["scale"]) or 100 * min(W / iw, H / ih)
            name = {"align_left": "middle_left", "align_right": "middle_right", "align_top": "top_center",
                    "align_bottom": "bottom_center"}.get(arr, arr)
            cx, cy = _pos(name, iw * s / 100, ih * s / 100, W, H, m)
        c.scale, c.center = [(0.0, round(s, 3))], [(0.0, cx, cy)]
        n_set += 1
    out.name = f"{tl.name} - Layout"
    return dict(timeline=out, report=dict(clips=n_set, arrange=arr))


# ---------------------------------------------------------------- add layer (solid / transparent / gradient …)

LAYER_DEFAULTS = dict(kind="solid", color="#000000", color2="#FFFFFF", opacity=100, duration=5.0, aspect=2.39)
LAYER_CHOICES = dict(kind=["solid", "transparent", "gradient", "vignette", "letterbox", "grid_guides"])
LAYER_HELP = ("Adds a generated layer at the playhead on a new top track: solid color, transparent (null-style "
              "placeholder), gradient (color → color2), vignette, letterbox bars for `aspect` (e.g. 2.39) or "
              "rule-of-thirds guides. duration 0 = to the end of the sequence.")


def _bgr(h):
    h = str(h).lstrip("#")
    return [int(h[i:i + 2], 16) for i in (4, 2, 0)]


def make_layer(kind, W, H, color, color2, opacity, aspect):
    import cv2
    img = np.zeros((H, W, 4), np.uint8)
    a = int(255 * float(opacity) / 100)
    if kind == "solid":
        img[..., :3], img[..., 3] = _bgr(color), a
    elif kind == "gradient":
        t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        img[..., :3] = (np.array(_bgr(color)) * (1 - t) + np.array(_bgr(color2)) * t).astype(np.uint8)
        img[..., 3] = a
    elif kind == "vignette":
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        img[..., :3] = _bgr(color)
        img[..., 3] = (np.clip((r - .35) / .65, 0, 1) ** 1.6 * a).astype(np.uint8)
    elif kind == "letterbox":
        bar = max(0, int((H - W / float(aspect)) / 2))
        if bar:
            img[:bar, :, :3] = img[H - bar:, :, :3] = _bgr(color)
            img[:bar, :, 3] = img[H - bar:, :, 3] = 255
    elif kind == "grid_guides":
        for k in (1, 2):
            cv2.line(img, (W * k // 3, 0), (W * k // 3, H), (*_bgr(color2), 255), max(1, W // 640))
            cv2.line(img, (0, H * k // 3), (W, H * k // 3), (*_bgr(color2), 255), max(1, W // 640))
    return img


def add_layer(tl, p, ctx):
    import cv2
    img = make_layer(p["kind"], tl.width, tl.height, p["color"], p["color2"], p["opacity"], p["aspect"])
    f = ctx.out_dir / f"Kerf {p['kind']} {tl.width}x{tl.height} {str(p['color']).lstrip('#')}.png"
    cv2.imwrite(str(f), img)
    d = float(p["duration"]) or max(1.0, tl.duration - tl.playhead)
    out = copy.deepcopy(tl)
    add_track(out, "video", [Clip(str(f), 0.0, d, tl.playhead)])
    out.name = f"{tl.name} - {p['kind'].title()}"
    return dict(timeline=out, files=[str(f)], insert=dict(path=str(f), at=tl.playhead, duration=d),
                report=dict(layer=p["kind"], at=round(tl.playhead, 2), duration=round(d, 2)))


# ---------------------------------------------------------------- frame export

FRAME_DEFAULTS = dict(time="playhead", format="png", folder="", scale=100)
FRAME_CHOICES = dict(format=["png", "jpg"])
FRAME_HELP = "Saves the frame at the playhead (or `time` in seconds) as an image. folder empty = your Desktop."


def frame_export(tl, p, ctx):
    t = tl.playhead if str(p["time"]).strip().lower() in ("", "playhead") else float(p["time"])
    hit = [c for tr in reversed(tl.video) for c in tr if c.enabled and c.start - EPS <= t < c.end]  # topmost first
    if not hit:
        raise ValueError(f"no video at {t:.2f}s")
    c = hit[0]
    desk = Path.home() / "Desktop"
    folder = Path(p["folder"]) if p["folder"] else desk if desk.is_dir() else ctx.out_dir
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{tl.name} {int(t // 60):02d}m{t % 60:05.2f}s.{p['format']}"
    seek = [] if media.probe(c.path)["duration"] == 0 else ["-ss", f"{c.src_in + t - c.start:.3f}"]
    media.ffmpeg(*seek, "-i", c.path, "-frames:v", "1", "-vf", f"scale=iw*{float(p['scale']) / 100:.3f}:-2",
                 *(["-q:v", "2"] if p["format"] == "jpg" else []), f)
    return dict(files=[str(f)], report=dict(saved=str(f), time=round(t, 3), clip=Path(c.path).name))


# ---------------------------------------------------------------- beat markers

BEATM_DEFAULTS = dict(music="", track="1", every=1, offset=0.0, label="Beat", downbeats_only=False)
BEATM_HELP = ("Detects the tempo and drops sequence markers on the beat. music = a song file; empty = the first "
              "clip on audio `track`. every = mark every N beats; downbeats_only = one per bar (4 beats).")


def beat_markers(tl, p, ctx):
    from .sound import beats
    if p["music"]:
        src, start, a, b = p["music"], 0.0, 0.0, 1e9
    else:
        ti = parse_tracks(p["track"])[0]
        tr = tl.audio[ti] if ti < len(tl.audio) else []
        if not tr:
            raise ValueError("no clip on that audio track: set `music`")
        c = tr[0]
        src, start, a, b = c.path, c.start, c.src_in, c.src_out
    bt, bpm = beats(src)
    step = 4 if p["downbeats_only"] else max(1, int(p["every"]))
    ts = [start + x - a + float(p["offset"]) for x in bt[::step] if a <= x < b]
    marks = [dict(t=round(t, 3), name=f"{p['label']} {i + 1}") for i, t in enumerate(ts) if t >= 0]
    return dict(markers=marks, report=dict(bpm=round(bpm, 1), markers=len(marks)))


# ---------------------------------------------------------------- quick mask (offline AI cutout)

MODELS = {"u2netp": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
          "u2net_human_seg": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
          "silueta": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx"}
MASK_DEFAULTS = dict(track="1", clips="playhead", model="u2netp", output="cutout", region="", threshold=0.5,
                     softness=0.15, feather=2, smooth=0.5)
MASK_CHOICES = dict(model=list(MODELS), output=["cutout", "matte"])
MASK_HELP = ("AI subject cutout that runs offline (U²-Net via ONNX Runtime; the model downloads once). cutout = the "
             "subject with transparency on a new track above (put text/graphics between), matte = black/white "
             "matte for Track Matte Key. u2net_human_seg is best for people; u2netp is fastest. smooth = temporal "
             "steadiness 0-1. region = x,y,w,h (0-1 fractions, drawn in the panel): only that part of the frame is "
             "masked.")


def _model(name):
    f = media.HOME / "models" / f"{name}.onnx"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        urllib.request.urlretrieve(MODELS[name], tmp)
        tmp.replace(f)
    import onnxruntime as ort
    prov = [p for p in ("CUDAExecutionProvider", "CoreMLExecutionProvider", "CPUExecutionProvider")
            if p in ort.get_available_providers()]
    return ort.InferenceSession(str(f), providers=prov)


def mask_frame(sess, rgb, size=320):
    import cv2
    x = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = ((x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)).transpose(2, 0, 1)[None].astype(np.float32)
    m = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    m = (m - m.min()) / max(1e-6, float(m.max() - m.min()))
    return cv2.resize(m, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)


def quick_mask(tl, p, ctx):
    import cv2
    track = parse_tracks(p["track"])[0]
    sess = _model(p["model"])
    out, made = copy.deepcopy(tl), []
    thr, soft, feather, sm = float(p["threshold"]), max(.01, float(p["softness"])), int(p["feather"]), float(p["smooth"])
    for c in _clips(out, p, track):
        info = media.probe(c.path)
        w, h = info["width"], info["height"]
        if not w:
            continue
        alpha_out = p["output"] == "cutout"
        r = [float(v) for v in str(p["region"]).split(",")] if str(p["region"]).strip() else [0, 0, 1, 1]
        box = (int(r[0] * w), int(r[1] * h), max(int(r[0] * w) + 8, int((r[0] + r[2]) * w)),
               max(int(r[1] * h) + 8, int((r[1] + r[3]) * h)))
        dest = _out(ctx, c, "cutout" if alpha_out else "matte", "mov" if alpha_out else "mp4")
        rd = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{c.src_in:.3f}", "-t", f"{c.dur:.3f}", "-i", c.path,
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        wr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba" if alpha_out else "gray",
                               "-s", f"{w}x{h}", "-r", f"{info['fps'] or tl.fps:.3f}", "-i", "-",
                               *_encode(dest, alpha=alpha_out)], stdin=subprocess.PIPE)
        prev = None
        try:
            while True:
                buf = rd.stdout.read(w * h * 3)
                if len(buf) < w * h * 3:
                    break
                rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                m = np.zeros((h, w), np.float32)
                x0, y0, x1, y1 = box
                m[y0:y1, x0:x1] = np.clip((mask_frame(sess, rgb[y0:y1, x0:x1]) - thr) / soft + .5, 0, 1)
                if prev is not None:
                    m = sm * prev + (1 - sm) * m
                prev = m
                if feather:
                    m = cv2.GaussianBlur(m, (0, 0), feather)
                a = (m * 255).astype(np.uint8)
                wr.stdin.write(np.dstack([rgb, a]).tobytes() if alpha_out else a.tobytes())
        finally:
            wr.stdin.close()
            wr.wait()
            rd.stdout.close()
            rd.wait()
        if wr.returncode:
            raise RuntimeError(f"encoding the {p['output']} failed")
        made.append(Clip(str(dest), 0.0, c.dur, c.start))
    if made:
        add_track(out, "video", made)
    out.name = f"{tl.name} - Quick mask"
    return dict(timeline=out, files=[c.path for c in made], report=dict(clips=len(made), output=p["output"], model=p["model"]))


# ---------------------------------------------------------------- project sorter + FX presets (the host does the work)

SORT_BINS = {"Video": [".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".mts", ".r3d", ".braw", ".webm"],
             "Audio": [".wav", ".mp3", ".aac", ".m4a", ".aif", ".aiff", ".flac", ".ogg"],
             "Images": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp", ".heic", ".exr", ".dpx"],
             "Graphics": [".mogrt", ".psd", ".ai", ".aep", ".svg", ".eps"],
             "Captions": [".srt", ".vtt", ".scc", ".xml"]}
SORT_DEFAULTS = dict(sequences_bin="Sequences", other_bin="Other", prefix="")
SORT_HELP = ("Organizes the project panel (Premiere bins / Resolve Media Pool folders) into Video, Audio, Images, "
             "Graphics, Captions, Sequences and Other. Only top-level items move; existing bins are left alone.")


def project_sort(tl, p, ctx):
    pre = p["prefix"]
    bins = {f"{pre}{k}": v for k, v in SORT_BINS.items()}
    return dict(sort=dict(bins=bins, sequences=f"{pre}{p['sequences_bin']}", other=f"{pre}{p['other_bin']}"),
                report=dict(bins=[*bins, pre + p["sequences_bin"], pre + p["other_bin"]]))


FX_DIR = media.HOME / "fx"
FX_HELP = ("Save a clip's whole effect stack with its keyframes and reapply it to other clips in one click "
           "(Premiere: select a clip → Copy effects; select clips → Apply).")


def _fx_file(name):
    safe = re.sub(r'[<>:"/\\|?*]', "_", str(name)).strip() or "preset"
    return FX_DIR / f"{safe}.json"


def fx_list():
    return sorted(f.stem for f in FX_DIR.glob("*.json")) if FX_DIR.exists() else []


def fx_save(name, chain):
    FX_DIR.mkdir(parents=True, exist_ok=True)
    _fx_file(name).write_text(json.dumps(chain, indent=1), "utf-8")
    return dict(saved=name, components=len(chain.get("components", [])) if isinstance(chain, dict) else 0)


def fx_get(name):
    return json.loads(_fx_file(name).read_text("utf-8"))


def fx_delete(name):
    _fx_file(name).unlink(missing_ok=True)
    return dict(deleted=name)


# ---------------------------------------------------------------- zoom in / out (eased scale move)

ZOOMM_DEFAULTS = dict(direction="in", ease="out", amount=120.0, duration=0.6, at="playhead", track="1",
                      anchor_x=0.5, anchor_y=0.5, curve="")
ZOOMM_CHOICES = dict(direction=["in", "out"], ease=["in", "out", "in_out", "linear"], at=["playhead", "clip_start", "clip_end"])
ZOOMM_HELP = ("Smooth zoom transition on the clip under the playhead: direction in (100% → amount) or out (amount → "
              "100%), eased in / out / in_out (or your bezier `curve`), starting at the playhead or the clip start "
              "(clip_end = finishes at the cut). Written as Motion keyframes you can still edit.")


def zoom_move(tl, p, ctx):
    track = parse_tracks(p["track"])[0]
    out = copy.deepcopy(tl)
    hit = _clips(out, dict(clips="playhead"), track)
    if not hit:
        raise ValueError("no clip on that track")
    c, d = hit[0], min(float(p["duration"]), hit[0].dur)
    t0 = {"clip_start": c.start, "clip_end": c.end - d}.get(p["at"], max(c.start, min(tl.playhead, c.end - d)))
    ease = curve_fn(p["curve"] or {"in": "ease_in", "out": "ease_out", "in_out": "ease_in_out"}.get(p["ease"], "linear"))
    a, b = (100.0, float(p["amount"])) if p["direction"] == "in" else (float(p["amount"]), 100.0)
    ax, ay = float(p["anchor_x"]), float(p["anchor_y"])
    n = 12
    sk = [(t0 + d * k / n, a + (b - a) * ease(k / n)) for k in range(n + 1)]
    sk = [(c.start, a)] * (t0 > c.start + EPS) + sk + [(c.end, b)] * (t0 + d < c.end - EPS)
    rel = lambda kf: [(t - c.start, *v) for t, *v in kf]
    c.scale = rel(sk)
    c.center = rel([(t, (ax - .5) * (1 - s / 100), (ay - .5) * (1 - s / 100)) for t, s in sk])
    out.name = f"{tl.name} - Zoom {p['direction']}"
    return dict(timeline=out, report=dict(clip=Path(c.path).name, start=round(t0, 2), duration=d,
                                          scale=f"{a:.0f}% → {b:.0f}%"))


def frame_image(tl, t=None, width=480):
    """Data-URL JPEG of the topmost video at t (playhead by default): used to draw Quick Mask regions."""
    import base64
    t = tl.playhead if t is None else float(t)
    hit = [c for tr in reversed(tl.video) for c in tr if c.enabled and c.start - EPS <= t < c.end]
    if not hit:
        raise ValueError(f"no video at {t:.2f}s")
    c = hit[0]
    f = media.CACHE / "frame.jpg"
    media.CACHE.mkdir(parents=True, exist_ok=True)
    seek = [] if media.probe(c.path)["duration"] == 0 else ["-ss", f"{c.src_in + t - c.start:.3f}"]
    media.ffmpeg(*seek, "-i", c.path, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", f)
    return dict(image="data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode(), t=t)
