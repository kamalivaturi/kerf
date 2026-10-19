"""Core checks. Run: python -m pytest tests  (or python tests/test_core.py). Needs ffmpeg on PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
TMP = Path(tempfile.mkdtemp(prefix="kerf-test-"))
os.environ["KERF_HOME_DIR"] = str(TMP / "home")  # isolate cache/presets/settings from the real ~/.kerf

from kerf import camera, features, llm, media  # noqa: E402
from kerf.silence import speech_ranges  # noqa: E402
from kerf.timeline import Clip, Timeline, invert, keep, merge, to_xmeml  # noqa: E402

VIDEO = TMP / "talk.mp4"


def setup_module(_=None):
    # 20 s: tone for 2 s, silence for 1 s, repeated (6 gaps)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20", "-f", "lavfi",
                    "-i", "aevalsrc='0.3*sin(2*PI*220*t)*lt(mod(t,3),2)':s=48000:d=20", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(VIDEO)], check=True)


def test_ranges():
    assert merge([(0, 1), (0.5, 2), (3, 4)]) == [(0, 2), (3, 4)]
    assert invert([(1, 2)], 5) == [(0.0, 1), (2, 5)]


def test_keep_ripple_remaps_time():
    tl = Timeline(video=[[Clip("a.mp4", 10, 20, 0)]], audio=[[]])
    c1, c2 = keep(tl, [(0, 2), (5, 7)]).video[0]
    assert (c1.src_in, c1.start, c1.dur) == (10, 0, 2)
    assert (c2.src_in, c2.start, c2.dur) == (15, 2, 2)  # source keeps its offset, record time closes the gap


def test_speech_ranges_merges_short_gaps():
    import numpy as np
    db = np.full(300, -80.0)
    db[0:100] = db[110:200] = -20  # the 0.1 s gap is shorter than min_silence → one segment
    assert speech_ranges(db, -40, min_silence=0.3, min_talk=0.2, pad_before=0, pad_after=0) == [(0.0, 2.0)]


def test_hysteresis_switches_and_respects_min_shot():
    segs = camera.hysteresis([0] * 30 + [1] * 30 + [0] * 3 + [1] * 30, hop=0.1, mn=2.0)
    assert [s[2] for s in segs] == [0, 1]  # the 0.3 s blip back to cam 0 is ignored
    assert all(b - a >= 2.0 - 1e-9 for a, b, _ in segs)


def test_silences_end_to_end_and_xml():
    res = features.run("silences", str(VIDEO), {}, TMP / "out")
    assert 3.0 < res["report"]["removed"] < 4.0, res["report"]  # 6 gaps × (1 s − 2×0.2 s margins)
    root = ET.parse(res["xml"][0]).getroot()
    assert len(root.find("sequence/media/video/track").findall("clipitem")) == 7


def test_enhance_never_deletes_source():
    res = features.run("enhance", str(VIDEO), {}, TMP / "out")
    assert VIDEO.exists(), "enhance must never delete the user's media"
    assert Path(res["files"][0]).exists()


def test_presets_round_trip():
    features.save_preset("zoom", "Mine", {"rhythm": "calm", "max_zoom": "125"})
    p = features.get_preset("zoom", "Mine")
    assert p["rhythm"] == "calm" and p["max_zoom"] == 125  # typed back from the form's string


def test_prompt_edit_runs_planned_chain():
    plan = {"summary": "tighten", "steps": [
        {"feature": "silences", "reason": "dead air", "params": [{"key": "preset", "value": "paced"}]},
        {"feature": "zoom", "reason": "energy", "params": []}]}
    orig = llm.complete
    llm.complete = lambda *a, **k: json.dumps(plan)  # no network: fake the provider's structured reply
    try:
        res = features.run("prompt_edit", str(VIDEO), {"prompt": "tighten it and add zooms"}, TMP / "out")
    finally:
        llm.complete = orig
    assert [s["feature"] for s in res["plan"]] == ["silences", "zoom"]
    assert res["xml"] and Path(res["xml"][0]).exists()


def test_download_options_map_to_yt_dlp():
    from kerf import download
    p = features.coerce(download.DOWNLOAD_DEFAULTS, {"quality": "720", "subtitles": True, "embed_subs": True,
                                                     "section": "01:00-01:30", "sponsorblock_remove": True})
    o = download.options(p, TMP, [])
    assert o["format"] == "bv*[height<=720]+ba/b[height<=720]/b" and o["merge_output_format"] == "mp4"
    keys = [pp["key"] for pp in o["postprocessors"]]
    assert "FFmpegEmbedSubtitle" in keys and "SponsorBlock" in keys and "download_ranges" in o
    a = download.options(features.coerce(download.DOWNLOAD_DEFAULTS, {"audio_only": True, "audio_format": "wav"}), TMP, [])
    assert a["format"] == "bestaudio/best" and a["postprocessors"][0]["preferredcodec"] == "wav"
    assert features.REGISTRY["download"].needs_timeline is False


def test_transcript_corrections_win_and_teach_vocabulary():
    from kerf import speech
    words = [dict(w=w, s=i * .5, e=i * .5 + .4) for i, w in enumerate("welcome to the curf channel".split())]
    fixed, learned = speech._apply_fix(words, 0, 2.4, "welcome to the Kerf channel")
    assert [w["w"] for w in fixed] == ["welcome", "to", "the", "Kerf", "channel"] and learned == ["Kerf"]
    assert fixed[0]["s"] == 0 and fixed[-1]["e"] == 2.4  # timing spread over the original span
    speech.fixed_path(str(VIDEO)).write_text(json.dumps(dict(language="en", words=fixed)), "utf-8")
    assert speech.transcribe(str(VIDEO))["words"][3]["w"] == "Kerf"  # served before any model runs
    assert speech.learn(learned) == ["Kerf"] and speech.learn(learned) == []  # no duplicates
    assert "hinglish" in speech.languages()["profiles"] and len(speech.languages()["codes"]) >= 99


def test_xmeml_keyframes_and_disabled():
    tl = Timeline(fps=30, video=[[Clip(str(VIDEO), 0, 2, 0, scale=[(0, 100), (1, 120)]),
                                  Clip(str(VIDEO), 2, 4, 2, enabled=False)]], audio=[[]])
    root = ET.fromstring(to_xmeml(tl, media.probe))
    assert len(list(root.iter("keyframe"))) == 2
    assert [c.findtext("enabled") for c in root.iter("clipitem")] == ["TRUE", "FALSE"]


if __name__ == "__main__":
    setup_module()
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(tests)} passed")
