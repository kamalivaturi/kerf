"""Which editors are running (process list) and what their Kerf panels last reported (heartbeats).

`follow()` makes the engine exit once no editor has run for a grace period, so Kerf only lives alongside
Premiere Pro, After Effects or DaVinci Resolve (Settings → "Run only while an editor is open").
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

from . import settings

GRACE = 60   # seconds without any editor before the engine stops
FRESH = 6    # a panel heartbeat older than this is stale
LIVE: dict = {}  # host -> last heartbeat {project, sequence, playhead, fps, width, height, t}
_cache = [0.0, set()]
_seen = [time.time()]


def editor_of(process: str):
    """Process path/name → host id. Covers Windows, macOS and Linux names, yearly and Beta builds."""
    n = re.sub(r"\.exe$", "", os.path.basename(process.strip().strip('"')), flags=re.I).lower()
    n = re.sub(r"\s*(\(beta\)|20\d\d)$", "", n).strip()
    if n.startswith("adobe premiere pro"):
        return "premiere"
    if n in ("afterfx", "after effects", "adobe after effects"):
        return "aftereffects"
    if n == "resolve":
        return "resolve"
    return None


def _processes():
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return [line.split('","')[0].strip('"') for line in out.splitlines()]
    return subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, errors="replace").stdout.splitlines()


def running():
    """Host ids whose editor process is running (cached for 5 s: tasklist takes ~1 s)."""
    if time.time() - _cache[0] > 5:
        try:
            _cache[1] = {h for h in map(editor_of, _processes()) if h}
        except OSError:
            pass  # keep the last answer if the process list can't be read
        _cache[0] = time.time()
    return _cache[1]


def beat(host, state):
    if host not in ("premiere", "aftereffects", "resolve"):
        raise ValueError(f"unknown host {host!r}")
    LIVE[host] = dict(state, t=time.time())
    return dict(ok=True)


def _active():
    now = time.time()
    live = {h: s for h, s in LIVE.items() if now - s["t"] < FRESH}
    if running() or live:
        _seen[0] = now
    return live


def status():
    live = _active()
    follow_on = settings.get("follow_editors") != "off"
    left = int(_seen[0] + GRACE - time.time())
    return dict(running=sorted(running() | set(live)), live=live, follow=follow_on,
                exit_in=max(0, left) if follow_on and FOLLOWING[0] and left < GRACE else None)


FOLLOWING = [False]


def follow(grace=GRACE):
    """Exit the engine once no editor (or panel heartbeat) has been seen for `grace` seconds."""
    FOLLOWING[0] = True

    def loop():
        while True:
            time.sleep(5)
            _active()
            if settings.get("follow_editors") == "off":
                _seen[0] = time.time()
            elif time.time() - _seen[0] > grace:
                print("kerf: no editor running, stopping the engine", flush=True)
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()
