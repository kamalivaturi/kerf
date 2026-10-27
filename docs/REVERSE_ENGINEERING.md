# AutoCut feature teardown → Kerf implementation map

Source of truth: the public autocut.com marketing pages (all 11 feature pages, pricing, FAQ)
and four public help-center settings articles, scraped 2026-10-16, plus a static look at the
AutoCut 4.60.37 Windows installer on 2026-10-27 (see below; nothing was run or copied).
Everything here is either **observed** or **design** (how Kerf does it). Where Kerf deviates, it says so.

## What AutoCut is (observed)

- Paid plugin (Basic $6.6/mo silences only; AI plan $14.9/mo everything) for
  Premiere Pro 2023–2026 and DaVinci Resolve 18.6+ (Free and Studio).
- Works "inside the timeline": reads the active sequence, analyses audio/transcript,
  then edits the timeline.
- 11 features: Silences, Captions, Podcast, Angles, Zoom, Viral, B-Rolls, Repeat,
  Profanity Filter, Chapters, Resize.
- Transcription: 80+ languages, word-by-word.

## Kerf architecture (design)

```
 Premiere UXP panel ─┐                       ┌─ ffmpeg (audio envelope, beeps, caption render)
                     ├─ HTTP 127.0.0.1:7878 ─┤─ faster-whisper (local transcription, 99 langs)
 Resolve script ─────┘   (token-protected)   ├─ OpenCV (face tracking for Resize)
                                             └─ optional OpenAI-compatible LLM (Ollama etc.)
        reads active timeline → engine computes a new edit → FCP7 XML → NLE imports it
```

Kerf never mutates your original sequence: every feature produces a **new sequence** (FCP7
XML, imported by both Premiere and Resolve), plus SRT/ASS/MOV/TXT side files. AutoCut edits
in place; Kerf trades that for undo-safety and one exporter shared by both NLEs.

Everything runs locally and free. Cloud-only AutoCut bits (Storyblocks, AI image generation)
are replaced by Pexels (free API key) or a local footage folder.

## Feature map

| AutoCut feature | Observed settings | Kerf module / method |
|---|---|---|
| **Silences** | Noise threshold dB (manual / auto / "by AI"); presets Calm, Measured, Paced, Energetic, Jumpy; remove silences longer than (300 ms); keep talks longer than (200 ms); margin before/after (200 ms); track selection; modes Remove / Keep / Mute / Remove-but-keep-spaces; transitions None / J-cut / L-cut / Constant Power; preview | `silence.py`: 10 ms RMS envelope of chosen tracks, percentile auto-threshold, gap-merge → drop short talk → pad. All four modes and all four transitions. Preview = `preview:true` returns ranges. |
| **Captions** | 80+ languages; word-by-word; font, text colour, highlight colour, bigger active word, floating text, box, transitions Zoom-in / Blur-in / Zoom+Blur, remove punctuation, uppercase, italic, glow (colour/intensity), outline (colour/px), global box, font size, lines 1–5, max width %, Y position, presets, translate, SRT import, edit transcript, auto-emoji | `captions.py`: faster-whisper words → pages → SRT (editable NLE captions) **and** animated ASS rendered to a transparent ProRes 4444 overlay placed on the top track. Style options map to ASS tags. Presets = JSON files in `~/.kerf/presets`. Translate via LLM. SRT import via `srt` param. Emoji: keyword map (libass renders emoji monochrome). |
| **Podcast** | Speakers ↔ audio tracks; priority Normal/High/Very High; cameras ↔ visible speakers (wide shots); virtual wide shots; presets Calm/Paced/Energetic/Hyperactive with min/max shot; reaction shots; unused clips Disable/Delete; cut audio toggle; saved presets | `camera.py:podcast`: per-mic loudness at 100 ms, priority = dB bonus, close-up preferred, wide when ≥2 talk, min/max shot + cutaways. Disables/deletes clips per camera track. |
| **Angles** | One voice track; camera tracks; triggers existing cuts / silences / emotion / transcript; camera priorities (bias, not %); min shot; never same cam twice; direct or multicam; disable/remove; also cut audio | `camera.py:angles`: candidate switch points from the four triggers, weighted random choice excluding the current camera, min shot. Direct edit only. |
| **Zoom** | Rhythm Very Calm…Hyperactive; triggers Cut (mandatory), Speaking, Emotion (AI), Highlight Meaning (AI); anchor point; min/max zoom; styles Jump Cut / Smooth / Snap-in; zoom sound FX; camera movement; target tracks | `motion.py:zoom`: triggers from clip boundaries, speech onsets, loudness peaks, emphasis words; anchor-preserving scale/center keyframes; Jump = split clips + static scale (no keyframes, as on their site); sound FX on a new audio track; sine drift for camera movement. |
| **Viral** | Language; detection by transcript, emotion, or both; ranked list with "viral potential score"; adjustable length | `speech.py:viral`: sentence-aligned windows scored on hooks/questions/numbers, loudness energy, speech density; optional LLM rerank. Each pick → own sequence (optionally vertical). |
| **B-Rolls** | Language; prompt style; AI or manual moments; Pexels/Storyblocks or AI images | `broll.py`: sentence picks every N s; query from LLM or keyword heuristic; Pexels API (free key) or local folder; new top track. |
| **Repeat** | In/out range; language; optional script; review editor; cut & delete | `speech.py:repeat`: an earlier sentence that prefix-matches a later one is a bad take (difflib ≥ threshold); optional filler removal. Review via items. |
| **Profanity** | Language; preset or custom sound; review editor; saved library; timeline scan | `speech.py:profanity`: wordlist + stem match; beep / mute / cut; custom sound; library `~/.kerf/profanity.txt`. |
| **Chapters** | YouTube-ready timestamps | `speech.py:chapters`: lexical-cohesion boundaries (TextTiling-style), ≥3 chapters, first at 00:00, titles via LLM or keywords; also sequence markers. |
| **Resize** | Reels/Shorts/TikTok + custom; anchor; zoom; watermark; sections | `motion.py:resize`: 9:16, 4:5, 1:1, 16:9, custom; OpenCV face track at 2 fps, smoothed, clamped so no black bars; watermark; `ranges`. |

## Beyond AutoCut (Kerf add-ons)

AI Prompt Edit (Claude / OpenAI / Gemini / local) · Pipelines · Silero-VAD silence detection · South Asian
transcription profiles (Hinglish, Tanglish, 12 languages) + fine-tuned model support · Audio Enhance
(ElevenLabs / local) · GPU render up to 4K60 + ProRes 4444 alpha · batch processing · yt-dlp downloads ·
custom MOGRT captions · drop-in plugins · per-feature presets · standalone web app · customizable UI.

## Known gaps vs AutoCut

- In-place timeline editing → Kerf creates a new sequence instead.
- Multicam-sequence output for Angles/Podcast; virtual wide shots.
- AI-image B-roll, Storyblocks, script-aligned Repeat.
- Colour emoji in captions (libass limitation).
- "Emotion AI" is loudness-peak based, not a trained emotion model.

## AutoCut desktop app (installer, static analysis 2026-10-27)

Observed by listing and reading the shipped files, without running the installer:

- **Packaging:** Velopack 1.2.161 installer (`AutoCut-win-Setup.exe`, 4.60.37) around an Electron app built with
  Electron Forge and Vite, code-signed through Azure Trusted Signing.
- **Thin shell:** the ASAR holds only a main process (`packages/main/dist/index.js`, 0.6 MB) and a preload
  (0.1 MB); the remaining 100 MB is telemetry (Sentry, PostHog, OpenTelemetry), the Velopack updater and HTTP
  clients. None of the eleven features (silences, captions, podcast, zoom, B-roll, viral...) appears in the code.
- **Where the features live:** the window loads the web app at `autocut.com/app`, which talks to their backend.
  An offline page and a bundled "system report" are the only local UI.
- **Local powers given to the web app** through the preload bridge: file system and paths, child processes,
  downloads (FFmpeg/ffprobe fetched from their CDN on first use), clipboard, save dialogs, cookies.
- **Editor integration:** a Premiere ExtendScript bundle (`ppro-jsx`) is downloaded at runtime and prepared in
  AppData, and a separate "AutoCut tools installer" is downloaded on Windows; neither ships in the installer.

Consequence for Kerf: the binary holds no algorithms to learn from, so the feature map above (built from their
public settings) stays the reference. Kerf's design choice remains the opposite of theirs: everything runs
locally, nothing needs an account or a server.

## CarVinci Resolve macros → Kerf FX

The CarVinci Ultra Speedramping and Ultra MotionBlur 2.0 plugins are `.drfx` bundles holding one Fusion macro
each, installed as Edit page effects. Observed structure:

| Plugin | How it works (observed) | Kerf FX (design, own implementation) |
|---|---|---|
| Speedramping | Ten preset bezier time curves (Anim Curves over the clip duration) each drive a Time Stretcher; a selector slider and buttons pick one, the others pass through. Clip length never changes. | **Kerf Speed Ramp** (OpenFX): ten own curves (slow-fast-slow, fast-slow-fast, speed up, slow down, wave, double wave, boomerang, reverse boomerang, steps, hold in the middle), strength, play backwards, frame blending, and motion blur on the fast parts by blending the frames they skip. |
| MotionBlur 2.0 | Automatic: Optical Flow into Vector Motion Blur with a strength curve. Manual: Directional Blur (angle, length). Effect mask input. | **Kerf Motion Blur** (OpenFX): automatic mode measures the shot's global motion between neighbouring frames and blurs along it (180-degree shutter at Amount 1); directional mode with angle and length. Per-pixel optical flow is not implemented (pans and tilts only). |

## HyperFrames desktop (installer, static analysis 2026-10-27)

Observed from the NSIS installer's files without running it: an Electron app (`hyperframes-desktop` 0.1.0) with a
local Hono server, the HyperFrames HTML-to-video packages (`@hyperframes/core`, studio server, inspector, lint),
an agent runtime (DeepSeek `dsh` tools, MCP SDK), `sharp` for images, bundled Node and FFmpeg, and Datadog telemetry.
It ships ten agent "skills" (embedded captions, faceless explainer, general video, motion graphics, music to video,
PR to video, product launch video, Remotion to HyperFrames, slideshow, talking-head recut) and an offline voice:
the open Kokoro v1.0 int8 model from the public sherpa-onnx releases, run on-device.

Taken into Kerf (design, own code): **Voiceover** (`kerf/voice.py`) uses the same open model and runtime for offline
narration. Kerf already covers captions, music-to-video (beat edit) and talking-head recuts; HTML-composition
rendering and the agent skills are outside Kerf's editor-panel scope.

## 360 Tool (360mediaedits.com) → Kerf Toolkit

Observed from the public product page (2026-10-19): a paid After Effects panel with 13 tools in 5 tabs. No
code or assets were copied; each tool was re-designed for Premiere, After Effects, Resolve and Kerf Studio.

| 360 Tool | Kerf | Notes |
|---|---|---|
| Speed Graph (5 presets + custom) | Graphs tab: speed ramp presets + bezier editor (`speed_ramp`) | Premiere/Resolve: rendered ramp with ripple; AE: time-remap ease |
| Value Graph (bezier handles) | value-curve buttons, bezier curve reused by zoom | Premiere UXP exposes only linear/bezier/hold interpolation |
| Camera Shake (6 sliders, flash, chromatic) | `camera_shake`: 6 axes, 8 sliders, live preview | keyframes (editable) or render with flash + RGB split; AE uses expressions + sliders |
| Warp Stabilizer (pre-comp) | `stabilize` (vidstab/deshake) · AE: pre-comp + Warp Stabilizer | |
| Zoom In / Out | `zoom_move`: in/out × ease in/out/in-out/custom | |
| Anchor Point (9 positions) | Premiere: anchor of selected clips with position compensation · AE: same · else `layout` | |
| Align & Distribute (6 + 2) | `layout` + AE align/distribute | |
| Project Sorter (6 categories) | Premiere bins / Resolve folders / AE folders (7 categories) | host-side |
| Add Layer (Null, Null+Parent, Adj, Solid) | AE: all four · Premiere: transparent/solid/bars/vignette/guides + reuse of an existing adjustment layer | Premiere has no "create adjustment layer" API |
| Frame Export | `frame_export` · AE `saveFrameToPng` | |
| Beat Markers | `beat_markers` (spectral-flux tempo, every N / bars) · clear | |
| Quick Mask (offline AI) | `quick_mask`: U²-Net ONNX, drawn region, alpha cutout or matte | model downloads once from the rembg releases |
| FX Presets (effect stack + keyframes) | Premiere component chains / AE effect JSON incl. expressions | stored in `~/.kerf/fx` |
| Custom Layout (toggle, reorder, per project) | Tools tab "Customize layout", saved per project | |

## XML motion units (measured)

Measured by importing `scripts/calibrate_xml.py` output into Premiere Pro 25 and Resolve Studio 21:

- Premiere reads Basic Motion `center` as a fraction of the **source** clip's size; Resolve reads it as a fraction
  of the **timeline** size. Kerf writes per host (`to_xmeml(..., host=)`; the Resolve script sends `host="resolve"`).
- Scale: Premiere 100 = native source pixels; Resolve applies the XML scale on top of its fit-to-frame input
  scaling, so Kerf divides by `min(W/sw, H/sh)` for Resolve.
- Keyframe `<when>` is media-start based (in-point + offset) in both.

## Unverified assumptions (check in-app)

- Premiere maps FCP "Cross Fade (+3dB)" to Constant Power on import.
