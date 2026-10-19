# Kerf

**Free, open-source AI editing assistant for Adobe Premiere Pro and DaVinci Resolve.**
Cut silences and bad takes, add animated captions, punch-in zooms, B-roll, multicam podcast
switching, viral shorts, chapters, audio cleanup and reframing — from inside your editor, running
on your own computer.

[Download](https://github.com/kamalivaturi/kerf/releases/latest) ·
[Website](https://kamalivaturi.github.io/kerf/) ·
[Feature teardown](docs/REVERSE_ENGINEERING.md) ·
[Changelog](CHANGELOG.md)

---

## Features

| Group | Feature | What it does |
|---|---|---|
| **AI** | **Prompt Edit** | Type what you want ("tighten pacing, yellow captions, vertical Short"). Claude, OpenAI/Codex, Gemini or a local model plans a chain of Kerf features and runs it. |
| | **Pipeline** | Your own multi-step macros (no AI needed), saved as presets. |
| **Cut** | **Silences** | Loudness or Silero-VAD ("AI") detection · presets Calm→Jumpy · margins · remove / keep / mute / keep-spaces · J-cut, L-cut, constant-power. |
| | **Repeat** | Finds restarted sentences (bad takes) and filler words, keeps the last take. Review before cutting. |
| | **Profanity Filter** | Beep, mute or cut swear words · custom sound · personal word library. |
| **Style** | **Captions** | Word-by-word animated captions: 8 built-in styles, 10 animations (pop, bounce, karaoke, typewriter…), cycling highlight colours, glow, box, outline, emoji, translation · **your own MOGRT** in Premiere · SRT always written. |
| | **AutoZoom** | Punch-ins on cuts / speech / emotion / emphasis words · Jump-cut, Smooth, Snap-in · anchor point · handheld drift · whoosh SFX. |
| | **B-Rolls** | Picks moments from the transcript, finds footage on Pexels (free key) or in your own folder. |
| **Audio** | **Enhance** | ElevenLabs Voice Isolator (your key) or free local denoise / de-hiss / de-click + loudness to -14/-16 LUFS. |
| **Multicam** | **Podcast** | Per-mic speaker detection, speaker priority, wide shots, reaction shots, min/max shot length. |
| | **Angles** | One voice, several cameras: switches on cuts, pauses, energy peaks and sentences. |
| **Repurpose** | **Viral** | Ranks 20–60 s moments (hooks, energy, pace, optional AI rerank) with a 0–100 score; each becomes a vertical sequence. |
| | **Resize** | 9:16, 4:5, 1:1, 16:9 or custom with face tracking, watermark, section ranges. |
| | **Chapters** | YouTube-ready timestamps + chapter markers on the timeline. |
| **Import** | **Download** | Any yt-dlp supported site: quality cap, container, audio-only, subtitles (embed), playlists & item ranges, section clips, SponsorBlock, metadata/thumbnail, rate limit, proxy, browser cookies · lands in your project bin · optionally runs another feature on it. |
| **Export** | **Render** | MP4 up to 4K60 on NVENC / QuickSync / AMF (auto-detected) or ProRes 4444 with alpha · **batch** whole folders. |

**The panel is yours to shape:** light / dark / auto theme, accent colour, compact or comfortable
density, text size, favourites (★ tab), feature search, run history with one-click "load settings",
Ctrl/⌘+Enter to apply, and a changed-setting marker so you always see what differs from defaults.

Every feature has **presets** (built-in + your own), a **review step** where it makes sense, and runs
**non-destructively**: Kerf creates a new sequence/timeline and never touches your original edit or media.

**Languages:** 99 via Whisper, plus South Asian profiles — `hinglish`, `tanglish` (Roman-script
output), `hindi`, `urdu`, `bengali`, `tamil`, `telugu`, `punjabi`, `marathi`, `gujarati`, `kannada`,
`malayalam`, `nepali`, `sinhala`. Point *Settings → Whisper model* at `large-v3` or any fine-tuned
faster-whisper model (Hugging Face id or local folder) for best accuracy.

## Install

**1. Engine** (Python 3.10+ and FFmpeg on PATH)

```bash
pip install -e ".[ai]"
```

```bash
python -m kerf serve
```

The Premiere panel can also start it for you (`start-kerf.cmd` / `start-kerf.command`).

**2a. Premiere Pro 25.6+ (UXP)** — run `install\install-premiere.ps1` (opens `release/kerf-premiere-*.ccx`
in Creative Cloud), then *Window → UXP Plugins → Kerf*. Developers: load `ui/dist-uxp/manifest.json`
in the **UXP Developer Tool**.

**2b. DaVinci Resolve 18.6+ (Free or Studio)** — run `install\install-resolve.ps1`, then
*Workspace → Scripts → Kerf*.

**2c. No editor?** Open <http://127.0.0.1:7878/app/> — the same UI works on media files and writes
XML you can import anywhere, or renders finished MP4s.

## AI providers (optional)

Kerf works fully offline. Add keys in the panel's ⚙ Settings (stored only in `~/.kerf/settings.json`):

| Provider | Used for | Default model |
|---|---|---|
| Claude (Anthropic) | Prompt Edit, chapter titles, viral rerank, translation, B-roll queries | `claude-opus-5-5` |
| OpenAI / Codex | same | `gpt-5` (any model id) |
| Google Gemini | same | `gemini-2.5-pro` |
| Local (Ollama, LM Studio…) | same, private | `llama3.1` |
| ElevenLabs | Studio voice isolation | — |
| Pexels | Stock B-roll | — |

## Command line

```bash
python -m kerf run silences --media talk.mp4 --preset Paced
```

```bash
python -m kerf batch captions D:\Shorts --preset "Bold Yellow" --render
```

```bash
python -m kerf features
```

## Extending Kerf

Drop a Python file in `~/.kerf/plugins/` — it appears in every panel automatically:

```python
def run(tl, params, ctx):          # tl: kerf.timeline.Timeline
    ...                            # cut, keyframe, add tracks…
    return {"timeline": tl, "report": {"done": True}}

FEATURES = [dict(name="myfx", title="My Effect", run=run, defaults={"strength": 1.0},
                 help="What it does", group="Style")]
```

Monetization hooks (paid tiers, licence checks, update channel) are described in
[docs/MONETIZATION.md](docs/MONETIZATION.md).

## How it works

```
Premiere UXP panel (React + TS) ┐                      ┌ FFmpeg · faster-whisper · Silero VAD
Resolve script (Fusion UI)      ├─ 127.0.0.1:7878 ─────┤ OpenCV YuNet · NumPy
Standalone web app              ┘   token-protected    └ Claude / OpenAI / Gemini / Ollama (opt-in)
     reads the timeline  →  engine builds the new edit  →  FCP7 XML  →  editor imports it
```

```
kerf/        engine (Python): timeline model + XML, one module per feature, server, CLI
ui/          React + TypeScript + SCSS, built with Vite → dist-uxp/ (Premiere) and dist/ (web app)
resolve/     DaVinci Resolve script
install/     installers · scripts/ release builder · tests/ · docs/ website + teardown
```

## Develop

```bash
python tests/test_core.py
```

```bash
cd ui && npm install && npm run build
```

`npm run dev:uxp` rebuilds on save for the UXP Developer Tool; `npm run dev:web` serves the web app.

## Known limits

- Animated zoom/resize keyframes are written to the XML; the built-in renderer uses each clip's first keyframe.
- MOGRT captions are Premiere-only (Resolve gets the animated overlay clip + SRT).
- XML motion units are verified on synthetic tests, not yet in every NLE version — see the teardown doc.

## License

[MIT](LICENSE). Kerf is an independent project and is not affiliated with Adobe, Blackmagic Design,
or any commercial plugin vendor.
