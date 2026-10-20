"""Kerf MOGRT library: build original, fully editable Motion Graphics templates with After Effects,
make live previews, import your own .mogrt files, and save customized variants (MOGRT Studio).

Library layout (~/.kerf/mogrt/):  pack/ (Kerf-built)  custom/ (Studio)  user/ (imported)  previews/  index.json
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from . import media

ROOT = Path(__file__).resolve().parent.parent / "mogrt"
LIB = media.HOME / "mogrt"
INDEX = LIB / "index.json"
AE_DIRS = [Path(os.environ.get("KERF_AE_DIR", "")), *sorted(Path("C:/Program Files/Adobe").glob("Adobe After Effects*"), reverse=True),
           *sorted(Path("/Applications").glob("Adobe After Effects*"), reverse=True)]

# Text animator recipes. props = (AE match name, "full effect" value); amount 1 → fully applied (hidden).
# based_on: 1 characters, 2 characters excl. spaces, 3 words, 4 lines.
ANIMS = {
    "pop": dict(props=[["ADBE Text Scale 3D", [0, 0, 100]], ["ADBE Text Opacity", 0]], ease="back", dur=.35, stagger=.08, based_on=3),
    "typewriter": dict(props=[["ADBE Text Opacity", 0]], ease="step", dur=.01, stagger=.04, based_on=2),
    "rise": dict(props=[["ADBE Text Position 3D", [0, 70, 0]], ["ADBE Text Opacity", 0]], ease="cubic", dur=.45, stagger=.07, based_on=3),
    "slide": dict(props=[["ADBE Text Position 3D", [-140, 0, 0]], ["ADBE Text Opacity", 0]], ease="cubic", dur=.45, stagger=.06, based_on=3),
    "blur": dict(props=[["ADBE Text Blur", [40, 40]], ["ADBE Text Opacity", 0]], ease="cubic", dur=.5, stagger=.03, based_on=2),
    "bounce": dict(props=[["ADBE Text Position 3D", [0, -120, 0]], ["ADBE Text Opacity", 0]], ease="bounce", dur=.7, stagger=.05, based_on=2),
    "stomp": dict(props=[["ADBE Text Scale 3D", [320, 320, 100]], ["ADBE Text Opacity", 0]], ease="expo", dur=.3, stagger=.12, based_on=3),
    "zoom": dict(props=[["ADBE Text Scale 3D", [170, 170, 100]], ["ADBE Text Opacity", 0]], ease="cubic", dur=.6, stagger=0, based_on=4),
    "spin": dict(props=[["ADBE Text Rotation", 90], ["ADBE Text Opacity", 0]], ease="back", dur=.5, stagger=.03, based_on=2),
    "spread": dict(props=[["ADBE Text Tracking Amount", 60], ["ADBE Text Opacity", 0]], ease="cubic", dur=.8, stagger=0, based_on=4),
    "flicker": dict(props=[["ADBE Text Opacity", 0]], ease="flicker", dur=.5, stagger=0, based_on=2),
    "wave": dict(props=[["ADBE Text Position 3D", [0, -22, 0]]], ease="wave", dur=1, stagger=0, based_on=2),
    "drop": dict(props=[["ADBE Text Position 3D", [0, -200, 0]], ["ADBE Text Opacity", 0]], ease="back", dur=.5, stagger=.09, based_on=3),
    "fade": dict(props=[["ADBE Text Opacity", 0]], ease="cubic", dur=.5, stagger=.05, based_on=3),
}
LOOKS = {
    "clean": dict(font="Arial-BoldMT", fill="#FFFFFF", stroke="#000000", stroke_width=0, highlight="#FFD400",
                  highlight_on=False, box=False, box_color="#000000", box_opacity=60, shadow=True, glow=0),
    "bold": dict(font="Arial-Black", fill="#FFFFFF", stroke="#000000", stroke_width=9, highlight="#FFD400",
                 highlight_on=True, box=False, box_color="#000000", box_opacity=60, shadow=False, glow=0),
    "boxed": dict(font="Arial-BoldMT", fill="#FFFFFF", stroke="#000000", stroke_width=0, highlight="#2BFF88",
                  highlight_on=True, box=True, box_color="#111111", box_opacity=78, shadow=False, glow=0),
    "neon": dict(font="Impact", fill="#E8FFFF", stroke="#00E5FF", stroke_width=3, highlight="#FF3D7F",
                 highlight_on=True, box=False, box_color="#000000", box_opacity=60, shadow=False, glow=55),
    "yellow": dict(font="Impact", fill="#FFD400", stroke="#000000", stroke_width=8, highlight="#FFFFFF",
                   highlight_on=True, box=False, box_color="#000000", box_opacity=60, shadow=True, glow=0),
}
KINDS = {  # size for 1080p frames; position as frame fractions
    "caption": dict(size=92, pos=(.5, .8), text="MAKE EVERY WORD COUNT", looks=list(LOOKS)),
    "title": dict(size=160, pos=(.5, .5), text="YOUR TITLE HERE", looks=["clean", "bold", "neon"]),
    "lower_third": dict(size=78, pos=(.3, .78), text="Alex Morgan", subtext="Creative Director",
                        looks=["clean", "boxed", "neon"], anims=["slide", "rise", "fade", "blur"]),
}
FORMATS = {"16x9": (1920, 1080), "9x16": (1080, 1920)}
TEXT_KEYS = ("tracking", "leading", "kerning", "align")
ANIM_KEYS = ("ease", "dur", "stagger", "based_on")


def spec(kind, anim, look, fmt="16x9", overrides=None, name=None):
    """One AE builder spec. overrides may set any look key, animation timing, text, size, pos or duration."""
    k, (w, h) = KINDS[kind], FORMATS[fmt]
    vertical = h > w
    s = dict(id=f"{kind}-{anim}-{look}-{fmt}".replace("_", "-"), kind=kind, anim_name=anim, look_name=look, format=fmt,
             name=name or f"Kerf {kind.replace('_', ' ').title()} - {anim.title()} - {look.title()}{' 9x16' if vertical else ''}",
             w=w, h=h, duration=10, preview_seconds=3, text=k["text"], subtext=k.get("subtext", ""),
             size=round(k["size"] * (.9 if vertical else 1)),
             pos=[k["pos"][0], .72 if vertical and kind == "caption" else k["pos"][1]],
             anim=copy.deepcopy(ANIMS[anim]), look=copy.deepcopy(LOOKS[look]))
    for key, v in (overrides or {}).items():
        if key in s["look"] or key in TEXT_KEYS:
            s["look"][key] = v
        elif key in ANIM_KEYS:
            s["anim"][key] = v
        elif key in ("text", "subtext", "size", "pos", "duration"):
            s[key] = v
    return s


def catalog():
    """Every template in the Kerf pack, as builder specs."""
    return [spec(kind, anim, look, fmt)
            for kind, k in KINDS.items() for look in k["looks"] for anim in k.get("anims", ANIMS)
            for fmt in (FORMATS if kind == "caption" else ["16x9"])]


# ---------------------------------------------------------------- build with After Effects

def after_effects():
    for d in AE_DIRS:
        for exe in (d / "Support Files" / "AfterFX.exe", d / "Contents" / "MacOS" / "After Effects"):
            if str(d) not in ("", ".") and exe.exists():
                return exe
    raise FileNotFoundError("After Effects not found. Set KERF_AE_DIR to its install folder.")


def build(specs, dest="pack", previews=True, timeout=7200):
    """Build specs with After Effects into ~/.kerf/mogrt/<dest>, render previews, update the index."""
    out = LIB / dest
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    result = work / "result.json"
    result.unlink(missing_ok=True)
    (work / "specs.json").write_text(json.dumps(dict(out=str(out), templates=specs, quit=True)), "utf-8")
    ae = after_effects()
    subprocess.Popen([str(ae), "-r", str(ROOT / "kerf_mogrt_builder.jsx")])
    t0 = time.time()
    while not result.exists():
        if time.time() - t0 > timeout:
            raise TimeoutError("After Effects did not finish the MOGRT build")
        time.sleep(2)
    time.sleep(1)
    res = json.loads(result.read_text("utf-8"))
    if any(x.startswith("ABORT") for x in res["log"]):
        raise RuntimeError(res["log"][0])
    by_id = {s["id"]: s for s in specs}
    entries = []
    for r in res["templates"]:
        if not r["exported"]:
            continue
        s = by_id[r["id"]]
        mogrt = out / f"{_safe(r['comp'])}.mogrt"
        entry = dict(id=s["id"], name=s["name"], kind=s["kind"], anim=s["anim_name"], look=s["look_name"],
                     format=s["format"], source=dest, file=str(mogrt), controls=r["controls"], spec=s)
        if previews:
            entry.update(render_preview(Path(res["aep"]), r["comp"], s["id"], ae))
        entries.append(entry)
    _merge_index(entries)
    return dict(built=len(entries), requested=len(specs),
                failed=[x for x in res["log"] if "FAILED" in x or "FATAL" in x or "NOT exported" in x], log=res["log"])


def render_preview(aep, comp, pid, ae):
    """aerender the comp's work area → looping GIF (panel gallery), MP4 (large preview) and PNG poster."""
    pv = LIB / "previews"
    pv.mkdir(parents=True, exist_ok=True)
    # Windows: next to AfterFX.exe · macOS: in the After Effects folder, outside the .app bundle
    aer = next((p for p in (ae.with_name("aerender.exe" if ae.suffix == ".exe" else "aerender"),
                            *(ae.parents[3:4] and [ae.parents[3] / "aerender"])) if p.exists()), ae.with_name("aerender"))
    err = ""
    for template in ("H.264 - Match Render Settings - 15 Mbps", "Lossless"):
        for old in pv.glob(f"{pid}.raw.*"):
            old.unlink()
        r = subprocess.run([str(aer), "-project", str(aep), "-comp", comp, "-OMtemplate", template,
                            "-output", str(pv / f"{pid}.raw.[fileExtension]")], capture_output=True, text=True)
        raw = next(iter(pv.glob(f"{pid}.raw.*")), None)
        if raw:
            break
        err = (r.stdout + r.stderr)[-400:]
    else:
        return dict(preview_error=err)
    gif, mp4, png = pv / f"{pid}.gif", pv / f"{pid}.mp4", pv / f"{pid}.png"
    media.ffmpeg("-i", raw, "-vf", "fps=15,scale=360:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse",
                 "-loop", "0", gif)
    media.ffmpeg("-i", raw, "-vf", "scale=540:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", mp4)
    media.ffmpeg("-ss", "1.5", "-i", raw, "-frames:v", "1", "-vf", "scale=360:-2", png)
    raw.unlink(missing_ok=True)
    return dict(gif=str(gif), mp4=str(mp4), png=str(png))


# ---------------------------------------------------------------- library, import, studio

def _safe(s):
    return re.sub(r'[<>:"/\\|?*]', "_", s)


def library():
    entries = json.loads(INDEX.read_text("utf-8")) if INDEX.exists() else []
    return [e for e in entries if Path(e["file"]).exists()]


def _merge_index(new):
    cur = {e["id"]: e for e in (json.loads(INDEX.read_text("utf-8")) if INDEX.exists() else [])}
    cur.update({e["id"]: e for e in new})
    LIB.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(list(cur.values()), indent=1), "utf-8")


def _ui_name(v):
    if isinstance(v, dict):
        for item in v.get("strDB", []):
            if item.get("str"):
                return item["str"]
    return str(v or "")


def inspect(path):
    """Name and editable controls of any .mogrt (reads its definition.json)."""
    with zipfile.ZipFile(path) as z:
        d = json.loads(z.read("definition.json"))
        names = z.namelist()
    kinds = {1: "checkbox", 2: "slider", 3: "angle", 4: "color", 5: "point", 6: "text", 13: "dropdown", 10: "group"}
    return dict(name=_ui_name(d.get("capsuleNameLocalized")) or d.get("capsuleName") or Path(path).stem,
                author_app=d.get("authorApp"), has_preview="thumb.mp4" in names,
                controls=[dict(name=_ui_name(c.get("uiName")), type=kinds.get(c.get("type"), c.get("type")))
                          for c in d.get("clientControls", [])])


def import_mogrt(path):
    """Add a .mogrt you own to the library (copied to ~/.kerf/mogrt/user) with previews from its thumbnails."""
    src = Path(path)
    info = inspect(src)
    dest = LIB / "user" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    pid = "user-" + re.sub(r"\W+", "-", src.stem.lower()).strip("-")
    entry = dict(id=pid, name=info["name"], kind="imported", anim="", look="", format="", source="user", file=str(dest),
                 controls=len(info["controls"]), control_names=[c["name"] for c in info["controls"]])
    pv = LIB / "previews"
    pv.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        for member, key in (("thumb.mp4", "mp4"), ("thumb.png", "png")):
            if member in z.namelist():
                f = pv / f"{pid}.{key}"
                f.write_bytes(z.read(member))
                entry[key] = str(f)
    if "mp4" in entry:
        gif = pv / f"{pid}.gif"
        media.ffmpeg("-i", entry["mp4"], "-t", "4", "-vf", "fps=15,scale=360:-2,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                     "-loop", "0", gif)
        entry["gif"] = str(gif)
    _merge_index([entry])
    return entry


def studio(base_id, overrides, name, previews=True):
    """Save a customized copy of a Kerf template as your own MOGRT. Every control stays editable."""
    base = next((e["spec"] for e in library() if e["id"] == base_id and "spec" in e), None) or \
        next((s for s in catalog() if s["id"] == base_id), None)
    if base is None:
        raise KeyError(f"no Kerf template '{base_id}' to customize")
    num = re.compile(r"-?\d+(\.\d+)?$")  # panel form values arrive as strings
    o = {k: float(v) if isinstance(v, str) and k not in ("text", "subtext", "font") and num.match(v) else v
         for k, v in overrides.items()}
    anim, look, fmt = o.pop("anim", "") or base["anim_name"], o.pop("look", "") or base["look_name"], o.pop("format", "") or base["format"]
    keep = {**base["look"], **{k: base["anim"][k] for k in ANIM_KEYS if anim == base["anim_name"]},
            **{k: base[k] for k in ("text", "subtext", "size", "pos", "duration")}}
    s = spec(base["kind"], anim, look, fmt, name=name, overrides={**keep, **o})
    s["id"] = "custom-" + re.sub(r"\W+", "-", name.lower()).strip("-")
    return build([s], dest="custom", previews=previews)


# ---------------------------------------------------------------- the downloadable Kerf pack

# A permanent pre-release holds the pack (built once with After Effects); pre-releases never become "latest".
PACK_URL = "https://github.com/{repo}/releases/download/mogrt-pack/kerf-mogrt-pack.zip"


def export_pack(dest):
    """Zip the built pack (.mogrt + previews) with a manifest of relative paths: what the release ships."""
    entries = [e for e in library() if e["source"] == "pack"]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = []
        for e in entries:
            rel = dict(e, file=f"pack/{Path(e['file']).name}")
            z.write(e["file"], rel["file"])
            for k in ("gif", "mp4", "png"):
                if e.get(k) and Path(e[k]).exists():
                    rel[k] = f"previews/{Path(e[k]).name}"
                    z.write(e[k], rel[k])
            manifest.append(rel)
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    return dict(templates=len(entries), file=str(dest))


def install_pack(source=""):
    """Install the Kerf pack from a zip path, or download this version's pack from the release page."""
    from . import REPO
    src = Path(source) if source else None
    if src is None or not src.exists():
        import urllib.request
        src = media.CACHE / "kerf-mogrt-pack.zip"
        src.parent.mkdir(parents=True, exist_ok=True)
        tmp = src.with_suffix(".part")
        urllib.request.urlretrieve(source or PACK_URL.format(repo=REPO), tmp)
        tmp.replace(src)
    with zipfile.ZipFile(src) as z:
        manifest = json.loads(z.read("manifest.json"))
        for name in z.namelist():  # only the pack's own two folders; never write outside the library
            if name.startswith(("pack/", "previews/")) and ".." not in name and not name.endswith("/"):
                out = LIB / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(name))
    for e in manifest:
        for k in ("file", "gif", "mp4", "png"):
            if e.get(k):
                e[k] = str(LIB / e[k])
    _merge_index(manifest)
    return dict(installed=len(manifest))
