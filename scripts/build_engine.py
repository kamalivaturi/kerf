"""Freeze the Kerf engine into engine-dist/kerf-engine/ (PyInstaller onedir) with ffmpeg + ffprobe in bin/.

    python scripts/build_engine.py               # ffmpeg copied from PATH
    python scripts/build_engine.py --download    # static ffmpeg for this OS (what CI uses)

The folder is self-contained: the desktop app (desktop/) bundles it, and it is also the portable build
(kerf-engine serve → http://127.0.0.1:7878/app/). Run from the repo root after `npm run build` in ui/.
"""
import io
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "engine-dist"
EXE = ".exe" if sys.platform == "win32" else ""
FFMPEG = {  # static builds (GPL: includes libvidstab for the stabilizer)
    "win32": ["https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"],
    "linux": ["https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"],
    "darwin": [f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{'arm64' if platform.machine() == 'arm64' else 'amd64'}/release/{n}.zip"
               for n in ("ffmpeg", "ffprobe")],
}
EXCLUDE = ["torch", "torchaudio", "torchvision", "tensorflow", "jax", "scipy", "pandas", "matplotlib", "sklearn", "numba",
           "transformers", "librosa", "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "gi", "IPython", "jupyter", "notebook",
           "pytest", "sympy", "playwright", "selenium"]
DATA = ["ui/dist:ui/dist", "CHANGELOG.md:.", "NOTICES.md:.", "licenses:licenses", "mogrt:mogrt", "aftereffects:aftereffects"]


def fetch_ffmpeg(dest):
    for url in FFMPEG["darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "linux"]:
        print("downloading", url)
        blob = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kerf-build"}), timeout=600).read()
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                members = [(m, z.read(m)) for m in z.namelist()]
        else:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as t:
                members = [(m.name, t.extractfile(m).read()) for m in t.getmembers() if m.isfile()]
        for name, data in members:
            if Path(name).name in (f"ffmpeg{EXE}", f"ffprobe{EXE}"):
                f = dest / Path(name).name
                f.write_bytes(data)
                f.chmod(0o755)


FFMPEG_SOURCE = """ffmpeg and ffprobe in this folder: where they come from, and how to get their source

These two programs are FFmpeg (https://ffmpeg.org), free software you may use, change and share under the
GNU General Public License, version 3 or later (full text: FFMPEG-LICENSE-GPL-3.0.txt). Kerf only runs them;
Kerf's own code is MIT licensed (see NOTICES.md).

Build:   {version}
From:    {origin}
{configuration}

Complete corresponding source:
  FFmpeg itself, at the git revision in the build line above (the part after "-g"):
    https://git.ffmpeg.org/ffmpeg.git  (mirror: https://github.com/FFmpeg/FFmpeg)
  The scripts and every library the build compiles in, with their versions:
    {scripts}

Written offer: for at least three years after we last distribute this build, anyone can ask for the complete
corresponding source of these two programs, and we will provide it on a medium customarily used for software
interchange for no more than the cost of physically performing that distribution. Ask by opening an issue at
https://github.com/kamalivaturi/kerf/issues.
"""
SCRIPTS = {"win32": "https://github.com/BtbN/FFmpeg-Builds (build scripts; the release matching the date in the build line)",
           "linux": "https://github.com/BtbN/FFmpeg-Builds (build scripts; the release matching the date in the build line)",
           "darwin": "https://ffmpeg.martin-riedl.de (build scripts and per-build source listings)"}


def ffmpeg_notice(bin_dir, origin):
    """GPL: the licence beside the binaries, and exactly which source they were built from."""
    ff = bin_dir / f"ffmpeg{EXE}"
    lines = subprocess.run([str(ff), "-version"], capture_output=True, text=True, check=True).stdout.splitlines()
    config = next((ln for ln in lines if ln.startswith("configuration:")), "")  # the configure options are part of the source
    plat = "darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "linux"
    (bin_dir / "FFMPEG-SOURCE.txt").write_text(
        FFMPEG_SOURCE.format(version=lines[0], origin=origin, scripts=SCRIPTS[plat],
                             configuration=("Config:   " + config.split(":", 1)[1].strip()) if config else ""), encoding="utf-8")
    shutil.copy2(ROOT / "licenses" / "GPL-3.0.txt", bin_dir / "FFMPEG-LICENSE-GPL-3.0.txt")


def main():
    if not (ROOT / "ui/dist/index.html").exists():
        sys.exit("build the UI first: cd ui && npm ci && npm run build")
    shutil.rmtree(DIST, ignore_errors=True)
    sep = ";" if sys.platform == "win32" else ":"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "kerf-engine",
            "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "pyinstaller"), "--specpath", str(ROOT / "build"),
            "--collect-data", "faster_whisper", "--collect-binaries", "ctranslate2", "--collect-binaries", "onnxruntime",
            "--collect-binaries", "sherpa_onnx", "--collect-submodules", "sherpa_onnx",
            "--collect-submodules", "yt_dlp", "--copy-metadata", "yt_dlp"]
    for heavy in EXCLUDE:  # not used by Kerf; keeps a dev machine's extra packages out of the bundle
        args += ["--exclude-module", heavy]
    for d in DATA:
        src, dst = d.rsplit(":", 1)
        args += ["--add-data", f"{ROOT / src}{sep}{dst}"]
    subprocess.run([*args, str(ROOT / "scripts" / "engine_entry.py")], check=True, cwd=ROOT)
    out = DIST / "kerf-engine"
    bin_dir = out / "_internal" / "bin"  # kerf/__init__.py puts <package parent>/bin on PATH
    bin_dir.mkdir(parents=True, exist_ok=True)
    if "--download" in sys.argv:
        fetch_ffmpeg(bin_dir)
        origin = ", ".join(FFMPEG["darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "linux"])
    else:
        for tool in ("ffmpeg", "ffprobe"):
            found = shutil.which(tool)
            if not found:
                sys.exit(f"{tool} not on PATH: rerun with --download")
            shutil.copy2(found, bin_dir)
            for lib in Path(found).parent.glob("*.dll"):  # shared Windows builds keep av*.dll beside the exe
                shutil.copy2(lib, bin_dir)
        origin = "the ffmpeg on the build machine's PATH"
    ffmpeg_notice(bin_dir, origin)
    exe = out / f"kerf-engine{EXE}"
    print(subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=True).stdout.strip(), "->", out)


if __name__ == "__main__":
    main()
