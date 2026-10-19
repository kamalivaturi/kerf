"""Calibration kit for Kerf's FCP7 XML motion export. Import the XMLs into an NLE and compare
what it shows against the expected values printed below.

    python scripts/calibrate_xml.py OUT_DIR

calib_main.xml (1920x1080 @30):
  clip A  0–4 s   center (0.25, 0.25), scale 100   → image moved right 480 px and down 270 px
  clip B  4–8 s   source starts at 5 s; scale keyframes 100 at clip-local 0.5 s, 150 at 1.5 s
calib_916.xml (1080x1920): scale 177.78, center x 0.2 → image moved right 216 px
plus real Kerf Zoom (smooth, anchor 0.75/0.25) and 9:16 Resize outputs of the same media.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kerf import features, media  # noqa: E402
from kerf.timeline import Clip, Timeline, to_xmeml  # noqa: E402


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src = out / "calib.mp4"
    if not src.exists():
        media.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12", "-f", "lavfi",
                     "-i", "aevalsrc='0.3*sin(2*PI*220*t)*lt(mod(t,3),2)':s=48000:d=12",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src)
    s = str(src)
    main_tl = Timeline(30, 1920, 1080, "Kerf calib main",
                       video=[[Clip(s, 0, 4, 0, scale=[(0, 100.0)], center=[(0, 0.25, 0.25)]),
                               Clip(s, 5, 9, 4, scale=[(0.5, 100.0), (1.5, 150.0)])]],
                       audio=[[Clip(s, 0, 4, 0), Clip(s, 5, 9, 4)]])
    tall = Timeline(30, 1080, 1920, "Kerf calib 916",
                    video=[[Clip(s, 0, 4, 0, scale=[(0, 177.78)], center=[(0, 0.2, 0.0)])]], audio=[[Clip(s, 0, 4, 0)]])
    for name, tl in (("calib_main.xml", main_tl), ("calib_916.xml", tall)):
        (out / name).write_text(to_xmeml(tl, media.probe), "utf-8")
    z = features.run("zoom", s, dict(style="smooth", anchor_x=0.75, anchor_y=0.25, max_zoom=150, rhythm="energetic",
                                     triggers="cuts,speaking"), out)
    r = features.run("resize", s, dict(format="9:16", follow_subject=False, anchor_x=0.75), out)
    print("\n".join([str(out / "calib_main.xml"), str(out / "calib_916.xml"), *z["xml"], *r["xml"]]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "calibration")
