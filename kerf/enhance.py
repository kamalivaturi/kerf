"""Audio enhancement: ElevenLabs Voice Isolator (API key) or a free local FFmpeg chain
(high-pass, spectral denoise for traffic/crowd/hiss, de-click, EBU R128 loudness)."""
from __future__ import annotations

import copy
import urllib.request
import uuid
from pathlib import Path

from . import media, settings
from .timeline import parse_tracks

ENHANCE_DEFAULTS = dict(provider="local", strength="medium", tracks="1", loudness=-14.0, highpass=80,
                        declick=False, normalize=True)
ENHANCE_CHOICES = dict(provider=["local", "elevenlabs"], strength=["light", "medium", "strong"])
ENHANCE_HELP = ("Cleans dialogue on the chosen audio tracks and swaps in the enhanced audio. elevenlabs = studio "
                "voice isolation (needs an ElevenLabs API key in AI settings); local = free FFmpeg denoise. "
                "loudness in LUFS (-14 YouTube/Spotify, -16 podcasts).")
NR = {"light": 6, "medium": 12, "strong": 24}
ISOLATE_URL = "https://api.elevenlabs.io/v1/audio-isolation"


def local_chain(p):
    af = [f"highpass=f={int(p['highpass'])}", f"afftdn=nr={NR[p['strength']]}:nf=-40:tn=1"]
    if p["strength"] == "strong":
        af.append("anlmdn=s=7")  # extra broadband hiss / crowd suppression
    if p["declick"]:
        af.append("adeclick")
    return af


def elevenlabs(path, key, out):
    tmp = out.with_suffix(".src.mp3")
    media.ffmpeg("-i", path, "-vn", "-ac", "1", "-b:a", "192k", tmp)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{tmp.name}\"\r\n"
            "Content-Type: audio/mpeg\r\n\r\n").encode() + tmp.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(ISOLATE_URL, body, {"xi-api-key": key,
                                                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
    iso = out.with_suffix(".iso.mp3")
    with urllib.request.urlopen(req, timeout=1800) as r:
        iso.write_bytes(r.read())
    tmp.unlink(missing_ok=True)
    return iso


def enhance_file(path, p, out_dir):
    out = out_dir / "enhanced" / f"{Path(path).stem}_{media.cache_key(path, sorted(p.items()))[:8]}.wav"
    if out.exists():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    src, temp, af = path, None, []
    if p["provider"] == "elevenlabs":
        key = settings.get("elevenlabs_api_key")
        if not key:
            raise RuntimeError("ElevenLabs needs an API key: add it in Kerf AI settings")
        src = temp = elevenlabs(path, key, out)
    else:
        af = local_chain(p)
    if p["normalize"]:
        af.append(f"loudnorm=I={float(p['loudness'])}:TP=-1.5:LRA=11")
    media.ffmpeg("-i", src, "-vn", *(["-af", ",".join(af)] if af else []), "-ar", "48000", "-ac", "2", out)
    if temp is not None:  # only ever delete our own intermediate file, never the user's media
        temp.unlink(missing_ok=True)
    return str(out)


def run(tl, p, ctx):
    out = copy.deepcopy(tl)
    done = {}
    for ti in parse_tracks(p["tracks"]):
        for c in (out.audio[ti] if ti < len(out.audio) else []):
            if c.path not in done:
                done[c.path] = enhance_file(c.path, p, ctx.out_dir)
            c.path = done[c.path]  # same timing: enhanced file starts at source t=0
    out.name = f"{tl.name} - Enhanced"
    return dict(timeline=out, files=list(done.values()), report=dict(files=len(done), provider=p["provider"]))
