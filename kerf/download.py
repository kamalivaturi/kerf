"""Downloader: any yt-dlp supported site, straight into the editor's project.

Uses the yt_dlp Python API. Only download media you have the rights to use.
"""
from __future__ import annotations

import re
from pathlib import Path

from .timeline import Timeline, fmt_time

DOWNLOAD_DEFAULTS = dict(
    urls="", quality="best", container="mp4", audio_only=False, audio_format="mp3",
    subtitles=False, auto_subtitles=False, sub_langs="en", embed_subs=False,
    playlist=False, playlist_items="", section="", sponsorblock_remove=False,
    embed_thumbnail=False, embed_metadata=True, filename="%(title)s [%(id)s].%(ext)s", folder="",
    rate_limit="", cookies_from_browser="", proxy="", then="", preview=False, items="")
DOWNLOAD_CHOICES = dict(
    quality=["best", "2160", "1440", "1080", "720", "480", "360"], container=["mp4", "mkv", "webm", "mov"],
    audio_format=["mp3", "m4a", "wav", "opus", "flac"],
    cookies_from_browser=["", "chrome", "edge", "firefox", "brave", "opera", "safari"])
DOWNLOAD_HELP = ("Paste one or more links (one per line) from any yt-dlp supported site. Analyze lists the videos "
                 "(and playlist entries) first. section e.g. '01:00-02:30' downloads only that part. then = a Kerf "
                 "feature to run on the download (e.g. silences, captions, viral). Only download media you have the "
                 "rights to use.")


def _secs(t):
    parts = [float(x) for x in t.strip().split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))


def options(p, folder, files):
    import yt_dlp
    o = dict(outtmpl=str(Path(folder) / p["filename"]), quiet=True, no_warnings=True, noprogress=True,
             noplaylist=not p["playlist"], windowsfilenames=True,
             post_hooks=[lambda path: files.append(path)], postprocessors=[])
    pp = o["postprocessors"]
    if p["audio_only"]:
        o["format"] = "bestaudio/best"
        pp.append(dict(key="FFmpegExtractAudio", preferredcodec=p["audio_format"]))
    else:
        h = "" if p["quality"] == "best" else f"[height<={p['quality']}]"
        o["format"] = f"bv*{h}+ba/b{h}/b"
        o["merge_output_format"] = p["container"]
    if p["subtitles"] or p["auto_subtitles"]:
        o.update(writesubtitles=p["subtitles"], writeautomaticsub=p["auto_subtitles"],
                 subtitleslangs=[s.strip() for s in p["sub_langs"].split(",") if s.strip()] or ["en"])
        if p["embed_subs"] and not p["audio_only"]:
            pp.append(dict(key="FFmpegEmbedSubtitle"))
    if p["playlist_items"]:
        o["playlist_items"] = p["playlist_items"]
    if p["section"]:
        a, b = p["section"].split("-", 1)
        o["download_ranges"] = yt_dlp.utils.download_range_func(None, [(_secs(a), _secs(b))])
        o["force_keyframes_at_cuts"] = True
    if p["sponsorblock_remove"]:
        cats = ["sponsor", "selfpromo", "interaction"]
        pp += [dict(key="SponsorBlock", categories=cats), dict(key="ModifyChapters", remove_sponsor_segments=cats)]
    if p["embed_metadata"]:
        pp.append(dict(key="FFmpegMetadata", add_metadata=True))
    if p["embed_thumbnail"]:
        o["writethumbnail"] = True
        pp.append(dict(key="EmbedThumbnail"))
    if p["rate_limit"]:
        o["ratelimit"] = yt_dlp.utils.parse_bytes(p["rate_limit"])
    if p["cookies_from_browser"]:
        o["cookiesfrombrowser"] = (p["cookies_from_browser"],)
    if p["proxy"]:
        o["proxy"] = p["proxy"]
    return o


def entries(info):
    """Flatten a playlist/single-video info dict into (url, title, duration, uploader)."""
    for e in info.get("entries") or [info]:
        if e:
            yield (e.get("webpage_url") or e.get("url") or info.get("webpage_url"), e.get("title") or "?",
                   e.get("duration") or 0, e.get("uploader") or e.get("channel") or "")


def run(tl, p, ctx):
    import yt_dlp
    urls = [u.strip() for u in re.split(r"[\s,]+", p["urls"]) if u.strip()]
    if not urls:
        raise ValueError("Paste at least one link in 'urls'")
    folder = Path(p["folder"] or Path.home() / "Kerf Downloads")
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    o = options(p, folder, files)

    listing = []
    with yt_dlp.YoutubeDL({**o, "extract_flat": "in_playlist"}) as y:
        for u in urls:
            listing += list(entries(y.extract_info(u, download=False)))
    items = [dict(id=i, url=u, label=f"{t} · {fmt_time(d) if d else '?'}{' · ' + up if up else ''}")
             for i, (u, t, d, up) in enumerate(listing)]
    if p["preview"]:
        return dict(report=dict(videos=len(items), folder=str(folder)), items=items)

    from .speech import selected
    chosen = [it["url"] for it in selected(p, items)]
    try:
        _download(o, p, chosen, folder, files)
    except yt_dlp.utils.DownloadError as e:
        if "403" in str(e):
            raise RuntimeError("The site refused the download (HTTP 403). Sites change often: update yt-dlp with "
                               "`pip install -U yt-dlp`, or set cookies_from_browser for logged-in content.") from e
        raise
    files[:] = [f for f in dict.fromkeys(files) if Path(f).exists()]
    res = dict(files=files, imports=files, report=dict(downloaded=len(files), folder=str(folder)))
    if p["then"] and files:  # chain a Kerf feature onto the first download
        from . import license, media
        from .features import REGISTRY, coerce
        f = REGISTRY[p["then"]]
        license.check(f)
        sub = f.run(Timeline.from_media(files[0], media.probe), coerce(f.defaults, {}), ctx)
        res.update({k: v for k, v in sub.items() if k in ("timeline", "timelines", "text", "markers", "srt")})
        res["files"] = files + sub.get("files", [])
        res["report"]["then"] = sub.get("report", {})
    return res


def _download(o, p, chosen, folder, files):
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({**o, "noplaylist": True}) as y:
            y.download(chosen)
    except yt_dlp.utils.DownloadError:
        if not p["section"]:
            raise
        # Some sites (YouTube at times) refuse ranged fetches: download whole, then trim locally.
        from . import media
        full = []
        o2 = {**options({**p, "section": ""}, folder, full), "noplaylist": True}
        with yt_dlp.YoutubeDL(o2) as y:
            y.download(chosen)
        a, b = (_secs(x) for x in p["section"].split("-", 1))
        files.clear()
        for f in dict.fromkeys(full):
            src = Path(f)
            out = src.with_name(f"{src.stem} [{p['section'].replace(':', '.')}]{src.suffix}")
            media.ffmpeg("-ss", a, "-to", b, "-i", src, "-c", "copy", out)
            files.append(str(out))
