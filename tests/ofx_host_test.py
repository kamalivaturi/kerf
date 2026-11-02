"""Stand-in OpenFX host for Kerf FX: loads the plugin the way Resolve does (load, describe, describe in context,
create instance, render, destroy, unload) and renders every effect on test frames, including extreme settings,
half-resolution renders and a 9:16 frame. Fails on a crash, a non-OK status, NaNs, or an effect that does nothing.

    python tests/ofx_host_test.py [path/to/KerfFX.ofx.bundle]     (previews go to build/ofx/test/*.png)

On Apple silicon run it with an x86_64 Python (arch -x86_64): ctypes callbacks cannot read arm64 variadic
arguments, and paramGetValueAtTime is variadic.
"""
import ctypes as C
import math
import os
import platform
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCH = {"Windows": "Win64", "Darwin": "MacOS", "Linux": "Linux-x86-64"}[platform.system()]
OK, FAILED, UNKNOWN, UNSUPPORTED, BAD_HANDLE, BAD_INDEX, IMAGE_FORMAT = 0, 1, 3, 5, 9, 10, 1000

# ------------------------------------------------------------------------------------------------ handles
objects, _next = {}, [1]


def new(obj):
    h = _next[0]
    _next[0] += 1
    objects[h] = obj
    return h


def props(**values):
    return new({k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in values.items()})


keep = []  # C strings and callbacks handed to the plugin must outlive the call


def cstr(s):
    b = C.create_string_buffer(s.encode() if isinstance(s, str) else s)
    keep.append(b)
    return C.addressof(b)


def _write(out, value):
    if out:
        C.cast(out, C.POINTER(C.c_void_p))[0] = value


# ------------------------------------------------------------------------------------------------ property suite
def _set(h, name, i, v):
    p = objects.get(h)
    if not isinstance(p, dict):
        return BAD_HANDLE
    vals = p.setdefault(name.decode(), [])
    vals.extend([None] * (i + 1 - len(vals)))
    vals[i] = v
    return OK


def _get(h, name, i):
    p = objects.get(h)
    if not isinstance(p, dict):
        return BAD_HANDLE, None
    vals = p.get(name.decode())
    if vals is None:
        return UNKNOWN, None
    if i >= len(vals):
        return BAD_INDEX, None
    return OK, vals[i]


def _setN(kind):
    def f(h, n, count, arr):
        for i in range(count):
            v = C.cast(arr, C.POINTER(kind))[i]
            r = _set(h, n, i, v.decode() if isinstance(v, bytes) else v)
            if r:
                return r
        return OK
    return f


def _getter(kind, convert):
    def f(h, n, i, out):
        st, v = _get(h, n, i)
        if st:
            return st
        C.cast(out, C.POINTER(kind))[0] = convert(v)
        return OK
    return f


def _getterN(kind, convert):
    def f(h, n, count, out):
        for i in range(count):
            st, v = _get(h, n, i)
            if st:
                return st
            C.cast(out, C.POINTER(kind))[i] = convert(v)
        return OK
    return f


def _dim(h, n, out):
    p = objects.get(h)
    if not isinstance(p, dict):
        return BAD_HANDLE
    C.cast(out, C.POINTER(C.c_int))[0] = len(p.get(n.decode(), []))
    return OK


H, S, P, F = C.c_void_p, C.c_char_p, C.c_void_p, C.CFUNCTYPE
ptr = lambda v: v or 0  # noqa: E731
PROP_SUITE = [  # order of OfxPropertySuiteV1
    (F(C.c_int, H, S, C.c_int, P), lambda h, n, i, v: _set(h, n, i, v)),
    (F(C.c_int, H, S, C.c_int, S), lambda h, n, i, v: _set(h, n, i, v.decode())),
    (F(C.c_int, H, S, C.c_int, C.c_double), lambda h, n, i, v: _set(h, n, i, v)),
    (F(C.c_int, H, S, C.c_int, C.c_int), lambda h, n, i, v: _set(h, n, i, v)),
    (F(C.c_int, H, S, C.c_int, P), _setN(C.c_void_p)),
    (F(C.c_int, H, S, C.c_int, P), _setN(C.c_char_p)),
    (F(C.c_int, H, S, C.c_int, P), _setN(C.c_double)),
    (F(C.c_int, H, S, C.c_int, P), _setN(C.c_int)),
    (F(C.c_int, H, S, C.c_int, P), _getter(C.c_void_p, ptr)),
    (F(C.c_int, H, S, C.c_int, P), _getter(C.c_void_p, cstr)),
    (F(C.c_int, H, S, C.c_int, P), _getter(C.c_double, float)),
    (F(C.c_int, H, S, C.c_int, P), _getter(C.c_int, int)),
    (F(C.c_int, H, S, C.c_int, P), _getterN(C.c_void_p, ptr)),
    (F(C.c_int, H, S, C.c_int, P), _getterN(C.c_void_p, cstr)),
    (F(C.c_int, H, S, C.c_int, P), _getterN(C.c_double, float)),
    (F(C.c_int, H, S, C.c_int, P), _getterN(C.c_int, int)),
    (F(C.c_int, H, S), lambda h, n: OK),
    (F(C.c_int, H, S, P), _dim),
]


# ------------------------------------------------------------------------------------------------ effects, clips, images
class Effect:
    def __init__(self):
        self.props = props()
        self.params = new({})  # param name -> param handle
        self.clips = {}        # clip name -> clip handle


class Frame:
    """Float RGBA test image: colour bars with a white grid, so moves, zooms and splits all show."""

    def __init__(self, w, h, blank=False, shift=0):
        self.w, self.h = w, h
        self.buf = (C.c_float * (w * h * 4))()
        if blank:
            return
        bars = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1)]
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 4
                u = (x - shift) % w  # the picture pans right by `shift` pixels
                self.buf[i:i + 4] = [1.0] * 4 if u % 20 == 0 or y % 20 == 0 else [*map(float, bars[u * 6 // w]), 1.0]


state = {"source": None, "output": None, "depth": "OfxBitDepthFloat", "size": (320, 180)}
PAN = 3  # source pixels the test picture pans per frame, so time-based effects see real motion
_frames = {}


def source_at(t):
    """The Source clip's frame at time t (cached): what a host returns for temporal clip access."""
    key = (*state["size"], int(round(t)))
    if key not in _frames:
        _frames[key] = Frame(*state["size"], shift=PAN * key[2])
    return _frames[key]


def _clip_get_image(clip, t, region, out):
    if objects[clip]["name"] == "Source" and state.get("no_source"):  # a General-context node with nothing wired in
        return FAILED
    frame = source_at(t) if objects[clip]["name"] == "Source" else state["output"]
    _write(out, props(OfxImagePropData=C.addressof(frame.buf), OfxImagePropBounds=[0, 0, frame.w, frame.h],
                      OfxImagePropRowBytes=frame.w * 16, OfxImageEffectPropPixelDepth=state["depth"],
                      OfxImageEffectPropComponents="OfxImageComponentRGBA", OfxImagePropPixelAspectRatio=1.0))
    return OK


def _fx(h):
    return objects.get(h) if isinstance(objects.get(h), Effect) else None


def _clip_define(fx, name, out):
    pid = props(OfxImageEffectPropFrameRate=30.0, OfxImageEffectPropFrameRange=[0.0, 90.0])
    _fx(fx).clips[name.decode()] = new({"name": name.decode(), "props": pid})
    _write(out, pid)
    return OK


def _clip_get_handle(fx, name, out_clip, out_props):
    clip = _fx(fx) and _fx(fx).clips.get(name.decode())
    if not clip:
        return UNKNOWN
    _write(out_clip, clip)
    _write(out_props, objects[clip]["props"])
    return OK


def _effect_get(attr):
    def f(fx, out):
        if not _fx(fx):
            return BAD_HANDLE
        _write(out, getattr(_fx(fx), attr))
        return OK
    return f


unsupported = lambda *a: UNSUPPORTED  # noqa: E731
FX_SUITE = [  # order of OfxImageEffectSuiteV1
    (F(C.c_int, H, P), _effect_get("props")),
    (F(C.c_int, H, P), _effect_get("params")),
    (F(C.c_int, H, S, P), _clip_define),
    (F(C.c_int, H, S, P, P), _clip_get_handle),
    (F(C.c_int, H, P), lambda clip, out: (_write(out, objects[clip]["props"]), OK)[1]),
    (F(C.c_int, H, C.c_double, P, P), _clip_get_image),
    (F(C.c_int, H), lambda img: OK if img in objects else BAD_HANDLE),
    (F(C.c_int, H, C.c_double, P), unsupported),
    (F(C.c_int, H), lambda fx: 0),
    (F(C.c_int, H, C.c_size_t, P), unsupported),
    (F(C.c_int, H), unsupported),
    (F(C.c_int, H, P), unsupported),
    (F(C.c_int, H), unsupported),
]

# ------------------------------------------------------------------------------------------------ parameter suite
overrides = {}  # param name -> value for the current render


def _param_define(ps, ptype, name, out):
    pid = props()
    objects[ps][name.decode()] = new({"type": ptype.decode(), "props": pid, "name": name.decode()})
    _write(out, pid)
    return OK


def _param_get_handle(ps, name, out, out_props):
    h = objects[ps].get(name.decode())
    if not h:
        return UNKNOWN
    _write(out, h)
    _write(out_props, objects[h]["props"])
    return OK


def _param_value(param, t, out, out2=None, out3=None):
    p = objects.get(param)
    if not isinstance(p, dict) or "type" not in p:
        return BAD_HANDLE
    default = objects[p["props"]].get("OfxParamPropDefault", [0])
    v = overrides.get(p["name"], default if p["type"] == "OfxParamTypeRGB" else default[0])
    if p["type"] == "OfxParamTypeDouble":
        C.cast(out, C.POINTER(C.c_double))[0] = float(v)
    elif p["type"] == "OfxParamTypeRGB":  # one pointer per component
        for ptr_, x in zip((out, out2, out3), v):
            C.cast(ptr_, C.POINTER(C.c_double))[0] = float(x)
    elif p["type"] == "OfxParamTypeString":
        _write(out, cstr(str(v or "")))
    else:
        C.cast(out, C.POINTER(C.c_int))[0] = int(v)
    return OK


PARAM_SUITE = [  # order of OfxParameterSuiteV1; the get-value calls are variadic: the value pointers come after
    (F(C.c_int, H, S, S, P), _param_define),
    (F(C.c_int, H, S, P, P), _param_get_handle),
    (F(C.c_int, H, P), unsupported),
    (F(C.c_int, H, P), lambda p, out: (_write(out, objects[p]["props"]), OK)[1]),
    (F(C.c_int, H, P), lambda p, out: _param_value(p, 0.0, out)),
    (F(C.c_int, H, C.c_double, P, P, P), _param_value),
] + [(F(C.c_int, H), unsupported)] * 12


# ------------------------------------------------------------------------------------------------ host
def suite(fns):
    cbs = [proto(fn) for proto, fn in fns]
    arr = (C.c_void_p * len(cbs))(*[C.cast(c, C.c_void_p) for c in cbs])
    keep.extend([cbs, arr])
    return C.addressof(arr)


SUITES = {b"OfxPropertySuite": suite(PROP_SUITE), b"OfxImageEffectSuite": suite(FX_SUITE),
          b"OfxParameterSuite": suite(PARAM_SUITE)}
fetch = F(C.c_void_p, H, S, C.c_int)(lambda host, name, ver: SUITES.get(name) if ver == 1 else None)


class OfxHost(C.Structure):
    _fields_ = [("host", C.c_void_p), ("fetchSuite", C.c_void_p)]


class OfxPlugin(C.Structure):
    _fields_ = [("pluginApi", C.c_char_p), ("apiVersion", C.c_int), ("pluginIdentifier", C.c_char_p),
                ("versionMajor", C.c_uint), ("versionMinor", C.c_uint), ("setHost", C.c_void_p), ("mainEntry", C.c_void_p)]


HOST = OfxHost(props(OfxPropName="com.kerf.testhost"), C.cast(fetch, C.c_void_p))
MAIN = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p)
SETHOST = C.CFUNCTYPE(None, C.POINTER(OfxHost))


def png(path, frame):
    rows = (b"\0" + bytes(int(max(0.0, min(1.0, frame.buf[(y * frame.w + x) * 4 + c])) * 255)
                          for x in range(frame.w) for c in range(3)) for y in range(frame.h - 1, -1, -1))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", frame.w, frame.h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


# Kerf FX is one effect: the Mode menu picks what it does; each mode's params are "<prefix>_<name>".
MODES = ["Shake", "Zoom", "RGBSplit", "Vignette", "Letterbox", "SpeedRamp", "MotionBlur", "Captions"]
PREFIX = ["shake", "zoom", "split", "vignette", "letterbox", "ramp", "blur", "cap"]
TEST = ROOT / "build" / "ofx" / "test"
WORDS = TEST / "words.tsv"  # Kerf transcript: start<TAB>end<TAB>word (seconds)
INDIC = TEST / "indic.tsv"
SRT = TEST / "subs.srt"


def caption_files():
    TEST.mkdir(parents=True, exist_ok=True)
    text = "Make every word count with Kerf captions in Resolve today".split()
    WORDS.write_text("".join(f"{0.3 * i + 0.2:.2f}\t{0.3 * i + 0.45:.2f}\t{w}\n" for i, w in enumerate(text)), "utf-8")
    # Hindi, Tamil, Telugu, Punjabi, Bengali, Kannada, Malayalam, Gujarati, Odia: conjuncts and vowel signs need shaping
    indic = ["नमस्ते", "दोस्तों", "क्षमा", "வணக்கம்", "నమస్తే", "ਸਤਿ", "নমস্কার", "ನಮಸ್ಕಾರ", "നമസ്കാരം", "નમસ્તે", "ନମସ୍କାର"]
    INDIC.write_text("".join(f"{0.4 * i + 0.2:.2f}\t{0.4 * i + 0.55:.2f}\t{w}\n" for i, w in enumerate(indic)), "utf-8")
    SRT.write_text("﻿1\n00:00:00,500 --> 00:00:02,500\nSubtitles from Resolve\nwork too\n\n", "utf-8")


# Per mode: (settings, frame) pairs: defaults first, then extremes that must stay stable.
CASES = {
    "Shake": [({}, 5), ({"amplitude": 400, "rotation": 45, "frequency": 40}, 17), ({"axis": 1, "hideEdges": 0}, 3)],
    "Zoom": [({}, 9), ({"amount": 400, "direction": 1, "ease": 2}, 4), ({"at": 1, "centerX": 0, "centerY": 100}, 85)],
    "RGBSplit": [({}, 0), ({"amount": 200, "angle": -90}, 0)],
    "Vignette": [({}, 0), ({"amount": 1, "size": 0.1, "softness": 0.01, "roundness": 0}, 0)],
    "Letterbox": [({}, 0), ({"aspect": 0.3, "opacity": 0.5}, 0), ({"aspect": 4}, 0)],
    "SpeedRamp": [({}, 30), ({"curve": 6, "rampBlur": 1}, 60), ({"curve": 8, "smooth": 0, "reverse": 1}, 40),
                  ({"curve": 0, "strength": 0.5}, 1), ({"curve": 9}, 30)],  # clip ends map to themselves
    "MotionBlur": [({}, 20), ({"mode": 1, "length": 120, "angle": 30}, 0), ({"amount": 3}, 89)],
    "Captions": [({"file": str(WORDS), "template": 1}, 30), ({"file": str(WORDS), "template": 13}, 45),
                 ({"file": str(WORDS), "template": 8, "words": 12}, 30), ({"file": str(WORDS), "template": 11, "case": 1}, 50),
                 ({"file": str(WORDS), "template": 4, "custom": 1, "highlight": (1, 0, 0), "size": 400}, 40),
                 ({"file": str(SRT), "template": 0, "raise": 70}, 40), ({"file": str(INDIC), "template": 10}, 30),
                 ({"file": str(WORDS), "template": 6, "offset": -0.5}, 20),  # typewriter, captions moved earlier
                 ({"media": "Z:/no such clip.mp4"}, 10)],  # no transcript yet: a status line says what to do
}


def grad(frame, dx, dy):
    """Mean absolute luma difference to the neighbour at (dx, dy): drops in the direction of a blur."""
    w, h, b, tot = frame.w, frame.h, frame.buf, 0.0
    for y in range(4, h - 4, 2):
        for x in range(4, w - 4, 2):
            i, j = (y * w + x) * 4, ((y + dy) * w + x + dx) * 4
            tot += abs(sum(b[i:i + 3]) - sum(b[j:j + 3]))
    return tot
SIZES = [(320, 180, 1.0), (160, 90, 0.5), (108, 192, 1.0)]  # 16:9, half-res proxy render, 9:16


def secret(desc, name):
    """Whether the plugin hid this param (or group) for the current mode."""
    h = objects[objects[desc].params][name]
    return bool(objects[objects[h]["props"]].get("OfxParamPropSecret", [0])[0])


def instance(call, desc, ctx, w, h, scale, mode):
    inst = new(Effect())
    e = objects[inst]
    e.params, e.clips = objects[desc].params, objects[desc].clips
    objects[e.props].update(OfxImageEffectPropProjectExtent=[w / scale, h / scale], OfxImageEffectPropContext=[ctx])
    overrides.clear()
    overrides["mode"] = mode
    assert call(b"OfxActionCreateInstance", inst) == 0, f"{MODES[mode]}: create instance"
    return inst


def render(call, inst, w, h, scale, t):
    state["size"] = (w, h)
    state["source"], state["output"] = source_at(t), Frame(w, h, blank=True)
    return call(b"OfxImageEffectActionRender", inst, props(OfxPropTime=float(t), OfxImageEffectPropRenderWindow=[0, 0, w, h],
                                                           OfxImageEffectPropRenderScale=[scale, scale]))


def changed(call, inst, name):
    """The host telling the plugin a param changed (the user picked a mode, pressed a button)."""
    return call(b"OfxActionInstanceChanged", inst, props(OfxPropType="OfxTypeParameter", OfxPropName=name, OfxPropTime=0.0,
                                                         OfxPropChangeReason="OfxChangeUserEdited",
                                                         OfxImageEffectPropRenderScale=[1.0, 1.0]))


def main():
    bundle = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "panels" / "KerfFX.ofx.bundle"
    home = TEST / "home"  # a Kerf home with no engine running (port 1 refuses), before the plugin reads the env
    (home / "captions").mkdir(parents=True, exist_ok=True)
    (home / "engine.json").write_text('{"port": 1}')
    for f in (home / "captions").glob("*"):
        f.unlink()
    os.environ["KERF_HOME_DIR"] = str(home)
    caption_files()
    lib = C.CDLL(str(bundle / "Contents" / ARCH / "KerfFX.ofx"))
    lib.OfxGetPlugin.restype = C.POINTER(OfxPlugin)
    out_dir = TEST
    n, fails = lib.OfxGetNumberOfPlugins(), []
    assert n == 1, f"plugin count {n}: Kerf FX is one effect"
    plug = lib.OfxGetPlugin(0).contents
    assert plug.pluginIdentifier == b"com.kerf.fx", plug.pluginIdentifier
    SETHOST(plug.setHost)(C.pointer(HOST))
    entry = MAIN(plug.mainEntry)
    call = lambda action, h=None, args=None: entry(action, h, args, None)  # noqa: E731
    assert call(b"OfxActionLoad") == 0, "load"
    for ctx in ("OfxImageEffectContextFilter", "OfxImageEffectContextGeneral"):  # Edit/Color pages, Fusion page
        desc = new(Effect())  # a fresh descriptor per context, as hosts do
        assert call(b"OfxActionDescribe", desc) == 0, "describe"
        assert objects[objects[desc].props]["OfxPropLabel"] == ["Kerf FX"]
        assert ctx in objects[objects[desc].props]["OfxImageEffectPropSupportedContexts"], f"no {ctx}"
        assert call(b"OfxImageEffectActionDescribeInContext", desc, props(OfxImageEffectPropContext=ctx)) == 0, (
            f"describe in {ctx}")
        short = ctx.rsplit("Context", 1)[1]
        for mi, name in enumerate(MODES):
            for w, h, scale in SIZES:
                inst = instance(call, desc, ctx, w, h, scale, mi)
                wrong = [p for p in objects[objects[desc].params] if "_" in p and  # every mode's group and params
                         secret(desc, p) != (p.split("_", 1)[1 if p.startswith("g_") else 0] != PREFIX[mi])]
                if wrong:
                    fails.append(f"{name}: shows or hides the wrong controls: {wrong[:4]}")
                for k, (settings, t) in enumerate(CASES[name]):
                    overrides.clear()
                    overrides["mode"] = mi
                    overrides.update({f"{PREFIX[mi]}_{key}": v for key, v in settings.items()})
                    st = render(call, inst, w, h, scale, t)
                    out, label = state["output"], f"{name} {short} {w}x{h} case {k}"
                    vals = list(out.buf)
                    if st != 0:
                        fails.append(f"{label}: render returned {st}")
                    elif not all(math.isfinite(v) for v in vals):
                        fails.append(f"{label}: NaN/inf in output")
                    elif all(abs(a - b) < 1e-6 for a, b in zip(vals, state["source"].buf)):
                        fails.append(f"{label}: output identical to the input")
                    elif name == "MotionBlur" and k == 0:  # the picture pans sideways: blur must follow it
                        src, hx, vy = state["source"], grad(out, 1, 0), grad(out, 0, 1)
                        if not (hx < 0.9 * grad(src, 1, 0) and vy > 0.9 * grad(src, 0, 1)):
                            fails.append(f"{label}: automatic blur did not follow the horizontal pan")
                    if (w, h) == SIZES[0][:2] and short == "Filter":
                        png(out_dir / f"{name}_{k}.png", out)
                state["depth"] = "OfxBitDepthByte"  # a wrong pixel format must be refused, never crash
                st = call(b"OfxImageEffectActionRender", inst, props(OfxPropTime=0.0, OfxImageEffectPropRenderWindow=[0, 0, w, h],
                                                                    OfxImageEffectPropRenderScale=[scale, scale]))
                state["depth"] = "OfxBitDepthFloat"
                if st != IMAGE_FORMAT:
                    fails.append(f"{name}: 8-bit image gave status {st}, expected kOfxStatErrImageFormat")
                if short == "General":  # nothing connected to Source: refuse the frame, never crash
                    state["no_source"] = True
                    st = call(b"OfxImageEffectActionRender", inst, props(OfxPropTime=0.0, OfxImageEffectPropRenderWindow=[0, 0, w, h],
                                                                        OfxImageEffectPropRenderScale=[scale, scale]))
                    state["no_source"] = False
                    if st != FAILED:
                        fails.append(f"{name}: render with no Source gave status {st}, expected kOfxStatFailed")
                assert call(b"OfxActionDestroyInstance", inst) == 0
            if short == "Filter":
                print(f"ok   {name}")

    # Picking another mode swaps the controls shown.
    w, h = SIZES[0][:2]
    inst = instance(call, desc, "OfxImageEffectContextFilter", w, h, 1.0, 7)
    overrides["mode"] = 2
    if changed(call, inst, "mode") != 0 or secret(desc, "g_split") or not secret(desc, "g_cap"):
        fails.append("changing the mode did not swap the controls")
    # Transcribe with Kerf not running: the frame says so, nothing blocks or crashes.
    overrides.update(mode=7, cap_media=str(TEST / "clip.mp4"), cap_language=2)
    assert changed(call, inst, "cap_transcribe") == 0
    for _ in range(100):
        errs = list((home / "captions").glob("*.err"))
        if errs and not list((home / "captions").glob("*.pending")):
            break
        time.sleep(0.05)
    if not errs or "isn't running" not in errs[0].read_text("utf-8"):
        fails.append(f"Transcribe without Kerf running: {[e.read_text('utf-8') for e in errs] or 'no message'}")
    elif render(call, inst, w, h, 1.0, 10) != 0 or all(abs(a - b) < 1e-6 for a, b in zip(state["output"].buf, state["source"].buf)):
        fails.append("Transcribe without Kerf running: the frame shows no message")
    assert call(b"OfxActionDestroyInstance", inst) == 0
    print("ok   mode switch, Transcribe button")

    # Every caption template, larger, to look at.
    w, h = 640, 360
    for i in range(15):
        inst = instance(call, desc, "OfxImageEffectContextFilter", w, h, 1.0, 7)
        overrides.update(cap_file=str(INDIC if i in (1, 10) else WORDS), cap_template=i)
        if render(call, inst, w, h, 1.0, 45 if i not in (1, 10) else 60) != 0:
            fails.append(f"caption template {i}: render failed")
        png(out_dir / f"Captions_template_{i:02}.png", state["output"])
        assert call(b"OfxActionDestroyInstance", inst) == 0
    inst = instance(call, desc, "OfxImageEffectContextFilter", w, h, 1.0, 7)  # every script at once, to look at
    overrides.update(cap_file=str(INDIC), cap_template=8, cap_words=12)
    render(call, inst, w, h, 1.0, 9)
    png(out_dir / "Captions_indian_scripts.png", state["output"])
    assert call(b"OfxActionDestroyInstance", inst) == 0
    print("ok   15 caption templates")
    assert call(b"OfxActionUnload") == 0
    state["size"] = SIZES[0][:2]
    png(out_dir / "Source.png", source_at(0))
    print("\n".join(fails) or f"all {len(MODES)} modes pass; previews in {out_dir}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
