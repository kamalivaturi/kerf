# Third-party notices

Kerf's own code is MIT licensed (see `LICENSE`). Kerf ships, or downloads on first use, the open-source work
below; each keeps its own licence. Versions are those of the 0.3 builds.

## Programs shipped with the engine

| Program | Licence | Notes |
|---|---|---|
| FFmpeg (`ffmpeg`, `ffprobe`) | GPL-3.0-or-later | Run as separate programs. Licence text and source: `bin/FFMPEG-LICENSE-GPL-3.0.txt` and `bin/FFMPEG-SOURCE.txt` beside them. Windows and Linux builds: BtbN/FFmpeg-Builds; macOS: ffmpeg.martin-riedl.de |
| Python runtime | PSF-2.0 | Bundled by PyInstaller |

## Python libraries shipped with the engine

| Library | Version | Licence |
|---|---|---|
| anyio | 4.12.1 | MIT |
| av (PyAV) | 18.1.0 | BSD-3-Clause; its wheel includes FFmpeg libraries under the LGPL |
| certifi | 2026.6.17 | MPL-2.0 |
| click | 8.4.2 | BSD-3-Clause |
| colorama | 0.4.6 | BSD |
| ctranslate2 | 4.8.1 | MIT |
| faster-whisper | 1.2.1 | MIT (includes the Silero VAD model, MIT) |
| filelock | 3.32.3 | MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |
| fsspec | 2026.7.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| hf-xet | 1.6.0 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| huggingface-hub | 1.27.0 | Apache-2.0 |
| idna | 3.18 | BSD-3-Clause |
| numpy | 2.5.1 | BSD-3-Clause and others (0BSD, MIT, Zlib, CC0-1.0) |
| onnxruntime | 1.28.0 | MIT |
| opencv-python | 5.0.0.93 | Apache-2.0; its wheel includes FFmpeg libraries under the LGPL |
| packaging | 26.3 | Apache-2.0 or BSD-2-Clause |
| protobuf | 6.33.6 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| setuptools | 84.0.0 | MIT |
| sherpa-onnx, sherpa-onnx-core | 2.0.1 | Apache-2.0 |
| tokenizers | 0.22.2 | Apache-2.0 |
| tqdm | 4.70.0 | MPL-2.0 and MIT |
| typing-extensions | 4.15.0 | PSF-2.0 |
| yt-dlp | 2026.8.19 | Unlicense |

## Models downloaded on first use (not in the installer)

| Model | Used for | From | Licence |
|---|---|---|---|
| Whisper (faster-whisper conversions) | Transcripts and captions | Hugging Face (Systran) | MIT |
| Kokoro v1.0, int8 multi-language | Voiceover | k2-fsa/sherpa-onnx releases | Apache-2.0 |
| U²-Net (`u2netp`, `u2net_human_seg`), Silueta | Quick mask cutouts | danielgatis/rembg releases | U²-Net: Apache-2.0; Silueta: as published by rembg |
| YuNet (2023mar) | Face tracking for reframing | opencv/opencv_zoo | as published in opencv_zoo |

## Services Kerf can call only when you switch them on

ElevenLabs (voice isolation, dubbing), Claude, OpenAI, Gemini or a local Ollama model (prompt edits), a speech
server you configure, GitHub (updates, the MOGRT pack). Their own terms apply to what you send them.

## The Kerf helper and panels

The installer and helper are built with Tauri (MIT or Apache-2.0) and Rust crates under permissive licences; the
panels with React (MIT) and Vite (MIT). Kerf FX is built against the OpenFX headers (BSD-3-Clause).
