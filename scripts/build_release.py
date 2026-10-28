"""Build release artifacts into release/.

    python scripts/build_release.py [--skip-ui]          host packages (any OS):
        kerf-<v>.zip                  engine source + built UIs + host scripts + installers
        kerf-premiere-<v>.ccx         Premiere Pro UXP plugin (double-click → Creative Cloud installs it)
        kerf-aftereffects-<v>.zip     After Effects panel (Kerf.jsx) + installers
        kerf-<v>-py3-none-any.whl     pip install kerf (engine + CLI)
    python scripts/build_release.py --portable NAME      engine-dist/ → kerf-studio-portable-<v>-NAME.zip|.tar.gz
    python scripts/build_release.py --collect-desktop NAME   Tauri installers (.exe .msi .dmg .AppImage .deb .rpm)
    python scripts/build_release.py --mogrt-pack         kerf-mogrt-pack-<v>.zip from the built library (needs After Effects once)
    python scripts/build_release.py --updater-manifest OWNER/REPO   latest.json (signed auto-update feed)
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
INCLUDE = ["kerf", "aftereffects", "ofx", "mogrt/kerf_mogrt_builder.jsx", "install", "docs", "tests", "scripts",
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
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-q", "-w", str(OUT)], check=True)


def portable(name):
    eng = ROOT / "engine-dist" / "kerf-engine"
    if not eng.is_dir():
        sys.exit("engine-dist/kerf-engine missing: python scripts/build_engine.py")
    base = f"kerf-portable-{V}-{name}"
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


# Tauri output → release name suffix. The *.sig files are the updater signatures of the packages before them.
KINDS = [("-setup.exe", "-setup.exe"), (".msi", ".msi"), (".dmg", ".dmg"), (".app.tar.gz", ".app.tar.gz"),
         (".AppImage", ".AppImage"), (".deb", ".deb"), (".rpm", ".rpm")]
UPDATER = {"windows-x64": ("windows-x86_64", "-setup.exe"), "macos-arm64": ("darwin-aarch64", ".app.tar.gz"),
           "macos-x64": ("darwin-x86_64", ".app.tar.gz"), "linux-x64": ("linux-x86_64", ".AppImage")}


def collect_desktop(name):
    bundle = ROOT / "desktop/src-tauri/target/release/bundle"
    n = 0
    for f in (f for f in bundle.rglob("*") if f.is_file()):
        sig = f.name.endswith(".sig")
        base = f.name[:-4] if sig else f.name
        kind = next((k for k in KINDS if base.endswith(k[0])), None)
        if kind and not (kind[0] == ".exe" and not base.endswith("-setup.exe")):
            dest = OUT / f"Kerf-{V}-{name}{kind[1]}{'.sig' if sig else ''}"
            shutil.copy2(f, dest)
            print(dest.name)
            n += 1
    if not n:
        sys.exit(f"no installers under {bundle}: run `npx tauri build` in desktop/")


def updater_manifest(repo):
    """latest.json for the Kerf updater, from the signed packages collected into release/."""
    import datetime
    import json
    sections = (ROOT / "CHANGELOG.md").read_text("utf-8").split(chr(10) + "## ")
    notes = sections[1].partition(chr(10))[2].strip()  # this version's entry, without its heading
    platforms = {}
    for name, (key, suffix) in UPDATER.items():
        pkg = OUT / f"Kerf-{V}-{name}{suffix}"
        sig = pkg.with_name(pkg.name + ".sig")
        if pkg.exists() and sig.exists():
            platforms[key] = dict(signature=sig.read_text().strip(),
                                  url=f"https://github.com/{repo}/releases/download/v{V}/{pkg.name}")
    if not platforms:
        sys.exit("no signed updater packages in release/ (TAURI_SIGNING_PRIVATE_KEY missing at build time?)")
    (OUT / "latest.json").write_text(json.dumps(dict(version=V, notes=notes, platforms=platforms,
                                                     pub_date=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")), indent=1))
    print("latest.json:", ", ".join(platforms))


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
    elif "--updater-manifest" in a:
        updater_manifest(a[a.index("--updater-manifest") + 1])
    elif "--mogrt-pack" in a:  # after building the pack with After Effects: python -c "from kerf import mogrt; mogrt.build(mogrt.catalog())"
        from kerf import mogrt
        print(mogrt.export_pack(OUT / f"kerf-mogrt-pack-{V}.zip"))
    elif "--sums" in a:
        sums()
    else:
        packages()
        sums()


if __name__ == "__main__":
    main()
