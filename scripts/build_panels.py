"""Bundle the editor panels that the Kerf installer puts in place (build/panels/):

    kerf-premiere.ccx          Premiere Pro UXP panel (ui/dist-uxp), installed with Adobe's own plugin installer
    com.kerf.aftereffects/     After Effects HTML panel (scripts/build_cep.py)
Run `npm run build` in ui/ first.
"""
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_cep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "panels"


def main():
    uxp = ROOT / "ui" / "dist-uxp"
    if not (uxp / "manifest.json").is_file():
        sys.exit("ui/dist-uxp is missing: run `npm run build` in ui/")
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(OUT / "kerf-premiere.ccx", "w", zipfile.ZIP_DEFLATED) as z:  # a .ccx is a zip of the plugin
        for f in sorted(p for p in uxp.rglob("*") if p.is_file() and p.suffix != ".map"):
            z.write(f, f.relative_to(uxp).as_posix())
    shutil.copytree(build_cep.build(), OUT / "com.kerf.aftereffects")
    print("panels in", OUT)


if __name__ == "__main__":
    main()
