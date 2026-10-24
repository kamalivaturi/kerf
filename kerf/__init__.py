"""Kerf: free, open-source AI editing assistant for Premiere Pro, After Effects and DaVinci Resolve."""
import os
from pathlib import Path

__version__ = "0.3.0"
# Desktop/portable builds ship ffmpeg + ffprobe in <bundle>/bin: put them first on PATH for every subprocess.
_BIN = Path(__file__).resolve().parent.parent / "bin"
if _BIN.is_dir():
    os.environ["PATH"] = str(_BIN) + os.pathsep + os.environ.get("PATH", "")
# GitHub "owner/repo" used by the in-panel update checker.
REPO = os.environ.get("KERF_REPO", "kamalivaturi/kerf")
