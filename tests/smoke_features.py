"""Smoke test: every feature with its default settings on a short talking-style clip.

A feature passes if it runs, or stops with a plain-language ValueError/PermissionError telling the editor what it
needs (an API key, a music file, a URL...). Any other exception is a bug.  python tests/smoke_features.py [name ...]
"""
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kerf import features  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="kerf-smoke-"))
VIDEO, MUSIC = TMP / "clip.mp4", TMP / "music.wav"
EXTRA = {  # inputs a real editor would pick
    "beat_sync": dict(music=str(MUSIC)), "music": dict(music=str(MUSIC)), "beat_markers": dict(music=str(MUSIC)),
    "render": dict(quality="draft"), "pipeline": dict(steps='[{"feature": "silences", "params": {}}]'),
}


def media():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12", "-f", "lavfi",
                    "-i", "aevalsrc='0.3*sin(2*PI*220*t)*lt(mod(t,3),2)':s=48000:d=12", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(VIDEO)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t,0.5),0.03)':s=44100:d=12", str(MUSIC)], check=True)


def main(names):
    media()
    rows, bugs = [], 0
    for name in names or list(features.REGISTRY):
        t0 = time.time()
        try:
            res = features.run(name, str(VIDEO) if features.REGISTRY[name].needs_timeline else None,
                               EXTRA.get(name, {}), TMP / "out", host="premiere")
            status, note = "ok", f"{len(res.get('xml', []))} xml, {len(res.get('files', []) or [])} files"
        except (ValueError, PermissionError, FileNotFoundError) as e:
            status, note = "needs input", str(e).splitlines()[0][:110]
        except Exception as e:  # a crash: report with the trace
            status, note, bugs = "BUG", f"{type(e).__name__}: {e}"[:200], bugs + 1
            traceback.print_exc()
        rows.append((name, status, round(time.time() - t0, 1), note))
        print(f"{name:14} {status:12} {rows[-1][2]:6}s  {note}", flush=True)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(rows)} features: {sum(r[1] == 'ok' for r in rows)} ok, {sum(r[1] == 'needs input' for r in rows)} need input, {bugs} bugs")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
