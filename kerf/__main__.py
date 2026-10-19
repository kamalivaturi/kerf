"""CLI.  python -m kerf serve | features | run FEATURE --media FILE [--set key=value ...]"""
import argparse
import json
import sys

from . import __version__, features, server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kerf", description=f"Kerf {__version__}")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the local API for the editor panels")
    s.add_argument("--port", type=int, default=server.PORT)
    sub.add_parser("features", help="list features and their default settings")
    r = sub.add_parser("run", help="run a feature on a media file or timeline JSON")
    r.add_argument("feature")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--media", help="single media file (treated as a one-clip timeline)")
    src.add_argument("--timeline", help="timeline JSON exported by a panel")
    r.add_argument("--preset", help="named preset (built-in or saved)")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    r.add_argument("--out", help="output folder (default ~/.kerf/output)")
    b = sub.add_parser("batch", help="run a feature over many files or a folder")
    b.add_argument("feature")
    b.add_argument("paths", nargs="+", help="media files and/or folders")
    b.add_argument("--render", action="store_true", help="also render each result to MP4")
    b.add_argument("--preset")
    b.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    b.add_argument("--out")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        server.serve(a.port)
    elif a.cmd == "batch":
        from pathlib import Path
        exts = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".wav", ".mp3", ".m4a", ".mxf"}
        files = [f for p in map(Path, a.paths) for f in (sorted(p.rglob("*")) if p.is_dir() else [p])
                 if f.suffix.lower() in exts]
        params = features.get_preset(a.feature, a.preset) if a.preset else {}
        params.update(kv.split("=", 1) for kv in a.set)
        print(json.dumps(features.run_batch(a.feature, files, params, a.out, a.render), indent=1))
    elif a.cmd == "features":
        print(json.dumps(features.describe(), indent=1, default=str))
    else:
        params = features.get_preset(a.feature, a.preset) if a.preset else {}
        params.update(kv.split("=", 1) for kv in a.set)
        tl = json.load(open(a.timeline, encoding="utf-8")) if a.timeline else a.media
        print(json.dumps(features.run(a.feature, tl, params, a.out), indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
