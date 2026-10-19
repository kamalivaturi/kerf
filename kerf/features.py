"""Feature registry: built-ins, drop-in plugins, presets, typed params, entitlement check, XML output.

Add a feature without touching Kerf: drop a .py file in ~/.kerf/plugins/ that defines

    FEATURES = [dict(name="myfeature", title="My Feature", run=my_run, defaults={...},
                     choices={...}, help="...", tier="free", review=False, presets={})]

where my_run(timeline, params, ctx) returns {"timeline": Timeline | None, "report": {...}, ...}.
"""
from __future__ import annotations

import importlib.util
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import ai, broll, camera, captions, download, enhance, license, media, motion, render, silence, sound, speech
from .timeline import Timeline, to_xmeml


@dataclass
class Feature:
    name: str
    title: str
    run: callable
    defaults: dict
    choices: dict = field(default_factory=dict)
    help: str = ""
    tier: str = "free"        # "free" | "pro"; enforced by license.py (everything free by default)
    review: bool = False      # supports preview → pick items → apply
    presets: dict = field(default_factory=dict)  # built-in named presets {name: partial params}
    group: str = "Edit"
    needs_timeline: bool = True  # False: runs without an open sequence (e.g. downloads)


@dataclass
class Ctx:
    out_dir: Path


REGISTRY: dict[str, Feature] = {}


def register(f):
    REGISTRY[f.name] = f
    return f


for _f in [
    Feature("silences", "Silences", silence.run, silence.DEFAULTS, silence.CHOICES, silence.HELP, review=True,
            presets={k.title(): dict(preset=k) for k in silence.PRESETS}, group="Cut"),
    Feature("transcript", "Transcript & language", speech.transcript, speech.TRANSCRIPT_DEFAULTS, {},
            speech.TRANSCRIPT_HELP, review=True, group="Cut"),
    Feature("repeat", "Repeat (bad takes)", speech.repeat, speech.REPEAT_DEFAULTS, {}, speech.REPEAT_HELP,
            review=True, group="Cut"),
    Feature("profanity", "Profanity Filter", speech.profanity, speech.PROFANITY_DEFAULTS, speech.PROFANITY_CHOICES,
            speech.PROFANITY_HELP, review=True, group="Cut"),
    Feature("captions", "Captions", captions.run, captions.CAPTION_DEFAULTS, captions.CAPTION_CHOICES,
            captions.CAPTION_HELP, presets=captions.BUILTIN_PRESETS, group="Style"),
    Feature("zoom", "AutoZoom", motion.zoom, motion.ZOOM_DEFAULTS, motion.ZOOM_CHOICES, motion.ZOOM_HELP,
            presets={k.replace("_", " ").title(): dict(rhythm=k) for k in motion.RHYTHM}, group="Style"),
    Feature("broll", "B-Rolls", broll.run, broll.BROLL_DEFAULTS, broll.BROLL_CHOICES, broll.BROLL_HELP,
            review=True, group="Style"),
    Feature("podcast", "Podcast multicam", camera.podcast, camera.PODCAST_DEFAULTS, camera.PODCAST_CHOICES,
            camera.PODCAST_HELP, presets={k.title(): dict(preset=k) for k in camera.SHOT_PRESETS}, group="Multicam"),
    Feature("angles", "Angles", camera.angles, camera.ANGLES_DEFAULTS, camera.ANGLES_CHOICES, camera.ANGLES_HELP,
            group="Multicam"),
    Feature("viral", "Viral clips", speech.viral, speech.VIRAL_DEFAULTS, speech.VIRAL_CHOICES, speech.VIRAL_HELP,
            review=True, group="Repurpose"),
    Feature("resize", "Resize", motion.resize, motion.RESIZE_DEFAULTS, motion.RESIZE_CHOICES, motion.RESIZE_HELP,
            presets={"TikTok / Reels / Shorts": dict(format="9:16"), "Instagram feed": dict(format="4:5"),
                     "Square": dict(format="1:1")}, group="Repurpose"),
    Feature("chapters", "Chapters", speech.chapters, speech.CHAPTER_DEFAULTS, {}, speech.CHAPTER_HELP,
            group="Repurpose"),
    Feature("enhance", "Enhance Audio", enhance.run, enhance.ENHANCE_DEFAULTS, enhance.ENHANCE_CHOICES,
            enhance.ENHANCE_HELP, presets={"Podcast (-16 LUFS)": dict(loudness=-16.0), "Noisy street": dict(
                strength="strong"), "Studio isolation (ElevenLabs)": dict(provider="elevenlabs")}, group="Audio"),
    Feature("music", "Music (auto-duck)", sound.music, sound.MUSIC_DEFAULTS, {}, sound.MUSIC_HELP, group="Audio",
            presets={"Subtle bed": dict(volume_db=-20.0), "Upbeat, strong duck": dict(volume_db=-12.0, duck_amount=12.0)}),
    Feature("sfx", "Sound effects", sound.sfx, sound.SFX_DEFAULTS, sound.SFX_CHOICES, sound.SFX_HELP, group="Audio",
            presets={k.replace("_", " ").title(): dict(sound=k) for k in sound.SFX}),
    Feature("dub", "Translate & dub", sound.dub, sound.DUB_DEFAULTS, {}, sound.DUB_HELP, group="Audio"),
    Feature("beat_sync", "Beat edit (music video)", sound.beat_sync, sound.BEAT_DEFAULTS, {}, sound.BEAT_HELP,
            group="Repurpose", presets={"Every beat": dict(every=1), "Every 2 beats": dict(every=2),
                                        "Every bar (4)": dict(every=4)}),
    Feature("render", "Render / Export", render.run, render.RENDER_DEFAULTS, render.RENDER_CHOICES, render.RENDER_HELP,
            presets={"4K60 HEVC": dict(width=3840, height=2160, fps=60.0, codec="hevc"),
                     "Transparent overlay (ProRes 4444)": dict(format="mov_alpha"),
                     "Fast draft": dict(quality="draft")}, group="Export"),
    Feature("prompt_edit", "AI Prompt Edit", ai.prompt_edit, ai.PROMPT_DEFAULTS, ai.PROMPT_CHOICES, ai.PROMPT_HELP,
            review=True, group="AI"),
    Feature("pipeline", "Pipeline (macro)", ai.pipeline, ai.PIPELINE_DEFAULTS, {}, ai.PIPELINE_HELP, group="AI",
            presets={"Talking head: tighten + zoom + captions": dict(steps=json.dumps([
                {"feature": "silences", "params": {"preset": "paced"}}, {"feature": "repeat"},
                {"feature": "zoom"}, {"feature": "captions"}])),
                "Shorts factory": dict(steps=json.dumps([{"feature": "silences"}, {"feature": "viral"}])),
                "Recipe: TikTok talking head": dict(steps=json.dumps([
                    {"feature": "silences", "params": {"preset": "energetic"}}, {"feature": "repeat"},
                    {"feature": "zoom", "params": {"style": "snap_in", "rhythm": "energetic"}},
                    {"feature": "resize", "params": {"format": "9:16"}},
                    {"feature": "captions", "params": {"animation": "pop", "words_per_line": 2}},
                    {"feature": "sfx", "params": {"sound": "whoosh"}}])),
                "Recipe: YouTube vlog": dict(steps=json.dumps([
                    {"feature": "silences", "params": {"preset": "paced"}}, {"feature": "repeat"},
                    {"feature": "zoom", "params": {"style": "smooth"}}, {"feature": "chapters"}])),
                "Recipe: Podcast": dict(steps=json.dumps([
                    {"feature": "enhance", "params": {"loudness": -16.0}}, {"feature": "silences", "params": {"preset": "calm"}},
                    {"feature": "podcast"}, {"feature": "chapters"}])),
                "Recipe: Tutorial": dict(steps=json.dumps([
                    {"feature": "silences", "params": {"preset": "measured"}}, {"feature": "repeat"},
                    {"feature": "captions", "params": {"animation": "fade", "lines": 2, "words_per_line": 7}},
                    {"feature": "chapters"}])),
                "Recipe: Instagram reel": dict(steps=json.dumps([
                    {"feature": "silences", "params": {"preset": "energetic"}},
                    {"feature": "resize", "params": {"format": "4:5"}},
                    {"feature": "captions", "params": {"animation": "bounce"}}])),
                "Recipe: Music video / event recap (set music in Beat edit)": dict(steps=json.dumps([
                    {"feature": "beat_sync", "params": {"every": 2}}, {"feature": "sfx", "params": {"sound": "riser",
                                                                                                    "on": "cuts", "min_gap": 8.0}}]))}),
    Feature("download", "Download (yt-dlp)", download.run, download.DOWNLOAD_DEFAULTS, download.DOWNLOAD_CHOICES,
            download.DOWNLOAD_HELP, review=True, group="Import", needs_timeline=False,
            presets={"Best MP4": dict(quality="best", container="mp4"), "1080p for editing": dict(quality="1080"),
                     "Audio only (WAV)": dict(audio_only=True, audio_format="wav"),
                     "Podcast → viral clips": dict(quality="1080", then="viral"),
                     "With subtitles": dict(subtitles=True, auto_subtitles=True, embed_subs=True)}),
]:
    register(_f)
download.DOWNLOAD_CHOICES["then"] = [""] + [n for n in REGISTRY if n not in ("download", "prompt_edit")]

PLUGIN_DIR = media.HOME / "plugins"
PRESET_DIR = media.HOME / "presets"
plugin_errors: dict[str, str] = {}


def load_plugins():
    for f in sorted(PLUGIN_DIR.glob("*.py")) if PLUGIN_DIR.exists() else []:
        try:
            spec = importlib.util.spec_from_file_location(f"kerf_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for d in getattr(mod, "FEATURES", []):
                register(Feature(**d))
        except Exception:
            plugin_errors[f.name] = traceback.format_exc(limit=3)


load_plugins()


# ---------------------------------------------------------------- params & presets

def coerce(defaults, params):
    """Cast incoming values (often strings from UI forms) to the type of each default."""
    out = dict(defaults)
    for k, v in (params or {}).items():
        if k == "items":
            out[k] = v
        elif k in defaults:
            d = defaults[k]
            if isinstance(d, bool):
                out[k] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(d, int):
                out[k] = int(float(v))
            elif isinstance(d, float):
                out[k] = float(v)
            else:
                out[k] = "" if v is None else str(v)
    out.setdefault("items", "")
    return out


def _safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip() or "untitled"


def list_presets(name):
    f = REGISTRY[name]
    user = sorted(p.stem for p in (PRESET_DIR / name).glob("*.json")) if (PRESET_DIR / name).exists() else []
    return dict(builtin=list(f.presets), user=user)


def get_preset(name, preset):
    f = REGISTRY[name]
    path = PRESET_DIR / name / f"{_safe(preset)}.json"
    raw = json.loads(path.read_text("utf-8")) if path.exists() else f.presets.get(preset)
    if raw is None:
        raise KeyError(f"no preset '{preset}' for {name}")
    return coerce(f.defaults, {**f.defaults, **raw})


def save_preset(name, preset, params):
    f = REGISTRY[name]
    p = {k: v for k, v in coerce(f.defaults, params).items() if k in f.defaults and k not in ("preview",)}
    (PRESET_DIR / name).mkdir(parents=True, exist_ok=True)
    (PRESET_DIR / name / f"{_safe(preset)}.json").write_text(json.dumps(p, indent=1), "utf-8")


def delete_preset(name, preset):
    (PRESET_DIR / name / f"{_safe(preset)}.json").unlink(missing_ok=True)


def export_presets(names=None):
    """Shareable bundle of the user's presets: {"kerf_presets": 1, "features": {feature: {preset: params}}}."""
    out = {}
    for n in names or REGISTRY:
        d = PRESET_DIR / n
        if n in REGISTRY and d.exists():
            out[n] = {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(d.glob("*.json"))}
    return dict(kerf_presets=1, features={k: v for k, v in out.items() if v})


def import_presets(bundle):
    """Inverse of export_presets; unknown features and keys are dropped by save_preset/coerce."""
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    done = [f"{n}/{p}" for n, ps in bundle.get("features", {}).items() if n in REGISTRY
            for p, params in ps.items() if save_preset(n, p, params) is None]
    return dict(imported=done)


def describe():
    return {n: dict(title=f.title, group=f.group, defaults=f.defaults, choices=f.choices, help=f.help, tier=f.tier,
                    review=f.review, entitled=license.entitled(f), presets=list_presets(n),
                    needs_timeline=f.needs_timeline)
            for n, f in REGISTRY.items()}


# ---------------------------------------------------------------- run

def run(name, timeline, params=None, out_dir=None):
    """timeline: dict (from an NLE panel) or a media file path."""
    if name not in REGISTRY:
        raise KeyError(f"unknown feature '{name}'. Available: {', '.join(REGISTRY)}")
    f = REGISTRY[name]
    license.check(f)
    p = coerce(f.defaults, params)
    if timeline is None:
        if f.needs_timeline:
            raise ValueError(f"{f.title} needs a timeline or media file")
        tl = None
    elif isinstance(timeline, dict):
        tl = Timeline.from_dict(timeline)
    else:
        tl = Timeline.from_media(str(timeline), media.probe)
    out = Path(out_dir or media.HOME / "output")
    out.mkdir(parents=True, exist_ok=True)
    res = f.run(tl, p, Ctx(out))
    tls = res.pop("timelines", None) or ([res["timeline"]] if res.get("timeline") else [])
    res.pop("timeline", None)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    res["xml"] = []
    for i, t in enumerate(tls):
        path = out / f"{_safe(t.name)} {stamp}{f'-{i + 1}' if len(tls) > 1 else ''}.xml"
        path.write_text(to_xmeml(t, media.probe), "utf-8")
        res["xml"].append(str(path))
    res["feature"] = name
    res["sequence_names"] = [t.name for t in tls]
    return res


def run_batch(name, paths, params=None, out_dir=None, render_after=False):
    """Run a feature over many media files (optionally rendering each result). Errors don't stop the batch."""
    results = []
    for path in paths:
        try:
            if render_after:
                steps = [dict(feature=name, params=params or {}), dict(feature="render", params={})]
                res = run("pipeline", str(path), dict(steps=json.dumps(steps)), out_dir)
            else:
                res = run(name, str(path), params, out_dir)
            results.append(dict(path=str(path), ok=True, xml=res["xml"], files=res.get("files", [])))
        except Exception as e:
            results.append(dict(path=str(path), ok=False, error=f"{type(e).__name__}: {e}"))
    return dict(results=results, ok=sum(r["ok"] for r in results), failed=sum(not r["ok"] for r in results))
