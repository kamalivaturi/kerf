"""Build the Kerf FX OpenFX plugin into build/panels/KerfFX.ofx.bundle (needs CMake and a C++ compiler).

The bundle sits next to the other panels so the Kerf installer copies it into the user's OFX folder."""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFX_REPO, OFX_COMMIT = "https://github.com/AcademySoftwareFoundation/openfx", "c3f1c2dcf4f51762b794c4fc21181b4a501be1bf"
# Captions: HarfBuzz shapes text (Indian scripts need it), stb_truetype draws the glyphs. Pinned, like OpenFX.
HB_REPO, HB_COMMIT = "https://github.com/harfbuzz/harfbuzz", "3ef8709829a5884517ad91a97b32b9435b2f20d1"  # 10.4.0
STB_REPO, STB_COMMIT = "https://github.com/nothings/stb", "d14d46f6b44456eb88beac58cba833a4135d4c89"
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


def checkout(repo, commit, into, marker):
    """One pinned commit of a source dependency (shallow), fetched once per build folder."""
    if not (into / marker).exists():
        into.mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", cwd=into)
        run("git", "fetch", "-q", "--depth", "1", repo, commit, cwd=into)
        run("git", "checkout", "-q", "FETCH_HEAD", cwd=into)
    return into


def main():
    headers = checkout(OFX_REPO, OFX_COMMIT, BUILD / "openfx", "include/ofxImageEffect.h")
    hb = checkout(HB_REPO, HB_COMMIT, BUILD / "harfbuzz", "src/harfbuzz.cc")
    stb = checkout(STB_REPO, STB_COMMIT, BUILD / "stb", "stb_truetype.h")
    run("cmake", "-S", ROOT / "ofx", "-B", BUILD / "cmake", f"-DOFX_INCLUDE={headers / 'include'}",
        f"-DHB_DIR={hb}", f"-DSTB_DIR={stb}", "-DCMAKE_BUILD_TYPE=Release")
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
