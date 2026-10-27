"""Voiceover: offline text-to-speech with the open Kokoro v1.0 model (Apache-2.0), run through sherpa-onnx.

54 voices in 9 languages at 24 kHz on the CPU; nothing is uploaded. The int8 model (132 MB) downloads once to
~/.kerf/models the first time a voiceover is made.
"""
from __future__ import annotations

import copy
import tarfile
import time
import urllib.request
import wave
from functools import lru_cache

import numpy as np

from . import media
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

VOICE_DEFAULTS = dict(text="", voice="af_heart", speed=1.0, at="playhead", volume_db=0.0)
VOICE_CHOICES = dict(voice=VOICES, at=["playhead", "start"])
VOICE_HELP = ("Speaks your script with a natural offline voice and adds it on a new audio track, at the playhead or "
              "the start. 54 voices: af_/am_ US English, bf_/bm_ UK English, ef_/em_ Spanish, ff_ French, hf_/hm_ "
              "Hindi, if_/im_ Italian, jf_/jm_ Japanese, pf_/pm_ Portuguese, zf_/zm_ Mandarin (f = female, m = male). "
              "speed 0.5 to 2. The first voiceover downloads the voice model (132 MB) once.")


def voice_label(v):
    return f"{v[3:].replace('_', ' ').title()} ({LANGS[v[0]]}, {'female' if v[1] == 'f' else 'male'})"


def model_dir():
    d = media.HOME / "models" / MODEL
    if not (d / "model.int8.onnx").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        tmp = d.parent / f"{MODEL}.tar.bz2.part"
        urllib.request.urlretrieve(URL, tmp)
        with tarfile.open(tmp) as tar:
            tar.extractall(d.parent, filter="data")  # "data" refuses paths outside the folder and links
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


def voiceover(tl, p, ctx):
    out = ctx.out_dir / f"{tl.name} - voiceover {time.strftime('%Y%m%d-%H%M%S')}.wav"
    seconds = speak(p["text"], out, p["voice"], p["speed"], p["volume_db"])
    at = tl.playhead if p["at"] == "playhead" else 0.0
    res = copy.deepcopy(tl)
    add_track(res, "audio", [Clip(str(out), 0.0, seconds, at)])
    res.name = f"{tl.name} - Voiceover"
    return dict(timeline=res, files=[str(out)],
                report=dict(voice=voice_label(p["voice"]), seconds=round(seconds, 2), at=round(at, 2)))
