"""Local JSON API used by the Premiere Pro and After Effects panels. Binds 127.0.0.1 only.

Every route except /health needs header X-Kerf-Token (the value in ~/.kerf/token), so random
web pages in a browser can't drive the engine.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pathlib import Path

from . import REPO, __version__, captions, features, hosts, license, media, mogrt, settings, speech, tools
from .timeline import Timeline

PORT = 7878
TOKEN_FILE = media.HOME / "token"
LOCATOR = media.HOME / "engine.json"  # port, token file and helper: the one place every panel looks
TOKEN = ""


def token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(t)
    return t


def vtuple(v):
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def check_update():
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "kerf"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.loads(r.read())
        return dict(current=__version__, latest=rel["tag_name"], url=rel["html_url"],
                    update_available=vtuple(rel["tag_name"]) > vtuple(__version__),
                    # Kerf Studio started this engine and updates itself (unless switched off in Settings)
                    auto=bool(os.environ.get("KERF_STUDIO")) and settings.get("auto_update") != "off")
    except Exception as e:
        return dict(current=__version__, update_available=False, error=str(e))


ERRORS = media.HOME / "logs" / "errors.jsonl"


def _redact(text):
    return str(text).replace(str(Path.home()), "~")


def log_error(path, e):
    """Unexpected engine errors, kept locally (home folder redacted) for Settings → Report a bug."""
    ERRORS.parent.mkdir(parents=True, exist_ok=True)
    rows = ERRORS.read_text("utf-8").splitlines()[-49:] if ERRORS.exists() else []
    rows.append(json.dumps(dict(t=time.strftime("%Y-%m-%d %H:%M:%S"), route=path.split("?")[0], version=__version__,
                                error=_redact(f"{type(e).__name__}: {e}"), trace=_redact(traceback.format_exc(limit=8)))))
    ERRORS.write_text("".join(r + "\n" for r in rows), "utf-8")


def diagnostics():
    import platform
    from . import render
    ff = (subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True, text=True).stdout.splitlines() or [""])[0]
    errs = [json.loads(r) for r in ERRORS.read_text("utf-8").splitlines()[-10:]] if ERRORS.exists() else []
    return dict(version=__version__, os=platform.platform(), python=platform.python_version(), frozen=bool(getattr(sys, "frozen", False)),
                ffmpeg=ff, encoders=render.candidates("h264", False), errors=errs)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Kerf-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _guard(self):
        if secrets.compare_digest(self.headers.get("X-Kerf-Token", ""), TOKEN):
            return True
        self._send(401, dict(error="missing or wrong X-Kerf-Token"))
        return False

    def _handle(self, fn):
        try:
            self._send(200, fn())
        except PermissionError as e:
            self._send(402, dict(error=str(e)))
        except (KeyError, ValueError, FileNotFoundError) as e:
            self._send(400, dict(error=str(e), trace=traceback.format_exc(limit=4)))
        except Exception as e:
            log_error(self.path, e)
            self._send(500, dict(error=f"{type(e).__name__}: {e}", trace=traceback.format_exc(limit=6)))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/health":
            return self._send(200, dict(ok=True, version=__version__))
        if u.path == "/" or u.path.startswith("/app"):  # no browser app: Kerf lives inside the editors
            return self._send(404, dict(error="Kerf runs inside Premiere Pro, After Effects and DaVinci Resolve: "
                                              "open the Kerf panel there."))
        img = u.path == "/mogrt/media" and secrets.compare_digest(q.get("token", ""), TOKEN)  # <img> can't send headers
        if not img and not self._guard():
            return
        routes = {
            "/features": lambda: dict(features=features.describe(), editors=features.EDITORS, plugin_errors=features.plugin_errors),
            "/presets": lambda: (features.get_preset(q["feature"], q["name"]) if "name" in q
                                 else features.list_presets(q["feature"])),
            "/update": check_update,
            "/license": license.status,
            "/settings": settings.public,
            "/mogrt": lambda: dict(library=mogrt.library(), catalog=mogrt.catalog(), anims=list(mogrt.ANIMS),
                                   looks=list(mogrt.LOOKS), kinds=list(mogrt.KINDS), formats=list(mogrt.FORMATS)),
            "/changelog": lambda: dict(text=(Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text("utf-8")),
            "/languages": speech.languages,
            "/fx": lambda: dict(presets=tools.fx_list()),
            "/diagnostics": diagnostics,
            "/host": hosts.status,
        }
        if u.path == "/mogrt/media":  # previews of library entries only (never arbitrary paths)
            e = next((x for x in mogrt.library() if x["id"] == q.get("id")), None)
            f = Path(e.get(q.get("kind", "gif")) or "") if e else None
            if not f or not f.is_file():
                return self._send(404, dict(error="no preview"))
            return self._bytes(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        if u.path not in routes:
            return self._send(404, dict(error="not found"))
        self._handle(routes[u.path])

    def do_POST(self):
        if not self._guard():
            return
        n = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(n) or b"{}")
        routes = {
            "/run": lambda: features.run(b["feature"], b["timeline"], b.get("params"), b.get("out_dir"), b.get("host")),
            "/presets": lambda: features.save_preset(b["feature"], b["name"], b["params"]) or dict(ok=True),
            "/presets/delete": lambda: features.delete_preset(b["feature"], b["name"]) or dict(ok=True),
            "/batch": lambda: features.run_batch(b["feature"], b["paths"], b.get("params"), b.get("out_dir"),
                                                 b.get("render", False)),
            "/settings": lambda: settings.save(b) or settings.public(),
            "/media": lambda: dict(timeline=Timeline.from_media(b["path"], media.probe).to_dict()),
            "/mogrt/import": lambda: mogrt.import_mogrt(b["path"]),
            "/mogrt/install-pack": lambda: mogrt.install_pack(b.get("path", "")),
            "/mogrt/studio": lambda: mogrt.studio(b["base"], b.get("overrides", {}), b["name"]),
            "/mogrt/build": lambda: mogrt.build([s for s in mogrt.catalog() if not b.get("ids") or s["id"] in b["ids"]]),
            "/captions/preview": lambda: captions.preview(b.get("path", ""), b.get("params", {}), float(b.get("t", 1.0)),
                                                          b.get("aspect", "auto"), b.get("safe", True), b.get("size")),
            "/license/activate": lambda: license.activate(b["key"]),
            "/license/deactivate": license.deactivate,
            "/fx/save": lambda: tools.fx_save(b["name"], b["chain"]),
            "/fx/get": lambda: tools.fx_get(b["name"]),
            "/fx/delete": lambda: tools.fx_delete(b["name"]),
            "/frame": lambda: tools.frame_image(Timeline.from_dict(b["timeline"]) if isinstance(b["timeline"], dict)
                                                else Timeline.from_media(b["timeline"], media.probe), b.get("t")),
            "/presets/export": lambda: features.export_presets(b.get("features")),
            "/presets/import": lambda: features.import_presets(b["bundle"]),
            "/host/heartbeat": lambda: hosts.beat(b["host"], b.get("state") or {}),
        }
        path = urlparse(self.path).path
        if path not in routes:
            return self._send(404, dict(error="not found"))
        self._handle(routes[path])

    def _bytes(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("kerf: " + fmt % args + "\n")


def serve(port=PORT, follow=False):
    global TOKEN
    TOKEN = token()
    if follow:
        hosts.follow()  # Kerf only runs alongside Premiere Pro, After Effects or Resolve
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # bound first: a second engine never rewrites the locator
    print(f"Kerf {__version__} listening on http://127.0.0.1:{srv.server_port}  (token in {TOKEN_FILE})", flush=True)
    LOCATOR.write_text(json.dumps(dict(port=srv.server_port, token_file=str(TOKEN_FILE),
                                       helper=os.environ.get("KERF_HELPER", ""), version=__version__)))
    try:
        srv.serve_forever()
    finally:  # a clean stop takes its locator along, so panels fall back to the default port, not a dead one
        try:
            if json.loads(LOCATOR.read_text()).get("port") == srv.server_port:
                LOCATOR.unlink()
        except (OSError, ValueError):
            pass
