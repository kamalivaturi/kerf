"""Assemble the After Effects HTML panel: aftereffects/cep + the built Kerf UI (ui/dist) + Kerf.jsx.

    python scripts/build_cep.py            → build/cep/com.kerf.aftereffects/
    python scripts/build_cep.py --install  → also copies it into this user's CEP extensions folder
Run `npm run build` in ui/ first.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "cep" / "com.kerf.aftereffects"


def build():
    ui = ROOT / "ui" / "dist"
    if not (ui / "index.html").is_file():
        sys.exit("ui/dist is missing: run `npm run build` in ui/")
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(ROOT / "aftereffects" / "cep", OUT)
    shutil.copytree(ui, OUT / "ui")
    shutil.copy2(ROOT / "aftereffects" / "Kerf.jsx", OUT / "Kerf.jsx")
    return OUT


def user_extensions():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Adobe" / "CEP" / "extensions"
    return Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions"


if __name__ == "__main__":
    out = build()
    print("built", out)
    if "--install" in sys.argv:
        dest = user_extensions() / out.name
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(out, dest)
        print("installed", dest)
