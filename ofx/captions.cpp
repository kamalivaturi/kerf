// Kerf FX captions. Words come from an SRT or a Kerf transcript (start<TAB>end<TAB>word, written by the engine);
// HarfBuzz shapes each word (Devanagari, Tamil, Bengali... need real shaping) and stb_truetype turns its glyphs
// into signed distance fields, so fill, outline, glow, shadow and soft "blur in" all come from one cached bitmap.
#include "captions.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>

#include "hb.h"
#define STB_TRUETYPE_IMPLEMENTATION
#define STBTT_STATIC
#include "stb_truetype.h"

#ifdef _WIN32
#define NOMINMAX  // keep std::min / std::max
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace captions {

// ------------------------------------------------------------------------------------------------ templates
enum Anim { NONE, FADE, FADE_UP, BLUR, POP, SLIDE, TYPE, KARAOKE };
enum Face { SEMIBOLD, BOLD, BLACK };
struct Tmpl {
  Face face;
  float size;        // px at 1080p
  bool upper;
  int words;         // per caption
  float fill[3], hi[3];
  float outline, glow, shadow;  // outline and glow in px at 1080p; shadow is its opacity
  bool byWord;       // words appear as they are spoken (else the whole caption at once)
  Anim anim;
  float dur;         // seconds of the in-animation
  float activeScale; // the word being spoken grows to this
  bool activeColor;  // ...and takes the highlight colour
  bool box;          // ...on a highlight-coloured box
  bool lineBox;      // a dark band behind each line (subtitles)
  float dim;         // opacity of words not yet spoken (0 = hidden until spoken, when byWord)
  float y;           // baseline of the last line, % of the height from the bottom
};
#define WHITE {1, 1, 1}
#define YELLOW {1, .83f, 0}
static const Tmpl T[] = {
    // face   size upper words fill   hi                  outl glow shad byWord anim     dur  scale  actC  box  lineB dim  y
    {SEMIBOLD, 64, false, 6, WHITE, WHITE,             0, 0, .5f, false, FADE,    .20f, 1.f,  false, false, false, 1, 20},  // Clean
    {SEMIBOLD, 66, false, 5, WHITE, WHITE,             0, 0, .45f, true, FADE_UP, .35f, 1.f,  false, false, false, 0, 20},  // Apple fade up
    {SEMIBOLD, 66, false, 5, WHITE, WHITE,             0, 0, .35f, true, BLUR,    .40f, 1.f,  false, false, false, 0, 20},  // Apple blur in
    {SEMIBOLD, 66, false, 6, WHITE, WHITE,             0, 0, .4f, false, FADE,    .25f, 1.f,  false, false, false, .38f, 20},  // Spoken, the rest dim
    {SEMIBOLD, 64, false, 5, WHITE, {.62f, .82f, 1},   0, 14, 0,  true,  FADE,    .30f, 1.f,  false, false, false, 0, 20},  // Soft glow
    {SEMIBOLD, 44, false, 8, WHITE, WHITE,             0, 0, .3f, false, FADE,    .25f, 1.f,  false, false, false, 1, 8},   // Minimal lower
    {SEMIBOLD, 62, false, 6, WHITE, WHITE,             0, 0, .5f, true,  TYPE,    .01f, 1.f,  false, false, false, 0, 20},  // Typewriter
    {BOLD,     70, false, 4, WHITE, WHITE,             0, 0, .6f, false, SLIDE,   .30f, 1.f,  false, false, false, 1, 22},  // Slide up
    {SEMIBOLD, 52, false, 10, WHITE, WHITE,            0, 0, 0,  false, FADE,    .12f, 1.f,  false, false, true,  1, 9},   // Subtitle
    {BOLD,     68, false, 5, WHITE, {.3f, .88f, 1},    4, 0, .3f, false, KARAOKE, .15f, 1.f,  false, false, false, 1, 22},  // Karaoke
    {BLACK,    78, true,  3, WHITE, YELLOW,            6, 0, 0,  false, POP,     .25f, 1.12f, true, false, false, 1, 24},  // Highlight yellow
    {BOLD,     70, true,  3, WHITE, {1, .27f, .45f},   0, 0, .4f, false, POP,     .25f, 1.06f, false, true, false, 1, 24},  // Box highlight
    {BLACK,    80, true,  3, WHITE, {.55f, 1, .35f},   5, 0, 0,  true,  POP,     .25f, 1.1f, true,  false, false, 0, 24},  // Pop words
    {BLACK,   110, true,  1, WHITE, YELLOW,            7, 0, 0,  true,  POP,     .20f, 1.f,  false, false, false, 0, 30},  // One word
    {BLACK,    76, true,  4, WHITE, YELLOW,            8, 0, 0,  false, FADE,    .10f, 1.08f, true, false, false, 1, 24},  // Bold outline
};
const char *TEMPLATES[] = {"Clean", "Apple fade up", "Apple blur in", "Spoken, the rest dim", "Soft glow",
                           "Minimal lower", "Typewriter", "Slide up", "Subtitle", "Karaoke", "Highlight yellow",
                           "Box highlight", "Pop words", "One word", "Bold outline", nullptr};
static const int NT = sizeof(T) / sizeof(T[0]);

// Engine language values: Kerf's speech profiles (the code-switching ones romanise) or Whisper codes.
const char *LANGUAGES[] = {"Detect", "English", "Hindi", "Hinglish (Hindi + English)", "Bengali", "Assamese", "Tamil",
                           "Tanglish (Tamil + English)", "Telugu", "Kannada", "Malayalam", "Marathi", "Gujarati",
                           "Punjabi", "Urdu", "Nepali", "Sinhala", "Sanskrit", nullptr};
const char *LANGUAGE_CODES[] = {"", "en", "hindi", "hinglish", "bengali", "as", "tamil", "tanglish", "telugu",
                                "kannada", "malayalam", "marathi", "gujarati", "punjabi", "urdu", "nepali", "sinhala",
                                "sa", nullptr};

// ------------------------------------------------------------------------------------------------ fonts
struct Font {
  std::vector<unsigned char> data;
  stbtt_fontinfo info{};
  hb_font_t *hb = nullptr;
  int upem = 1000, ascent = 800, descent = -200;
  std::mutex lock;  // guards the glyph cache
  std::map<std::pair<int, int>, std::shared_ptr<std::vector<unsigned char>>> sdf;  // (glyph, px) -> header + SDF
  bool has(unsigned cp) { return cp < 0x20 || cp == 0x200C || cp == 0x200D || stbtt_FindGlyphIndex(&info, (int)cp); }
};
static std::mutex gFontsLock;
static std::map<std::string, std::unique_ptr<Font>> gFonts;  // "path#index" -> font, kept while the plugin is loaded

static Font *loadFont(const std::string &path, int index) {
  std::lock_guard<std::mutex> g(gFontsLock);
  std::string key = path + "#" + std::to_string(index);
  auto it = gFonts.find(key);
  if (it != gFonts.end()) return it->second.get();
  auto f = std::make_unique<Font>();
  std::ifstream in(fs::u8path(path), std::ios::binary);
  f->data.assign(std::istreambuf_iterator<char>(in), {});
  int off = f->data.empty() ? -1 : stbtt_GetFontOffsetForIndex(f->data.data(), index);
  if (off < 0 || !stbtt_InitFont(&f->info, f->data.data(), off)) {
    gFonts[key] = nullptr;
    return nullptr;
  }
  hb_blob_t *blob = hb_blob_create((const char *)f->data.data(), (unsigned)f->data.size(), HB_MEMORY_MODE_READONLY,
                                   nullptr, nullptr);
  hb_face_t *face = hb_face_create(blob, (unsigned)index);
  f->hb = hb_font_create(face);
  f->upem = (int)hb_face_get_upem(face);
  hb_font_set_scale(f->hb, f->upem, f->upem);  // positions in font units
  hb_face_destroy(face);
  hb_blob_destroy(blob);
  int gap;
  stbtt_GetFontVMetrics(&f->info, &f->ascent, &f->descent, &gap);
  return (gFonts[key] = std::move(f)).get();
}

// The template's face, then fonts that cover the Indian scripts and Arabic (Urdu), per OS.
static std::vector<std::pair<std::string, int>> fontChain(Face face, const std::string &custom) {
  std::vector<std::pair<std::string, int>> c;
  if (!custom.empty()) c.push_back({custom, 0});
#ifdef _WIN32
  const char *win = std::getenv("WINDIR");
  std::string d = std::string(win ? win : "C:\\Windows") + "\\Fonts\\";
  const char *main[] = {"seguisb.ttf", "segoeuib.ttf", "seguibl.ttf"};
  c.push_back({d + main[face], 0});
  c.push_back({d + "Nirmala.ttc", 1});   // Nirmala UI Bold: every Indian script, with shaping tables
  c.push_back({d + "NirmalaB.ttf", 0});  // older Windows 10
  c.push_back({d + "segoeuib.ttf", 0});  // Arabic script (Urdu)
  c.push_back({d + "arialbd.ttf", 0});
#elif defined(__APPLE__)
  const char *main[] = {"Arial Bold.ttf", "Arial Bold.ttf", "Arial Black.ttf"};
  c.push_back({std::string("/System/Library/Fonts/Supplemental/") + main[face], 0});
  for (const char *f : {"/System/Library/Fonts/Kohinoor.ttc", "/System/Library/Fonts/Supplemental/Tamil Sangam MN.ttc",
                        "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
                        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"})
    c.push_back({f, 0});
#else
  c.push_back({"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0});
  for (const char *f : {"/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
                        "/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf",
                        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf"})
    c.push_back({f, 0});
#endif
  return c;
}

static std::vector<unsigned> codepoints(const std::string &s) {
  std::vector<unsigned> out;
  for (size_t i = 0; i < s.size();) {
    unsigned char c = (unsigned char)s[i];
    int n = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
    unsigned cp = n == 1 ? c : c & (0xFF >> (n + 1));
    for (int k = 1; k < n && i + k < s.size(); k++) cp = (cp << 6) | ((unsigned char)s[i + k] & 0x3F);
    out.push_back(cp);
    i += n;
  }
  return out;
}

// The first font in the chain with a glyph for every character of the word.
static Font *fontFor(const std::string &word, const std::vector<std::pair<std::string, int>> &chain) {
  std::vector<unsigned> cps = codepoints(word);
  Font *first = nullptr;
  for (auto &entry : chain) {
    Font *f = loadFont(entry.first, entry.second);
    if (!f) continue;
    if (!first) first = f;
    if (std::all_of(cps.begin(), cps.end(), [&](unsigned cp) { return f->has(cp); })) return f;
  }
  return first;
}

// ------------------------------------------------------------------------------------------------ shaping
struct Glyph {
  int id;
  float x, y;  // glyph origin, px from the word's origin on the baseline (y down)
};
struct Run {
  Font *font = nullptr;
  std::vector<Glyph> glyphs;
  float width = 0, asc = 0, desc = 0, px = 0;
};

static Run shape(const std::string &text, Font *f, float px) {
  Run r;
  r.font = f;
  r.px = px;
  if (!f) return r;
  float k = px / f->upem;
  r.asc = f->ascent * k;
  r.desc = -f->descent * k;
  hb_buffer_t *b = hb_buffer_create();
  hb_buffer_add_utf8(b, text.c_str(), -1, 0, -1);
  hb_buffer_guess_segment_properties(b);  // script and direction from the text itself
  hb_shape(f->hb, b, nullptr, 0);
  unsigned n = 0;
  hb_glyph_info_t *info = hb_buffer_get_glyph_infos(b, &n);
  hb_glyph_position_t *pos = hb_buffer_get_glyph_positions(b, &n);
  float pen = 0;
  for (unsigned i = 0; i < n; i++) {
    r.glyphs.push_back({(int)info[i].codepoint, pen + pos[i].x_offset * k, -pos[i].y_offset * k});
    pen += pos[i].x_advance * k;
  }
  r.width = pen;
  hb_buffer_destroy(b);
  return r;
}

// Signed distance field of one glyph at `px` em size: 128 is the edge, one step is 1/PDS px. Cached per font.
struct Sdf {
  int w = 0, h = 0, x0 = 0, y0 = 0;
  const unsigned char *v = nullptr;
};
static const int PAD = 24, ONEDGE = 128;
static const float PDS = (float)ONEDGE / PAD;

static Sdf glyphSdf(Font *f, int glyph, int px) {
  std::lock_guard<std::mutex> g(f->lock);
  auto &slot = f->sdf[{glyph, px}];
  if (!slot) {
    int w = 0, h = 0, xo = 0, yo = 0;
    float scale = stbtt_ScaleForMappingEmToPixels(&f->info, (float)px);
    unsigned char *bm = stbtt_GetGlyphSDF(&f->info, scale, glyph, PAD, ONEDGE, PDS, &w, &h, &xo, &yo);
    if (!bm) w = h = 0;  // a space or an empty glyph
    slot = std::make_shared<std::vector<unsigned char>>(16 + (size_t)w * h);
    int hdr[4] = {w, h, xo, yo};
    std::memcpy(slot->data(), hdr, 16);
    if (bm) {
      std::memcpy(slot->data() + 16, bm, (size_t)w * h);
      stbtt_FreeSDF(bm, nullptr);
    }
  }
  Sdf s;
  int hdr[4];
  std::memcpy(hdr, slot->data(), 16);
  s.w = hdr[0], s.h = hdr[1], s.x0 = hdr[2], s.y0 = hdr[3];
  s.v = slot->data() + 16;
  return s;
}

// ------------------------------------------------------------------------------------------------ caption files
struct Word {
  std::string text;
  double s, e;
};

static std::string trim(std::string s) {
  while (!s.empty() && std::isspace((unsigned char)s.back())) s.pop_back();
  size_t i = 0;
  while (i < s.size() && std::isspace((unsigned char)s[i])) i++;
  return s.substr(i);
}
static double srtTime(const std::string &t) {  // 00:01:02,345
  int h = 0, m = 0, s = 0, ms = 0;
  std::sscanf(t.c_str(), "%d:%d:%d%*[,.]%d", &h, &m, &s, &ms);
  return h * 3600 + m * 60 + s + ms / 1000.0;
}

static std::vector<Word> parse(const std::string &path) {
  std::ifstream in(fs::u8path(path), std::ios::binary);
  std::string all((std::istreambuf_iterator<char>(in)), {});
  if (all.rfind("\xEF\xBB\xBF", 0) == 0) all.erase(0, 3);
  std::vector<Word> out;
  std::istringstream ss(all);
  std::string line;
  if (path.size() > 4 && path.substr(path.size() - 4) == ".tsv") {  // start<TAB>end<TAB>word
    while (std::getline(ss, line)) {
      size_t a = line.find('\t'), b = a == std::string::npos ? a : line.find('\t', a + 1);
      if (b == std::string::npos) continue;
      std::string w = trim(line.substr(b + 1));
      if (!w.empty()) out.push_back({w, std::atof(line.substr(0, a).c_str()), std::atof(line.substr(a + 1).c_str())});
    }
    return out;
  }
  // SRT: a cue's words share its time, in proportion to their length
  while (std::getline(ss, line)) {
    size_t arrow = line.find("-->");
    if (arrow == std::string::npos) continue;
    double s = srtTime(trim(line.substr(0, arrow))), e = srtTime(trim(line.substr(arrow + 3)));
    std::vector<std::string> words;
    while (std::getline(ss, line) && !trim(line).empty()) {
      std::istringstream ws(line);
      for (std::string w; ws >> w;) words.push_back(w);
    }
    double total = 0;
    for (auto &w : words) total += (double)codepoints(w).size() + 1;
    double t = s;
    for (auto &w : words) {
      double d = (e - s) * (codepoints(w).size() + 1) / std::max(1.0, total);
      out.push_back({w, t, t + d});
      t += d;
    }
  }
  return out;
}

static std::mutex gFilesLock;
static std::map<std::string, std::pair<fs::file_time_type, std::shared_ptr<std::vector<Word>>>> gFiles;

static std::shared_ptr<std::vector<Word>> words(const std::string &path) {  // re-read when the file changes
  std::error_code ec;
  auto mt = fs::last_write_time(fs::u8path(path), ec);
  if (ec) return nullptr;
  std::lock_guard<std::mutex> g(gFilesLock);
  auto &slot = gFiles[path];
  if (!slot.second || slot.first != mt) slot = {mt, std::make_shared<std::vector<Word>>(parse(path))};
  return slot.second;
}

// ------------------------------------------------------------------------------------------------ engine link
static std::string home() {
  if (const char *h = std::getenv("KERF_HOME_DIR")) return h;
#ifdef _WIN32
  const char *u = std::getenv("USERPROFILE");
#else
  const char *u = std::getenv("HOME");
#endif
  return std::string(u ? u : ".") + "/.kerf";
}
static std::string readFile(const std::string &p) {
  std::ifstream in(fs::u8path(p), std::ios::binary);
  return trim(std::string((std::istreambuf_iterator<char>(in)), {}));
}
static void writeFile(const std::string &p, const std::string &text) {
  std::ofstream(fs::u8path(p), std::ios::binary) << text;
}

// Where the engine writes the transcript of a media file in a language (the same name every time).
static std::string transcriptPath(const std::string &media, const std::string &language) {
  unsigned long long h = 1469598103934665603ULL;  // FNV-1a
  for (char ch : media + "|" + language) h = (h ^ (unsigned char)ch) * 1099511628211ULL;
  char name[32];
  std::snprintf(name, sizeof name, "%016llx", h);
  return home() + "/captions/" + name + ".tsv";
}

static std::string jsonStr(const std::string &s) {
  std::string o = "\"";
  for (char ch : s) {
    if ((unsigned char)ch < 0x20) continue;
    if (ch == '"' || ch == '\\') o += '\\';
    o += ch;
  }
  return o + "\"";
}

// POST to the local engine (port from engine.json, token from ~/.kerf/token): (HTTP status, body), 0 = not running.
static std::pair<int, std::string> post(const std::string &route, const std::string &body) {
  int port = 7878;
  std::string loc = readFile(home() + "/engine.json");
  size_t p = loc.find("\"port\"");
  if (p != std::string::npos && loc.find(':', p) != std::string::npos) port = std::atoi(loc.c_str() + loc.find(':', p) + 1);
  std::string token = readFile(home() + "/token");
#ifdef _WIN32
  WSADATA wsa;
  WSAStartup(MAKEWORD(2, 2), &wsa);
  SOCKET fd = socket(AF_INET, SOCK_STREAM, 0);
  bool ok = fd != INVALID_SOCKET;
#else
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  bool ok = fd >= 0;
#endif
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_port = htons((unsigned short)port);
  inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
  std::pair<int, std::string> res{0, ""};
  if (ok && connect(fd, (sockaddr *)&a, sizeof a) == 0) {
    std::string req = "POST " + route + " HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                      "X-Kerf-Token: " + token + "\r\nContent-Length: " + std::to_string(body.size()) + "\r\n\r\n" + body;
    send(fd, req.data(), (int)req.size(), 0);
    std::string got;
    char buf[4096];
    for (int n; (n = (int)recv(fd, buf, sizeof buf, 0)) > 0;) got.append(buf, n);
    size_t sp = got.find(' '), at = got.find("\r\n\r\n");
    res = {sp == std::string::npos ? 0 : std::atoi(got.c_str() + sp + 1), at == std::string::npos ? "" : got.substr(at + 4)};
  }
#ifdef _WIN32
  if (ok) closesocket(fd);
#else
  if (ok) close(fd);
#endif
  return res;
}

static std::string errorOf(const std::string &body) {  // {"error": "..."} -> the message
  size_t p = body.find("\"error\"");
  if (p == std::string::npos) return "";
  size_t q = body.find('"', body.find(':', p) + 1);
  if (q == std::string::npos) return "";
  std::string out;
  for (size_t i = q + 1; i < body.size() && body[i] != '"'; i++) {
    if (body[i] == '\\' && i + 1 < body.size()) i++;
    out += body[i];
  }
  return out;
}

void transcribe(const std::string &media, const std::string &language) {
  if (media.empty()) return;
  std::string out = transcriptPath(media, language);
  std::error_code ec;
  fs::create_directories(fs::u8path(home() + "/captions"), ec);
  fs::remove(fs::u8path(out + ".err"), ec);
  writeFile(out + ".pending", "");
  std::thread([media, language, out] {  // transcription can take minutes: never block the editor
    try {
      auto res = post("/captions/words", "{\"path\": " + jsonStr(media) + ", \"language\": " + jsonStr(language) +
                                             ", \"out\": " + jsonStr(out) + "}");
      if (res.first == 0) writeFile(out + ".err", "Kerf isn't running: start Kerf, then press Transcribe again");
      else if (res.first != 200)
        writeFile(out + ".err", errorOf(res.second).empty() ? "Kerf couldn't transcribe this file" : errorOf(res.second));
    } catch (...) {
      writeFile(out + ".err", "Kerf couldn't transcribe this file");
    }
    std::error_code ec2;
    fs::remove(fs::u8path(out + ".pending"), ec2);
  }).detach();
}

// ------------------------------------------------------------------------------------------------ drawing
struct Look {
  float fill[3] = {1, 1, 1}, outlineColor[3] = {0, 0, 0}, glowColor[3] = {1, 1, 1};
  float opacity = 1, scale = 1, dx = 0, dy = 0, blur = 0, outline = 0, glow = 0, shadow = 0;
  int maxGlyphs = 1 << 30;
};

static float clamp01(float v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
static void over(float *p, const float *col, float a) {
  if (a <= 0) return;
  for (int c = 0; c < 3; c++) p[c] = p[c] * (1 - a) + col[c] * a;
  p[3] = p[3] * (1 - a) + a;
}

// OFX pixels (y up) <-> text space (x right, y down, origin at the frame's top-left corner).
struct Frame {
  const Canvas &c;
  float *px(int X, int Y) const { return (float *)((char *)c.base + (ptrdiff_t)(Y - c.y1) * c.row) + (ptrdiff_t)(X - c.x1) * 4; }
  bool writable(int X, int Y) const {
    return X >= std::max(c.x1, c.wx1) && X < std::min(c.x2, c.wx2) && Y >= std::max(c.y1, c.wy1) && Y < std::min(c.y2, c.wy2);
  }
  float tx(int X) const { return (float)(X + 0.5 - c.fx); }
  float ty(int Y) const { return (float)(c.fy + c.H - (Y + 0.5)); }
  int X(float tx) const { return (int)std::floor(tx + c.fx); }
  int Y(float ty) const { return (int)std::floor(c.fy + c.H - ty); }
};

static void roundRect(const Frame &f, float x0, float y0, float x1, float y1, float r, const float *col, float a) {
  for (int Y = f.Y(y1) - 1; Y <= f.Y(y0) + 1; Y++)
    for (int X = f.X(x0) - 1; X <= f.X(x1) + 1; X++) {
      if (!f.writable(X, Y)) continue;
      float qx = std::max(std::fabs(f.tx(X) - (x0 + x1) / 2) - ((x1 - x0) / 2 - r), 0.f);
      float qy = std::max(std::fabs(f.ty(Y) - (y0 + y1) / 2) - ((y1 - y0) / 2 - r), 0.f);
      over(f.px(X, Y), col, a * clamp01(r - std::sqrt(qx * qx + qy * qy) + 0.5f));
    }
}

// Distance to the edge of the whole word (the union of its glyphs) at word-local (x, y): px, + inside.
static float distance(const Run &r, const std::vector<Sdf> &sdfs, int n, float x, float y) {
  float best = 0;
  for (int i = 0; i < n; i++) {
    const Sdf &s = sdfs[i];
    float u = x - (r.glyphs[i].x + s.x0) - 0.5f, v = y - (r.glyphs[i].y + s.y0) - 0.5f;
    int u0 = (int)std::floor(u), v0 = (int)std::floor(v);
    if (u0 < -1 || v0 < -1 || u0 >= s.w || v0 >= s.h) continue;
    float fu = u - u0, fv = v - v0, acc = 0;
    for (int j = 0; j < 2; j++)
      for (int k = 0; k < 2; k++) {
        int uu = u0 + k, vv = v0 + j;
        float val = uu >= 0 && vv >= 0 && uu < s.w && vv < s.h ? s.v[vv * s.w + uu] : 0;
        acc += val * (k ? fu : 1 - fu) * (j ? fv : 1 - fv);
      }
    best = std::max(best, acc);
  }
  return (best - ONEDGE) / PDS;
}

// One word with its baseline origin at text-space (ox, oy): shadow, glow, outline, then fill, drawn as one shape,
// so the joins of connected scripts (Devanagari's headline) never show seams.
static void drawWord(const Frame &f, const Run &r, float ox, float oy, const Look &lk, float unit) {
  if (!r.font || r.glyphs.empty() || lk.opacity <= 0.003f) return;
  int n = std::min((int)r.glyphs.size(), lk.maxGlyphs);
  std::vector<Sdf> sdfs;
  for (int i = 0; i < n; i++) sdfs.push_back(glyphSdf(r.font, r.glyphs[i].id, (int)std::lround(r.px)));
  float cx = r.width / 2, cy = (r.desc - r.asc) / 2, s = lk.scale;
  float pad = PAD * s + lk.glow + 6 * unit + 2;
  float bx0 = ox + lk.dx + cx - cx * s - pad, bx1 = ox + lk.dx + cx + (r.width - cx) * s + pad;
  float by0 = oy + lk.dy + cy + (-r.asc - cy) * s - pad, by1 = oy + lk.dy + cy + (r.desc - cy) * s + pad;
  float soft = 1 + lk.blur, shOff = 3 * unit, shSoft = 4 * unit + lk.blur;
  static const float black[3] = {0, 0, 0};
  for (int Y = f.Y(by1); Y <= f.Y(by0); Y++)
    for (int X = f.X(bx0); X <= f.X(bx1); X++) {
      if (!f.writable(X, Y)) continue;
      // inverse of: scale by s around the word centre, then move by (dx, dy)
      float lx = cx + (f.tx(X) - ox - lk.dx - cx) / s, ly = cy + (f.ty(Y) - oy - lk.dy - cy) / s;
      float d = distance(r, sdfs, n, lx, ly) * s;
      float *p = f.px(X, Y);
      if (lk.shadow > 0) {
        float ds = distance(r, sdfs, n, lx - shOff / s, ly - shOff / s) * s;
        over(p, black, lk.shadow * lk.opacity * clamp01(ds / shSoft + 0.5f));
      }
      if (lk.glow > 0 && d < 0) {
        float g = clamp01(1 + d / lk.glow);
        over(p, lk.glowColor, 0.85f * lk.opacity * g * g);
      }
      if (lk.outline > 0) over(p, lk.outlineColor, lk.opacity * clamp01((d + lk.outline) / soft + 0.5f));
      over(p, lk.fill, lk.opacity * clamp01(d / soft + 0.5f));
    }
}

static float easeOut(float p) { return 1 - std::pow(1 - clamp01(p), 3.f); }
static float backOut(float p) {  // overshoots a little, then settles: the "pop"
  p = clamp01(p);
  const float k = 1.7f;
  return 1 + (k + 1) * std::pow(p - 1, 3.f) + k * std::pow(p - 1, 2.f);
}

static std::string upper(std::string s) {  // Latin only: Indian scripts have no case
  for (char &ch : s)
    if (ch >= 'a' && ch <= 'z') ch = (char)(ch - 32);
  return s;
}

// One line near the top of the frame: progress and problems ("Kerf is transcribing…"). Never in the final render
// once the transcript exists.
static void status(const Frame &f, const std::string &msg, float unit) {
  Run r = shape(msg, fontFor(msg, fontChain(SEMIBOLD, "")), 30 * unit);
  Look lk;
  float x = ((float)f.c.W - r.width) / 2, y = 60 * unit;
  static const float band[3] = {0, 0, 0};
  roundRect(f, x - 14 * unit, y - r.asc - 8 * unit, x + r.width + 14 * unit, y + r.desc + 8 * unit, 10 * unit, band, 0.6f);
  drawWord(f, r, x, y, lk, unit);
}

bool draw(const Settings &st, double sec, const Canvas &c) {
  Frame f{c};
  float unit = (float)(std::min(c.W, c.H) / 1080.0);  // 1 px at 1080p, in render pixels
  std::string path = st.file;
  if (path.empty()) {
    if (st.media.empty()) return false;
    path = transcriptPath(st.media, st.language);
    std::error_code ec;
    if (!fs::exists(fs::u8path(path), ec)) {
      if (fs::exists(fs::u8path(path + ".pending"), ec)) status(f, "Kerf is transcribing\xE2\x80\xA6", unit);
      else if (fs::exists(fs::u8path(path + ".err"), ec)) status(f, readFile(path + ".err"), unit);
      else status(f, "Press Transcribe with Kerf, or choose a captions file", unit);
      return true;
    }
  }
  auto ws = words(path);
  if (!ws) {
    status(f, "Kerf can't open the captions file: check its path", unit);
    return true;
  }
  if (ws->empty()) return false;
  const Tmpl &t = T[std::clamp(st.tmpl, 0, NT - 1)];
  int per = st.words > 0 ? st.words : t.words;
  bool caps = st.letterCase == 0 ? t.upper : st.letterCase == 1;
  float fill[3], hi[3];
  for (int i = 0; i < 3; i++) {
    fill[i] = st.customColors ? (float)st.color[i] : t.fill[i];
    hi[i] = st.customColors ? (float)st.highlight[i] : t.hi[i];
  }
  sec -= st.offset;

  // Captions of up to `per` words, broken early at a pause or a sentence end; each stays up until the next.
  const auto &W = *ws;
  int a = -1, b = -1;
  for (int i = 0; i < (int)W.size();) {
    int j = i + 1;
    while (j < (int)W.size() && j - i < per && W[j].s - W[j - 1].e < 0.6) {
      const std::string &prev = W[j - 1].text;
      char last = prev.empty() ? 0 : prev.back();
      if (last == '.' || last == '?' || last == '!' || prev.find("\xE0\xA5\xA4") != std::string::npos) break;  // danda
      j++;
    }
    double end = std::min(j < (int)W.size() ? W[j].s : 1e300, W[j - 1].e + 0.5);
    if (sec >= W[i].s && sec < end) {
      a = i, b = j;
      break;
    }
    if (W[i].s > sec) break;
    i = j;
  }
  if (a < 0) return false;

  // Lines no wider than 86% of the frame; the last line's baseline sits at the template's height.
  float px = t.size * (float)(st.size / 100) * unit;
  auto chain = fontChain(t.face, st.font);
  std::vector<Run> runs;
  for (int i = a; i < b; i++) {
    std::string text = caps ? upper(W[i].text) : W[i].text;
    runs.push_back(shape(text, fontFor(text, chain), px));
  }
  // a word gap, plus room for the outlines and the highlight box, which grow outside the letters
  float space = 0.28f * px + 2 * t.outline * unit + (t.box ? 0.32f * px : 0), maxW = (float)c.W * 0.86f;
  std::vector<std::vector<int>> lines(1);
  float lineW = 0;
  for (int i = 0; i < (int)runs.size(); i++) {
    float add = (lines.back().empty() ? 0 : space) + runs[i].width;
    if (!lines.back().empty() && lineW + add > maxW) lines.push_back({}), lineW = 0, add = runs[i].width;
    lines.back().push_back(i);
    lineW += add;
  }
  float asc = 0, desc = 0;
  for (auto &r : runs) asc = std::max(asc, r.asc), desc = std::max(desc, r.desc);
  float lineH = (asc + desc) * 1.12f, baseY = (float)c.H * (1 - (t.y + (float)st.raise) / 100);

  float pageP = (float)((sec - W[a].s) / std::max(0.01f, t.dur));
  for (int li = 0; li < (int)lines.size(); li++) {
    float y = baseY - (float)(lines.size() - 1 - li) * lineH, total = 0;
    for (int k = 0; k < (int)lines[li].size(); k++) total += (k ? space : 0) + runs[lines[li][k]].width;
    float x = ((float)c.W - total) / 2;
    if (t.lineBox) {
      static const float band[3] = {0, 0, 0};
      roundRect(f, x - 0.4f * px, y - asc - 0.18f * px, x + total + 0.4f * px, y + desc + 0.18f * px, 0.18f * px, band,
                0.55f * easeOut(pageP));
    }
    for (int i : lines[li]) {
      const Word &w = W[a + i];
      const Run &r = runs[i];
      bool last = i + 1 == (int)runs.size(), spoken = sec >= w.s;
      bool active = spoken && (sec < w.e || last || sec < W[a + i + 1].s);
      if (t.byWord && !spoken && t.dim <= 0) {  // not said yet: keep its place, draw nothing
        x += r.width + space;
        continue;
      }
      Look lk;
      std::copy(fill, fill + 3, lk.fill);
      std::copy(hi, hi + 3, lk.glowColor);
      lk.outline = t.outline * unit;
      lk.glow = t.glow * unit;
      lk.shadow = t.shadow;
      float p = t.byWord && spoken ? (float)((sec - w.s) / std::max(0.01f, t.dur)) : pageP, e = easeOut(p);
      switch (t.anim) {
        case FADE: lk.opacity = e; break;
        case FADE_UP: lk.opacity = e, lk.dy = (1 - e) * 0.25f * px; break;
        case BLUR: lk.opacity = e, lk.blur = (1 - e) * 0.3f * px; break;
        case POP: lk.opacity = clamp01(p * 3), lk.scale = 0.6f + 0.4f * backOut(p); break;
        case SLIDE: lk.opacity = e, lk.dy = (1 - e) * 0.5f * px; break;
        case TYPE:  // letters appear across the time the word is said
          lk.maxGlyphs = (int)std::ceil(r.glyphs.size() * clamp01(spoken ? (float)((sec - w.s) / std::max(0.05, w.e - w.s)) : 0));
          break;
        case KARAOKE:
          lk.opacity = e;
          if (spoken) std::copy(hi, hi + 3, lk.fill);
          break;
        default: break;
      }
      if (!spoken && t.dim < 1) lk.opacity *= t.dim;
      if (active && (t.activeScale != 1 || t.activeColor || t.box)) {
        float pop = easeOut((float)((sec - w.s) / 0.12));
        lk.scale *= 1 + (t.activeScale - 1) * pop;
        if (t.activeColor) std::copy(hi, hi + 3, lk.fill);
        if (t.box) {
          float m = 0.16f * px;
          roundRect(f, x - m, y - r.asc * 0.8f - m * 0.5f, x + r.width + m, y + r.desc * 0.6f + m * 0.5f, 0.22f * px, hi,
                    lk.opacity * pop);
        }
      }
      drawWord(f, r, x, y, lk, unit);
      x += r.width + space;
    }
  }
  return true;
}

}  // namespace captions
