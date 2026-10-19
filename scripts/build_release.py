"""Build release artifacts into release/:
  kerf-<v>.zip              engine + built UIs + Resolve script + installers (what users download)
  kerf-premiere-<v>.ccx     Premiere UXP plugin package (double-click to install via Creative Cloud)
  SHA256SUMS.txt
Run from the repo root:  python scripts/build_release.py [--skip-ui]
"""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kerf import __version__  # noqa: E402

OUT = ROOT / "release"
INCLUDE = ["kerf", "resolve", "install", "docs", "tests", "ui/dist", "ui/dist-uxp", "ui/src", "ui/public",
           "ui/package.json", "ui/package-lock.json", "ui/vite.config.ts", "ui/tsconfig.json", "ui/index.html",
           "start-kerf.cmd", "start-kerf.command", "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md"]
SKIP = {"__pycache__", "node_modules", ".pytest_cache"}


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


def main():
    if "--skip-ui" not in sys.argv:
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm, "run", "build"], cwd=ROOT / "ui", check=True)
    if not (ROOT / "ui/dist-uxp/manifest.json").exists():
        sys.exit("ui/dist-uxp missing: build the UI first (cd ui && npm install && npm run build)")
    OUT.mkdir(exist_ok=True)
    bundle = OUT / f"kerf-{__version__}.zip"
    zip_paths(bundle, [f for rel in INCLUDE for f in files(rel)], ROOT, prefix=f"kerf-{__version__}/")
    ccx = OUT / f"kerf-premiere-{__version__}.ccx"
    zip_paths(ccx, list(files("ui/dist-uxp")), ROOT / "ui/dist-uxp")  # a .ccx is a zip of the plugin folder
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in (bundle, ccx))
    (OUT / "SHA256SUMS.txt").write_text(sums)
    print(sums, end="")


if __name__ == "__main__":
    main()
