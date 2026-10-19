# Changelog

## Unreleased

- Graphics & MOGRTs: a 194-template Kerf pack (captions, titles, lower thirds; 14 animations × 5 looks,
  16:9 and 9:16) with live animated previews in the panel, built by After Effects into real .mogrt files
  where every control stays editable in Essential Graphics. Import any .mogrt you own.
- MOGRT Studio: change animation, speed, stagger, length, font, size, colors, stroke, highlight, letter
  spacing, line spacing, kerning, alignment, box, shadow and glow; save styles or your own MOGRT.
- Insert a MOGRT at the playhead; caption MOGRT text now also fills AE text fields correctly.
- Captions: live preview with safe zones for 9:16, 1:1 and 16:9.
- Transcription: large-v3-turbo on GPU, automatic language detection, 21 mixed-language profiles
  (Hinglish, Tanglish, Spanglish…), an editable transcript, and a vocabulary that learns from your fixes.
- Silences: new "hybrid" detection (loudness and the speech model must agree).
- Audio: music with auto-ducking, a sound-effect pack on cuts, beat-synced edits, translate and dub.
- One-click recipes: TikTok talking head, YouTube vlog, podcast, tutorial, Instagram reel, music video.
- Share presets: export or import all your presets as one block of text.
- Panel in 10 languages (follows your system language, Arabic right-to-left), What's new, F1 help.

## 0.1.1 — 2026-10-19

- Downloads from YouTube work again: Kerf now requires yt-dlp 2026.08.19 or newer (older versions got
  HTTP 403 from YouTube). Existing installs: run `pip install -U yt-dlp`.

## 0.1.0 — 2026-10-19

First release.

- Engine: Silences (loudness + Silero VAD), Repeat, Profanity, Captions (8 styles, 10 animations, MOGRT,
  SRT, translation, South Asian profiles), AutoZoom, B-Rolls, Podcast, Angles, Viral, Resize, Chapters,
  Enhance (ElevenLabs / local), Render (GPU, 4K60, alpha), batch, AI Prompt Edit (Claude, OpenAI, Gemini,
  local), Pipelines, presets for every feature, drop-in plugins, entitlement hook, update checker.
- Download from any yt-dlp supported site (formats, audio-only, subtitles, playlists, sections, SponsorBlock).
- Premiere Pro UXP plugin (React + TypeScript + Vite + SCSS): light/dark/auto theme, accent colours, density,
  text size, favourites, search, run history, Ctrl+Enter.
- DaVinci Resolve script (Free & Studio).
- Standalone web app at http://127.0.0.1:7878/app/.
