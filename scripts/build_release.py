"""Build release artifacts into release/.

    python scripts/build_release.py [--skip-ui]          host packages (any OS):
        kerf-<v>.zip                  engine source + built UIs + host scripts + installers
        kerf-premiere-<v>.ccx         Premiere Pro UXP plugin (double-click → Creative Cloud installs it)
        kerf-aftereffects-<v>.zip     After Effects panel (Kerf.jsx) + installers
        kerf-resolve-<v>.zip          DaVinci Resolve script + installers
        kerf-<v>-py3-none-any.whl     pip install kerf (engine + CLI)
    python scripts/build_release.py --portable NAME      engine-dist/ → kerf-studio-portable-<v>-NAME.zip|.tar.gz
    python scripts/build_release.py --collect-desktop NAME   Tauri installers (.exe .msi .dmg .AppImage .deb .rpm)
    python scripts/build_release.py --sums               SHA256SUMS.txt for everything in release/
"""
import hashlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kerf import __version__ as V  # noqa: E402

OUT = ROOT / "release"
INCLUDE = ["kerf", "resolve", "aftereffects", "mogrt/kerf_mogrt_builder.jsx", "install", "docs", "tests", "scripts",
           "ui/dist", "ui/dist-uxp", "ui/src", "ui/public", "ui/package.json", "ui/package-lock.json", "ui/vite.config.ts",
           "ui/tsconfig.json", "ui/index.html", "start-kerf.cmd", "start-kerf.command", "start-kerf.sh", "pyproject.toml",
           "README.md", "LICENSE", "CHANGELOG.md"]
SKIP = {"__pycache__", "node_modules", ".pytest_cache"}
INSTALLERS = (".exe", ".msi", ".dmg", ".AppImage", ".deb", ".rpm")


def files(rel):
    p = ROOT / rel
    if p.is_file():
        yield p
    elif p.is_dir():
        yield from (f for f in sorted(p.rglob("*")) if f.is_file() and not SKIP & set(f.parts))


def zip_paths(dest, paths, base, prefix=""):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in paths:
            z.write(f, prefix + f.relative_to(base).as_posix())
    return dest


def packages():
    if "--skip-ui" not in sys.argv:
        subprocess.run(["npm.cmd" if sys.platform == "win32" else "npm", "run", "build"], cwd=ROOT / "ui", check=True)
    if not (ROOT / "ui/dist-uxp/manifest.json").exists():
        sys.exit("ui/dist-uxp missing: build the UI first (cd ui && npm install && npm run build)")
    zip_paths(OUT / f"kerf-{V}.zip", [f for rel in INCLUDE for f in files(rel)], ROOT, prefix=f"kerf-{V}/")
    zip_paths(OUT / f"kerf-premiere-{V}.ccx", list(files("ui/dist-uxp")), ROOT / "ui/dist-uxp")  # a .ccx is a zip of the plugin
    host = lambda *rels: [f for rel in (*rels, "install", "README.md", "LICENSE") for f in files(rel)]
    zip_paths(OUT / f"kerf-aftereffects-{V}.zip", host("aftereffects"), ROOT, prefix=f"kerf-aftereffects-{V}/")
    zip_paths(OUT / f"kerf-resolve-{V}.zip", host("resolve"), ROOT, prefix=f"kerf-resolve-{V}/")
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-q", "-w", str(OUT)], check=True)


def portable(name):
    eng = ROOT / "engine-dist" / "kerf-engine"
    if not eng.is_dir():
        sys.exit("engine-dist/kerf-engine missing: python scripts/build_engine.py")
    base = f"kerf-studio-portable-{V}-{name}"
    extras = [ROOT / n for n in ("README.md", "LICENSE", "start-kerf.cmd", "start-kerf.command", "start-kerf.sh")]
    if name.startswith("windows"):
        with zipfile.ZipFile(OUT / f"{base}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(eng.rglob("*")):
                if f.is_file():
                    z.write(f, f"{base}/kerf-engine/{f.relative_to(eng).as_posix()}")
            for f in extras:
                z.write(f, f"{base}/{f.name}")
    else:  # tar keeps the executable bits
        with tarfile.open(OUT / f"{base}.tar.gz", "w:gz") as t:
            t.add(eng, f"{base}/kerf-engine")
            for f in extras:
                t.add(f, f"{base}/{f.name}")


def collect_desktop(name):
    bundle = ROOT / "desktop/src-tauri/target/release/bundle"
    found = [f for f in bundle.rglob("*") if f.is_file() and f.suffix in INSTALLERS]
    if not found:
        sys.exit(f"no installers under {bundle}: run `npx tauri build` in desktop/")
    for f in found:
        dest = OUT / f"Kerf-Studio-{V}-{name}{'-setup' if f.name.endswith('-setup.exe') else ''}{f.suffix}"
        shutil.copy2(f, dest)
        print(dest.name)


def sums():
    lines = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                    for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt")
    (OUT / "SHA256SUMS.txt").write_text(lines)
    print(lines, end="")


def main():
    OUT.mkdir(exist_ok=True)
    a = sys.argv[1:]
    if "--portable" in a:
        portable(a[a.index("--portable") + 1])
    elif "--collect-desktop" in a:
        collect_desktop(a[a.index("--collect-desktop") + 1])
    elif "--sums" in a:
        sums()
    else:
        packages()
        sums()


if __name__ == "__main__":
    main()
