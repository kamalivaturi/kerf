"""AutoZoom (anchor-preserving punch-ins) and AutoResize (subject-tracked social reframing)."""
from __future__ import annotations

import copy
import math
import subprocess
import sys

import numpy as np

from . import media
from .silence import auto_threshold, peaks, speech_ranges, timeline_db
from .timeline import Clip, add_track, interp, keep, parse_tracks, set_keyframes, split

RHYTHM = {"very_calm": 12.0, "calm": 8.0, "moderate": 5.0, "energetic": 3.0, "hyperactive": 1.5}
EMPHASIS = set(("never always important biggest best worst must secret huge only every nothing everything million "
                "billion first key remember crazy insane incredible literally exactly").split())
ZOOM_DEFAULTS = dict(rhythm="moderate", triggers="cuts,speaking,emotion", style="smooth", min_zoom=100,
                     max_zoom=115, anchor_x=0.5, anchor_y=0.4, target_tracks="1", ignore_tracks="",
                     camera_movement=False, sound="", language="")
ZOOM_CHOICES = dict(rhythm=list(RHYTHM), style=["jump_cut", "smooth", "snap_in"])
ZOOM_HELP = ("Triggers: cuts (always), speaking, emotion (loudness peaks), highlight (emphasis words, needs "
             "transcription). anchor_x/y = zoom focus (0-1). sound = optional whoosh file on each zoom.")

FORMATS = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}
RESIZE_DEFAULTS = dict(format="9:16", width=0, height=0, track="1", follow_subject=True, smoothing=1.5, zoom=100,
                       anchor_x=0.5, watermark="", watermark_x=0.85, watermark_y=0.08, watermark_size=15, ranges="")
RESIZE_CHOICES = dict(format=list(FORMATS) + ["custom"])
RESIZE_HELP = ("Reframes to a social format, keeping the face centered (OpenCV). width/height for custom. "
               "ranges '0-30,45-60' (seconds) resizes only those sections.")


def anchor_center(scale_pct, ax, ay):
    k = 1 - scale_pct / 100
    return (ax - 0.5) * k, (ay - 0.5) * k


def zoom(tl, p, ctx):
    targets = parse_tracks(p["target_tracks"])
    ignore = set(parse_tracks(p["ignore_tracks"]))
    trig = {t.strip() for t in str(p["triggers"]).split(",")}
    db = timeline_db(tl, [0])
    gap = RHYTHM.get(p["rhythm"], 5.0)
    cuts = {0.0} | {c.start for ti in targets if ti not in ignore and ti < len(tl.video) for c in tl.video[ti]}
    extra = set()
    if "speaking" in trig:
        extra |= {a for a, _ in speech_ranges(db, auto_threshold(db), 0.5, 0.2, 0.0, 0.0)}
    if "emotion" in trig:
        extra |= set(peaks(db, min_gap=gap / 2))
    warn = []
    if "highlight" in trig:
        from .speech import norm, timeline_words
        try:
            extra |= {w["s"] for w in timeline_words(tl, 0, p["language"])
                      if norm(w["w"]) in EMPHASIS or any(ch.isdigit() for ch in w["w"])}
        except Exception as e:  # transcription unavailable: the other triggers still work
            warn.append(f"highlight trigger skipped: {type(e).__name__}")
    times, last = [], -1e9
    for t in sorted(cuts | extra):
        if (t in cuts or t - last >= gap) and not (times and t - times[-1] < 0.5):
            times.append(t)
            last = t
    times.append(tl.duration)

    lo, hi = float(p["min_zoom"]), float(p["max_zoom"])
    if p["camera_movement"]:
        lo = max(lo, 103.0)
    ax, ay = float(p["anchor_x"]), float(p["anchor_y"])
    style = p["style"]
    zoomed = [(a, b) for i, (a, b) in enumerate(zip(times, times[1:])) if i % 2 == 1 and b - a > 0.2]

    if style == "jump_cut":  # hard zoom, no keyframes: split clips, static scale per piece
        out = split(tl, times, kinds=("video",), tracks=set(targets))
        for ti in targets:
            for c in out.video[ti]:
                mid = (c.start + c.end) / 2
                s = hi if any(a <= mid < b for a, b in zoomed) else lo
                c.scale = [(0.0, s)]
                c.center = [(0.0, *anchor_center(s, ax, ay))]
    else:
        out = copy.deepcopy(tl)
        sk = [(0.0, lo)]
        for a, b in zoomed:
            ramp = min(0.6, (b - a) / 3) if style == "smooth" else min(0.15, (b - a) / 3)
            back = ramp if style == "smooth" else 1 / tl.fps
            sk += [(a, lo), (a + ramp, hi), (b - back, hi), (b, lo)]
        sk.append((tl.duration, lo))
        if p["camera_movement"]:  # handheld drift on top of the anchor offset
            pts = sorted({t for t, _ in sk} | set(np.arange(0, tl.duration, 0.5).tolist()))
            ck = []
            for t in pts:
                cx, cy = anchor_center(interp(sk, t)[0], ax, ay)
                ck.append((t, cx + 0.004 * math.sin(t * 1.3), cy + 0.003 * math.cos(t * 0.9)))
        else:
            ck = [(t, *anchor_center(s, ax, ay)) for t, s in sk]
        set_keyframes(out, targets, scale=sk, center=ck)
    if p["sound"]:
        sd = media.probe(p["sound"])["duration"]
        add_track(out, "audio", [Clip(p["sound"], 0.0, min(sd, b - a), a) for a, b in zoomed])
    out.name = f"{tl.name} - Zoom"
    return dict(timeline=out, report=dict(zooms=len(zoomed), triggers=len(times) - 1, warnings=warn))


# ---------------------------------------------------------------- Resize

STEP = 0.5
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")


def face_detector(w, h):
    """gray frame → [(x, y, w, h), ...]. Haar (OpenCV 4) → YuNet (OpenCV 5, model fetched once) → none."""
    import cv2
    if hasattr(cv2, "CascadeClassifier"):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        return lambda fr: c.detectMultiScale(fr, 1.1, 5, minSize=(16, 16))
    model = media.HOME / "models" / "face_detection_yunet_2023mar.onnx"
    if not model.exists():
        import urllib.request
        model.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(YUNET_URL, model)
    det = cv2.FaceDetectorYN.create(str(model), "", (w, h), 0.6)

    def run(fr):
        _, faces = det.detect(cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR))
        return [] if faces is None else [f[:4] for f in faces]
    return run


def face_track(path):
    """Normalized x of the largest face every STEP seconds of the whole file (NaN = none). Cached."""
    f = media.CACHE / f"{media.cache_key(path, 'face', STEP)}.npy"
    if f.exists():
        return np.load(f)
    import cv2
    info = media.probe(path)
    w, h = 320, int(round(320 * info["height"] / info["width"] / 2)) * 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={1 / STEP},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w)
    detect = face_detector(w, h)
    xs = []
    for fr in frames:
        faces = detect(fr)
        if len(faces):
            x, _, fw, _ = max(faces, key=lambda r: r[2] * r[3])[:4]
            xs.append((x + fw / 2) / w)
        else:
            xs.append(np.nan)
    xs = np.array(xs, np.float32)
    media.CACHE.mkdir(parents=True, exist_ok=True)
    np.save(f, xs)
    return xs


def subject_x(path, a, b, smoothing, default=0.5):
    xs = face_track(path)
    i = int(a / STEP)
    j = max(i + 1, int(math.ceil(b / STEP)) + 1)
    seg = xs[i:j].astype(np.float64)
    if not len(seg) or np.isnan(seg).all():
        return np.full(max(1, j - i), default)
    idx = np.arange(len(seg))
    ok = ~np.isnan(seg)
    seg = np.interp(idx, idx[ok], seg[ok])
    k = max(1, int(smoothing / STEP))
    pad = np.pad(seg, k, mode="edge")
    return np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]


def reframe(tl, fmt="9:16", track=0, follow=True, smoothing=1.5, zoom_pct=100.0, anchor_x=0.5, W=0, H=0):
    W, H = (int(W), int(H)) if fmt == "custom" else FORMATS[fmt]
    out = copy.deepcopy(tl)
    out.width, out.height = W, H
    for ti, tr in enumerate(out.video):
        for c in tr:
            info = media.probe(c.path)
            if not info["width"]:
                continue
            s = max(W / info["width"], H / info["height"]) * float(zoom_pct)
            disp = info["width"] * s / 100 / W  # displayed width in sequence widths
            lim = max(0.0, (disp - 1) / 2)       # keeps the frame covered: no black bars
            clamp = lambda v: float(np.clip(v, -lim, lim))
            c.scale = [(0.0, s)]
            if ti == track and follow and info["duration"]:
                try:
                    xs = subject_x(c.path, c.src_in, c.src_out, smoothing, anchor_x)
                except Exception as e:  # no detector/model available: static framing on anchor_x
                    print(f"kerf: face tracking unavailable ({e}); using anchor_x", file=sys.stderr)
                    xs = [anchor_x]
                kf, prev = [], None
                for k, fx in enumerate(xs):
                    cx = clamp(-(fx - 0.5) * disp)
                    if prev is None or abs(cx - prev) > 0.004:
                        kf.append((min(k * STEP, c.dur), cx, 0.0))
                        prev = cx
                c.center = kf if len(kf) > 1 else [(0.0, kf[0][1] if kf else 0.0, 0.0)]
            else:
                c.center = [(0.0, clamp(-(anchor_x - 0.5) * disp), 0.0)]
    return out


def resize(tl, p, ctx):
    if str(p["ranges"]).strip():
        rs = [tuple(float(x) for x in r.split("-")) for r in str(p["ranges"]).split(",") if "-" in r]
        tl = keep(tl, rs)
    track = (parse_tracks(p["track"]) or [0])[0]
    out = reframe(tl, p["format"], track, p["follow_subject"], float(p["smoothing"]), float(p["zoom"]),
                  float(p["anchor_x"]), int(p["width"]), int(p["height"]))
    if p["watermark"]:
        info = media.probe(p["watermark"])
        s = float(p["watermark_size"]) / 100 * out.width / info["width"] * 100
        wm = Clip(p["watermark"], 0.0, out.duration, 0.0, scale=[(0.0, s)],
                  center=[(0.0, float(p["watermark_x"]) - 0.5, float(p["watermark_y"]) - 0.5)])
        add_track(out, "video", [wm])
    out.name = f"{tl.name} - {p['format'].replace(':', 'x')}"
    return dict(timeline=out, report=dict(width=out.width, height=out.height))
