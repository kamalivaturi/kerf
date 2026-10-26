# Kerf

**Free, open-source AI editing toolkit for Premiere Pro, After Effects and DaVinci Resolve,
on Windows, macOS and Linux.**
Cut silences and bad takes, animated captions and 194 editable MOGRT templates, speed ramps, camera
shakes, stabilizer, offline AI cutouts, punch-in zooms, B-roll, multicam switching, viral shorts,
music with auto-ducking, beat edits, audio cleanup and reframing. It runs on your own computer.

[Download](https://github.com/kamalivaturi/kerf/releases/latest) ·
[Website](https://kamalivaturi.github.io/kerf/) ·
[Feature teardown](docs/REVERSE_ENGINEERING.md) ·
[Changelog](CHANGELOG.md) ·
[Design brief](docs/DESIGN.md) ·
[☕ Buy me a coffee](https://buymeacoffee.com/kamalivaturi)

---

## Download

**One installer adds Kerf to every editor on your computer.** There is no separate app: open the Kerf panel
inside Premiere Pro, After Effects or DaVinci Resolve and it works on the open sequence, composition or timeline.

| Your computer | Get | Then open Kerf in your editor |
|---|---|---|
| **Windows** | `Kerf-…-windows-x64-setup.exe` (or `.msi` for IT deployment) | **Premiere Pro 25.6+:** Window › UXP Plugins › Kerf · **After Effects 2022+:** Window › Extensions › Kerf · **Resolve 18.6+:** Workspace › Scripts › Kerf |
| **macOS** (Apple silicon / Intel) | `Kerf-…-macos-arm64.dmg` / `…-macos-x64.dmg` | Drag Kerf to Applications and open it once (right-click → Open the first time); it adds the panels, then use the same menus. |
| **Linux** | `.AppImage`, `.deb` or `.rpm` | DaVinci Resolve: Workspace › Scripts › Kerf. |
| **No installer** | `kerf-portable-…` (zip / tar.gz) | Unpack, run `kerf-engine/kerf-engine serve`, and install the panels from `kerf-premiere-….ccx`, `kerf-resolve-….zip`. |
| **Python** | `pip install kerf-…whl` or `pip install -e ".[ai]"` | `kerf serve` (needs FFmpeg on PATH). |

Every release lists SHA-256 checksums in `SHA256SUMS.txt`. Kerf starts when you open a panel, stops about a minute
after your editors close, and updates itself in between (Settings › Automatic updates). Upgrading from Kerf Studio
0.2.x removes the old app automatically.

Kerf runs alongside your editor: it shows the open project, sequence or composition and the playhead live, and closes about a minute after the last of Premiere Pro, After Effects or Resolve closes (Settings → Run only while … is open).

## What's inside

**Toolkit** (one-click tools, Tools / Graphs / Motion / Shakes tabs)

| Tool | Premiere Pro | After Effects | Resolve |
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
Kerf helper (Tauri / Rust)      ┘    token-protected      └ Claude / OpenAI / Gemini / Ollama (opt-in)
   reads the timeline → engine builds the new edit → FCP7 XML / clips / markers → the editor applies it
```

```
kerf/          engine (Python): timeline model + XML, one module per feature, server, CLI, licensing
ui/            React + TypeScript + SCSS (Vite) → dist-uxp/ (Premiere) and dist/ (After Effects panel)
aftereffects/  After Effects panel (ExtendScript)     resolve/  DaVinci Resolve script
desktop/       Kerf installer + background helper (Tauri 2, Rust): engine + panels → .exe .msi .dmg .AppImage .deb .rpm
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
- Some third-party After Effects scripts open as floating windows when run from the Kerf Scripts hub (that's how AE runs ScriptUI panels from a script).

## License

[MIT](LICENSE). Kerf is an independent project and is not affiliated with Adobe, Blackmagic Design,
or any commercial plugin vendor.

## Support Kerf

Kerf is free and stays free. If it saves you editing time, you can
[buy me a coffee](https://buymeacoffee.com/kamalivaturi). It keeps new tools coming.

[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-%E2%98%95-FFDD00?style=for-the-badge&labelColor=1a0f08)](https://buymeacoffee.com/kamalivaturi)
