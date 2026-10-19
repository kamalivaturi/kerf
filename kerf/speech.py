"""Transcript-driven features: transcription, Profanity, Repeat, Chapters, Viral."""
from __future__ import annotations

import difflib
import json
import math
import os
import re
from collections import Counter

import numpy as np

from . import llm, media
from .silence import peaks, timeline_db
from .timeline import Clip, add_track, fmt_time, invert, keep, merge

STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those i you he she we they me him her us them my your his our their mine yours what which who whom
do does did done have has had having not no yes just very really also too can could would should will shall may might
must there here when where why how all any both each few more most other some such only own same than up down out over
under again further once about into through during before after above below between um uh like okay ok yeah oh well
gonna wanna got get going go know think mean thing things right now way let lets because im youre dont thats its""".split())

_models = {}
_NO_CUDA = False  # set once a CUDA model fails to run (missing cuBLAS/cuDNN): stay on CPU


def norm(w):
    return re.sub(r"[^\w']", "", w.lower()).replace("'", "")


# Transcription profiles (use the name as `language`). Any ISO code also works ("hi", "ur", "ta"...).
# For best South Asian accuracy set Whisper model to "large-v3" or a fine-tuned CTranslate2 model in Settings.
PROFILES = {
    "hinglish": dict(language="hi", romanize=True,
                     prompt="Yeh conversation Hinglish mein hai, Hindi aur English mix. Okay so, let's start the video."),
    "hindi": dict(language="hi"), "urdu": dict(language="ur"), "bengali": dict(language="bn"),
    "tamil": dict(language="ta"), "telugu": dict(language="te"), "punjabi": dict(language="pa"),
    "marathi": dict(language="mr"), "gujarati": dict(language="gu"), "kannada": dict(language="kn"),
    "malayalam": dict(language="ml"), "nepali": dict(language="ne"), "sinhala": dict(language="si"),
    "tanglish": dict(language="ta", romanize=True, prompt="Tamil and English mixed conversation."),
    "benglish": dict(language="bn", romanize=True, multilingual=True, prompt="Bengali and English mixed conversation."),
    "taglish": dict(language="tl", multilingual=True, prompt="Tagalog at English, halo-halo. Okay, so let's start."),
    "spanglish": dict(language="es", multilingual=True, prompt="Spanish and English mixed, like, ¿sabes? Okay."),
    "manglish": dict(language="ms", multilingual=True, prompt="Malay and English mixed lah, okay can."),
    "arabizi": dict(language="ar", multilingual=True, prompt="Arabic and English mixed conversation."),
    "franglais": dict(language="fr", multilingual=True, prompt="Français et anglais mélangés, okay, let's go."),
    "konglish": dict(language="ko", multilingual=True, prompt="Korean and English mixed conversation."),
}
for _p in PROFILES.values():  # code-switching profiles detect the language per segment
    _p.setdefault("multilingual", bool(_p.get("romanize")))
VOCAB = media.HOME / "vocabulary.txt"


def languages():
    """Every language code Whisper knows, plus Kerf's named profiles (for UI pickers)."""
    from faster_whisper.tokenizer import _LANGUAGE_CODES
    return dict(profiles=sorted(PROFILES), codes=sorted(_LANGUAGE_CODES))


def vocabulary():
    return [w for w in VOCAB.read_text("utf-8").split("\n") if w.strip()] if VOCAB.exists() else []


def learn(words):
    """Add names/terms to the personal vocabulary used as Whisper hotwords (self-improving accuracy)."""
    cur = vocabulary()
    new = [w for w in dict.fromkeys(w.strip() for w in words) if w and w not in cur]
    if new:
        VOCAB.parent.mkdir(parents=True, exist_ok=True)
        VOCAB.write_text("\n".join(cur + new), "utf-8")
    return new


def _whisper(model=None):
    """(WhisperModel, name). 'auto' = large-v3-turbo on a CUDA GPU, small on CPU."""
    from . import settings
    import ctranslate2
    from faster_whisper import WhisperModel
    global _NO_CUDA
    dev = settings.get("whisper_device")
    gpu = dev != "cpu" and not _NO_CUDA and ctranslate2.get_cuda_device_count() > 0
    name = model or settings.get("whisper_model")
    if name in ("", "auto"):
        name = "large-v3-turbo" if gpu else "small"
    if name not in _models:
        m = None
        if gpu:  # a GPU without the CUDA 12 runtime (cuBLAS/cuDNN) only fails on first use: probe, then fall back
            try:
                m = WhisperModel(name, device="cuda", compute_type="float16")
                m.detect_language(np.zeros(16000, np.float32))
            except (RuntimeError, OSError):
                _NO_CUDA, m = True, None
                if model in (None, "", "auto") and settings.get("whisper_model") in ("", "auto"):
                    name = "small"
        _models[name] = m or WhisperModel(name, device="cpu", compute_type="int8")
    return _models[name], name


def detect_language(path, segments=4):
    """Language of a file from several 30 s windows: (code, confidence, top-5 [(code, p)])."""
    m, _ = _whisper()
    code, prob, probs = m.detect_language(media.load_audio(path), language_detection_segments=segments)
    return code, round(prob, 3), [(c, round(p, 3)) for c, p in probs[:5]]
DEVANAGARI = re.compile(r"[ऀ-෿]")  # Devanagari … Sinhala blocks


def romanize(words):
    """Native-script words → Latin (Hinglish style). indic_transliteration if installed, else the LLM, else as-is."""
    idx = [i for i, w in enumerate(words) if DEVANAGARI.search(w["w"])]
    if not idx:
        return words
    try:
        from indic_transliteration import detect, sanscript
        for i in idx:
            w = words[i]["w"]
            words[i]["w"] = re.sub(r"[.~^]", "", sanscript.transliterate(w, detect.detect(w), sanscript.ITRANS)).lower()
        return words
    except Exception:
        pass
    if llm.available():
        for k in range(0, len(idx), 200):
            chunk = idx[k:k + 200]
            out = llm.chat_json("Transliterate each word to casual Roman script as people type Hinglish on social "
                                "media. JSON array, same order and count.\n" +
                                json.dumps([words[i]["w"] for i in chunk], ensure_ascii=False))
            if isinstance(out, list) and len(out) == len(chunk):
                for i, t in zip(chunk, out):
                    words[i]["w"] = str(t)
    return words


def transcribe(path, language="", model=None):
    """Word-level transcript of a whole media file via faster-whisper (cached)."""
    from . import settings
    prof = PROFILES.get((language or "").strip().lower(), {})
    lang = prof.get("language", language or "")
    vocab = vocabulary()
    key = media.cache_key(path, "words", model or settings.get("whisper_model"), language or "", len(vocab))
    fixed = fixed_path(path, language)  # user corrections win over the model
    if fixed.exists():
        return json.loads(fixed.read_text("utf-8"))
    f = media.CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text("utf-8"))
    m, _ = _whisper(model)
    prompt = " ".join(x for x in (prof.get("prompt"), ", ".join(vocab[:80])) if x) or None
    segs, info = m.transcribe(
        str(path), language=lang or None, initial_prompt=prompt, hotwords=" ".join(vocab[:200]) or None,
        multilingual=prof.get("multilingual", False), word_timestamps=True, beam_size=5,
        condition_on_previous_text=False, hallucination_silence_threshold=2.0, language_detection_segments=4,
        vad_filter=True, vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=150))
    words = [dict(w=w.word.strip(), s=round(w.start, 3), e=round(w.end, 3))
             for s in segs for w in (s.words or []) if w.word.strip()]
    if prof.get("romanize"):
        words = romanize(words)
    out = dict(language=info.language, language_probability=round(info.language_probability, 3), words=words, key=key)
    media.CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out), "utf-8")
    return out


def timeline_words(tl, track=0, language=""):
    """Transcript of an audio track, mapped to record time."""
    out = []
    for c in (tl.audio[track] if track < len(tl.audio) else []):
        if not c.enabled:
            continue
        for w in transcribe(c.path, language)["words"]:
            if w["s"] >= c.src_in - 0.05 and w["e"] <= c.src_out + 0.05:
                out.append(dict(w=w["w"], s=c.start + max(w["s"], c.src_in) - c.src_in,
                                e=c.start + min(w["e"], c.src_out) - c.src_in))
    return sorted(out, key=lambda w: w["s"])


def sentences(words, gap=0.7, max_len=12.0):
    out, cur = [], []

    def flush():
        if cur:
            out.append(dict(start=cur[0]["s"], end=cur[-1]["e"], text=" ".join(w["w"] for w in cur), words=list(cur)))
            cur.clear()

    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > gap or cur[-1]["w"][-1:] in ".?!" or w["e"] - cur[0]["s"] > max_len):
            flush()
        cur.append(w)
    flush()
    return out


def selected(p, items):
    """Review step: params.items = list/'1,4,7' of item ids to apply. Empty = all."""
    ids = p.get("items")
    if ids in (None, "", []):
        return items
    if isinstance(ids, str):
        ids = [x for x in ids.split(",") if x.strip()]
    ids = {int(x) for x in ids}
    return [it for it in items if it["id"] in ids]


# ---------------------------------------------------------------- Transcript review / corrections

TRANSCRIPT_DEFAULTS = dict(language="", preview=False, items="", edits="")
TRANSCRIPT_HELP = ("Review the transcript sentence by sentence and fix anything misheard. Corrections are saved and used by "
                   "every feature (captions, repeat, chapters…), and new names/terms are learned as vocabulary so future "
                   "transcriptions get them right. Shows the detected language and its confidence.")


def fixed_path(path, language=""):
    """Corrected transcript for a file: independent of model/vocabulary so corrections are never orphaned."""
    return media.CACHE / f"{media.cache_key(path, 'fixed', language or '')}.json"


def _apply_fix(words, start, end, text):
    """Replace the words in [start, end] with `text`, spreading the original timing across the new tokens."""
    idx = [i for i, w in enumerate(words) if w["s"] >= start - 1e-3 and w["e"] <= end + 1e-3]
    toks = text.split()
    if not idx or not toks:
        return words, []
    a, b = words[idx[0]]["s"], words[idx[-1]]["e"]
    step = (b - a) / len(toks)
    fixed = [dict(w=t, s=round(a + i * step, 3), e=round(a + (i + 1) * step, 3)) for i, t in enumerate(toks)]
    old = {norm(words[i]["w"]) for i in idx}
    learned = [t.strip(".,!?;:\"'") for t in toks if norm(t) not in old and (t[:1].isupper() or any(c.isdigit() for c in t))]
    return words[:idx[0]] + fixed + words[idx[-1] + 1:], learned


def transcript(tl, p, ctx):
    track = 0
    sents = sentences(timeline_words(tl, track, p["language"]))
    clips = [c for c in tl.audio[track] if c.enabled] if tl.audio else []
    langs = {c.path: transcribe(c.path, p["language"]) for c in clips}
    lang = next(iter(langs.values()), {})
    report = dict(sentences=len(sents), language=lang.get("language"), confidence=lang.get("language_probability"),
                  vocabulary=len(vocabulary()))
    items = [dict(id=i, label=f"{fmt_time(s['start'])}  {s['text']}", text=s["text"], start=s["start"], end=s["end"],
                  editable=True) for i, s in enumerate(sents)]
    if p["preview"] or not p["edits"]:
        return dict(report=report, items=items)
    edits = json.loads(p["edits"]) if isinstance(p["edits"], str) else p["edits"]
    learned = []
    for c in clips:  # map each edited record-time sentence back onto its source file's transcript
        data = langs[c.path]
        words = data["words"]
        for sid, text in edits.items():
            s = items[int(sid)]
            if s["start"] < c.start or s["end"] > c.end + 0.05 or text.strip() == s["text"].strip():
                continue
            off = c.src_in - c.start
            words, new = _apply_fix(words, s["start"] + off, s["end"] + off, text)
            learned += new
        fixed = fixed_path(c.path, p["language"])
        fixed.write_text(json.dumps({**data, "words": words, "corrected": True}), "utf-8")
    report.update(corrected=len(edits), learned=learn(learned))
    return dict(report=report)


# ---------------------------------------------------------------- Profanity

DEFAULT_PROFANITY = ("fuck shit bitch asshole bastard dick cunt motherfucker bullshit pussy cock whore slut "
                     "dickhead wanker twat bollocks").split()
LIBRARY = media.HOME / "profanity.txt"
PROFANITY_DEFAULTS = dict(language="", action="beep", sound="", extra_words="", save_to_library=False,
                          padding=0.03, preview=False, items="")
PROFANITY_CHOICES = dict(action=["beep", "mute", "cut"])
PROFANITY_HELP = ("Finds swear words in the A1 transcript. extra_words: comma list; save_to_library stores them in "
                  "~/.kerf/profanity.txt. sound: path to a custom bleep (default 1 kHz tone).")


def library_words():
    return {norm(w) for w in LIBRARY.read_text("utf-8").split()} if LIBRARY.exists() else set()


def is_profane(w, lib):
    return w in lib or any(len(r) >= 4 and r in w for r in lib)


def make_beep(out_dir, dur=10.0):
    f = out_dir / "kerf_beep.wav"
    if not f.exists():
        media.ffmpeg("-f", "lavfi", "-i", f"sine=frequency=1000:duration={dur}", "-ar", "48000", "-ac", "2",
                     "-af", "volume=0.3", f)
    return str(f)


def profanity(tl, p, ctx):
    extra = {norm(w) for w in str(p["extra_words"]).split(",") if norm(w)}
    if extra and p["save_to_library"]:
        LIBRARY.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY.write_text("\n".join(sorted(library_words() | extra)), "utf-8")
    lib = {norm(w) for w in DEFAULT_PROFANITY} | library_words() | extra
    hits = [w for w in timeline_words(tl, 0, p["language"]) if norm(w["w"]) and is_profane(norm(w["w"]), lib)]
    items = [dict(id=i, label=f"{fmt_time(w['s'])}  {w['w']}", start=w["s"], end=w["e"]) for i, w in enumerate(hits)]
    report = dict(found=len(items))
    if p["preview"]:
        return dict(report=report, items=items)
    pad = float(p["padding"])
    ranges = merge([(it["start"] - pad, it["end"] + pad) for it in selected(p, items)])
    rest = invert(ranges, tl.duration)
    if p["action"] == "cut":
        out = keep(tl, rest)
    else:
        out = keep(tl, rest, ripple=False, kinds=("audio",))
        if p["action"] == "beep":
            snd = p["sound"] or make_beep(ctx.out_dir)
            sd = media.probe(snd)["duration"]
            add_track(out, "audio", [Clip(snd, 0.0, min(b - a, sd), a) for a, b in ranges])
    out.name = f"{tl.name} - Clean"
    report["censored"] = len(ranges)
    return dict(timeline=out, report=report)


# ---------------------------------------------------------------- Repeat

REPEAT_DEFAULTS = dict(language="", similarity=0.6, lookahead=3, remove_fillers=True,
                       fillers="um,uh,erm,er,hmm,uhm,ah,mm", padding=0.05, preview=False, items="")
REPEAT_HELP = ("Detects bad takes: a sentence whose opening words are repeated by one of the next `lookahead` "
               "sentences is removed (the last take is kept). Optional filler-word removal.")


def repeat(tl, p, ctx):
    sents = sentences(timeline_words(tl, 0, p["language"]))
    toks = [[norm(w["w"]) for w in s["words"] if norm(w["w"])] for s in sents]
    items = []
    for i, a in enumerate(toks):
        if len(a) < 2:
            continue
        for j in range(i + 1, min(len(sents), i + 1 + int(p["lookahead"]))):
            b = toks[j]
            k = min(len(a), len(b), 10)
            if k >= 2 and difflib.SequenceMatcher(None, a[:k], b[:k]).ratio() >= float(p["similarity"]):
                items.append(dict(id=len(items), kind="take", start=sents[i]["start"], end=sents[j]["start"],
                                  label=f"{fmt_time(sents[i]['start'])}  bad take: “{sents[i]['text'][:70]}”"))
                break
    if p["remove_fillers"]:
        fill = {norm(x) for x in str(p["fillers"]).split(",")}
        for s in sents:
            for w in s["words"]:
                if norm(w["w"]) in fill:
                    items.append(dict(id=len(items), kind="filler", start=w["s"], end=w["e"],
                                      label=f"{fmt_time(w['s'])}  filler: {w['w']}"))
    report = dict(takes=sum(i["kind"] == "take" for i in items), fillers=sum(i["kind"] == "filler" for i in items))
    if p["preview"]:
        return dict(report=report, items=items)
    pad = float(p["padding"])
    cut = merge([(it["start"] - (pad if it["kind"] == "filler" else 0), it["end"]) for it in selected(p, items)])
    out = keep(tl, invert(cut, tl.duration))
    out.name = f"{tl.name} - Repeat"
    report["removed_seconds"] = round(sum(b - a for a, b in cut), 2)
    return dict(timeline=out, report=report)


# ---------------------------------------------------------------- Chapters

CHAPTER_DEFAULTS = dict(language="", count=0, min_length=30.0, add_markers=True)
CHAPTER_HELP = "YouTube chapters (first at 00:00, at least 3). count 0 = automatic. Titles by LLM if configured."


def _bag(sents):
    return Counter(t for s in sents for t in (norm(w["w"]) for w in s["words"]) if len(t) > 3 and t not in STOP)


def _cos(a, b):
    num = sum(a[k] * b[k] for k in a if k in b)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def keyword_title(sents, overall):
    bag = _bag(sents)
    top = sorted(bag, key=lambda k: bag[k] ** 2 / (overall[k] or 1), reverse=True)[:3]
    return " ".join(top).title() or "Chapter"


def chapters(tl, p, ctx):
    sents = sentences(timeline_words(tl, 0, p["language"]))
    if not sents:
        return dict(text="", report=dict(error="no speech found"))
    dur, mn = tl.duration, float(p["min_length"])
    n = int(p["count"]) or int(np.clip(round(dur / 150), 3, 12))
    k = 4
    scores = [(_cos(_bag(sents[max(0, i - k + 1):i + 1]), _bag(sents[i + 1:i + 1 + k])), sents[i + 1]["start"])
              for i in range(len(sents) - 1)]
    cuts = []
    for _, t in sorted(scores):
        if len(cuts) >= n - 1:
            break
        if t >= mn and dur - t >= mn and all(abs(t - c) >= mn for c in cuts):
            cuts.append(t)
    starts = [0.0] + sorted(cuts)
    groups = [[s for s in sents if a <= s["start"] < b] for a, b in zip(starts, starts[1:] + [dur + 1])]
    titles = None
    if llm.available():
        prompt = ("Write a short YouTube chapter title (max 6 words) for each transcript section below. "
                  "Return a JSON array of strings, same order.\n\n" +
                  "\n\n".join(f"Section {i + 1}: " + " ".join(s["text"] for s in g)[:1500] for i, g in enumerate(groups)))
        titles = llm.chat_json(prompt)
        if not (isinstance(titles, list) and len(titles) == len(groups)):
            titles = None
    overall = _bag(sents)
    titles = titles or [("Intro" if i == 0 else keyword_title(g, overall)) for i, g in enumerate(groups)]
    text = "\n".join(f"{fmt_time(t)} {title}" for t, title in zip(starts, titles))
    markers = [dict(t=t, name=str(title)) for t, title in zip(starts, titles)] if p["add_markers"] else []
    (ctx.out_dir / f"{tl.name} - chapters.txt").write_text(text, "utf-8")
    return dict(text=text, markers=markers, report=dict(chapters=len(starts)))


# ---------------------------------------------------------------- Viral

HOOKS = set(("why how what secret never always best worst mistake truth nobody everyone crazy insane important "
             "stop money free first biggest real actually wrong problem hack tip story imagine").split())
VIRAL_DEFAULTS = dict(language="", detection="both", min_length=20.0, max_length=60.0, count=5, vertical=True,
                      format="9:16", preview=False, items="")
VIRAL_CHOICES = dict(detection=["both", "transcript", "emotion"], format=["9:16", "4:5", "1:1", "16:9"])
VIRAL_HELP = "Ranks sentence-aligned windows by hook, energy and pace (0-100); each pick becomes its own sequence."


def viral(tl, p, ctx):
    sents = sentences(timeline_words(tl, 0, p["language"]))
    db = timeline_db(tl, [0])
    voiced = db[db > -60]
    g_mean, g_std = (voiced.mean(), voiced.std() + 1e-6) if len(voiced) else (-30.0, 1.0)
    pk = np.array(peaks(db, min_gap=1.0))
    mn, mx = float(p["min_length"]), float(p["max_length"])
    cands = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            a, b = sents[i]["start"], sents[j]["end"]
            if b - a > mx:
                break
            if b - a < mn:
                continue
            first = sents[i]["text"]
            ft = [norm(w) for w in first.split()]
            hook = min(2.0, first.strip().endswith("?") + 0.5 * sum(t in HOOKS for t in ft) +
                       0.5 * bool(re.search(r"\d", first)))
            nwords = sum(len(s["words"]) for s in sents[i:j + 1])
            seg = db[int(a / media.HOP):int(b / media.HOP)]
            energy = float(((seg[seg > -60].mean() if (seg > -60).any() else g_mean) - g_mean) / g_std)
            npk = int(((pk >= a) & (pk <= b)).sum()) * 60 / (b - a) if len(pk) else 0
            t_score = hook * 25 + (nwords / (b - a)) * 5 + 5 * (sents[j]["text"][-1:] in ".!?")
            e_score = energy * 20 + npk * 2
            score = {"transcript": t_score, "emotion": e_score}.get(p["detection"], t_score + e_score)
            cands.append(dict(start=a, end=b, raw=score, text=" ".join(s["text"] for s in sents[i:j + 1])))
    if not cands:
        return dict(report=dict(error="no clips fit the length range"), items=[])
    lo, hi = min(c["raw"] for c in cands), max(c["raw"] for c in cands)
    for c in cands:
        c["score"] = int(round(100 * (c["raw"] - lo) / (hi - lo + 1e-9)))
    cands.sort(key=lambda c: c["score"], reverse=True)
    if llm.available() and p["detection"] != "emotion":
        top = cands[:3 * int(p["count"])]
        ratings = llm.chat_json("Rate how likely each transcript excerpt is to perform as a standalone short-form "
                                "video (0-100). Return a JSON array of numbers in the same order.\n\n" +
                                "\n\n".join(f"{i + 1}. {c['text'][:800]}" for i, c in enumerate(top)))
        if isinstance(ratings, list) and len(ratings) == len(top):
            for c, r in zip(top, ratings):
                c["score"] = int(round((c["score"] + float(r)) / 2))
            cands = sorted(top, key=lambda c: c["score"], reverse=True) + cands[len(top):]
    picks = []
    for c in cands:
        if len(picks) >= int(p["count"]):
            break
        if all(c["end"] <= q["start"] or c["start"] >= q["end"] for q in picks):
            picks.append(c)
    items = [dict(id=i, label=f"{c['score']:3d}  {fmt_time(c['start'])}–{fmt_time(c['end'])}  “{c['text'][:60]}”",
                  start=c["start"], end=c["end"], score=c["score"]) for i, c in enumerate(picks)]
    report = dict(candidates=len(cands), picks=len(items))
    if p["preview"]:
        return dict(report=report, items=items)
    from .motion import reframe
    timelines = []
    for it in selected(p, items):
        out = keep(tl, [(it["start"], it["end"])])
        out.name = f"{tl.name} - Viral {it['id'] + 1} ({it['score']})"
        if p["vertical"]:
            out = reframe(out, p["format"])
        timelines.append(out)
    return dict(timelines=timelines, report=report, items=items)
