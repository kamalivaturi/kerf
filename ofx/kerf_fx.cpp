// Kerf FX: OpenFX effects for DaVinci Resolve (and any OFX host). Live, keyframeable versions of the Kerf toolkit
// effects that work on a clip in place: Shake, Zoom (eased), RGB Split, Vignette, Letterbox.
// Plain OpenFX C API, 32-bit float RGBA (Resolve's processing format), rows split across CPU threads.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <thread>
#include <vector>

#include "ofxImageEffect.h"

static OfxHost *gHost;
static const OfxPropertySuiteV1 *P;
static const OfxImageEffectSuiteV1 *E;
static const OfxParameterSuiteV1 *Pa;

enum Kind { SHAKE, ZOOM, SPLIT, VIGNETTE, LETTERBOX, KINDS };
static const char *LABELS[KINDS] = {"Kerf Shake", "Kerf Zoom", "Kerf RGB Split", "Kerf Vignette", "Kerf Letterbox"};
static const char *ABOUT[KINDS] = {
    "Camera shake that moves, rotates and hides its own edges. Keyframe Amplitude for impacts.",
    "Eased zoom in or out at the start or end of the clip, around any point.",
    "Pulls red and blue apart for a glitch / impact look.",
    "Darkens the frame edges.",
    "Cinema bars for any aspect ratio (2.39, 1.85, 4:3...)."};
static const double PI = 3.14159265358979;

// ------------------------------------------------------------------------------------------------ params
static OfxPropertySetHandle define(OfxParamSetHandle ps, const char *type, const char *name, const char *label,
                                   const char *hint) {
  OfxPropertySetHandle p;
  Pa->paramDefine(ps, type, name, &p);
  P->propSetString(p, kOfxPropLabel, 0, label);
  P->propSetString(p, kOfxParamPropHint, 0, hint);
  return p;
}
static void number(OfxParamSetHandle ps, const char *name, const char *label, double def, double lo, double hi,
                   const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeDouble, name, label, hint);
  P->propSetDouble(p, kOfxParamPropDefault, 0, def);
  P->propSetDouble(p, kOfxParamPropMin, 0, lo);
  P->propSetDouble(p, kOfxParamPropMax, 0, hi);
  P->propSetDouble(p, kOfxParamPropDisplayMin, 0, lo);
  P->propSetDouble(p, kOfxParamPropDisplayMax, 0, hi);
}
static void choice(OfxParamSetHandle ps, const char *name, const char *label, std::vector<const char *> options, int def,
                   const char *hint) {
  OfxPropertySetHandle p = define(ps, kOfxParamTypeChoice, name, label, hint);
  for (int i = 0; i < (int)options.size(); i++) P->propSetString(p, kOfxParamPropChoiceOption, i, options[i]);
  P->propSetInt(p, kOfxParamPropDefault, 0, def);
}
static void toggle(OfxParamSetHandle ps, const char *name, const char *label, int def, const char *hint) {
  P->propSetInt(define(ps, kOfxParamTypeBoolean, name, label, hint), kOfxParamPropDefault, 0, def);
}

static void describeParams(Kind k, OfxParamSetHandle ps) {
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
      number(ps, "amount", "Amount", 0.5, 0, 1, "How dark the edges get");
      number(ps, "size", "Size", 0.75, 0.1, 1.5, "Where the darkening starts (1 = frame edge)");
      number(ps, "softness", "Softness", 0.6, 0.01, 2, "Width of the fade");
      number(ps, "roundness", "Roundness", 1, 0, 1, "0 follows the frame shape, 1 is a circle");
      break;
    case LETTERBOX:
      number(ps, "aspect", "Aspect ratio", 2.39, 0.3, 4, "2.39 scope, 1.85 flat, 1.33 for 4:3 pillars");
      number(ps, "opacity", "Opacity", 1, 0, 1, "Bar opacity");
      break;
    default:
      break;
  }
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
    pool.emplace_back([=] {
      for (int y = a; y < b; y++) f(y);
    });
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

// ------------------------------------------------------------------------------------------------ render
static OfxStatus render(Kind k, OfxImageEffectHandle fx, OfxPropertySetHandle in) {
  double t = 0, rs[2] = {1, 1};
  OfxRectI w;
  P->propGetDouble(in, kOfxPropTime, 0, &t);
  P->propGetIntN(in, kOfxImageEffectPropRenderWindow, 4, &w.x1);
  P->propGetDoubleN(in, kOfxImageEffectPropRenderScale, 2, rs);

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
    double amp = num(fx, "amplitude", t) * k1080, freq = num(fx, "frequency", t), seed = num(fx, "seed", t);
    double rot = num(fx, "rotation", t) * PI / 180, sec = t / fps;
    int axis = pick(fx, "axis", t);
    dx = axis == 2 ? 0 : amp * wave(sec * freq, seed);
    dy = axis == 1 ? 0 : amp * wave(sec * freq * 0.93, seed + 11);
    a = rot * wave(sec * freq * 0.71, seed + 23);
    if (pick(fx, "hideEdges", t))  // enough overscan for the largest move and tilt
      s = 1 + 2 * amp / std::min(W, H) + std::sin(rot) * std::max(W, H) / std::min(W, H);
    affine = true;
  } else if (k == ZOOM) {
    double amount = num(fx, "amount", t) / 100, frames = std::max(1.0, num(fx, "duration", t) * fps);
    double start = pick(fx, "at", t) == 0 ? range[0] : range[1] - frames;
    double e = ease(pick(fx, "ease", t), (t - start) / frames);
    s = pick(fx, "direction", t) == 0 ? 1 + (amount - 1) * e : amount + (1 - amount) * e;
    zx = (cx - W / 2) + W * num(fx, "centerX", t) / 100;
    zy = (cy - H / 2) + H * num(fx, "centerY", t) / 100;
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
    double amt = num(fx, "amount", t) * k1080, ang = num(fx, "angle", t) * PI / 180;
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
    double amount = num(fx, "amount", t), size = num(fx, "size", t), soft = num(fx, "softness", t);
    double round = num(fx, "roundness", t), aspect = W / H;
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
    double target = num(fx, "aspect", t);
    float op = (float)num(fx, "opacity", t);
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
  }
  E->clipReleaseImage(src.h);
  E->clipReleaseImage(dst.h);
  return kOfxStatOK;
}

// ------------------------------------------------------------------------------------------------ actions
static OfxStatus describe(Kind k, OfxImageEffectHandle fx) {
  OfxPropertySetHandle p;
  E->getPropertySet(fx, &p);
  P->propSetString(p, kOfxPropLabel, 0, LABELS[k]);
  P->propSetString(p, kOfxPropPluginDescription, 0, ABOUT[k]);
  P->propSetString(p, kOfxImageEffectPluginPropGrouping, 0, "Kerf");
  P->propSetString(p, kOfxImageEffectPropSupportedContexts, 0, kOfxImageEffectContextFilter);
  P->propSetString(p, kOfxImageEffectPropSupportedPixelDepths, 0, kOfxBitDepthFloat);
  P->propSetInt(p, kOfxImageEffectPluginPropSingleInstance, 0, 0);
  P->propSetInt(p, kOfxImageEffectPluginPropHostFrameThreading, 0, 0);
  P->propSetString(p, kOfxImageEffectPluginRenderThreadSafety, 0, kOfxImageEffectRenderFullySafe);
  P->propSetInt(p, kOfxImageEffectPropSupportsMultiResolution, 0, 1);
  P->propSetInt(p, kOfxImageEffectPropSupportsTiles, 0, 0);
  P->propSetInt(p, kOfxImageEffectPropTemporalClipAccess, 0, 0);
  P->propSetInt(p, kOfxImageEffectPropSupportsMultipleClipDepths, 0, 0);
  return kOfxStatOK;
}

static OfxStatus describeInContext(Kind k, OfxImageEffectHandle fx) {
  OfxPropertySetHandle c;
  E->clipDefine(fx, kOfxImageEffectSimpleSourceClipName, &c);
  P->propSetString(c, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
  E->clipDefine(fx, kOfxImageEffectOutputClipName, &c);
  P->propSetString(c, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
  OfxParamSetHandle ps;
  E->getParamSet(fx, &ps);
  describeParams(k, ps);
  return kOfxStatOK;
}

static OfxStatus mainEntry(Kind k, const char *action, const void *handle, OfxPropertySetHandle in) {
  auto fx = (OfxImageEffectHandle)handle;
  if (!std::strcmp(action, kOfxActionLoad)) {
    if (!gHost) return kOfxStatErrMissingHostFeature;
    P = (const OfxPropertySuiteV1 *)gHost->fetchSuite(gHost->host, kOfxPropertySuite, 1);
    E = (const OfxImageEffectSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxImageEffectSuite, 1);
    Pa = (const OfxParameterSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxParameterSuite, 1);
    return P && E && Pa ? kOfxStatOK : kOfxStatErrMissingHostFeature;
  }
  if (!std::strcmp(action, kOfxActionDescribe)) return describe(k, fx);
  if (!std::strcmp(action, kOfxImageEffectActionDescribeInContext)) return describeInContext(k, fx);
  if (!std::strcmp(action, kOfxImageEffectActionRender)) return render(k, fx, in);
  if (!std::strcmp(action, kOfxActionCreateInstance) || !std::strcmp(action, kOfxActionDestroyInstance) ||
      !std::strcmp(action, kOfxActionUnload))
    return kOfxStatOK;
  return kOfxStatReplyDefault;
}

template <int K>
static OfxStatus entry(const char *action, const void *handle, OfxPropertySetHandle in, OfxPropertySetHandle) {
  try {
    return mainEntry((Kind)K, action, handle, in);
  } catch (...) {  // never let an exception cross into the host
    return kOfxStatFailed;
  }
}
static void setHost(OfxHost *h) { gHost = h; }

static OfxPlugin PLUGINS[KINDS] = {
    {kOfxImageEffectPluginApi, 1, "com.kerf.fx.Shake", 1, 0, setHost, entry<SHAKE>},
    {kOfxImageEffectPluginApi, 1, "com.kerf.fx.Zoom", 1, 0, setHost, entry<ZOOM>},
    {kOfxImageEffectPluginApi, 1, "com.kerf.fx.RGBSplit", 1, 0, setHost, entry<SPLIT>},
    {kOfxImageEffectPluginApi, 1, "com.kerf.fx.Vignette", 1, 0, setHost, entry<VIGNETTE>},
    {kOfxImageEffectPluginApi, 1, "com.kerf.fx.Letterbox", 1, 0, setHost, entry<LETTERBOX>},
};

extern "C" {
OfxExport int OfxGetNumberOfPlugins(void) { return KINDS; }
OfxExport OfxPlugin *OfxGetPlugin(int nth) { return nth >= 0 && nth < KINDS ? &PLUGINS[nth] : nullptr; }
}
