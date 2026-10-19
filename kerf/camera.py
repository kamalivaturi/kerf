"""Podcast (speaker-driven multicam) and Angles (single-voice camera switching)."""
from __future__ import annotations

import bisect
import random

import numpy as np

from . import media
from .silence import auto_threshold, peaks, speech_ranges, timeline_db
from .timeline import parse_tracks, split

PRIORITY_DB = {"normal": 0.0, "high": 3.0, "very_high": 6.0}
SHOT_PRESETS = {"calm": (4.0, 15.0), "paced": (2.5, 10.0), "energetic": (1.5, 6.0), "hyperactive": (0.8, 3.0)}

PODCAST_DEFAULTS = dict(speaker_tracks="1,2", priorities="normal,normal", cameras="1:1;2:2;3:1+2",
                        preset="paced", min_shot=0.0, max_shot=0.0, reaction_shots=True, unused="disable",
                        cut_audio=False, threshold_db="auto")
PODCAST_CHOICES = dict(preset=list(SHOT_PRESETS), unused=["disable", "delete"])
PODCAST_HELP = ("speaker_tracks: audio track of each speaker's mic (speaker 1 first). priorities: normal/high/very_high "
                "per speaker. cameras: 'videoTrack:speakers' joined by ';', e.g. '1:1;2:2;3:1+2' = V3 is a wide shot. "
                "min_shot/max_shot 0 = use preset.")

ANGLES_DEFAULTS = dict(voice_track="1", cameras="1,2", priorities="1,1", triggers="cuts,silences,emotion,transcript",
                       min_shot=2.0, unused="disable", cut_audio=False, language="", seed=7)
ANGLES_CHOICES = dict(unused=["disable", "delete"])
ANGLES_HELP = ("Switch between camera video tracks at trigger points. priorities bias how often each camera is "
               "chosen. Never picks the same camera twice in a row.")


def apply_switch(tl, segs, cam_tracks, unused, cut_audio):
    """segs [(a, b, video_track)] → each camera track cut at switches, inactive clips disabled or deleted."""
    times = [a for a, _, _ in segs[1:]]
    out = split(tl, times, kinds=("video",), tracks=set(cam_tracks))
    if cut_audio:
        out = split(out, times, kinds=("audio",))
    starts = [a for a, _, _ in segs]
    for ti in cam_tracks:
        if ti >= len(out.video):
            continue
        for c in out.video[ti]:
            cam = segs[max(0, bisect.bisect_right(starts, (c.start + c.end) / 2) - 1)][2]
            c.enabled = cam == ti
        if unused == "delete":
            out.video[ti] = [c for c in out.video[ti] if c.enabled]
    return out


def rle(values, hop):
    segs = []
    for i, v in enumerate(values):
        if segs and segs[-1][2] == v:
            segs[-1][1] = (i + 1) * hop
        else:
            segs.append([i * hop, (i + 1) * hop, v])
    return segs


def hysteresis(desired, hop, mn, confirm=0.5):
    """Switch only when the wanted camera has persisted `confirm` s and the current shot is ≥ mn s.
    The cut lands where the new speaker started when that still respects mn."""
    cur, start, cand, since, segs = desired[0], 0.0, None, 0.0, []
    for i, v in enumerate(desired):
        t = i * hop
        if v == cur:
            cand = None
            continue
        if v != cand:
            cand, since = v, t
        if t - since >= confirm and t - start >= mn:
            cut = since if since - start >= mn else t
            segs.append([start, cut, cur])
            start, cur, cand = cut, v, None
    segs.append([start, len(desired) * hop, cur])
    return segs


def enforce_min(segs, mn):
    out = []
    for a, b, v in segs:
        if out and (b - a < mn or out[-1][2] == v):
            out[-1][1] = b
        else:
            out.append([a, b, v])
    if len(out) > 1 and out[0][1] - out[0][0] < mn:  # short first shot absorbed by the next
        out[1][0] = out[0][0]
        out.pop(0)
    return out


def screen_time(segs):
    t = {}
    for a, b, v in segs:
        t[f"V{v + 1}"] = round(t.get(f"V{v + 1}", 0) + b - a, 1)
    return t


def podcast(tl, p, ctx):
    hop, step = 0.1, int(round(0.1 / media.HOP))
    spk = parse_tracks(p["speaker_tracks"])
    pri = [PRIORITY_DB.get(x.strip().lower().replace(" ", "_"), 0.0) for x in str(p["priorities"]).split(",")]
    pri += [0.0] * (len(spk) - len(pri))
    dbs, act = [], []
    for ti in spk:
        db = timeline_db(tl, [ti])
        n = len(db) // step
        db = db[:n * step].reshape(n, step).mean(axis=1)
        thr = auto_threshold(db) if str(p["threshold_db"]).lower() == "auto" else float(p["threshold_db"])
        dbs.append(db)
        act.append(db > thr)
    n = min(len(d) for d in dbs)
    dbs, act = np.stack([d[:n] for d in dbs]), np.stack([a[:n] for a in act])
    score = np.where(act, dbs + np.array(pri[:len(spk)])[:, None], -np.inf)
    who = np.where(act.any(axis=0), score.argmax(axis=0), -1)
    n_active = act.sum(axis=0)

    cams = {}
    for part in str(p["cameras"]).split(";"):
        if ":" in part:
            v, s = part.split(":")
            cams[int(v) - 1] = {int(x) - 1 for x in s.replace(",", "+").split("+") if x.strip()}
    wide = max(cams, key=lambda c: len(cams[c]))
    close = {s: min((c for c in cams if s in cams[c]), key=lambda c: len(cams[c]), default=wide)
             for s in range(len(spk))}

    mn, mx = SHOT_PRESETS.get(p["preset"], (2.5, 10.0))
    mn, mx = float(p["min_shot"]) or mn, float(p["max_shot"]) or mx
    desired, prev = [], wide
    for i in range(n):
        prev = wide if n_active[i] >= 2 else close[int(who[i])] if who[i] >= 0 else prev
        desired.append(prev)
    segs = hysteresis(desired, hop, mn)

    if p["reaction_shots"]:
        rng, out = random.Random(1), []
        for a, b, v in segs:
            while b - a > mx:
                alt = wide if v != wide else rng.choice([c for c in cams if c != wide] or [wide])
                cut = min(mn * 1.5, 3.0)
                out += [[a, a + mx - cut, v], [a + mx - cut, a + mx, alt]]
                a += mx
            out.append([a, b, v])
        segs = enforce_min(out, 0.01)
    segs[-1][1] = max(segs[-1][1], tl.duration)
    out = apply_switch(tl, segs, list(cams), p["unused"], p["cut_audio"])
    out.name = f"{tl.name} - Podcast"
    return dict(timeline=out, report=dict(shots=len(segs), screen_time=screen_time(segs)))


def angles(tl, p, ctx):
    voice = parse_tracks(p["voice_track"])
    cams = parse_tracks(p["cameras"])
    w = [float(x) for x in str(p["priorities"]).split(",") if x.strip()]
    w += [1.0] * (len(cams) - len(w))
    trig = {t.strip() for t in str(p["triggers"]).split(",")}
    db = timeline_db(tl, voice)
    thr = auto_threshold(db)
    cands = set()
    if "cuts" in trig:
        cands |= {c.start for ti in cams if ti < len(tl.video) for c in tl.video[ti] if c.start > 0}
    if "silences" in trig:
        cands |= {a for a, _ in speech_ranges(db, thr, 0.3, 0.2, 0.05, 0.0)}
    if "emotion" in trig:
        cands |= set(peaks(db, min_gap=1.5))
    if "transcript" in trig:
        from .speech import sentences, timeline_words
        cands |= {s["start"] for s in sentences(timeline_words(tl, voice[0], p["language"]))}

    rng = random.Random(int(p["seed"]))
    weight = dict(zip(cams, w))

    def pick(exclude):
        pool = [c for c in cams if c != exclude] or cams
        return rng.choices(pool, [weight[c] for c in pool])[0]

    mn, cur, last, segs = float(p["min_shot"]), pick(None), 0.0, []
    for t in sorted(cands):
        if t - last >= mn and tl.duration - t >= mn / 2:
            segs.append([last, t, cur])
            last, cur = t, pick(cur)
    segs.append([last, tl.duration, cur])
    out = apply_switch(tl, segs, cams, p["unused"], p["cut_audio"])
    out.name = f"{tl.name} - Angles"
    return dict(timeline=out, report=dict(shots=len(segs), screen_time=screen_time(segs)))
