// Kerf FX: one OpenFX effect for DaVinci Resolve (and any OFX host) with a Mode menu: Shake, Zoom (eased),
// RGB Split, Vignette, Letterbox, Speed Ramp, Motion Blur and Captions. Only the chosen mode's controls show.
// Plain OpenFX C API, 32-bit float RGBA (Resolve's processing format), rows split across CPU threads.
// Speed Ramp and Motion Blur read other frames of the clip (temporal clip access), so they never change its length.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <string>
#include <thread>
#include <vector>

#include "captions.h"
#include "ofxImageEffect.h"

static OfxHost *gHost;
static const OfxPropertySuiteV1 *P;
static const OfxImageEffectSuiteV1 *E;
static const OfxParameterSuiteV1 *Pa;

enum Kind { SHAKE, ZOOM, SPLIT, VIGNETTE, LETTERBOX, SPEEDRAMP, MOTIONBLUR, CAPTIONS, KINDS };
static const char *MODES[KINDS] = {"Shake",      "Zoom",       "RGB split",   "Vignette",
                                   "Letterbox",  "Speed ramp", "Motion blur", "Captions"};
static const char *PREFIX[KINDS] = {"shake", "zoom", "split", "vignette", "letterbox", "ramp", "blur", "cap"};
static const char *ABOUT =
    "Kerf's effects in one: pick a Mode. Shake, eased Zoom, RGB split, Vignette, Letterbox, Speed ramp and Motion "
    "blur work on the clip in place; Captions draws word-timed captions from an SRT or a Kerf transcript.";
static const double PI = 3.14159265358979;

// ------------------------------------------------------------------------------------------------ params
// Every mode's params are named "<prefix>_<name>" and sit in the group "g_<prefix>", so modes never share a name
// (several have an "amount") and a whole mode can be shown or hidden at once.
static Kind gKind;                              // the mode whose params are being defined
static std::vector<std::string> gNames[KINDS];  // each mode's params, to show only the chosen mode's
static std::string key(int k, const char *name) { return std::string(PREFIX[k]) + "_" + name; }

static OfxPropertySetHandle define(OfxParamSetHandle ps, const char *type, const char *name, const char *label,
                                   const char *hint) {
  std::string full = key(gKind, name);
  if (std::find(gNames[gKind].begin(), gNames[gKind].end(), full) == gNames[gKind].end())
    gNames[gKind].push_back(full);
  if (!ps) return nullptr;  // only collecting names
  OfxPropertySetHandle p;
  Pa->paramDefine(ps, type, full.c_str(), &p);
  P->propSetString(p, kOfxPropLabel, 0, label);
  P->propSetString(p, kOfxParamPropHint, 0, hint);
  P->propSetString(p, kOfxParamPropParent, 0, (std::string("g_") + PREFIX[gKind]).c_str());
  return p;
}
static void number(OfxParamSetHandle ps, const char *name, const char *label, double def, double lo, double hi,
                   const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeDouble, name, label, hint);
  if (!p) return;
  P->propSetDouble(p, kOfxParamPropDefault, 0, def);
  P->propSetDouble(p, kOfxParamPropMin, 0, lo);
  P->propSetDouble(p, kOfxParamPropMax, 0, hi);
  P->propSetDouble(p, kOfxParamPropDisplayMin, 0, lo);
  P->propSetDouble(p, kOfxParamPropDisplayMax, 0, hi);
}
static void choice(OfxParamSetHandle ps, const char *name, const char *label, std::vector<const char *> options, int def,
                   const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeChoice, name, label, hint);
  if (!p) return;
  for (int i = 0; i < (int)options.size(); i++) P->propSetString(p, kOfxParamPropChoiceOption, i, options[i]);
  P->propSetInt(p, kOfxParamPropDefault, 0, def);
}
static void toggle(OfxParamSetHandle ps, const char *name, const char *label, int def, const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeBoolean, name, label, hint);
  if (p) P->propSetInt(p, kOfxParamPropDefault, 0, def);
}
static void text(OfxParamSetHandle ps, const char *name, const char *label, bool file, const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeString, name, label, hint);
  if (!p) return;
  P->propSetString(p, kOfxParamPropStringMode, 0, file ? kOfxParamStringIsFilePath : kOfxParamStringIsSingleLine);
  if (file) P->propSetInt(p, kOfxParamPropStringFilePathExists, 0, 1);
  P->propSetString(p, kOfxParamPropDefault, 0, "");
  P->propSetInt(p, kOfxParamPropAnimates, 0, 0);
}
static void button(OfxParamSetHandle ps, const char *name, const char *label, const char *hint) {
  define(ps, kOfxParamTypePushButton, name, label, hint);
}
static void rgb(OfxParamSetHandle ps, const char *name, const char *label, double r, double g, double b,
                const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeRGB, name, label, hint);
  if (!p) return;
  P->propSetDouble(p, kOfxParamPropDefault, 0, r);
  P->propSetDouble(p, kOfxParamPropDefault, 1, g);
  P->propSetDouble(p, kOfxParamPropDefault, 2, b);
}
static std::vector<const char *> list(const char *const *items) {
  std::vector<const char *> v;
  while (*items) v.push_back(*items++);
  return v;
}

static void describeParams(Kind k, OfxParamSetHandle ps) {
  gKind = k;
  switch (k) {
    case SHAKE:
      number(ps, "amplitude", "Amplitude (px)", 28, 0, 400, "How far the frame moves, in pixels at 1080p");
      number(ps, "frequency", "Frequency (Hz)", 11, 0.1, 40, "Shakes per second");
      number(ps, "rotation", "Rotation (deg)", 1.5, 0, 45, "How far the frame tilts");
      choice(ps, "axis", "Axis", {"Both", "Horizontal", "Vertical"}, 0, "Directions the frame moves in");
      number(ps, "seed", "Seed", 1, 0, 1000, "Change for a different shake pattern");
      toggle(ps, "hideEdges", "Hide edges", 1, "Scale up just enough that the frame edges never show");
      break;
    case ZOOM:
      choice(ps, "direction", "Direction", {"Zoom in", "Zoom out"}, 0, "Zoom in to Amount, or out from Amount");
      number(ps, "amount", "Amount (%)", 120, 100, 400, "Scale at the end of a zoom in (start of a zoom out)");
      number(ps, "duration", "Duration (s)", 0.6, 0.04, 30, "Length of the move");
      choice(ps, "at", "At", {"Clip start", "Clip end"}, 0, "The move starts with the clip, or ends with it");
      choice(ps, "ease", "Ease", {"Ease out", "Ease in", "Ease in-out", "Linear"}, 0, "Speed curve of the move");
      number(ps, "centerX", "Center X (%)", 50, 0, 100, "Zoom point, from the left edge");
      number(ps, "centerY", "Center Y (%)", 50, 0, 100, "Zoom point, from the bottom edge");
      break;
    case SPLIT:
      number(ps, "amount", "Amount (px)", 12, 0, 200, "Distance between the red and blue copies, at 1080p");
      number(ps, "angle", "Angle (deg)", 0, -180, 180, "Direction of the split");
      break;
    case VIGNETTE:
      number(ps, "amount", "Amount", 0.45, 0, 1, "How dark the edges get");
      number(ps, "size", "Size", 0.85, 0.1, 1.5, "Where the darkening starts (1 = frame edge)");
      number(ps, "softness", "Softness", 0.9, 0.01, 2, "Width of the fade");
      number(ps, "roundness", "Roundness", 0.4, 0, 1, "0 follows the frame shape, 1 is a circle");
      break;
    case LETTERBOX:
      number(ps, "aspect", "Aspect ratio", 2.39, 0.3, 4, "2.39 scope, 1.85 flat, 1.33 for 4:3 pillars");
      number(ps, "opacity", "Opacity", 1, 0, 1, "Bar opacity");
      break;
    case SPEEDRAMP:
      choice(ps, "curve", "Ramp",
             {"Slow, fast, slow", "Fast, slow, fast", "Speed up", "Slow down", "Wave", "Double wave", "Boomerang",
              "Reverse boomerang", "Steps", "Hold in the middle"},
             1, "How speed changes across the clip; the clip keeps its length");
      number(ps, "strength", "Strength", 1, 0, 1, "0 = normal speed, 1 = the full ramp");
      toggle(ps, "reverse", "Play backwards", 0, "Run the ramped clip in reverse");
      toggle(ps, "smooth", "Smooth frames", 1, "Blend neighbouring frames so slow parts don't stutter");
      number(ps, "rampBlur", "Ramp blur", 0.5, 0, 1, "Motion blur on the fast parts (blends the frames they skip)");
      break;
    case MOTIONBLUR:
      choice(ps, "mode", "Mode", {"Automatic (camera motion)", "Directional"}, 0,
             "Automatic measures how the shot moves between frames; Directional blurs along an angle you set");
      number(ps, "amount", "Amount", 1, 0, 3, "1 is a natural 180-degree shutter; keyframe it for whip pans");
      number(ps, "length", "Length (px)", 40, 0, 400, "Directional mode: blur length, at 1080p");
      number(ps, "angle", "Angle (deg)", 0, -180, 180, "Directional mode: blur direction");
      break;
    case CAPTIONS:
      text(ps, "file", "Captions file", true,
           "An SRT (Resolve's own subtitles export one) or a Kerf transcript. Leave empty to transcribe below");
      text(ps, "media", "Media to transcribe", true, "This clip's media file: Kerf listens to it and times every word");
      choice(ps, "language", "Language", list(captions::LANGUAGES), 0,
             "The language spoken; Hinglish and Tanglish write Hindi or Tamil words in Latin letters");
      button(ps, "transcribe", "Transcribe with Kerf", "Needs Kerf running. The captions appear when it finishes");
      choice(ps, "template", "Template", list(captions::TEMPLATES), 1, "The caption look and how words appear");
      number(ps, "size", "Size (%)", 100, 20, 400, "Text size, relative to the template");
      number(ps, "raise", "Raise (%)", 0, -50, 70, "Move the captions up (or down, below 0), as % of the height");
      number(ps, "words", "Words per caption", 0, 0, 12, "0 uses the template's number");
      choice(ps, "case", "Letters", {"As the template", "UPPERCASE", "As spoken"}, 0, "Upper case or as transcribed");
      toggle(ps, "custom", "Custom colours", 0, "Use the two colours below instead of the template's");
      rgb(ps, "color", "Text colour", 1, 1, 1, "The words' colour, with Custom colours on");
      rgb(ps, "highlight", "Highlight colour", 1, 0.83, 0, "The spoken word's colour, box or glow");
      number(ps, "offset", "Sync (s)", 0, -10, 10, "Move the captions later (+) or earlier (-) to match the voice");
      text(ps, "font", "Font file", true, "Optional: a .ttf or .otf to use instead of the template's font");
      break;
    default:
      break;
  }
}

// Each mode's param names, without a host (for showing and hiding them even when the host cached descriptions).
static void collectNames() {
  if (!gNames[0].empty()) return;
  for (int k = 0; k < KINDS; k++) describeParams((Kind)k, nullptr);
}

static OfxParamHandle param(OfxImageEffectHandle fx, const char *name) {
  OfxParamSetHandle ps;
  OfxParamHandle h = nullptr;
  E->getParamSet(fx, &ps);
  Pa->paramGetHandle(ps, name, &h, nullptr);
  return h;
}
static double num(OfxImageEffectHandle fx, const char *name, double t) {
  double v = 0;
  Pa->paramGetValueAtTime(param(fx, name), t, &v);
  return v;
}
static int pick(OfxImageEffectHandle fx, const char *name, double t) {
  int v = 0;
  Pa->paramGetValueAtTime(param(fx, name), t, &v);
  return v;
}
static std::string str(OfxImageEffectHandle fx, const char *name) {
  char *v = nullptr;
  Pa->paramGetValue(param(fx, name), &v);
  return v ? v : "";
}

// Show the chosen mode's group and params, hide the others'.
static void showMode(OfxImageEffectHandle fx) {
  collectNames();
  int mode = 0;
  Pa->paramGetValue(param(fx, "mode"), &mode);
  auto secret = [&](const std::string &name, bool hide) {
    OfxParamHandle h = param(fx, name.c_str());
    OfxPropertySetHandle ps;
    if (h && Pa->paramGetPropertySet(h, &ps) == kOfxStatOK) P->propSetInt(ps, kOfxParamPropSecret, 0, hide ? 1 : 0);
  };
  for (int k = 0; k < KINDS; k++) {
    secret(std::string("g_") + PREFIX[k], k != mode);
    for (auto &n : gNames[k]) secret(n, k != mode);
  }
}

// ------------------------------------------------------------------------------------------------ images
struct Img {
  OfxPropertySetHandle h = nullptr;
  char *data = nullptr;
  OfxRectI b{0, 0, 0, 0};
  int row = 0;
  float *px(int x, int y) const { return (float *)(data + (ptrdiff_t)(y - b.y1) * row) + (ptrdiff_t)(x - b.x1) * 4; }
  bool in(int x, int y) const { return x >= b.x1 && x < b.x2 && y >= b.y1 && y < b.y2; }
};

static bool fetch(OfxImageEffectHandle fx, const char *clipName, double t, Img &im) {
  OfxImageClipHandle clip;
  if (E->clipGetHandle(fx, clipName, &clip, nullptr) != kOfxStatOK) return false;
  if (E->clipGetImage(clip, t, nullptr, &im.h) != kOfxStatOK || !im.h) return false;
  void *d = nullptr;
  P->propGetPointer(im.h, kOfxImagePropData, 0, &d);
  im.data = (char *)d;
  P->propGetIntN(im.h, kOfxImagePropBounds, 4, &im.b.x1);
  P->propGetInt(im.h, kOfxImagePropRowBytes, 0, &im.row);
  if (!im.data) {  // an image without pixels is no image: hand it back so it never leaks
    E->clipReleaseImage(im.h);
    im.h = nullptr;
  }
  return im.data != nullptr;
}

// Bilinear sample at pixel coordinates (pixel centres at +0.5); outside the image is transparent.
static void sample(const Img &s, double x, double y, float *o) {
  x -= 0.5;
  y -= 0.5;
  int x0 = (int)std::floor(x), y0 = (int)std::floor(y);
  float fx = (float)(x - x0), fy = (float)(y - y0), acc[4] = {0, 0, 0, 0};
  for (int j = 0; j < 2; j++)
    for (int i = 0; i < 2; i++) {
      if (!s.in(x0 + i, y0 + j)) continue;
      float w = (i ? fx : 1 - fx) * (j ? fy : 1 - fy);
      const float *p = s.px(x0 + i, y0 + j);
      for (int c = 0; c < 4; c++) acc[c] += w * p[c];
    }
  std::memcpy(o, acc, sizeof acc);
}

template <class F>
static void rows(int y1, int y2, F f) {
  int n = (int)std::max(1u, std::thread::hardware_concurrency()), step = std::max(1, (y2 - y1 + n - 1) / n);
  std::vector<std::thread> pool;
  for (int a = y1; a < y2; a += step) {
    int b = std::min(y2, a + step);
    try {
      pool.emplace_back([=] {
        for (int y = a; y < b; y++) f(y);
      });
    } catch (...) {  // no thread available: do this band here (an unjoined thread would terminate the host)
      for (int y = a; y < b; y++) f(y);
    }
  }
  for (auto &t : pool) t.join();
}

// Smooth pseudo-random wave in [-1, 1]: three detuned sines, so it never visibly repeats.
static double wave(double u, double seed) {
  return 0.6 * std::sin(2 * PI * u + seed * 1.7) + 0.3 * std::sin(2 * PI * 2.13 * u + seed * 3.1) +
         0.1 * std::sin(2 * PI * 4.37 * u + seed * 5.3);
}

static double ease(int kind, double p) {
  p = std::clamp(p, 0.0, 1.0);
  switch (kind) {
    case 0: return 1 - std::pow(1 - p, 3);                                   // ease out
    case 1: return p * p * p;                                                // ease in
    case 2: return p < 0.5 ? 4 * p * p * p : 1 - std::pow(-2 * p + 2, 3) / 2;  // ease in-out
    default: return p;
  }
}

// Speed ramp curves: position in the clip (p, 0..1) -> position in the source (0..1). The slope is the playback
// speed, so every curve starts at 0 and ends at 1 (the clip keeps its length) except the boomerangs, which come back.
static double rampCurve(int kind, double p) {
  p = std::clamp(p, 0.0, 1.0);
  switch (kind) {
    case 0: return p - std::sin(2 * PI * p) / (2 * PI);                  // slow, fast, slow
    case 1: return p + 0.9 * std::sin(2 * PI * p) / (2 * PI);            // fast, slow, fast
    case 2: return p * p;                                                // speed up
    case 3: return 1 - (1 - p) * (1 - p);                                // slow down
    case 4: return p + 0.9 * std::sin(4 * PI * p) / (4 * PI);            // wave
    case 5: return p + 0.9 * std::sin(8 * PI * p) / (8 * PI);            // double wave
    case 6: return std::sin(PI * p);                                     // boomerang: forward, then back
    case 7: return 1 - std::sin(PI * p);                                 // reverse boomerang
    case 8: {                                                            // steps: dash, settle, dash...
      double n = 4, i = std::floor(std::min(p * n, n - 1e-9)), f = p * n - i;
      return (i + f * f * (3 - 2 * f)) / n;
    }
    case 9: {                                                            // hold in the middle
      double d = 2 * p - 1;
      return 0.5 + 0.5 * d * d * d;
    }
    default: return p;
  }
}

// Frames of the source clip at other times, fetched once per render and released together.
struct FrameCache {
  OfxImageEffectHandle fx;
  double first, last;
  std::deque<std::pair<int, Img>> held;  // deque: pointers handed out stay valid as frames are added
  const Img *at(int f) {
    f = (int)std::clamp((double)f, first, last);
    for (auto &h : held)
      if (h.first == f) return h.second.data ? &h.second : nullptr;
    Img im;
    if (!fetch(fx, kOfxImageEffectSimpleSourceClipName, f, im)) im = Img();
    held.emplace_back(f, im);
    return im.data ? &held.back().second : nullptr;
  }
  ~FrameCache() {
    for (auto &h : held)
      if (h.second.h) E->clipReleaseImage(h.second.h);
  }
};

// Average of samples along (vx, vy), centred on each pixel: the motion blur kernel.
static void directional(const Img &src, const Img &dst, const OfxRectI &w, double vx, double vy) {
  int n = (int)std::clamp(std::ceil(std::hypot(vx, vy) / 1.5) + 1, 2.0, 48.0);  // >= 2 taps: short blurs still blur
  rows(w.y1, w.y2, [&](int y) {
    for (int x = w.x1; x < w.x2; x++) {
      float acc[4] = {0, 0, 0, 0}, s[4];
      for (int i = 0; i < n; i++) {
        double u = (double)i / (n - 1) - 0.5;
        sample(src, x + 0.5 + u * vx, y + 0.5 + u * vy, s);
        for (int c = 0; c < 4; c++) acc[c] += s[c];
      }
      float *o = dst.px(x, y);
      for (int c = 0; c < 4; c++) o[c] = acc[c] / n;
    }
  });
}

// Global motion between two frames: brute-force shift search on small luma thumbnails (pans and tilts).
static void shiftBetween(const Img &a, const Img &b, double &dx, double &dy) {
  const int gw = 96, R = 12;
  int W = a.b.x2 - a.b.x1, H = a.b.y2 - a.b.y1, gh = std::max(8, gw * H / std::max(1, W));
  auto thumb = [&](const Img &im) {
    std::vector<float> g(gw * gh, 0);
    for (int j = 0; j < gh; j++)
      for (int i = 0; i < gw; i++) {
        int x = im.b.x1 + (int)((i + 0.5) * W / gw), y = im.b.y1 + (int)((j + 0.5) * H / gh);
        if (!im.in(x, y)) continue;
        const float *p = im.px(x, y);
        g[j * gw + i] = 0.3f * p[0] + 0.59f * p[1] + 0.11f * p[2];
      }
    return g;
  };
  std::vector<float> ga = thumb(a), gb = thumb(b);
  double best = 1e30;
  dx = dy = 0;
  for (int sy = -R; sy <= R; sy++)
    for (int sx = -R; sx <= R; sx++) {
      double err = 0;
      int cnt = 0;
      for (int j = R; j < gh - R; j++)
        for (int i = R; i < gw - R; i++) {
          err += std::fabs(ga[j * gw + i] - gb[(j + sy) * gw + (i + sx)]);
          cnt++;
        }
      err = cnt ? err / cnt + 1e-4 * (sx * sx + sy * sy) : 1e30;  // tiny bias towards "no motion" on flat frames
      if (err < best) best = err, dx = sx, dy = sy;
    }
  dx *= (double)W / gw;  // a(x) matches b(x + s): the picture moved by +s from a to b
  dy *= (double)H / gh;
}

// ------------------------------------------------------------------------------------------------ render
static OfxStatus render(OfxImageEffectHandle fx, OfxPropertySetHandle in) {
  double t = 0, rs[2] = {1, 1};
  OfxRectI w;
  P->propGetDouble(in, kOfxPropTime, 0, &t);
  P->propGetIntN(in, kOfxImageEffectPropRenderWindow, 4, &w.x1);
  P->propGetDoubleN(in, kOfxImageEffectPropRenderScale, 2, rs);
  Kind k = (Kind)std::clamp(pick(fx, "mode", t), 0, KINDS - 1);
  auto N = [&](const char *name) { return num(fx, key(k, name).c_str(), t); };
  auto I = [&](const char *name) { return pick(fx, key(k, name).c_str(), t); };

  Img src, dst;
  if (!fetch(fx, kOfxImageEffectOutputClipName, t, dst)) return kOfxStatFailed;
  if (!fetch(fx, kOfxImageEffectSimpleSourceClipName, t, src)) {
    E->clipReleaseImage(dst.h);
    return kOfxStatFailed;
  }
  char *depth = nullptr, *comps = nullptr;
  P->propGetString(dst.h, kOfxImageEffectPropPixelDepth, 0, &depth);
  P->propGetString(dst.h, kOfxImageEffectPropComponents, 0, &comps);
  if (!depth || !comps || std::strcmp(depth, kOfxBitDepthFloat) || std::strcmp(comps, kOfxImageComponentRGBA)) {
    E->clipReleaseImage(src.h);
    E->clipReleaseImage(dst.h);
    return kOfxStatErrImageFormat;
  }

  // Frame geometry in render pixels: the project (timeline) frame, else the source image.
  OfxPropertySetHandle fxProps;
  E->getPropertySet(fx, &fxProps);
  double ext[2] = {0, 0};
  P->propGetDoubleN(fxProps, kOfxImageEffectPropProjectExtent, 2, ext);
  bool proj = ext[0] > 0 && ext[1] > 0;
  double W = proj ? ext[0] * rs[0] : src.b.x2 - src.b.x1, H = proj ? ext[1] * rs[1] : src.b.y2 - src.b.y1;
  double cx = proj ? W / 2 : (src.b.x1 + src.b.x2) / 2.0, cy = proj ? H / 2 : (src.b.y1 + src.b.y2) / 2.0;
  double k1080 = std::min(W, H) / 1080.0;  // pixel params are "at 1080p", scaled to this frame and render scale

  OfxImageClipHandle clip;
  OfxPropertySetHandle clipProps;
  E->clipGetHandle(fx, kOfxImageEffectSimpleSourceClipName, &clip, &clipProps);
  double fps = 0, range[2] = {0, 0};
  P->propGetDouble(clipProps, kOfxImageEffectPropFrameRate, 0, &fps);
  P->propGetDoubleN(clipProps, kOfxImageEffectPropFrameRange, 2, range);
  if (fps <= 0) fps = 30;

  // Affine inverse mapping (output -> source) shared by Shake and Zoom: src = z + R(-a) * (out - z - d) / s.
  double s = 1, a = 0, dx = 0, dy = 0, zx = cx, zy = cy;
  bool affine = false;
  if (k == SHAKE) {
    double amp = N("amplitude") * k1080, freq = N("frequency"), seed = N("seed");
    double rot = N("rotation") * PI / 180, sec = t / fps;
    int axis = I("axis");
    dx = axis == 2 ? 0 : amp * wave(sec * freq, seed);
    dy = axis == 1 ? 0 : amp * wave(sec * freq * 0.93, seed + 11);
    a = rot * wave(sec * freq * 0.71, seed + 23);
    if (I("hideEdges"))  // enough overscan for the largest move and tilt
      s = 1 + 2 * amp / std::min(W, H) + std::sin(rot) * std::max(W, H) / std::min(W, H);
    affine = true;
  } else if (k == ZOOM) {
    double amount = N("amount") / 100, frames = std::max(1.0, N("duration") * fps);
    double start = I("at") == 0 ? range[0] : range[1] - frames;
    double e = ease(I("ease"), (t - start) / frames);
    s = I("direction") == 0 ? 1 + (amount - 1) * e : amount + (1 - amount) * e;
    zx = (cx - W / 2) + W * N("centerX") / 100;
    zy = (cy - H / 2) + H * N("centerY") / 100;
    affine = true;
  }

  if (affine) {
    double ca = std::cos(-a), sa = std::sin(-a);
    rows(w.y1, w.y2, [&](int y) {
      for (int x = w.x1; x < w.x2; x++) {
        double ox = x + 0.5 - zx - dx, oy = y + 0.5 - zy - dy;
        sample(src, zx + (ca * ox - sa * oy) / s, zy + (sa * ox + ca * oy) / s, dst.px(x, y));
      }
    });
  } else if (k == SPLIT) {
    double amt = N("amount") * k1080, ang = N("angle") * PI / 180;
    double ox = amt * std::cos(ang), oy = amt * std::sin(ang);
    rows(w.y1, w.y2, [&](int y) {
      for (int x = w.x1; x < w.x2; x++) {
        float r[4], b[4], *o = dst.px(x, y);
        const float *g = src.in(x, y) ? src.px(x, y) : nullptr;
        sample(src, x + 0.5 + ox, y + 0.5 + oy, r);
        sample(src, x + 0.5 - ox, y + 0.5 - oy, b);
        o[0] = r[0];
        o[1] = g ? g[1] : 0;
        o[2] = b[2];
        o[3] = std::max({r[3], b[3], g ? g[3] : 0.f});
      }
    });
  } else if (k == VIGNETTE) {
    double amount = N("amount"), size = N("size"), soft = N("softness");
    double round = N("roundness"), aspect = W / H;
    rows(w.y1, w.y2, [&](int y) {
      for (int x = w.x1; x < w.x2; x++) {
        double nx = (x + 0.5 - cx) / (W / 2), ny = (y + 0.5 - cy) / (H / 2);
        if (aspect > 1) nx *= 1 + (aspect - 1) * round; else ny *= 1 + (1 / aspect - 1) * round;
        double d = std::sqrt(nx * nx + ny * ny), v = std::clamp((d - size) / soft, 0.0, 1.0);
        float f = (float)(1 - amount * v * v * (3 - 2 * v));
        const float *i = src.in(x, y) ? src.px(x, y) : nullptr;
        float *o = dst.px(x, y);
        for (int c = 0; c < 3; c++) o[c] = i ? i[c] * f : 0;
        o[3] = i ? i[3] : 0;
      }
    });
  } else if (k == LETTERBOX) {
    double target = N("aspect");
    float op = (float)N("opacity");
    double vw = std::min(W, H * target), vh = std::min(H, W / target);  // the picture area left between the bars
    rows(w.y1, w.y2, [&](int y) {
      for (int x = w.x1; x < w.x2; x++) {
        bool bar = std::fabs(x + 0.5 - cx) > vw / 2 || std::fabs(y + 0.5 - cy) > vh / 2;
        const float *i = src.in(x, y) ? src.px(x, y) : nullptr;
        float *o = dst.px(x, y), keep = bar ? 1 - op : 1.f, alpha = i ? i[3] : 0;
        for (int c = 0; c < 3; c++) o[c] = i ? i[c] * keep : 0;
        o[3] = bar ? alpha * keep + op : alpha;  // black bars over the picture
      }
    });
  } else if (k == SPEEDRAMP || k == MOTIONBLUR) {
    double first = range[0], last = std::max(range[0], range[1]);  // OFX frame ranges include their last frame
    FrameCache frames{fx, first, last, {}};
    auto copy = [&](const Img &from) {
      rows(w.y1, w.y2, [&](int y) {
        for (int x = w.x1; x < w.x2; x++) {
          const float *i = from.in(x, y) ? from.px(x, y) : nullptr;
          float *o = dst.px(x, y);
          for (int c = 0; c < 4; c++) o[c] = i ? i[c] : 0;
        }
      });
    };
    if (k == SPEEDRAMP) {
      double span = last - first, s = N("strength");
      int curve = I("curve");
      bool back = I("reverse"), smooth = I("smooth");
      auto pos = [&](double p) {  // clip position -> source position, both 0..1
        double q = p + s * (rampCurve(curve, p) - p);
        return back ? 1 - q : q;
      };
      if (span < 1) {
        copy(src);
      } else {
        double p = std::clamp((t - first) / span, 0.0, 1.0), e = 0.5 / span;
        double speed = std::fabs(pos(std::min(1.0, p + e)) - pos(std::max(0.0, p - e))) / (2 * e);
        double at = first + pos(p) * span, spread = std::min(6.0, N("rampBlur") * std::max(0.0, speed - 1));
        int n = spread > 0.25 ? 1 + 2 * (int)std::ceil(spread) : 1;
        std::vector<std::pair<const Img *, float>> taps;  // (frame, weight)
        for (int i = 0; i < n; i++) {
          double f = n == 1 ? at : at + spread * ((double)i / (n - 1) - 0.5), f0 = std::floor(f), a = f - f0;
          if (!smooth) f0 = std::round(f), a = 0;
          if (const Img *im = frames.at((int)f0)) taps.emplace_back(im, (float)((1 - a) / n));
          if (a > 1e-3)
            if (const Img *im = frames.at((int)f0 + 1)) taps.emplace_back(im, (float)(a / n));
        }
        if (taps.empty()) {
          copy(src);
        } else {
          float total = 0;
          for (auto &tp : taps) total += tp.second;
          rows(w.y1, w.y2, [&](int y) {
            for (int x = w.x1; x < w.x2; x++) {
              float acc[4] = {0, 0, 0, 0};
              for (auto &tp : taps)
                if (tp.first->in(x, y)) {
                  const float *i = tp.first->px(x, y);
                  for (int c = 0; c < 4; c++) acc[c] += i[c] * tp.second;
                }
              float *o = dst.px(x, y);
              for (int c = 0; c < 4; c++) o[c] = acc[c] / total;
            }
          });
        }
      }
    } else {
      double amount = N("amount"), vx = 0, vy = 0;
      if (I("mode") == 1) {
        double len = N("length") * k1080 * amount, ang = N("angle") * PI / 180;
        vx = len * std::cos(ang), vy = len * std::sin(ang);
      } else {
        const Img *prev = frames.at((int)std::floor(t) - 1), *next = frames.at((int)std::floor(t) + 1);
        if (prev && next && prev != next) {
          double mx, my, gap = std::min(last, std::floor(t) + 1) - std::max(first, std::floor(t) - 1);
          shiftBetween(*prev, *next, mx, my);
          vx = mx / std::max(1.0, gap) * 0.5 * amount;  // 180-degree shutter: half a frame's motion
          vy = my / std::max(1.0, gap) * 0.5 * amount;
        }
      }
      if (std::hypot(vx, vy) < 0.5) copy(src);
      else directional(src, dst, w, vx, vy);
    }
  } else if (k == CAPTIONS) {
    rows(w.y1, w.y2, [&](int y) {  // the picture as it is, then the captions over it
      for (int x = w.x1; x < w.x2; x++) {
        const float *i = src.in(x, y) ? src.px(x, y) : nullptr;
        float *o = dst.px(x, y);
        for (int c = 0; c < 4; c++) o[c] = i ? i[c] : 0;
      }
    });
    captions::Settings s;
    s.file = str(fx, key(k, "file").c_str());
    s.media = str(fx, key(k, "media").c_str());
    s.language = captions::LANGUAGE_CODES[std::clamp(I("language"), 0, (int)list(captions::LANGUAGES).size() - 1)];
    s.font = str(fx, key(k, "font").c_str());
    s.tmpl = I("template"), s.words = (int)std::lround(N("words")), s.letterCase = I("case");
    s.size = N("size"), s.raise = N("raise"), s.offset = N("offset");
    s.customColors = I("custom") != 0;
    Pa->paramGetValueAtTime(param(fx, key(k, "color").c_str()), t, &s.color[0], &s.color[1], &s.color[2]);
    Pa->paramGetValueAtTime(param(fx, key(k, "highlight").c_str()), t, &s.highlight[0], &s.highlight[1],
                            &s.highlight[2]);
    captions::Canvas c{(float *)dst.data, dst.b.x1, dst.b.y1, dst.b.x2, dst.b.y2, dst.row, w.x1, w.y1, w.x2, w.y2,
                       cx - W / 2, cy - H / 2, W, H};
    captions::draw(s, t / fps, c);  // OFX time is the clip's frame; its seconds match the media's transcript
  }
  E->clipReleaseImage(src.h);
  E->clipReleaseImage(dst.h);
  return kOfxStatOK;
}

// ------------------------------------------------------------------------------------------------ actions
static OfxStatus describe(OfxImageEffectHandle fx) {
  OfxPropertySetHandle p;
  E->getPropertySet(fx, &p);
  P->propSetString(p, kOfxPropLabel, 0, "Kerf FX");
  P->propSetString(p, kOfxPropPluginDescription, 0, ABOUT);
  P->propSetString(p, kOfxImageEffectPluginPropGrouping, 0, "Kerf");
  P->propSetString(p, kOfxImageEffectPropSupportedContexts, 0, kOfxImageEffectContextFilter);  // Edit/Color pages
  P->propSetString(p, kOfxImageEffectPropSupportedContexts, 1, kOfxImageEffectContextGeneral);  // Fusion page
  P->propSetString(p, kOfxImageEffectPropSupportedPixelDepths, 0, kOfxBitDepthFloat);
  P->propSetInt(p, kOfxImageEffectPluginPropSingleInstance, 0, 0);
  P->propSetInt(p, kOfxImageEffectPluginPropHostFrameThreading, 0, 0);
  P->propSetString(p, kOfxImageEffectPluginRenderThreadSafety, 0, kOfxImageEffectRenderFullySafe);
  P->propSetInt(p, kOfxImageEffectPropSupportsMultiResolution, 0, 1);
  P->propSetInt(p, kOfxImageEffectPropSupportsTiles, 0, 0);
  P->propSetInt(p, kOfxImageEffectPropTemporalClipAccess, 0, 1);  // Speed ramp and Motion blur read other frames
  P->propSetInt(p, kOfxImageEffectPropSupportsMultipleClipDepths, 0, 0);
  return kOfxStatOK;
}

static OfxStatus describeInContext(OfxImageEffectHandle fx) {
  OfxPropertySetHandle c;
  E->clipDefine(fx, kOfxImageEffectSimpleSourceClipName, &c);
  P->propSetString(c, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
  P->propSetInt(c, kOfxImageEffectPropTemporalClipAccess, 0, 1);
  E->clipDefine(fx, kOfxImageEffectOutputClipName, &c);
  P->propSetString(c, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
  OfxParamSetHandle ps;
  E->getParamSet(fx, &ps);
  OfxPropertySetHandle p;
  Pa->paramDefine(ps, kOfxParamTypeChoice, "mode", &p);
  P->propSetString(p, kOfxPropLabel, 0, "Mode");
  P->propSetString(p, kOfxParamPropHint, 0, "What Kerf FX does to this clip; only this mode's controls show");
  for (int k = 0; k < KINDS; k++) P->propSetString(p, kOfxParamPropChoiceOption, k, MODES[k]);
  P->propSetInt(p, kOfxParamPropDefault, 0, 0);
  P->propSetInt(p, kOfxParamPropAnimates, 0, 0);
  for (int k = 0; k < KINDS; k++) {
    Pa->paramDefine(ps, kOfxParamTypeGroup, (std::string("g_") + PREFIX[k]).c_str(), &p);
    P->propSetString(p, kOfxPropLabel, 0, MODES[k]);
    P->propSetInt(p, kOfxParamPropGroupOpen, 0, 1);
    describeParams((Kind)k, ps);
  }
  return kOfxStatOK;
}

static OfxStatus instanceChanged(OfxImageEffectHandle fx, OfxPropertySetHandle in) {
  char *name = nullptr;
  P->propGetString(in, kOfxPropName, 0, &name);
  if (!name) return kOfxStatReplyDefault;
  if (!std::strcmp(name, "mode")) {
    showMode(fx);
  } else if (key(CAPTIONS, "transcribe") == name) {
    int lang = 0;
    Pa->paramGetValue(param(fx, key(CAPTIONS, "language").c_str()), &lang);
    lang = std::clamp(lang, 0, (int)list(captions::LANGUAGES).size() - 1);
    captions::transcribe(str(fx, key(CAPTIONS, "media").c_str()), captions::LANGUAGE_CODES[lang]);
  }
  return kOfxStatOK;
}

static OfxStatus mainEntry(const char *action, const void *handle, OfxPropertySetHandle in) {
  auto fx = (OfxImageEffectHandle)handle;
  if (!std::strcmp(action, kOfxActionLoad)) {
    if (!gHost) return kOfxStatErrMissingHostFeature;
    P = (const OfxPropertySuiteV1 *)gHost->fetchSuite(gHost->host, kOfxPropertySuite, 1);
    E = (const OfxImageEffectSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxImageEffectSuite, 1);
    Pa = (const OfxParameterSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxParameterSuite, 1);
    return P && E && Pa ? kOfxStatOK : kOfxStatErrMissingHostFeature;
  }
  if (!std::strcmp(action, kOfxActionDescribe)) return describe(fx);
  if (!std::strcmp(action, kOfxImageEffectActionDescribeInContext)) return describeInContext(fx);
  if (!std::strcmp(action, kOfxImageEffectActionRender)) return render(fx, in);
  if (!std::strcmp(action, kOfxActionInstanceChanged)) return instanceChanged(fx, in);
  if (!std::strcmp(action, kOfxActionCreateInstance)) {
    showMode(fx);
    return kOfxStatOK;
  }
  if (!std::strcmp(action, kOfxActionDestroyInstance) || !std::strcmp(action, kOfxActionUnload)) return kOfxStatOK;
  return kOfxStatReplyDefault;
}

static OfxStatus entry(const char *action, const void *handle, OfxPropertySetHandle in, OfxPropertySetHandle) {
  try {
    return mainEntry(action, handle, in);
  } catch (...) {  // never let an exception cross into the host
    return kOfxStatFailed;
  }
}
static void setHost(OfxHost *h) { gHost = h; }

static OfxPlugin PLUGIN = {kOfxImageEffectPluginApi, 1, "com.kerf.fx", 1, 0, setHost, entry};

extern "C" {
OfxExport int OfxGetNumberOfPlugins(void) { return 1; }
OfxExport OfxPlugin *OfxGetPlugin(int nth) { return nth == 0 ? &PLUGIN : nullptr; }
}
