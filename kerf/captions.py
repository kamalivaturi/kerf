"""AutoCaptions equivalent: word-by-word animated captions.

Outputs (param `output`):
  overlay  – animated ASS rendered to a transparent ProRes 4444 clip on the top track (Premiere + Resolve)
  mogrt    – one instance of YOUR .mogrt per caption page, text injected (Premiere; panel does the insert)
  srt_only – SRT for the NLE's native caption/subtitle track
An SRT is always written so captions stay editable in the NLE.
"""
from __future__ import annotations

import copy
import json
import math
import re

from . import llm, media
from .speech import timeline_words
from .timeline import Clip, add_track

ANIMATIONS = ["none", "zoom_in", "blur_in", "zoom_blur", "pop", "bounce", "slide_up", "fade", "typewriter", "karaoke"]
CAPTION_DEFAULTS = dict(
    language="", srt_import="", translate_to="", output="overlay", mogrt="", mogrt_param="Source Text",
    font="Arial Black", active_font="", font_size=0, text_color="#FFFFFF", highlight_color="#FFD400",
    highlight_box=False, bigger_active=True, active_scale=115, animation="zoom_in", floating=False,
    uppercase=True, remove_punctuation=True, italic=False, outline_color="#000000", outline=6, shadow=0,
    glow=False, glow_color="#FFD400", glow_strength=8, box=False, box_color="#000000", box_opacity=60,
    lines=1, words_per_line=4, max_width=80, y_position=78, emoji=False)
CAPTION_CHOICES = dict(output=["overlay", "mogrt", "srt_only"], animation=ANIMATIONS)
CAPTION_HELP = ("Transcribes A1 (or imports srt_import). font_size 0 = auto. highlight_color accepts a comma list "
                "that cycles per caption. mogrt = path to a custom Motion Graphics Template (Premiere); mogrt_param = "
                "its text field name. translate_to needs an LLM (KERF_LLM_URL).")

# Built-in style gallery. Users save their own with the panel's "Save preset" (stored per feature).
BUILTIN_PRESETS = {
    "Bold Yellow": dict(font="Arial Black", text_color="#FFFFFF", highlight_color="#FFD400", animation="pop",
                        uppercase=True, outline=7, words_per_line=3),
    "Clean Subtitle": dict(font="Segoe UI", text_color="#FFFFFF", highlight_color="#FFFFFF", bigger_active=False,
                           animation="fade", uppercase=False, remove_punctuation=False, outline=0, box=True,
                           box_opacity=55, words_per_line=7, lines=2, y_position=86),
    "Neon Glow": dict(font="Impact", text_color="#E8FFFF", highlight_color="#00F0FF", glow=True,
                      glow_color="#00F0FF", glow_strength=10, animation="zoom_blur", outline=2),
    "Karaoke": dict(font="Montserrat ExtraBold", text_color="#FFFFFF", highlight_color="#2BFF88",
                    animation="karaoke", words_per_line=5, bigger_active=False),
    "Highlight Box": dict(font="Arial Black", text_color="#FFFFFF", highlight_color="#7B2CFF",
                          highlight_box=True, animation="bounce", words_per_line=3),
    "Typewriter": dict(font="Consolas", text_color="#FFFFFF", highlight_color="#FFFFFF", bigger_active=False,
                       animation="typewriter", uppercase=False, words_per_line=6),
    "Rainbow Pop": dict(font="Arial Black", highlight_color="#FF3D7F,#FFD400,#00E5FF,#7CFF4F", animation="pop",
                        floating=True, words_per_line=2, active_scale=125),
    "Minimal Lower": dict(font="Helvetica", text_color="#FFFFFF", highlight_color="#FFFFFF", bigger_active=False,
                          animation="slide_up", uppercase=False, outline=2, shadow=2, words_per_line=6,
                          y_position=88, font_size=0),
}
EMOJI = {"love": "❤", "money": "💰", "fire": "🔥", "happy": "😊", "sad": "😢", "laugh": "😂", "idea": "💡",
         "time": "⏰", "win": "🏆", "rocket": "🚀", "growth": "📈", "think": "🤔", "music": "🎵", "food": "🍕",
         "phone": "📱", "world": "🌍", "warning": "⚠", "yes": "✅", "no": "❌", "heart": "❤", "crazy": "🤯",
         "secret": "🤫", "eyes": "👀", "strong": "💪", "camera": "📷", "video": "🎬", "book": "📚", "car": "🚗"}


def ass_color(hex_, alpha=0):
    h = hex_.strip().lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ts_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ts_ass(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def clean(w, s):
    if s["remove_punctuation"]:
        w = re.sub(r"[^\w\s'’-]", "", w)
    return w.upper() if s["uppercase"] else w


def parse_srt(text):
    """SRT cues → pseudo words spread evenly across each cue."""
    words = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a, b = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        toks = " ".join(block[m.end():].split()).split()
        for i, w in enumerate(toks):
            words.append(dict(w=w, s=a + (b - a) * i / len(toks), e=a + (b - a) * (i + 1) / len(toks)))
    return words


def paginate(words, s, max_chars, gap=0.6):
    per_page = int(s["words_per_line"]) * int(s["lines"])
    out, cur = [], []
    for w in words:
        chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
        if cur and (len(cur) >= per_page or w["s"] - cur[-1]["e"] > gap or cur[-1]["w"][-1:] in ".?!"
                    or chars > max_chars * int(s["lines"])):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    pages = [dict(start=p[0]["s"], end=p[-1]["e"], words=p) for p in out]
    for a, b in zip(pages, pages[1:]):  # hold each page until the next one (max +0.5 s)
        a["end"] = min(b["start"], a["end"] + 0.5)
    if pages:
        pages[-1]["end"] += 0.5
    return pages


def lines_of(words, s):
    n = int(s["words_per_line"])
    return [words[i:i + n] for i in range(0, len(words), n)]


def page_text(pg, s, sep="\n"):
    return sep.join(" ".join(clean(w["w"], s) for w in ln) for ln in lines_of(pg["words"], s))


def write_srt(pages, s):
    return "\n".join(f"{i}\n{ts_srt(pg['start'])} --> {ts_srt(pg['end'])}\n{page_text(pg, s)}\n"
                     for i, pg in enumerate(pages, 1))


def write_ass(pages, s, w, h):
    fs = int(s["font_size"]) or int(h * (0.075 if h > w else 0.055))
    box = bool(s["box"])
    back = ass_color(s["box_color"], int(255 * (1 - float(s["box_opacity"]) / 100)))
    colors = [c for c in str(s["highlight_color"]).split(",") if c.strip()] or ["#FFD400"]
    fields = lambda name, prim, out, border, outline: (
        f"Style: {name},{s['font']},{fs},{prim},{ass_color(s['text_color'])},{out},{back},-1,"
        f"{-1 if s['italic'] else 0},0,0,100,100,0,0,{border},{outline},{s['shadow']},5,10,10,10,1")
    styles = [fields("Kerf", ass_color(s["text_color"]), back if box else ass_color(s["outline_color"]),
                     3 if box else 1, max(8, fs // 5) if box else s["outline"])]
    styles += [fields(f"KerfBox{i}", ass_color(s["text_color"]), ass_color(c), 3, max(6, fs // 6))
               for i, c in enumerate(colors)]
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n" + "\n".join(styles) + "\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    x, y = w // 2, int(h * float(s["y_position"]) / 100)
    big = int(s["active_scale"]) if s["bigger_active"] else 100
    anim = s["animation"]
    enter = {"zoom_in": r"\fscx70\fscy70\t(0,120,\fscx100\fscy100)", "blur_in": r"\blur12\t(0,150,\blur0)",
             "zoom_blur": r"\fscx70\fscy70\blur12\t(0,150,\fscx100\fscy100\blur0)",
             "pop": r"\fscx0\fscy0\t(0,90,\fscx115\fscy115)\t(90,160,\fscx100\fscy100)",
             "fade": r"\fad(150,0)", "slide_up": r"\fad(150,0)"}.get(anim, "")
    afont = rf"\fn{s['active_font']}" if s["active_font"] else ""
    ev = []

    def emit(a, b, tags, text):
        if s["glow"]:
            g = int(s["glow_strength"])
            ev.append(f"Dialogue: 0,{ts_ass(a)},{ts_ass(b)},Kerf,,0,0,0,,{{{tags}\\bord{g}\\blur{g}"
                      f"\\3c{ass_color(s['glow_color'])}\\1a&HFF&}}{text}")
        ev.append(f"Dialogue: 1,{ts_ass(a)},{ts_ass(b)},Kerf,,0,0,0,,{{{tags}}}{text}")

    for pi, pg in enumerate(pages):
        hl = colors[pi % len(colors)].strip()
        ws = pg["words"]
        if s["floating"]:
            dx, dy = int(w * 0.006 * math.sin(pi * 1.7)), int(h * 0.006 * math.cos(pi * 1.3))
            pos = rf"\move({x},{y},{x + dx},{y + dy})"
        elif anim == "bounce":
            pos = rf"\move({x},{y + int(h * 0.03)},{x},{y},0,150)"
        elif anim == "slide_up":
            pos = rf"\move({x},{y + int(h * 0.06)},{x},{y},0,200)"
        else:
            pos = rf"\pos({x},{y})"

        def word(wd):
            t = clean(wd["w"], s)
            if s["emoji"] and (e := EMOJI.get(re.sub(r"\W", "", wd["w"].lower()))):
                t += r"{\fnSegoe UI Emoji} " + e + r"{\fn" + s["font"] + "}"
            return t

        if anim == "karaoke":  # one event per page, words fill with the highlight colour as spoken
            parts = []
            for ln in lines_of(ws, s):
                parts.append(" ".join(rf"{{\kf{max(1, int(round((wd['e'] - wd['s']) * 100)))}}}{word(wd)}" for wd in ln))
            emit(pg["start"], pg["end"], pos + rf"\1c{ass_color(hl)}\2c{ass_color(s['text_color'])}", r"\N".join(parts))
            continue
        times = [wd["s"] for wd in ws] + [pg["end"]]
        times[0] = pg["start"]
        for k in range(len(ws)):
            a, b = times[k], max(times[k + 1], times[k] + 0.01)
            parts, i = [], 0
            for ln in lines_of(ws, s):
                toks = []
                for wd in ln:
                    t = word(wd)
                    if i == k:
                        style = rf"\rKerfBox{pi % len(colors)}" if s["highlight_box"] else rf"\c{ass_color(hl)}"
                        t = rf"{{{style}{afont}\fscx{big}\fscy{big}}}{t}{{\r}}"
                    elif anim == "typewriter" and i > k:
                        t = rf"{{\alpha&HFF&}}{t}{{\r}}"
                    toks.append(t)
                    i += 1
                parts.append(" ".join(toks))
            emit(a, b, pos + (enter if k == 0 else ""), r"\N".join(parts))
    return head + "\n".join(ev) + "\n"


def render_overlay(ass_path, w, h, fps, dur, out):
    media.ffmpeg("-f", "lavfi", "-i", f"color=c=black@0.0:s={w}x{h}:r={fps:.3f}:d={dur:.3f},format=rgba",
                 "-vf", f"ass={ass_path.name}:alpha=1", "-c:v", "prores_ks", "-profile:v", "4444",
                 "-pix_fmt", "yuva444p10le", out.name, cwd=ass_path.parent)


def translate(pages, lang):
    texts = [" ".join(w["w"] for w in pg["words"]) for pg in pages]
    out = []
    for i in range(0, len(texts), 40):
        chunk = texts[i:i + 40]
        tr = llm.chat_json(f"Translate each caption line to {lang}. Keep it short. Return a JSON array of strings, "
                           f"same order and count.\n" + json.dumps(chunk, ensure_ascii=False))
        out += tr if isinstance(tr, list) and len(tr) == len(chunk) else chunk
    for pg, t in zip(pages, out):  # word timing is lost across languages: spread evenly
        toks = str(t).split() or [""]
        d = (pg["end"] - pg["start"]) / len(toks)
        pg["words"] = [dict(w=x, s=pg["start"] + i * d, e=pg["start"] + (i + 1) * d) for i, x in enumerate(toks)]
    return pages


def run(tl, p, ctx):
    s = p
    if p["srt_import"]:
        words = parse_srt(open(p["srt_import"], encoding="utf-8-sig").read())
    else:
        words = timeline_words(tl, 0, p["language"])
    fs = int(s["font_size"]) or int(tl.height * (0.075 if tl.height > tl.width else 0.055))
    max_chars = max(4, int(tl.width * float(s["max_width"]) / 100 / (fs * 0.6)))
    pages = paginate(words, s, max_chars)
    if p["translate_to"]:
        if not llm.available():
            raise RuntimeError("translate_to needs an LLM: set KERF_LLM_URL (e.g. Ollama http://localhost:11434/v1)")
        pages = translate(pages, p["translate_to"])
    base = ctx.out_dir / f"{tl.name} - captions"
    srt = base.with_suffix(".srt")
    srt.write_text(write_srt(pages, s), "utf-8")
    files, out, result = [str(srt)], None, {}
    if p["output"] == "overlay" and pages:
        ass, mov = base.with_suffix(".ass"), base.with_suffix(".mov")
        ass.write_text(write_ass(pages, s, tl.width, tl.height), "utf-8")
        render_overlay(ass, tl.width, tl.height, tl.fps, tl.duration, mov)
        files += [str(ass), str(mov)]
        out = copy.deepcopy(tl)
        add_track(out, "video", [Clip(str(mov), 0.0, tl.duration, 0.0)])
        out.name = f"{tl.name} - Captions"
    elif p["output"] == "mogrt":
        if not p["mogrt"]:
            raise RuntimeError("output=mogrt needs the path of a .mogrt file")
        result["mogrt"] = dict(path=p["mogrt"], param=p["mogrt_param"],
                               pages=[dict(start=pg["start"], end=pg["end"], text=page_text(pg, s, "\r"))
                                      for pg in pages])
    return dict(timeline=out, files=files, srt=str(srt), report=dict(captions=len(pages), words=len(words)), **result)
