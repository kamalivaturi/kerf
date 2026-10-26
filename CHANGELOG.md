# Changelog

## 0.3.0 — 2026-10-26

Kerf now lives inside your editors. There is no separate app to open.

- **One installer, no app window.** Installing Kerf sets up the local engine and adds the Kerf panel to Premiere Pro
  (through Adobe's own plugin installer), After Effects and DaVinci Resolve. Opening a panel starts Kerf; it stops
  about a minute after your editors close and updates itself in between. Kerf 0.3 removes the old Kerf Studio app.
- **After Effects: the same Kerf panel as Premiere** (Window › Extensions › Kerf), replacing the grey ScriptUI panel.
  Every tool runs natively in AE as one undo step; captions, quick mask and beat detection run in the background so
  After Effects never freezes. New **Scripts hub**: search, pin and run the scripts and ScriptUI panels already
  installed in your After Effects, from one place.
- **DaVinci Resolve: a Kerf-styled window** with Tools, Motion, Shakes and Edit tabs, real settings controls instead
  of a JSON box (all values under "More settings"), and a review list only when there is something to review.
  The window sizes itself for high-DPI displays (all four tabs visible, fits a 1440p screen at 150%), zoom,
  shake, layout and stabilize timelines import reliably (clips already in the Media Pool are reused, repeat runs
  get numbered names), and Frame → Desktop saves the composited frame (every track, color and effects).
- **Only what works where you are:** each editor shows just the tools it supports (no Edit or Graphics tabs in
  After Effects, no MOGRT options in Resolve, no Premiere-only buttons elsewhere).
- **No file picking:** the media card is gone; Kerf works on the open sequence, composition or timeline.
- **Cleaner layout** (Laws of UX): one primary action per card, 44px targets, an 8px spacing scale, labels that never
  wrap, plain zoom controls ("Zoom in · Ease in / Ease out"), and Customize layout controls that no longer cover cards.
- **Sturdier:** every one of the 31 features runs with its defaults or asks for what it needs in plain language
  (missing API keys no longer show as errors); no repeating socket task inside After Effects.

## 0.2.3 — 2026-10-20

- **Premiere Pro 2026: the panel now reaches the Kerf engine.** Premiere 2026 rejects localhost network
  permissions, so 0.2.1 and 0.2.2 panels stayed on "engine offline"; this version connects.
- **Refined panel UI in Premiere:** buttons, icons, curve presets and the bezier curve now look the same as in
  Kerf Studio (Premiere drew them as plain grey native controls); sliders snap to whole values.
- **Responsive layout everywhere:** the toolkit cards flow into one, two or three columns with the panel width;
  the header stays on one line (details hide on narrow panels); nothing overflows sideways.
- **Effects keep each clip's framing:** zooms, shakes and other effects now build on a clip's existing Scale and
  Position (read from Premiere and Resolve) instead of resetting it, so a 16:9 clip filling a 9:16 sequence stays
  filled. Layouts and reframing still place clips themselves.
- **DaVinci Resolve window:** fixed garbled characters (the installer re-encoded the script), a branded header
  with live project/timeline/playhead, readable help text, a monospace settings editor, an orange Apply button,
  and the review list only appears when there is something to review.
- **Vertical scrolling:** the Premiere panel and Kerf Studio scroll when the panel is shorter than its content;
  the After Effects panel gets a scrollbar when docked short, and its side-by-side groups stack when narrow.
- The "closes in Ns" countdown no longer reports while an editor is open; heartbeats never overlap.

## 0.2.2 — 2026-10-20

- **Live editors:** Kerf sees which of Premiere Pro, After Effects and DaVinci Resolve are running and shows
  the open project, sequence/composition/timeline and playhead live in the header (hover a chip for size and fps).
  The Premiere panel updates every second, the After Effects panel every 2 s, the Resolve window while it is open.
- **Kerf runs only alongside an editor:** the engine and Kerf Studio close about a minute after the last editor
  closes; opened without one, Studio says so and counts down. Switch off in Settings → "Run only while … is open".
- **Effects adapt to the timeline:** rendered effects (speed ramps, rendered shakes, stabilizer) come out at the
  timeline's frame rate; shake strength and RGB split scale with the frame size (same look at 720p, 4K or 9:16);
  the caption preview and the MOGRT library default to the timeline's aspect ratio; and Kerf Studio builds its
  edits at the open editor sequence's resolution, fps and aspect (shown under the media field).
- The After Effects and Premiere panels start Kerf Studio when the engine isn't running.
- **XML motion fixed for Premiere and Resolve:** positions and scale were measured in both apps. Premiere now
  gets source-relative positions (9:16 reframes and picture-in-picture land where intended) and Resolve gets
  scale that accounts for its fit-to-frame, so zooms and resizes match in both.

## 0.2.1 — 2026-10-20

- **Automatic updates** in Kerf Studio: checks GitHub at launch and every 6 hours, downloads new versions in the
  background (signed and verified) and installs them when you quit. Switch off in Settings → Automatic updates.
  Installs from 0.2.0 need this one update by hand; every later version arrives by itself.
- **macOS:** the app is now signed (ad-hoc), so it no longer reports "damaged" on Apple silicon. First launch
  still asks once: right-click → Open (or System Settings → Privacy & Security → Open Anyway).
- **Choosing a video:** a "Choose video…" button (native file picker) and drag-and-drop anywhere in Kerf Studio.
  Tools pressed before a video is chosen now say so and open the picker instead of showing an error.
- **MOGRT pack:** 194 After Effects-built templates with previews. Graphics → Install the Kerf MOGRT pack.
  Essential Graphics controls now list Text first.

## 0.2.0 — 2026-10-19

- **Kerf Studio desktop app** (Rust/Tauri) for Windows, macOS and Linux: installers (.exe, .msi, .dmg,
  .AppImage, .deb, .rpm) and portable builds with the engine and FFmpeg bundled. No Python needed.
- **After Effects panel** (Window › Kerf.jsx): anchor, null/null+parent/adjustment/solid, beat markers, value
  and speed curves, editable expression shakes, Warp Stabilizer, eased zoom, align & distribute, project
  sorter, frame export, FX presets, offline AI cutout (draw a mask), captions.
- **Toolkit** in Premiere, Resolve and Studio: speed ramps with a bezier speed/value graph, camera shake
  (vertical, horizontal, HV, scale, all, custom; keyframes or rendered with flash + RGB split; live preview),
  one-click stabilizer, eased zoom in/out, anchor 9-grid, align/distribute/grid, generated layers, beat markers,
  Quick Mask (offline U²-Net cutout of a drawn region), project sorter, frame export, FX presets, per-project
  custom layout.
- **Premium UI**: new "ember" design with a segmented Tools / Graphs / Motion / Shakes / Edit / Graphics bar.
- **Licences**: optional Lemon Squeezy licence keys (activate in Settings) for future paid plans; all
  features remain free.
- Resolve: finds Kerf Studio's engine on every OS, reads the playhead, sorts the Media Pool, places layers.
- Transcription falls back to the CPU automatically when a GPU lacks the CUDA 12 libraries.
- CI now tests on Windows, macOS and Linux; every tag builds all installers.
- Fixes: hardware encoders are used only when they actually work (no GPU → x264); transcription works offline
  from cached models; a clear message when an FFmpeg build has no libass (captions); settings → Report a bug.
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
