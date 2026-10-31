"""Music & sound: background music with auto-ducking, sound effects on cuts (built-in synthesized pack or
your files), beat-synced cutting for music videos / recaps, and translate-and-dub (ElevenLabs)."""
from __future__ import annotations

import copy
import json
import random
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from . import media, settings
from .timeline import Clip, add_track, parse_tracks

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
SFX_DIR = media.HOME / "sfx"
# Original procedural effects (ffmpeg lavfi), so the pack is royalty-free and ships with Kerf.
SFX = {
    "whoosh": "anoisesrc=d=0.6:c=pink:a=0.6,highpass=f=400,lowpass=f=4000,afade=t=in:d=0.25,afade=t=out:st=0.3:d=0.3",
    "swoosh_up": "anoisesrc=d=0.5:c=white:a=0.4,bandpass=f=1800:w=1200,afade=t=in:d=0.4,afade=t=out:st=0.4:d=0.1",
    "pop": "sine=f=900:d=0.08,afade=t=out:d=0.08,volume=1.4",
    "click": "sine=f=2500:d=0.02,afade=t=out:d=0.02",
    "impact": "sine=f=55:d=0.7,afade=t=out:d=0.7,volume=2.2",
    "ding": "sine=f=1320:d=0.9,afade=t=out:d=0.9,aecho=0.8:0.6:40:0.3",
    "riser": "sine=f=200:d=1.2,vibrato=f=6:d=0.3,afade=t=in:d=1.1,volume=0.8",
}


def _audio_files(path_or_folder):
    if not path_or_folder:
        return []
    p = Path(path_or_folder)
    if p.is_file():
        return [p]
    return sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT) if p.exists() else []


def sfx_file(name):
    f = SFX_DIR / f"{name}.wav"
    if not f.exists():
        SFX_DIR.mkdir(parents=True, exist_ok=True)
        media.ffmpeg("-f", "lavfi", "-i", SFX[name], "-ar", "48000", "-ac", "2", f)
    return str(f)


def mixdown(tl, tracks, out):
    """Render the given audio tracks of a timeline to one WAV (record time)."""
    ins, labels, k = [], [], 0
    for ti in tracks:
        for c in (tl.audio[ti] if ti < len(tl.audio) else []):
            if c.enabled and media.probe(c.path)["channels"]:
                ins += ["-ss", f"{c.src_in:.3f}", "-t", f"{c.dur:.3f}", "-i", c.path]
                labels.append(f"[{k}:a]aresample=48000,adelay={int(c.start * 1000)}:all=1[a{k}]")
                k += 1
    if not k:
        raise ValueError("no audio on the chosen tracks")
    graph = ";".join(labels) + ";" + "".join(f"[a{i}]" for i in range(k)) + \
        f"amix=inputs={k}:normalize=0:duration=longest,apad,atrim=0:{tl.duration:.3f}[out]"
    media.ffmpeg(*ins, "-filter_complex", graph, "-map", "[out]", "-ac", "2", out)
    return str(out)


# ---------------------------------------------------------------- Music bed with ducking

MUSIC_DEFAULTS = dict(music="", volume_db=-16.0, duck=True, duck_amount=8.0, attack_ms=40, release_ms=450,
                      fade=1.5, voice_tracks="1", seed=0)
MUSIC_HELP = ("Adds background music under the edit and ducks it automatically while people talk. music = a file or a "
              "folder (a track is picked at random; seed fixes the pick). Use music you have the rights to.")


def music(tl, p, ctx):
    files = _audio_files(p["music"])
    if not files:
        raise ValueError("set 'music' to an audio file or a folder of music")
    track = random.Random(int(p["seed"])).choice(files) if len(files) > 1 else files[0]
    D, fade = tl.duration, float(p["fade"])
    out = ctx.out_dir / f"{tl.name} - music.wav"
    bed = (f"[0:a]aresample=48000,volume={float(p['volume_db'])}dB,atrim=0:{D:.3f},afade=t=in:d={fade},"
           f"afade=t=out:st={max(0, D - fade):.3f}:d={fade}")
    if p["duck"]:
        voice = mixdown(tl, parse_tracks(p["voice_tracks"]), ctx.out_dir / f"{tl.name} - voice.wav")
        ratio = max(1.5, float(p["duck_amount"]))
        graph = (f"{bed}[m];[1:a]aresample=48000[v];[m][v]sidechaincompress=threshold=0.02:ratio={ratio}:"
                 f"attack={int(p['attack_ms'])}:release={int(p['release_ms'])}[out]")
        media.ffmpeg("-stream_loop", "-1", "-i", track, "-i", voice, "-filter_complex", graph, "-map", "[out]",
                     "-t", f"{D:.3f}", out)
    else:
        media.ffmpeg("-stream_loop", "-1", "-i", track, "-filter_complex", bed + "[out]", "-map", "[out]", "-t", f"{D:.3f}", out)
    res = copy.deepcopy(tl)
    add_track(res, "audio", [Clip(str(out), 0.0, D, 0.0)])
    res.name = f"{tl.name} - Music"
    return dict(timeline=res, files=[str(out)], report=dict(track=Path(track).name, ducked=bool(p["duck"])))


# ---------------------------------------------------------------- Sound effects on cuts

SFX_DEFAULTS = dict(sound="whoosh", custom_sound="", on="cuts", min_gap=1.5, volume_db=-6.0, offset=-0.15,
                    video_track="1", randomize=False)
SFX_CHOICES = dict(sound=list(SFX), on=["cuts", "every_n_seconds"])
SFX_HELP = ("Places a sound effect on every cut (or every N seconds = min_gap). Built-in effects are synthesized by "
            "Kerf (royalty-free); custom_sound = your own file or folder. offset shifts the hit before the cut.")


def sfx(tl, p, ctx):
    pool = [str(f) for f in _audio_files(p["custom_sound"])] if p["custom_sound"] else [sfx_file(p["sound"])]
    if not pool:
        raise ValueError("custom_sound has no audio files")
    vt = (parse_tracks(p["video_track"]) or [0])[0]
    if p["on"] == "every_n_seconds":
        times = list(np.arange(float(p["min_gap"]), tl.duration, float(p["min_gap"])))
    else:
        times = sorted({c.start for tr in tl.video[vt:vt + 1] for c in tr if c.start > 0.05})
    picked, last = [], -1e9
    for t in times:
        if t - last >= float(p["min_gap"]):
            picked.append(t)
            last = t
    rng = random.Random(7)
    gain_dir = SFX_DIR / "gain"
    gain_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for t in picked:
        src = rng.choice(pool) if p["randomize"] else pool[0]
        g = gain_dir / f"{Path(src).stem}_{float(p['volume_db']):+.0f}dB.wav"
        if not g.exists():
            media.ffmpeg("-i", src, "-af", f"volume={float(p['volume_db'])}dB", "-ar", "48000", "-ac", "2", g)
        s = max(0.0, t + float(p["offset"]))
        clips.append(Clip(str(g), 0.0, min(media.probe(str(g))["duration"], tl.duration - s), s))
    res = copy.deepcopy(tl)
    add_track(res, "audio", clips)
    res.name = f"{tl.name} - SFX"
    return dict(timeline=res, report=dict(effects=len(clips)))


# ---------------------------------------------------------------- Beat-synced cutting

BEAT_DEFAULTS = dict(music="", every=1, min_shot=0.35, clips_track="1", offset=0.0, max_length=0.0)
BEAT_HELP = ("Music-video / recap edit: detects the beats in `music` and cuts your clips on them (every = cut every N "
             "beats). Clips on clips_track are used in order; the music goes on the audio track.")


def beats(path, sr=22050, hop=512):
    """Beat times (s) from spectral-flux onsets + autocorrelation tempo (70–180 BPM)."""
    a = media.load_audio(path, sr=sr)
    n = 2048
    frames = np.lib.stride_tricks.sliding_window_view(a, n)[::hop]  # a view: no copy yet
    flux, prev = [], None
    for i in range(0, len(frames), 4096):  # in blocks: the whole spectrogram of an hour-long mix is ~7 GB
        spec = np.log1p(np.abs(np.fft.rfft(frames[i:i + 4096] * np.hanning(n), axis=1)))
        flux.append(np.maximum(0, np.diff(spec if prev is None else np.vstack([prev, spec]), axis=0)).sum(axis=1))
        prev = spec[-1:]
    flux = np.concatenate(flux)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    ac = np.zeros(hi + 1)  # autocorrelation at the tempo lags only (a full one is O(n²))
    for lag in range(lo - 1, hi + 1):
        ac[lag] = flux[:len(flux) - lag] @ flux[lag:]
    k = lo + int(np.argmax(ac[lo:hi]))
    y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]  # parabolic interpolation: sub-frame tempo accuracy
    period = k + (0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) else 0.0)
    # refine on the peaks 16 and 256 beats away: a 0.1% tempo error drifts the last cut of an hour-long mix by 4 s
    for m in (16, 256):
        c = int(round(period * m))
        if c + 4 >= len(flux):
            break
        r = [flux[:len(flux) - lag] @ flux[lag:] for lag in range(c - 3, c + 4)]
        j = int(np.argmax(r[1:-1])) + 1
        y0, y1, y2 = r[j - 1:j + 2]
        period = (c - 3 + j + (0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) else 0.0)) / m
    grid = np.arange(int(len(flux) / period)) * period  # the phase whose beat grid lands on the most onsets
    phase = int(np.argmax([flux[(i + grid[grid < len(flux) - i]).astype(int)].sum() for i in range(k)]))
    n_beats = int((len(flux) - phase) / period) + 1
    lag = (hop + n / 2) / sr  # flux[i] is the change into frame i + 1, whose window is centred half a window in
    return [(phase + j * period) / fps + lag for j in range(n_beats)], round(60 * fps / period, 1)


def beat_sync(tl, p, ctx):
    files = _audio_files(p["music"])
    if not files:
        raise ValueError("set 'music' to the song to cut on")
    song = str(files[0])
    bt, bpm = beats(song)
    bt = [t + float(p["offset"]) for t in bt if t + float(p["offset"]) > 0][::max(1, int(p["every"]))]
    ct = (parse_tracks(p["clips_track"]) or [0])[0]
    src = [c for c in tl.video[ct] if c.enabled] if ct < len(tl.video) else []
    if not src:
        raise ValueError("no clips on clips_track")
    limit = float(p["max_length"]) or min(media.probe(song)["duration"], sum(c.dur for c in src))
    cuts = [t for t in bt if t < limit] + [limit]
    video, ci, pos, a = [], 0, src[0].src_in, 0.0
    for b in cuts:
        d = b - a
        if d < float(p["min_shot"]):
            continue
        c = src[ci % len(src)]
        if pos + d > c.src_out:  # take exhausted: move to the next clip
            ci += 1
            c = src[ci % len(src)]
            pos = c.src_in
        d = min(d, c.dur)
        video.append(Clip(c.path, pos, pos + d, a))
        pos += d
        a += d
    res = copy.deepcopy(tl)
    res.video, res.audio = [video], [[Clip(song, 0.0, a, 0.0)]]
    res.name = f"{tl.name} - Beat edit"
    return dict(timeline=res, report=dict(bpm=bpm, cuts=len(video)))


# ---------------------------------------------------------------- Translate & dub (ElevenLabs)

DUB_DEFAULTS = dict(target_language="es", source_language="auto", voice_tracks="1", keep_original=False)
DUB_HELP = ("Translates and dubs the speech into another language with ElevenLabs Dubbing (API key in Settings). "
            "The original voice is removed, or kept disabled with keep_original.")
DUB_URL = "https://api.elevenlabs.io/v1/dubbing"


def _multipart(fields, file_field, file_path):
    b = uuid.uuid4().hex
    body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in fields.items())
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{Path(file_path).name}\"\r\n"
             "Content-Type: audio/wav\r\n\r\n").encode() + Path(file_path).read_bytes() + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def dub(tl, p, ctx):
    key = settings.get("elevenlabs_api_key")
    if not key:
        raise ValueError("Dubbing needs an ElevenLabs API key: add it in Settings")
    voice = mixdown(tl, parse_tracks(p["voice_tracks"]), ctx.out_dir / f"{tl.name} - voice.wav")
    lang = p["target_language"]
    body, ctype = _multipart(dict(target_lang=lang, source_lang=p["source_language"]), "file", voice)
    did = json.loads(urllib.request.urlopen(urllib.request.Request(
        DUB_URL, body, {"xi-api-key": key, "Content-Type": ctype}), timeout=600).read())["dubbing_id"]
    for _ in range(360):  # up to 30 min
        st = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{DUB_URL}/{did}", headers={"xi-api-key": key}), timeout=60).read())
        if st.get("status") == "dubbed":
            break
        if st.get("status") == "failed":
            raise RuntimeError(f"ElevenLabs dubbing failed: {st.get('error', '')}")
        time.sleep(5)
    else:
        raise TimeoutError("dubbing did not finish in 30 minutes")
    out = ctx.out_dir / f"{tl.name} - {lang}.mp3"
    with urllib.request.urlopen(urllib.request.Request(f"{DUB_URL}/{did}/audio/{lang}", headers={"xi-api-key": key}),
                                timeout=600) as r:
        out.write_bytes(r.read())
    res = copy.deepcopy(tl)
    for ti in parse_tracks(p["voice_tracks"]):
        if ti < len(res.audio):
            for c in res.audio[ti]:
                c.enabled = False
            if not p["keep_original"]:
                res.audio[ti] = []
    add_track(res, "audio", [Clip(str(out), 0.0, min(tl.duration, media.probe(str(out))["duration"]), 0.0)])
    res.name = f"{tl.name} - {lang}"
    return dict(timeline=res, files=[str(out)], report=dict(language=lang, dubbing_id=did))
