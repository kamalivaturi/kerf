# AutoCut feature teardown → Kerf implementation map

Source of truth: the public autocut.com marketing pages (all 11 feature pages, pricing, FAQ)
and four public help-center settings articles, scraped 2026-10-16. No AutoCut binaries or
code were downloaded, decompiled, or copied. Everything below is either **observed** (stated
on their site) or **design** (how Kerf does it). Where Kerf deviates, it says so.

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

## Unverified assumptions (check in-app)

- FCP7 XML `center` units: Kerf writes frame fractions (x of width, y of height; ±0.5 = edge, +y = down).
  Constant `CENTER_UNIT` in `kerf/timeline.py`.
- Keyframe `<when>` measured from media start (in-point + offset).
- Premiere maps FCP "Cross Fade (+3dB)" to Constant Power on import.
