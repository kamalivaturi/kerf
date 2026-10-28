"""Build the Kerf FX OpenFX plugin into build/panels/KerfFX.ofx.bundle (needs CMake and a C++ compiler).

The bundle sits next to the other panels so the Kerf installer copies it into the user's OFX folder."""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFX_REPO, OFX_COMMIT = "https://github.com/AcademySoftwareFoundation/openfx", "c3f1c2dcf4f51762b794c4fc21181b4a501be1bf"
BUILD = ROOT / "build" / "ofx"
ARCH = {"Windows": "Win64", "Darwin": "MacOS", "Linux": "Linux-x86-64"}[platform.system()]
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>KerfFX.ofx</string>
<key>CFBundleIdentifier</key><string>com.kerf.fx</string>
<key>CFBundlePackageType</key><string>BNDL</string>
<key>CFBundleShortVersionString</key><string>{v}</string>
</dict></plist>
"""


def run(*cmd, cwd=None):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), cwd=cwd, check=True)


def main():
    headers = BUILD / "openfx"
    if not (headers / "include" / "ofxImageEffect.h").exists():
        headers.mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", cwd=headers)
        run("git", "fetch", "-q", "--depth", "1", OFX_REPO, OFX_COMMIT, cwd=headers)
        run("git", "checkout", "-q", "FETCH_HEAD", cwd=headers)
    run("cmake", "-S", ROOT / "ofx", "-B", BUILD / "cmake", f"-DOFX_INCLUDE={headers / 'include'}",
        "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", BUILD / "cmake", "--config", "Release")
    # Visual Studio puts each configuration in its own folder; single-config generators build in place
    built = next(p for p in (BUILD / "cmake" / "Release" / "KerfFX.ofx", BUILD / "cmake" / "KerfFX.ofx") if p.is_file())

    bundle = ROOT / "build" / "panels" / "KerfFX.ofx.bundle"
    shutil.rmtree(bundle, ignore_errors=True)
    (bundle / "Contents" / ARCH).mkdir(parents=True)
    shutil.copy2(built, bundle / "Contents" / ARCH / "KerfFX.ofx")
    if ARCH == "MacOS":
        sys.path.insert(0, str(ROOT))
        from kerf import __version__
        (bundle / "Contents" / "Info.plist").write_text(PLIST.format(v=__version__))
    print("bundle", bundle)


if __name__ == "__main__":
    main()
