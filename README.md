# Kerf

**Free, open-source AI editing toolkit for Premiere Pro, After Effects and DaVinci Resolve,
on Windows, macOS and Linux.**
Cut silences and bad takes, animated captions and 194 editable MOGRT templates, speed ramps, camera
shakes, stabilizer, offline AI cutouts, punch-in zooms, B-roll, multicam switching, viral shorts,
music with auto-ducking, beat edits, audio cleanup and reframing. It runs on your own computer.

[Download](https://github.com/kamalivaturi/kerf/releases/latest) ·
[Website](https://kamalivaturi.github.io/kerf/) ·
[Feature teardown](docs/REVERSE_ENGINEERING.md) ·
[Changelog](CHANGELOG.md)

---

## Download

| You use | Get | Then |
|---|---|---|
| **Windows** | `Kerf-Studio-…-windows-x64-setup.exe` (or `.msi`) | Run it. Kerf Studio starts the engine for every editor. |
| **macOS** (Apple silicon / Intel) | `Kerf-Studio-…-macos-arm64.dmg` / `…-macos-x64.dmg` | Drag to Applications. First launch: right-click → Open (unsigned build). |
| **Linux** | `.AppImage`, `.deb` or `.rpm` | `chmod +x` the AppImage and run it, or install the package. |
| **Premiere Pro 25.6+** | `kerf-premiere-….ccx` | Double-click (Creative Cloud installs it) → *Window → UXP Plugins → Kerf*. |
| **After Effects 2024+** | `kerf-aftereffects-….zip` | Run `install/install-aftereffects.ps1` (Windows) or `install/install.sh` (macOS) → *Window → Kerf.jsx*. Enable *Preferences → Scripting & Expressions → Allow Scripts to Write Files and Access Network*. |
| **DaVinci Resolve 18.6+** (Free or Studio) | `kerf-resolve-….zip` | `install/install-resolve.ps1` (Windows) or `install/install.sh` (macOS/Linux) → *Workspace → Scripts → Kerf*. |
| **No installer** | `kerf-studio-portable-…` (zip / tar.gz) | Unpack anywhere, run `kerf-engine/kerf-engine serve`, open <http://127.0.0.1:7878/app/>. FFmpeg included. |
| **Python** | `pip install kerf-…whl` or `pip install -e ".[ai]"` | `kerf serve` (needs FFmpeg on PATH). |

Every release lists SHA-256 checksums in `SHA256SUMS.txt`.

## What's inside

**Toolkit** (one-click tools, Tools / Graphs / Motion / Shakes tabs)

| Tool | Premiere Pro | After Effects | Resolve & Studio |
|---|---|---|---|
| **Anchor** (9 positions) | moves the anchor of selected clips, picture stays put | same, multi-layer | places clips at that spot |
| **Add layer** | Null, Adjustment (reuses yours), Solid, cinematic bars, vignette, thirds guides | Null, Null + Parent, Adjustment, Solid | generated layers on a new track |
| **Beat markers** | detect tempo → sequence markers, every N beats, clear | comp markers | timeline markers |
| **Curves**: value + speed graph | ease selected keyframes · speed ramps (ease in/out, speedramp, custom bezier editor) | keyframe ease · time-remap ramps | rendered speed ramps |
| **Camera shake** | vertical, horizontal, HV, scale, all, custom · on playhead, cuts, beats or whole clip · editable keyframes or rendered with flash + RGB split · live preview | expression + sliders (stays editable), flash | same as Premiere |
| **Stabilizer** | one-click (FFmpeg vidstab), smoothness % | pre-comp + Warp Stabilizer | one-click |
| **Zoom in / out** | eased scale moves (in / out / in-out / your curve) | eased scale keys | same |
| **Align & distribute** | 4 edges, distribute H/V, grid, picture-in-picture | align to comp, distribute | same |
| **Quick mask** | offline AI cutout (U²-Net, ONNX) of a region you draw → alpha clip above | draw a mask → cutout layer | same |
| **Project sorter** | bins: Video, Audio, Images, Graphics, Captions, Sequences, Other | folders | Media Pool folders |
| **Frame export** | playhead frame → Desktop | comp frame → Desktop | same |
| **FX presets** | copy a clip's effect stack (values + keyframes) and apply to other clips | effect stacks incl. expressions | — |
| **Custom layout** | hide and reorder tool cards, saved per project | — | — |

**Edit** (AI and automation features)

| Group | Feature | What it does |
|---|---|---|
| **AI** | **Prompt Edit** | Type what you want; Claude, OpenAI/Codex, Gemini or a local model plans a chain of Kerf features and runs it. |
| | **Pipeline / recipes** | Multi-step macros: TikTok talking head, YouTube vlog, podcast, tutorial, Instagram reel, music video. |
| **Cut** | **Silences** | Loudness, Silero speech model, or hybrid (both agree) · presets Calm→Jumpy · J/L cuts · review before cutting. |
| | **Transcript & language** | large-v3-turbo on GPU, auto language detection, 21 mixed-language profiles (Hinglish, Tanglish, Spanglish…), an editable transcript, and a vocabulary that learns from your fixes. |
| | **Repeat · Profanity** | Keep the last take, cut filler words · beep/mute/cut swearing. |
| **Style** | **Captions** | 8 styles, 10 animations, live preview with platform safe zones (9:16, 1:1, 16:9), MOGRT output, translation. |
| | **AutoZoom · B-roll** | Punch-ins on cuts, speech, emphasis · stock or your own footage from the transcript. |
| **Graphics** | **MOGRT library + Studio** | 194 templates (captions, titles, lower thirds; 14 animations × 5 looks) built by After Effects, every control editable in Essential Graphics · live animated previews · Studio: animation, speed, font, size, colours, spacing, kerning, alignment, box, shadow, glow → your own MOGRT · import any .mogrt. |
| **Audio** | **Enhance · Music · SFX · Dub** | ElevenLabs or local cleanup · music with auto-ducking · SFX pack on cuts · translate & dub. |
| **Multicam** | **Podcast · Angles** | Speaker detection with hysteresis · switch angles on cuts, pauses, energy. |
| **Repurpose** | **Viral · Resize · Chapters · Beat edit** | 0–100 scored shorts · face-tracked reframing · YouTube chapters · music-video cuts on the beat. |
| **Import / Export** | **Download · Render** | yt-dlp with every option · MP4 up to 4K60 (NVENC, QuickSync, AMF, VideoToolbox) or ProRes 4444 alpha · batch folders. |

**The panel is yours to shape:** premium dark "ember" or light theme, accent colour, density, text size, 10 languages
(follows your system, Arabic right-to-left), favourites, search, history, presets you can share, What's new, F1 help.
Edits are **non-destructive**: Kerf builds a new sequence and never touches your original edit or media.

## AI providers (optional)

Kerf works fully offline. Add keys in ⚙ Settings (stored only in `~/.kerf/settings.json`):

| Provider | Used for | Default model |
|---|---|---|
| Claude (Anthropic) | Prompt Edit, chapter titles, viral rerank, translation, B-roll queries | `claude-opus-5-5` |
| OpenAI / Codex | same | any model id |
| Google Gemini | same | any model id |
| Local (Ollama, LM Studio…) | same, private | any model id |
| ElevenLabs | voice isolation, dubbing | — |
| Pexels | stock B-roll | — |

## Command line

```bash
kerf run silences --media talk.mp4 --preset Paced
```

```bash
kerf batch captions D:\Shorts --preset "Bold Yellow" --render
```

```bash
kerf run camera_shake --media clip.mp4 --set on=whole --set axis=hv --set output=render
```

## How it works

```
Premiere UXP panel (React + TS) ┐                         ┌ FFmpeg · faster-whisper · Silero VAD
After Effects panel (ScriptUI)  │                         │ U²-Net (ONNX) · OpenCV YuNet · NumPy
Resolve script (Fusion UI)      ├── 127.0.0.1:7878 ───────┤ yt-dlp · beat tracking · vidstab
Kerf Studio (Tauri / Rust)      ┘    token-protected      └ Claude / OpenAI / Gemini / Ollama (opt-in)
   reads the timeline → engine builds the new edit → FCP7 XML / clips / markers → the editor applies it
```

```
kerf/          engine (Python): timeline model + XML, one module per feature, server, CLI, licensing
ui/            React + TypeScript + SCSS (Vite) → dist-uxp/ (Premiere) and dist/ (Studio + web)
aftereffects/  After Effects panel (ExtendScript)     resolve/  DaVinci Resolve script
desktop/       Kerf Studio (Tauri 2, Rust): bundles the frozen engine → .exe .msi .dmg .AppImage .deb .rpm
mogrt/         After Effects MOGRT builder            scripts/  engine freezer + release builder
```

## Extending and selling

Drop a Python file in `~/.kerf/plugins/` and it appears in every panel. Paid plans: mark features
`tier="pro"`, set your Lemon Squeezy product (`KERF_LS_PRODUCT`) and users activate a licence key in
Settings; or plug in your own provider. See [docs/MONETIZATION.md](docs/MONETIZATION.md).

## Develop

```bash
python tests/test_core.py
```

```bash
cd ui && npm install && npm run build
```

```bash
python scripts/build_engine.py && cd desktop && npm install && npx tauri build
```

CI tests the engine on Windows, macOS and Linux, and every `v*` tag builds all installers.

## Known limits

- macOS and Windows builds are not code-signed yet (Gatekeeper / SmartScreen will ask once).
- Premiere's scripting has no "create adjustment layer" call: make one once and Kerf reuses it.
- XML motion units are verified on synthetic tests, not yet in every NLE version (see the teardown doc).

## License

[MIT](LICENSE). Kerf is an independent project and is not affiliated with Adobe, Blackmagic Design,
or any commercial plugin vendor.
