"""Render a timeline to a finished file with FFmpeg: MP4 (H.264/HEVC, GPU encoders auto-detected:
NVENC → QuickSync → AMF → x264/x265), up to 4K60, or ProRes 4444 with alpha (.mov)."""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from . import media

RENDER_DEFAULTS = dict(format="mp4", codec="auto", quality="high", width=0, height=0, fps=0.0, output="")
RENDER_CHOICES = dict(format=["mp4", "mov_alpha"], codec=["auto", "h264", "hevc", "libx264", "libx265",
                                                          "h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv",
                                                          "h264_amf", "hevc_amf"], quality=["draft", "good", "high"])
RENDER_HELP = ("Exports the timeline (all tracks, transparent overlays, mixed audio). width/height/fps 0 = timeline. "
               "mov_alpha = ProRes 4444 with transparency. HEVC is chosen automatically above 1080p.")
CRF = {"draft": 28, "good": 23, "high": 18}


@functools.lru_cache(maxsize=None)
def encoders():
    return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout


def candidates(codec, big):
    if codec not in ("auto", "h264", "hevc"):
        return [codec]
    hevc = codec == "hevc" or (codec == "auto" and big)
    pref = (["hevc_nvenc", "hevc_videotoolbox", "hevc_qsv", "hevc_amf", "libx265"] if hevc  # videotoolbox = macOS
            else ["h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf", "libx264"])
    return [e for e in pref if f" {e} " in encoders()] or ["libx264"]


def video_args(enc, quality, W, H, fps):
    if enc.startswith("lib"):
        return ["-c:v", enc, "-crf", str(CRF[quality]), "-preset", "medium", "-pix_fmt", "yuv420p"]
    mbps = (45 if W * H > 2560 * 1440 else 16 if W * H > 1280 * 720 else 8) * (fps / 30) ** 0.5
    mbps *= {"draft": 0.5, "good": 0.8, "high": 1.0}[quality]
    return ["-c:v", enc, "-b:v", f"{mbps:.0f}M", "-maxrate", f"{mbps * 1.5:.0f}M", "-bufsize", f"{mbps * 2:.0f}M",
            "-pix_fmt", "yuv420p"]


def build(tl, W, H, fps, alpha):
    """→ (input args, filter graph). One fast-seeked input per clip, so only used frames are decoded."""
    # ponytail: one input per clip; past a few hundred clips render in chunks to stay under OS arg limits
    D = tl.duration
    ins, fc, n = [], [], [0]

    def add_input(c):
        info = media.probe(c.path)
        if info["fps"] == 0 and info["width"]:  # still image
            ins.extend(["-loop", "1", "-t", f"{c.dur:.3f}", "-i", c.path])
        else:
            ins.extend(["-ss", f"{c.src_in:.3f}", "-t", f"{c.dur:.3f}", "-i", c.path])
        n[0] += 1
        return n[0] - 1

    layers = []
    for ti, tr in enumerate(tl.video):
        clips = sorted((c for c in tr if c.enabled), key=lambda c: c.start)
        if not clips:
            continue
        bg = "black@0.0" if (ti or alpha) else "black"
        pieces, t = [], 0.0
        for c in clips:
            if c.start - t > 1e-3:
                pieces.append(f"color=c={bg}:s={W}x{H}:r={fps}:d={c.start - t:.3f},format=rgba")
            info = media.probe(c.path)
            # ponytail: first keyframe of scale/center only; animated zooms are exported through the NLE
            s = (c.scale[0][1] if c.scale else 100.0) / 100
            if not c.scale and (info["width"], info["height"]) != (W, H):
                s = min(W / info["width"], H / info["height"])  # fit, like an NLE default
            cx, cy = (c.center[0][1], c.center[0][2]) if c.center else (0.0, 0.0)
            sw, sh = max(2, int(info["width"] * s) // 2 * 2), max(2, int(info["height"] * s) // 2 * 2)
            k = add_input(c)
            x, y = int((W - sw) / 2 + cx * W), int((H - sh) / 2 + cy * H)
            pieces.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={fps},scale={sw}:{sh},format=rgba[c{k}];"
                          f"color=c={bg}:s={W}x{H}:r={fps}:d={c.dur:.3f},format=rgba[b{k}];"
                          f"[b{k}][c{k}]overlay=x={x}:y={y}:shortest=1:format=auto")
            t = c.end
        if D - t > 1e-3:
            pieces.append(f"color=c={bg}:s={W}x{H}:r={fps}:d={D - t:.3f},format=rgba")
        labels = []
        for i, pc in enumerate(pieces):
            fc.append(f"{pc}[t{ti}p{i}]")
            labels.append(f"[t{ti}p{i}]")
        fc.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[T{ti}]")
        layers.append(f"[T{ti}]")
    if not layers:
        fc.append(f"color=c=black:s={W}x{H}:r={fps}:d={D:.3f},format=rgba[T0]")
        layers = ["[T0]"]
    base = layers[0]
    for i, lay in enumerate(layers[1:]):
        fc.append(f"{base}{lay}overlay=0:0:format=auto[L{i}]")
        base = f"[L{i}]"
    fc.append(f"{base}null[vout]")

    alabels = []
    for tr in tl.audio:
        for c in tr:
            if c.enabled and media.probe(c.path)["channels"]:
                k = add_input(c)
                fc.append(f"[{k}:a]asetpts=PTS-STARTPTS,aresample=48000,adelay={int(round(c.start * 1000))}:all=1[a{k}]")
                alabels.append(f"[a{k}]")
    if alabels:
        fc.append(f"{''.join(alabels)}amix=inputs={len(alabels)}:normalize=0:duration=longest,"
                  f"apad,atrim=0:{D:.3f}[aout]")
    else:
        fc.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{D:.3f}[aout]")
    return ins, ";\n".join(fc)


def run(tl, p, ctx):
    W, H = int(p["width"]) or tl.width, int(p["height"]) or tl.height
    fps = round(float(p["fps"]) or tl.fps, 3)
    alpha = p["format"] == "mov_alpha"
    out = Path(p["output"]) if p["output"] else ctx.out_dir / f"{tl.name}.{'mov' if alpha else 'mp4'}"
    ins, graph = build(tl, W, H, fps, alpha)
    script = ctx.out_dir / f".{out.stem}.filter.txt"
    script.write_text(graph, "utf-8")
    common = ["ffmpeg", "-y", "-hide_banner", "-v", "error", *ins, "-filter_complex_script", str(script),
              "-map", "[vout]", "-map", "[aout]", "-r", str(fps)]
    encs = ["prores_ks"] if alpha else candidates(p["codec"], W * H > 1920 * 1080)
    if not alpha and "libx264" not in encs:
        encs.append("libx264")
    err = ""
    for enc in encs:
        v = (["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"] if alpha
             else video_args(enc, p["quality"], W, H, fps))
        a = ["-c:a", "pcm_s16le"] if alpha else ["-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
        r = subprocess.run(common + v + a + [str(out)], capture_output=True, text=True)
        if r.returncode == 0:
            script.unlink(missing_ok=True)
            return dict(timeline=None, files=[str(out)],
                        report=dict(output=str(out), encoder=enc, size=f"{W}x{H}", fps=fps))
        err = r.stderr[-1500:]  # a GPU encoder can be listed yet unusable on this machine → try the next
    raise RuntimeError(f"render failed: {err}")
