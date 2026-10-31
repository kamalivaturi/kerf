"""AutoB-Rolls equivalent: contextual stock footage from Pexels (free API key) or a local folder."""
from __future__ import annotations

import copy
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from . import llm, media
from .speech import STOP, norm, selected, sentences, timeline_words
from .timeline import Clip, add_track, fmt_time

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
BROLL_DEFAULTS = dict(language="", source="pexels", pexels_key="", folder="", style="", every=8.0, duration=3.5,
                      orientation="landscape", preview=False, items="")
BROLL_CHOICES = dict(source=["pexels", "folder"], orientation=["landscape", "portrait", "square"])
BROLL_HELP = ("Places B-roll on a new top track every `every` seconds of speech. pexels_key: free key from "
              "pexels.com/api (or env PEXELS_API_KEY). folder: local footage matched by file name. "
              "style: extra words added to every search (e.g. 'cinematic').")


def query_for(text, style=""):
    toks = [norm(w) for w in text.split()]
    toks = [t for t in toks if len(t) > 3 and t not in STOP and not t.isdigit()]
    q = " ".join(sorted(Counter(toks), key=lambda t: (-len(t), t))[:2]) or "abstract"
    return f"{q} {style}".strip()


def pexels(query, key, orientation, out_dir):
    f = out_dir / "broll" / (re.sub(r"\W+", "_", query) + ".mp4")
    if f.exists():
        return str(f)
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        dict(query=query, per_page=3, orientation=orientation, size="medium"))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": key}), timeout=30) as r:
        vids = json.loads(r.read()).get("videos", [])
    files = [vf for v in vids for vf in v["video_files"] if vf.get("width") and vf["width"] <= 1920]
    if not files:
        return None
    best = max(files, key=lambda vf: vf["width"])
    f.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(best["link"], timeout=120) as r:
        f.write_bytes(r.read())
    return str(f)


def from_folder(query, folder, used):
    files = [p for p in Path(folder).rglob("*") if p.suffix.lower() in VIDEO_EXT]
    q = set(query.lower().split())
    scored = sorted(files, key=lambda p: (-len(q & set(re.split(r"[\W_]+", p.stem.lower()))), str(p) in used))
    return str(scored[0]) if scored else None


def run(tl, p, ctx):
    sents = sentences(timeline_words(tl, 0, p["language"]))
    picks, last = [], -1e9
    for s in sents:
        if s["start"] - last >= float(p["every"]) and len(s["words"]) >= 4:
            picks.append(s)
            last = s["start"]
    queries = None
    if llm.available() and picks:
        queries = llm.chat_json("For each sentence, give a 2-4 word stock-footage search query that visually "
                                f"illustrates it{' in a ' + p['style'] + ' style' if p['style'] else ''}. "
                                "Return a JSON array of strings, same order.\n" +
                                json.dumps([s["text"] for s in picks], ensure_ascii=False))
    if not (isinstance(queries, list) and len(queries) == len(picks)):
        queries = [query_for(s["text"], p["style"]) for s in picks]
    items = [dict(id=i, label=f"{fmt_time(s['start'])}  [{q}]  “{s['text'][:50]}”", start=s["start"], query=str(q))
             for i, (s, q) in enumerate(zip(picks, queries))]
    if p["preview"]:
        return dict(report=dict(moments=len(items)), items=items)
    from . import settings
    key = p["pexels_key"] or settings.get("pexels_api_key")
    if p["source"] == "pexels" and not key:
        raise ValueError("Pexels B-roll needs a free API key from pexels.com/api: add it in Settings, or set source "
                         "to 'folder' to use your own footage")
    clips, used, missing = [], set(), []
    for it in selected(p, items):
        path = (pexels(it["query"], key, p["orientation"], ctx.out_dir) if p["source"] == "pexels"
                else from_folder(it["query"], p["folder"], used))
        if not path:
            missing.append(it["query"])
            continue
        used.add(path)
        d = min(float(p["duration"]), media.probe(path)["duration"] or float(p["duration"]), tl.duration - it["start"])
        clips.append(Clip(path, 0.0, d, it["start"]))
    out = copy.deepcopy(tl)
    add_track(out, "video", clips)
    out.name = f"{tl.name} - B-Roll"
    return dict(timeline=out, report=dict(placed=len(clips), not_found=missing))
