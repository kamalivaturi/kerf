"""Core checks. Run: python -m pytest tests  (or python tests/test_core.py). Needs ffmpeg on PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import pytest
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


def test_beat_detection_and_sound_features():
    from kerf import sound
    click = TMP / "click120.wav"
    media.ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t,0.5),0.03)':s=44100:d=20", click)
    bt, bpm = sound.beats(str(click))
    assert abs(bpm - 120) <= 1.5, bpm
    assert all(abs((b - bt[0]) % 0.5) < 0.05 or abs((b - bt[0]) % 0.5 - 0.5) < 0.05 for b in bt[:20])
    r = features.run("beat_sync", str(VIDEO), {"music": str(click)}, TMP / "out")
    assert r["report"]["cuts"] > 20 and r["xml"]
    r = features.run("pipeline", str(VIDEO), {"steps": json.dumps([{"feature": "silences"},
                                                                    {"feature": "sfx", "params": {"min_gap": 1.0}}])}, TMP / "out")
    assert r["report"]["steps"][1]["report"]["effects"] == 6  # one effect per silence cut


def test_preset_share_caption_preview_and_hybrid():
    features.save_preset("captions", "Share Me", {"font": "Impact", "outline": "3"})
    bundle = features.export_presets(["captions"])
    features.delete_preset("captions", "Share Me")
    assert features.import_presets(json.dumps(bundle))["imported"] == ["captions/Share Me"]
    assert features.get_preset("captions", "Share Me")["outline"] == 3
    from kerf import captions
    p = captions.preview(str(VIDEO), {"animation": "pop"}, 1.0, "16:9")
    assert p["image"].startswith("data:image/png;base64,") and len(p["image"]) > 2000
    r = features.run("silences", str(VIDEO), {"detection": "hybrid", "preview": True}, TMP / "out")
    assert r["report"]["segments"] <= 7  # a pure tone is loud but not speech: hybrid can only keep less


def test_toolkit():
    from kerf import tools
    sp = tools.speed_profile("speedramp", "", 30, 300)
    assert sp(0.0) > 290 and sp(0.5) < 40  # fast → slow → fast
    _, out_len = tools.ramp_expr(4.0, lambda u: 50)
    assert abs(out_len - 8.0) < 1e-6  # half speed doubles the length
    r = features.run("speed_ramp", str(VIDEO), {"preset": "ease_in_out", "min_speed": 50, "max_speed": 200,
                                               "clips": "all"}, TMP / "out")
    assert r["report"]["ramped"][0]["after"] != r["report"]["ramped"][0]["before"]
    r = features.run("camera_shake", str(VIDEO), {"on": "times", "times": "2,6", "axis": "all"}, TMP / "out")
    xml = Path(r["xml"][0]).read_text("utf-8")
    assert "<parameterid>rotation</parameterid>" in xml and xml.count("<keyframe>") > 20
    r = features.run("camera_shake", str(VIDEO), {"on": "times", "times": "1", "output": "render", "flash": 30,
                                                  "chromatic": 4, "axis": "all"}, TMP / "out")
    assert r["report"]["shakes"] == 1 and "shake" in Path(r["xml"][0]).read_text("utf-8")
    r = features.run("layout", str(VIDEO), {"tracks": "1", "arrange": "top_left", "scale": 50.0}, TMP / "out")
    root = ET.parse(r["xml"][0]).getroot()
    assert float(root.find(".//parameter[parameterid='center']/value/horiz").text) < 0  # left of centre
    for name, params in [("add_layer", {"kind": "letterbox"}), ("frame_export", {"time": "1.5", "folder": str(TMP)}),
                         ("zoom_move", {"direction": "in", "ease": "out"}), ("stabilize", {"method": "deshake"})]:
        assert features.run(name, str(VIDEO), params, TMP / "out")["report"], name
    click = TMP / "click120.wav"
    if not click.exists():
        media.ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t,0.5),0.03)':s=44100:d=20", click)
    m = features.run("beat_markers", str(VIDEO), {"music": str(click), "every": 2}, TMP / "out")
    assert 15 <= len(m["markers"]) <= 25
    assert set(tools.project_sort(None, tools.SORT_DEFAULTS, None)["sort"]["bins"]) >= {"Video", "Audio"}
    tools.fx_save("Glow", {"components": [{"match": "AE.ADBE Glow"}]})
    assert "Glow" in tools.fx_list() and tools.fx_get("Glow")["components"][0]["match"] == "AE.ADBE Glow"


def test_licence_keys_offline():
    import time as _t
    from kerf import license as lic
    calls = []
    good = {"activated": True, "instance": {"id": "i1"}, "meta": {"product_id": 7, "variant_name": "Monthly", "product_name": "Kerf Pro"},
            "license_key": {"status": "active", "expires_at": "2027-01-01T00:00:00Z"}}
    orig = lic._ls
    lic._ls = lambda action, **d: calls.append(action) or good
    try:
        pro = features.Feature("x", "X", None, {}, tier="pro")
        assert not lic.entitled(pro) and lic.entitled(features.REGISTRY["silences"])  # free stays free
        os.environ["KERF_LS_PRODUCT"] = "8"
        try:
            lic.activate("ABCD-1234-EFGH")
            raise AssertionError("a key for another product must be refused")
        except PermissionError:
            pass
        os.environ["KERF_LS_PRODUCT"] = "7"
        assert lic.activate("ABCD-1234-EFGH")["plan"] == "Monthly" and lic.entitled(pro)
        data = json.loads(lic.CACHE.read_text())
        data["checked"] = _t.time() - 10 * 86400
        lic.CACHE.write_text(json.dumps(data))

        def offline(action, **d):
            raise OSError("no network")
        lic._ls = offline
        assert lic.entitled(pro)  # within the 14-day offline grace
        lic._ls = lambda action, **d: calls.append(action) or {}
        lic.deactivate()
        assert not lic.entitled(pro) and calls[-1] == "deactivate"
    finally:
        lic._ls = orig
        os.environ.pop("KERF_LS_PRODUCT", None)


def test_mogrt_pack_round_trip():
    import zipfile
    from kerf import mogrt
    src = TMP / "built" / "Kerf Caption - Pop.mogrt"
    src.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("definition.json", json.dumps({"capsuleNameLocalized": {"strDB": [{"str": "Kerf Caption - Pop"}]},
                                                 "clientControls": [{"uiName": {"strDB": [{"str": "Text"}]}, "type": 6}]}))
    gif = TMP / "built" / "caption-pop.gif"
    gif.write_bytes(b"GIF89a")
    mogrt._merge_index([dict(id="caption-pop", name="Kerf Caption - Pop", kind="caption", source="pack", file=str(src), gif=str(gif))])
    pack = TMP / "kerf-mogrt-pack.zip"
    assert mogrt.export_pack(pack)["templates"] == 1
    with zipfile.ZipFile(pack, "a") as z:
        z.writestr("pack/../../escape.txt", "x")  # a hostile entry must never land outside the library
    mogrt.INDEX.unlink()
    assert mogrt.install_pack(str(pack))["installed"] == 1
    e = mogrt.library()[0]
    assert Path(e["file"]).parent == mogrt.LIB / "pack" and Path(e["gif"]).exists()
    assert not (mogrt.LIB.parent / "escape.txt").exists() and not (mogrt.LIB / "escape.txt").exists()
    assert mogrt.inspect(e["file"])["controls"][0]["name"] == "Text"


def test_error_log_redacts_home():
    from kerf import server
    try:
        raise RuntimeError(f"failed on {Path.home() / 'secret.mp4'}")
    except RuntimeError as e:
        server.log_error("/run?token=x", e)
    last = server.diagnostics()["errors"][-1]
    assert str(Path.home()) not in last["error"] + last["trace"] and last["route"] == "/run"


def test_xmeml_keyframes_and_disabled():
    tl = Timeline(fps=30, video=[[Clip(str(VIDEO), 0, 2, 0, scale=[(0, 100), (1, 120)]),
                                  Clip(str(VIDEO), 2, 4, 2, enabled=False)]], audio=[[]])
    root = ET.fromstring(to_xmeml(tl, media.probe))
    assert len(list(root.iter("keyframe"))) == 2
    assert [c.findtext("enabled") for c in root.iter("clipitem")] == ["TRUE", "FALSE"]


def test_xmeml_motion_units_per_host():
    # 640x360 source on a 1080x1920 sequence; units measured in Premiere 25 / Resolve 21 (scripts/calibrate_xml.py)
    tl = Timeline(fps=30, width=1080, height=1920,
                  video=[[Clip(str(VIDEO), 0, 2, 0, scale=[(0, 177.78)], center=[(0, 0.2, 0.1)])]], audio=[[]])
    def motion(host):
        root = ET.fromstring(to_xmeml(tl, media.probe, host))
        p = {e.findtext("parameterid"): e for e in root.iter("parameter")}
        return float(p["scale"].findtext("value")), float(p["center"].findtext("value/horiz")), \
            float(p["center"].findtext("value/vert"))
    assert motion("premiere") == (177.78, 0.3375, 0.53333)   # center: fraction of source size
    assert motion("resolve") == (105.351, 0.2, 0.1)          # scale over fit-to-frame (1.6875)


def test_effects_follow_timeline():
    from kerf import captions, tools
    baked = tools._bake(Clip(str(VIDEO), 0, 1, 0), "null", TMP / "baked.mp4", Timeline(fps=25, width=1080, height=1920))
    assert abs(media.probe(baked.path)["fps"] - 25) < 0.01
    assert [captions.aspect_of(*s) for s in ((1080, 1920), (1080, 1350), (1920, 1080), (3840, 1600))] == ["9:16", "1:1", "16:9", "16:9"]


def test_effects_keep_clip_framing():
    from kerf import tools
    tl = Timeline.from_dict(dict(fps=30, width=1080, height=1920, playhead=0.5, video=[[dict(
        path=str(VIDEO), src_in=0, src_out=2, start=0, base_scale=300.0, base_center=[0.1, 0])]], audio=[[]]))
    z = tools.zoom_move(tl, dict(tools.ZOOMM_DEFAULTS, amount=120.0, at="clip_start"), None)["timeline"]
    root = ET.fromstring(to_xmeml(z, media.probe, "premiere"))
    scales = [float(k.findtext("value")) for k in root.iter("keyframe") if k.find("value/horiz") is None]
    assert abs(scales[0] - 300) < .01 and abs(max(scales) - 360) < .01   # 120% of the clip's own 300%
    still = ET.fromstring(to_xmeml(tl, media.probe, "premiere"))       # untouched clips keep their framing
    assert float(next(p for p in still.iter("parameter") if p.findtext("parameterid") == "scale").findtext("value")) == 300


def test_editor_detection_and_heartbeat():
    from kerf import hosts
    names = {"Adobe Premiere Pro.exe": "premiere", "AfterFX.exe": "aftereffects", "Resolve.exe": "resolve",
             "/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app/Contents/MacOS/Adobe Premiere Pro 2026": "premiere",
             "/Applications/Adobe After Effects 2026/Adobe After Effects 2026.app/Contents/MacOS/After Effects": "aftereffects",
             "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve": "resolve", "/opt/resolve/bin/resolve": "resolve",
             "Adobe Premiere Pro (Beta).exe": "premiere", "Adobe Media Encoder.exe": None, "explorer.exe": None}
    assert {k: hosts.editor_of(k) for k in names} == names
    hosts.running()  # the real process list must be readable on every OS
    hosts.beat("premiere", dict(project="P", sequence="S", playhead=1.5))
    s = hosts.status()
    assert "premiere" in s["running"] and s["live"]["premiere"]["sequence"] == "S" and s["exit_in"] is None


if __name__ == "__main__":
    setup_module()
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(tests)} passed")


def test_voiceover_voices_and_plain_errors():
    from kerf import voice
    assert len(voice.VOICES) == 54 and voice.VOICES.index("af_heart") == 3  # the model's own speaker order
    assert voice.voice_label("bm_george") == "George (UK English, male)"
    tl = dict(name="vo", fps=30, width=1920, height=1080, video=[[]], audio=[[]])
    for bad in (dict(text=""), dict(text="hi", voice="zz_nobody")):  # rejected before the model is touched
        try:
            features.run("voiceover", tl, bad)
            raise AssertionError("expected a plain 'needs input' error")
        except ValueError:
            pass


def test_voiceover_speech_server_request_and_errors(tmp_path, monkeypatch):
    """The 'speech server' engine speaks through an OpenAI-compatible /audio/speech (VoiceStudio by default)."""
    import http.server
    import io
    import threading
    import wave as wav
    from kerf import settings
    got = {}

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got["path"], got["auth"] = self.path, self.headers.get("Authorization")
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if got.get("html"):  # a misconfigured server: an error page with status 200
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<html>Not found</html>")
                return
            buf = io.BytesIO()
            with wav.open(buf, "wb") as w:  # 0.5 s of quiet tone at 24 kHz
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\x10\x00" * 12000)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            self.wfile.write(buf.getvalue())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: {"speech_server_url": f"http://127.0.0.1:{srv.server_port}/v1",
                                                   "speech_api_key": ""}.get(k, real(k)))
    tl = dict(name="vo", fps=30, width=1920, height=1080, playhead=1.5, video=[[]], audio=[[]])
    r = features.run("voiceover", tl, dict(text="Hello  there", engine="speech server", server_voice="my-clone",
                                           style="calm", speed=1.2))
    assert got["path"] == "/v1/audio/speech" and got["auth"] is None
    assert got["body"] == dict(input="Hello there", voice="my-clone", response_format="wav", speed=1.2, instructions="calm")
    assert abs(r["report"]["seconds"] - 0.5) < 0.05 and r["report"]["at"] == 1.5 and r["report"]["voice"] == "my-clone"
    again = features.run("voiceover", tl, dict(text="Hello", engine="speech server"))  # same second: its own file
    assert again["files"][0] != r["files"][0] and Path(r["files"][0]).is_file()
    got["html"] = True
    try:  # not audio: a plain message, and the raw reply is not left behind
        features.run("voiceover", tl, dict(text="hi", engine="speech server"))
        raise AssertionError("expected a plain error")
    except ValueError as e:
        assert "didn't send back audio" in str(e)
    assert not list(Path(r["files"][0]).parent.glob("*(server).wav"))
    srv.shutdown()
    monkeypatch.setattr(settings, "get", lambda k: {"speech_server_url": "http://127.0.0.1:9/v1"}.get(k, real(k)))
    try:  # nothing listening: a plain "start VoiceStudio" message, not a crash
        features.run("voiceover", tl, dict(text="hi", engine="speech server"))
        raise AssertionError("expected a plain error")
    except ValueError as e:
        assert "Start VoiceStudio" in str(e)


def test_result_steps_are_one_ordered_list():
    """Every editor applies these steps; the Result keys themselves are never read by the adapters."""
    res = dict(insert=dict(path="a.mov", at=1.0, duration=2.0), imports=["b.mp4"], xml=["x.xml"], sequence_names=["Cut"],
               srt="c.srt", markers=[dict(t=1.0, name="Intro")], mogrt=dict(path="m.mogrt", param="Text", pages=[]))
    assert [s["op"] for s in features.steps(res)] == ["insert", "import", "timeline", "import", "markers", "mogrt"]
    assert features.steps(res)[2] == dict(op="timeline", xml="x.xml", name="Cut")
    assert features.steps(dict(sort={"bins": {}}, xml=["x.xml"])) == [dict(op="sort", plan={"bins": {}})]
    r = features.run("silences", str(VIDEO))
    assert r["steps"] and all(s["op"] == "timeline" for s in r["steps"])


def test_units_round_trip_per_editor():
    """Timeline intake owns every editor's units: raw reading -> Kerf -> raw reading is exact, and the XML agrees."""
    from kerf import units
    frame, source = (1920, 1080), (3840, 2160)
    for editor, raw in (("premiere", dict(scale=60.0, position=[1152.0, 432.0])),
                        ("resolve", dict(zoom=1.2, pan=192.0, tilt=108.0))):
        bs, bc = units.framing_in(editor, raw, frame, source)
        assert units.framing_out(editor, bs, bc, frame, source) == pytest.approx(raw)
    assert units.framing_in("premiere", dict(scale=100, position=[0.6, 0.4]), frame, source)[1] == pytest.approx((0.1, -0.1))
    bs, bc = units.framing_in("resolve", dict(zoom=1.2, pan=192.0, tilt=108.0), frame, source)
    fit, kx, ky = units.xml_motion("resolve", frame, source)
    assert bs / fit == pytest.approx(120.0) and (bc[0] * kx, bc[1] * ky) == pytest.approx((0.1, -0.1))
    tl = Timeline.from_dict(dict(width=1920, height=1080, editor="resolve", video=[[dict(
        path="x.mov", src_in=0, src_out=1, start=0, framing=dict(zoom=1.2, pan=192.0, tilt=108.0, source=[3840, 2160]))]]))
    assert tl.editor == "resolve" and tl.video[0][0].base_scale == pytest.approx(60.0)


def test_editor_actions_are_one_list():
    """Every action a panel asks about (host.has) is declared for some editor, and every toolkit feature exists."""
    import re
    asked = set()
    for f in (Path(__file__).resolve().parent.parent / "ui" / "src").glob("*.tsx"):
        asked |= set(re.findall(r'(?:host\.|[^.\w])has\("(\w+)"\)', f.read_text(encoding="utf-8")))
    declared = {a for acts in features.EDITORS.values() for a in acts}
    assert asked and asked <= declared, asked - declared
    assert {n for n, d in features.describe().items() if d["toolkit"]} == set(features.TOOLKIT) & set(features.REGISTRY)


def test_engine_writes_its_locator(monkeypatch):
    """Every panel finds the engine through one locator file: the port it really bound, token file, helper."""
    import threading
    import urllib.request
    from kerf import server
    server.LOCATOR.unlink(missing_ok=True)
    monkeypatch.setenv("KERF_HELPER", "/opt/kerf/helper")
    threading.Thread(target=server.serve, args=(0,), daemon=True).start()  # port 0: the OS picks one
    for _ in range(100):
        if server.LOCATOR.exists():
            break
        threading.Event().wait(0.05)
    loc = json.loads(server.LOCATOR.read_text())
    assert loc["helper"] == "/opt/kerf/helper" and loc["token_file"] == str(server.TOKEN_FILE) and loc["port"] > 0
    assert urllib.request.urlopen(f"http://127.0.0.1:{loc['port']}/health", timeout=5).status == 200


def test_missing_or_unreadable_media_says_what_to_do():
    """Offline media (26 Oct log: a clip on an unplugged drive) is a plain 400, not an ffprobe crash."""
    gone = TMP / "Food A'fair" / "C0186.MP4"
    with pytest.raises(FileNotFoundError, match="Relink"):
        media.probe(str(gone))
    with pytest.raises(FileNotFoundError):
        features.run("silences", dict(video=[[dict(path="1129270354", src_in=0, src_out=2, start=0)]]), {}, TMP / "out")
    junk = TMP / "junk.mp4"
    junk.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="can't read junk.mp4"):
        media.probe(str(junk))


def test_non_ascii_paths_for_images():
    """OpenCV's imread/imwrite fail on non-ASCII Windows paths: sizes fell back to 1920x1080 and layers weren't written."""
    d = TMP / "Ünïcode 日本 A'fair"
    d.mkdir(exist_ok=True)
    pic = d / "pic ü.png"
    media.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240", "-frames:v", "1", pic)
    info = media.probe(str(pic))
    assert (info["width"], info["height"]) == (320, 240)
    r = features.run("add_layer", str(VIDEO), {"kind": "vignette"}, d / "out")
    assert Path(r["files"][0]).stat().st_size > 0


def test_still_image_timeline_renders_and_ends():
    """A still image as the whole timeline was a zero-length clip: render ran FFmpeg with -loop 1 -t 0 forever."""
    import threading
    pic = TMP / "still.png"
    media.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240", "-frames:v", "1", pic)
    tl = Timeline.from_media(str(pic), media.probe)
    assert tl.duration == pytest.approx(5.0)
    out = {}
    t = threading.Thread(target=lambda: out.update(features.run("render", str(pic), {"quality": "draft"}, TMP / "out")),
                         daemon=True)
    t.start()
    t.join(120)
    assert not t.is_alive() and media.probe(out["files"][0])["duration"] == pytest.approx(5.0, abs=0.2)
    with pytest.raises(ValueError, match="Nothing to render"):
        features.run("render", dict(video=[[]]), {}, TMP / "out")


def test_transcribe_skips_files_without_audio(monkeypatch):
    """A video-only clip crashed faster-whisper (IndexError); now it simply has no words."""
    from kerf import speech
    silent = TMP / "no-audio.mp4"
    media.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=2", "-c:v", "libx264", silent)
    monkeypatch.setattr(speech, "_whisper", lambda *a: pytest.fail("loaded Whisper for a file with no audio"))
    assert speech.transcribe(str(silent))["words"] == []
    with pytest.raises(ValueError, match="No audio to enhance"):  # was an FFmpeg crash
        features.run("enhance", str(silent), {}, TMP / "out")


def test_stabilize_path_with_an_apostrophe():
    """vidstab's transforms file was named after the clip: a quote in "Food A'fair" broke the filter arguments."""
    if not media.has_filter("vidstabdetect"):
        pytest.skip("this FFmpeg has no vidstab")
    d = TMP / "Food A'fair"
    d.mkdir(exist_ok=True)
    clip = d / "c'lip, take 1.mp4"
    shutil.copy(VIDEO, clip)
    r = features.run("stabilize", str(clip), {"method": "vidstab"}, d / "out")
    assert r["report"]["stabilized"] == 1


def test_audio_only_media_and_ffmpeg_errors():
    """An audio file used as the timeline sat on the video track too: render divided by zero, video tools crashed."""
    wav = TMP / "voice.wav"
    media.ffmpeg("-f", "lavfi", "-i", "sine=d=3", wav)
    tl = Timeline.from_media(str(wav), media.probe)
    assert tl.video == [[]] and tl.audio[0][0].dur == pytest.approx(3.0, abs=0.05)
    r = features.run("render", str(wav), {"quality": "draft"}, TMP / "out")
    assert media.probe(r["files"][0])["duration"] == pytest.approx(3.0, abs=0.2)
    with pytest.raises(ValueError, match="No video"):
        features.run("frame_export", str(wav), {"folder": str(TMP / "out")}, TMP / "out")
    with pytest.raises(RuntimeError, match="FFmpeg failed: .*nope"):  # FFmpeg's reason, not just the command line
        media.ffmpeg("-i", TMP / "nope.mp4", TMP / "x.mp4")


def test_beats_on_long_music_across_blocks():
    """Beat detection runs in blocks (an hour-long mix needed ~7 GB), and every beat stays on the real click: the
    tempo used to come out 0.14% slow, so cuts drifted 0.25 s off the beat by the end of a 3-minute song."""
    from kerf import sound
    click = TMP / "click120-long.wav"  # clicks at every multiple of 0.5 s
    media.ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t,0.5),0.03)':s=22050:d=200", click)
    bt, bpm = sound.beats(str(click))
    assert bpm == pytest.approx(120, abs=0.2) and bt[-1] > 195
    off = [(b + 0.25) % 0.5 - 0.25 for b in bt]  # signed distance to the nearest click
    assert max(abs(o) for o in off) < 0.034  # within a frame at 30 fps, first beat to last (past the ~95 s block edge)


def test_quick_mask_reports_a_failed_encoder(monkeypatch):
    """An encoder that stops early is a plain error, and the decoding FFmpeg isn't left running."""
    from kerf import tools
    monkeypatch.setattr(tools, "_model", lambda name: None)
    monkeypatch.setattr(tools, "mask_frame", lambda sess, rgb: rgb[..., 0].astype("float32") / 255)
    monkeypatch.setattr(tools, "_encode", lambda out, alpha=False, tl=None: ["-c:v", "no_such_encoder", str(out)])
    with pytest.raises(RuntimeError, match="encoding the matte failed"):
        features.run("quick_mask", str(VIDEO), dict(output="matte"), TMP / "out")


def test_quick_mask_keeps_frame_order(monkeypatch):
    """Masks are computed a few frames at a time; they must land on the timeline in frame order."""
    from kerf import tools
    ramp = TMP / "ramp.mp4"  # frame n is grey level 40+6n: the fake model's mask is the frame itself
    media.ffmpeg("-f", "lavfi", "-i", "nullsrc=s=256x256:r=30:d=1,geq=lum=40+N*6:cb=128:cr=128", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", ramp)
    monkeypatch.setattr(tools, "_model", lambda name: None)
    monkeypatch.setattr(tools, "mask_frame", lambda sess, rgb: rgb[..., 0].astype("float32") / 255)
    r = features.run("quick_mask", str(ramp), dict(output="matte", threshold=0.5, softness=1.0, smooth=0.0, feather=0),
                     TMP / "out")
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", r["files"][0], "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    means = np.frombuffer(raw, np.uint8).reshape(-1, 256 * 256).mean(axis=1)
    assert len(means) == 30 and all(b > a for a, b in zip(means, means[1:]))


def test_client_hangup_is_not_logged_as_an_engine_error():
    """15 of 23 logged 'errors' were panels closing mid-reply (WinError 10053/10054)."""
    from kerf import server
    before = server.ERRORS.read_text("utf-8") if server.ERRORS.exists() else ""
    h = server.Handler.__new__(server.Handler)
    h.path = "/host"

    def hangup(code, obj):
        raise ConnectionResetError(10054, "forcibly closed")
    h._send = hangup
    h._handle(lambda: dict(ok=True))
    assert (server.ERRORS.read_text("utf-8") if server.ERRORS.exists() else "") == before
