"""Silences: loudness-based dead-air removal (AutoCut Silences equivalent)."""
from __future__ import annotations

import numpy as np

from . import media
from .timeline import fmt_time, keep, merge, parse_tracks, split

# (remove silences longer than, keep talks longer than, margin before, margin after) seconds
PRESETS = {"calm": (1.0, .30, .25, .30), "measured": (.7, .25, .2, .25), "paced": (.5, .2, .15, .2),
           "energetic": (.35, .15, .1, .12), "jumpy": (.2, .1, .05, .08)}
DEFAULTS = dict(detection="loudness", threshold_db="auto", preset="custom", remove_silences_longer_than=0.3, keep_talks_longer_than=0.2,
                margin_before=0.2, margin_after=0.2, tracks="1", mode="remove", transition="none",
                transition_length=0.25, preview=False)
CHOICES = dict(detection=["loudness", "ai_vad", "hybrid"], preset=["custom", *PRESETS], mode=["remove", "keep", "mute", "keep_spaces"],
               transition=["none", "j_cut", "l_cut", "constant_power"])
HELP = ("Detect dead air on the chosen audio tracks (1-based) and cut it. threshold_db: number or 'auto'. "
        "detection: loudness, ai_vad (Silero speech model) or hybrid (both must agree). "
        "mode: remove (ripple), keep (cut only), mute, keep_spaces (remove without closing gaps).")


def timeline_db(tl, tracks):
    """Record-time loudness (dB per media.HOP) of the given audio tracks, max across tracks."""
    hop = media.HOP
    n = int(tl.duration / hop) + 2
    out = np.full(n, -120.0, np.float32)
    for ti in tracks:
        for c in (tl.audio[ti] if ti < len(tl.audio) else []):
            if not c.enabled:
                continue
            env = media.envelope(c.path)
            a = int(round(c.src_in / hop))
            seg = env[a:a + int(round(c.dur / hop))]
            s = int(round(c.start / hop))
            seg = seg[:max(0, n - s)]
            np.maximum(out[s:s + len(seg)], seg, out=out[s:s + len(seg)])
    return out


def auto_threshold(db):
    v = np.maximum(db, -90.0)  # digital silence counts as a very low floor, not as missing data
    if len(v) < 10:
        return -40.0
    lo, hi = np.percentile(v, [10, 90])
    if hi - lo < 6:  # no dynamics (all speech or all noise): sit well below the level
        return float(hi - 12)
    return float(np.clip(lo + 0.3 * (hi - lo), -60, -12))


def runs(mask, hop=media.HOP):
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return [(s * hop, e * hop) for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0])]


def speech_ranges(db, thr, min_silence, min_talk, pad_before, pad_after, hop=media.HOP):
    total = len(db) * hop
    talks = [r for r in merge(runs(db > thr, hop), gap=min_silence) if r[1] - r[0] >= min_talk]
    return merge([(max(0.0, a - pad_before), min(total, b + pad_after)) for a, b in talks])


def vad_file(path):
    """Silero VAD (bundled with faster-whisper) speech spans of a whole file, seconds. Cached."""
    import json
    f = media.CACHE / f"{media.cache_key(path, 'vad')}.json"
    if f.exists():
        return json.loads(f.read_text())
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(media.load_audio(path), VadOptions(min_silence_duration_ms=100, speech_pad_ms=0))
    spans = [(t["start"] / media.SR, t["end"] / media.SR) for t in ts]
    media.CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(spans))
    return spans


def vad_ranges(tl, tracks, min_silence, min_talk, pad_before, pad_after):
    spans = []
    for ti in tracks:
        for c in (tl.audio[ti] if ti < len(tl.audio) else []):
            if c.enabled:
                spans += [(c.start + max(a, c.src_in) - c.src_in, c.start + min(b, c.src_out) - c.src_in)
                          for a, b in vad_file(c.path) if b > c.src_in and a < c.src_out]
    talks = [r for r in merge(spans, gap=min_silence) if r[1] - r[0] >= min_talk]
    return merge([(max(0.0, a - pad_before), min(tl.duration, b + pad_after)) for a, b in talks])


def peaks(db, min_gap=1.0, k=1.0, hop=media.HOP):
    """Loudness peaks ('emotion' proxy): local maxima of the smoothed envelope above mean + k*std."""
    w = max(1, int(0.3 / hop))
    sm = np.convolve(db, np.ones(w) / w, mode="same")
    voiced = sm[sm > -60]
    if len(voiced) < 10:
        return []
    thr = voiced.mean() + k * voiced.std()
    g = max(1, int(min_gap / hop))
    out = []
    for i in np.where(sm > thr)[0]:
        lo, hi = max(0, i - g // 2), i + g // 2 + 1
        if sm[i] == sm[lo:hi].max() and (not out or i * hop - out[-1] >= min_gap):
            out.append(i * hop)
    return out


def jl_cut(tl, off, kind):
    """Extend audio into the neighbouring cut (J: early in, L: late out); alternate tracks to avoid overlap."""
    new = []
    for tr in tl.audio:
        a, b = [], []
        for i, c in enumerate(sorted(tr, key=lambda c: c.start)):
            prev = tr[i - 1] if i else None
            if kind == "j_cut" and prev:
                o = min(off, c.src_in, prev.dur * 0.9)
                c.src_in -= o
                c.start -= o
            elif kind == "l_cut" and i < len(tr) - 1:
                o = min(off, max(0.0, media.probe(c.path)["duration"] - c.src_out), tr[i + 1].dur * 0.9)
                c.src_out += o
            (a if i % 2 == 0 else b).append(c)
        new += [a, b]
    tl.audio = new
    return tl


def settings(p):
    if p["preset"] in PRESETS:
        return PRESETS[p["preset"]]
    return (float(p["remove_silences_longer_than"]), float(p["keep_talks_longer_than"]),
            float(p["margin_before"]), float(p["margin_after"]))


def run(tl, p, ctx):
    tracks = parse_tracks(p["tracks"])
    if p["detection"] == "ai_vad":
        thr, ranges = None, vad_ranges(tl, tracks, *settings(p))
    else:
        db = timeline_db(tl, tracks)
        thr = auto_threshold(db) if str(p["threshold_db"]).strip().lower() == "auto" else float(p["threshold_db"])
        ranges = speech_ranges(db, thr, *settings(p))
        if p["detection"] == "hybrid":  # loud AND voiced: drops music/noise that loudness alone keeps
            vad = vad_ranges(tl, tracks, *settings(p))
            ranges = [(max(a, c), min(b, d)) for a, b in ranges for c, d in vad if min(b, d) > max(a, c)]
    ranges = [(a, min(b, tl.duration)) for a, b in ranges if a < tl.duration]
    kept = float(sum(b - a for a, b in ranges))
    report = dict(threshold_db=round(thr, 1) if thr is not None else "ai_vad", segments=len(ranges), duration_before=round(tl.duration, 2),
                  duration_after=round(kept, 2), removed=round(tl.duration - kept, 2))
    if p["preview"]:
        return dict(report=report, items=[dict(id=i, label=f"speech {fmt_time(a)}–{fmt_time(b)}", start=a, end=b)
                                          for i, (a, b) in enumerate(ranges)])
    if str(p.get("items", "")).strip():  # review step: keep only the speech segments the editor ticked
        keep_ids = {int(x) for x in str(p["items"]).split(",") if x.strip().lstrip("-").isdigit()}
        ranges = [r for i, r in enumerate(ranges) if i in keep_ids]
    cuts = sorted({t for r in ranges for t in r})
    mode = p["mode"]
    if mode == "remove":
        out = keep(tl, ranges)
    elif mode == "keep_spaces":
        out = keep(tl, ranges, ripple=False)
    elif mode == "keep":
        out = split(tl, cuts)
    else:  # mute: picture untouched (cut at boundaries), audio only during speech
        out = keep(split(tl, cuts, kinds=("video",)), ranges, ripple=False, kinds=("audio",))
    if p["transition"] in ("j_cut", "l_cut") and mode == "remove":
        out = jl_cut(out, float(p["transition_length"]), p["transition"])
    elif p["transition"] == "constant_power":
        out.transitions = sorted({c.start for tr in out.audio for c in tr if c.start > 0})
        out.transition_dur = float(p["transition_length"])
    out.name = f"{tl.name} - Silences"
    return dict(timeline=out, report=report)
