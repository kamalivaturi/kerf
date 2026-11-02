// Kerf FX captions: word-timed captions drawn into the frame, from an SRT or a Kerf transcript.
#pragma once
#include <string>

namespace captions {

extern const char *TEMPLATES[];  // names, in menu order (nullptr-terminated)
extern const char *LANGUAGES[];  // menu labels (nullptr-terminated); same order as the engine values below
extern const char *LANGUAGE_CODES[];

struct Settings {
  std::string file;      // SRT or Kerf words (.tsv); empty = the transcript of `media`
  std::string media;     // the clip's media file, for the Transcribe button
  std::string language;  // engine language value ("" = detect)
  std::string font;      // optional font file overriding the template's
  int tmpl = 0, words = 0, letterCase = 0;  // words 0 = template; case 0 template, 1 upper, 2 as spoken
  double size = 100, raise = 0, offset = 0;  // size %, position change (% of height), sync (s)
  bool customColors = false;
  double color[3] = {1, 1, 1}, highlight[3] = {1, 0.83, 0};
};

// A float RGBA image (premultiplied) the captions are drawn over, in OFX pixel coordinates (y up).
struct Canvas {
  float *base;
  int x1, y1, x2, y2, row;  // bounds and bytes per row
  int wx1, wy1, wx2, wy2;   // render window: only these pixels are written
  double fx, fy, W, H;      // the frame (project) rectangle in the same pixels
};

// Draws the captions (or a status line, such as "Transcribing…") for time `sec`; false = nothing to draw.
bool draw(const Settings &s, double sec, const Canvas &c);
// Asks the local Kerf engine to transcribe `media` in the background; the result appears on the next render.
void transcribe(const std::string &media, const std::string &language);

}  // namespace captions
