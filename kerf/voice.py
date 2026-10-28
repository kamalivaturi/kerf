"""Voiceover: offline text-to-speech with the open Kokoro v1.0 model (Apache-2.0), run through sherpa-onnx.

54 voices in 9 languages at 24 kHz on the CPU; nothing is uploaded. The int8 model (132 MB) downloads once to
~/.kerf/models the first time a voiceover is made.
"""
from __future__ import annotations

import copy
import json
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import media, settings
from .timeline import Clip, add_track

MODEL = "kokoro-int8-multi-lang-v1_0"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{MODEL}.tar.bz2"
# Speaker IDs in the model's own order (its id2speaker metadata). Prefix: language, then f(emale) / m(ale).
VOICES = ("af_alloy,af_aoede,af_bella,af_heart,af_jessica,af_kore,af_nicole,af_nova,af_river,af_sarah,af_sky,am_adam,"
          "am_echo,am_eric,am_fenrir,am_liam,am_michael,am_onyx,am_puck,am_santa,bf_alice,bf_emma,bf_isabella,bf_lily,"
          "bm_daniel,bm_fable,bm_george,bm_lewis,ef_dora,em_alex,ff_siwis,hf_alpha,hf_beta,hm_omega,hm_psi,if_sara,"
          "im_nicola,jf_alpha,jf_gongitsune,jf_nezumi,jf_tebukuro,jm_kumo,pf_dora,pm_alex,pm_santa,zf_xiaobei,zf_xiaoni,"
          "zf_xiaoxiao,zf_xiaoyi,zm_yunjian,zm_yunxi,zm_yunxia,zm_yunyang,em_santa").split(",")
LANGS = dict(a="US English", b="UK English", e="Spanish", f="French", h="Hindi", i="Italian", j="Japanese",
             p="Portuguese", z="Mandarin")

VOICE_DEFAULTS = dict(text="", engine="kokoro", voice="af_heart", server_voice="default", server_model="", style="",
                      speed=1.0, at="playhead", volume_db=0.0)
VOICE_CHOICES = dict(engine=["kokoro", "speech server"], voice=VOICES, at=["playhead", "start"])
VOICE_HELP = ("Speaks your script with a natural offline voice and adds it on a new audio track, at the playhead or "
              "the start. 54 voices: af_/am_ US English, bf_/bm_ UK English, ef_/em_ Spanish, ff_ French, hf_/hm_ "
              "Hindi, if_/im_ Italian, jf_/jm_ Japanese, pf_/pm_ Portuguese, zf_/zm_ Mandarin (f = female, m = male). "
              "speed 0.5 to 2. The first voiceover downloads the voice model (132 MB) once. "
              "engine 'speech server' uses an OpenAI-compatible speech API instead (Settings > Speech server): "
              "VoiceStudio on this computer by default, so server_voice can be one of your cloned voice profiles; "
              "style passes a delivery hint such as 'calm and warm'; server_model is only needed by OpenAI (tts-1).")


def voice_label(v):
    return f"{v[3:].replace('_', ' ').title()} ({LANGS[v[0]]}, {'female' if v[1] == 'f' else 'male'})"


_download = threading.Lock()  # the engine serves requests on threads: one download at a time


def _extract(tar, to):
    try:
        tar.extractall(to, filter="data")  # refuses paths outside the folder and links
    except TypeError:  # Python before 3.10.12 / 3.11.4 has no filter=: check the members ourselves
        safe = [m for m in tar.getmembers() if (m.isfile() or m.isdir()) and not m.name.startswith(("/", "\\"))
                and ".." not in Path(m.name).parts]
        tar.extractall(to, members=safe)


def model_dir():
    d = media.HOME / "models" / MODEL
    with _download:
        if not (d / "model.int8.onnx").exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            tmp, part = d.parent / f"{MODEL}.tar.bz2.part", d.parent / f"{MODEL}.extracting"
            shutil.rmtree(part, ignore_errors=True)
            urllib.request.urlretrieve(URL, tmp)
            with tarfile.open(tmp) as tar:
                _extract(tar, part)
            shutil.rmtree(d, ignore_errors=True)  # a half-extracted model from an older version
            (part / MODEL).rename(d)  # appears only once complete, so an interrupted install retries
            shutil.rmtree(part, ignore_errors=True)
            tmp.unlink()
    return d


@lru_cache(maxsize=1)
def _tts():
    try:
        import sherpa_onnx
    except ImportError as e:
        raise RuntimeError("Voiceover needs the sherpa-onnx package: pip install sherpa-onnx") from e
    d = model_dir()
    kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(d / "model.int8.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
        data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
        lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}")
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(kokoro=kokoro)))


def speak(text, out, voice="af_heart", speed=1.0, volume_db=0.0):
    """Writes `text` spoken by `voice` to the WAV file `out`; returns its length in seconds."""
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("Type the words to speak in 'text'")
    if voice not in VOICES:
        raise ValueError(f"Unknown voice '{voice}'. Pick one of: {', '.join(VOICES)}")
    audio = _tts().generate(text, sid=VOICES.index(voice), speed=min(2.0, max(0.5, float(speed))))
    samples = np.asarray(audio.samples, dtype=np.float32) * 10 ** (float(volume_db) / 20)
    if not samples.size:
        raise ValueError("The voice produced no audio for that text")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return samples.size / audio.sample_rate


def speak_server(text, out, voice="default", speed=1.0, style="", model="", volume_db=0.0):
    """Same as speak(), through an OpenAI-compatible POST {speech_server_url}/audio/speech (VoiceStudio, OpenAI...)."""
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("Type the words to speak in 'text'")
    base = str(settings.get("speech_server_url") or "").rstrip("/")
    if not base:
        raise ValueError("Set the Speech server in Settings (VoiceStudio: http://localhost:3900/v1)")
    body = dict(input=text, voice=voice or "default", response_format="wav", speed=min(4.0, max(0.25, float(speed))))
    if model:
        body["model"] = model
    if style:
        body["instructions"] = style
    headers = {"Content-Type": "application/json"}
    if settings.get("speech_api_key"):
        headers["Authorization"] = f"Bearer {settings.get('speech_api_key')}"
    req = urllib.request.Request(f"{base}/audio/speech", json.dumps(body).encode(), headers)
    raw = out.with_name(out.stem + " (server).wav")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            raw.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"The speech server refused it ({e.code}): {e.read().decode('utf-8', 'replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Can't reach the speech server at {base}. Start VoiceStudio (or change Speech server in "
                         f"Settings), then try again.") from e
    media.ffmpeg("-y", "-i", raw, "-af", f"volume={float(volume_db)}dB", "-ac", "1", out)  # clean header, gain
    raw.unlink(missing_ok=True)
    return media.probe(str(out))["duration"]


def voiceover(tl, p, ctx):
    out = ctx.out_dir / f"{tl.name} - voiceover {time.strftime('%Y%m%d-%H%M%S')}.wav"
    if p["engine"] == "speech server":
        seconds = speak_server(p["text"], out, p["server_voice"], p["speed"], p["style"], p["server_model"], p["volume_db"])
    else:
        seconds = speak(p["text"], out, p["voice"], p["speed"], p["volume_db"])
    at = tl.playhead if p["at"] == "playhead" else 0.0
    res = copy.deepcopy(tl)
    add_track(res, "audio", [Clip(str(out), 0.0, seconds, at)])
    res.name = f"{tl.name} - Voiceover"
    who = p["server_voice"] if p["engine"] == "speech server" else voice_label(p["voice"])
    return dict(timeline=res, files=[str(out)], report=dict(voice=who, seconds=round(seconds, 2), at=round(at, 2)))
