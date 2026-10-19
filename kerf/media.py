"""ffmpeg/ffprobe helpers and cached audio loudness envelopes."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np

HOME = Path(os.environ.get("KERF_HOME_DIR", Path.home() / ".kerf"))
CACHE = HOME / "cache"
SR = 16000
HOP = 0.01  # seconds per envelope frame
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def cache_key(path, *extra):
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime}|{extra}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def ffmpeg(*args, cwd=None):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *map(str, args)], check=True, cwd=cwd)


@functools.lru_cache(maxsize=None)
def probe(path):
    if Path(path).suffix.lower() in IMAGE_EXT:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        h, w = img.shape[:2] if img is not None else (1080, 1920)
        return dict(duration=0.0, fps=0.0, width=w, height=h, channels=0, sample_rate=48000)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    info = dict(duration=float(d["format"].get("duration", 0) or 0), fps=0.0, width=0, height=0,
                channels=0, sample_rate=48000)
    for s in d["streams"]:
        if s["codec_type"] == "video" and not info["width"] and s.get("disposition", {}).get("attached_pic") != 1:
            num, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1").split("/")
            info.update(fps=float(num) / float(den or 1) if float(num) else 30.0,
                        width=int(s["width"]), height=int(s["height"]))
        elif s["codec_type"] == "audio" and not info["channels"]:
            info.update(channels=int(s.get("channels", 2)), sample_rate=int(s.get("sample_rate", 48000)))
    return info


def load_audio(path, start=0.0, dur=None, sr=SR):
    """Mono float32 PCM via ffmpeg."""
    args = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path)]
    if dur:
        args += ["-t", str(dur)]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(args, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def envelope(path):
    """RMS loudness in dBFS, one value per HOP seconds of the whole file (cached)."""
    f = CACHE / f"{cache_key(path, 'env', HOP)}.npy"
    if f.exists():
        return np.load(f)
    if not probe(path)["channels"]:
        return np.full(int(probe(path)["duration"] / HOP) + 1, -120.0, np.float32)
    a = load_audio(path)
    n = int(SR * HOP)
    frames = a[: len(a) // n * n].reshape(-1, n)
    db = (20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)).astype(np.float32)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(f, db)
    return db
