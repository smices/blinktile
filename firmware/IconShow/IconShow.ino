#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

#include "assets.h"

namespace {

constexpr uint8_t kLedPin = 2;
constexpr uint8_t kWidth = 8;
constexpr uint8_t kHeight = 8;
constexpr uint16_t kPixels = kWidth * kHeight;
constexpr uint16_t kMaxRequest = 512;
constexpr uint16_t kMaxResponse = 2048;
constexpr uint8_t kQueueSize = 8;
constexpr uint32_t kBleTimeoutMs = 2000;
constexpr uint32_t kWifiAttemptMs = 30000;
constexpr uint32_t kApGraceMs = 15000;
constexpr uint8_t kDefaultBrightness = 64;
constexpr uint16_t kDefaultColorPeriod = 5000;
constexpr uint16_t kDefaultEffectPeriod = 2000;
constexpr uint16_t kDefaultScrollStep = 80;
constexpr float kPi = 3.14159265358979323846f;

Adafruit_NeoPixel pixels(kPixels, kLedPin, NEO_GRB + NEO_KHZ800);
WebServer http(80);
WebSocketsServer webSocket(81);
Preferences preferences;

enum Source : uint8_t { SOURCE_SERIAL, SOURCE_WS, SOURCE_BLE };
enum Mode : uint8_t { MODE_IDLE, MODE_SHOW, MODE_TEXT };
enum IdleMode : uint8_t { IDLE_OFF, IDLE_PET };
enum ColorMode : uint8_t { COLOR_SOLID, COLOR_STEP, COLOR_GRADIENT, COLOR_RAINBOW_CYCLE, COLOR_RAINBOW_FLOW };
enum EffectType : uint8_t { EFFECT_NONE, EFFECT_BREATHE, EFFECT_ALTERNATE, EFFECT_BLINK };

struct QueueItem {
  Source source;
  uint8_t client;
  uint16_t length;
  bool directResponse;
  uint32_t transportSession;
  char payload[kMaxRequest + 1];
};

QueueItem commandQueue[kQueueSize];
volatile uint8_t queueHead = 0;
volatile uint8_t queueTail = 0;
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
uint32_t activeResponseSession = UINT32_MAX;

struct ColorSpec {
  ColorMode mode = COLOR_SOLID;
  uint32_t values[8] = {};
  uint8_t count = 1;
  uint32_t periodMs = kDefaultColorPeriod;
  bool all = false;
};

struct EffectSpec {
  EffectType type = EFFECT_NONE;
  uint32_t periodMs = kDefaultEffectPeriod;
  uint8_t minValue = 0;
  uint8_t maxValue = 255;
};

struct AnimationSpec {
  bool enabled = true;
  uint32_t periodMs = 100;
  uint16_t repeat = 0;
  bool periodProvided = false;
};

struct RenderState {
  Mode mode = MODE_IDLE;
  const IconDef *icon = nullptr;
  char text[65] = {};
  ColorSpec color;
  EffectSpec effect;
  AnimationSpec animation;
  uint8_t brightness = kDefaultBrightness;
  uint32_t id = 0;
  uint32_t startedAt = 0;
  uint32_t ttlMs = 0;
  uint32_t deadline = 0;
  uint32_t virtualStarted = 0;
  bool staticText = true;
  bool scrollFinite = false;
  uint16_t scrollRepeat = 0;
  uint32_t scrollStepMs = kDefaultScrollStep;
  bool scrollRight = false;
};

RenderState state;
IdleMode idleMode = IDLE_OFF;
float speed = 1.0f;
bool paused = false;
uint32_t phaseRealOrigin = 0;
uint32_t phaseVirtualOrigin = 0;
uint32_t lastFrameAt = 0;
bool frameDirty = true;
float lastEstimatedMa = 64.0f;
bool lastPowerLimited = false;

bool wsAuthenticated[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
volatile uint32_t wsSession[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
char wsFragments[WEBSOCKETS_SERVER_CLIENT_MAX][kMaxRequest + 1] = {};
uint16_t wsFragmentLength[WEBSOCKETS_SERVER_CLIENT_MAX] = {};
bool wsFragmentOverflow[WEBSOCKETS_SERVER_CLIENT_MAX] = {};

BLEServer *bleServer = nullptr;
BLECharacteristic *bleWrite = nullptr;
BLECharacteristic *bleNotify = nullptr;
bool bleConnected = false;
bool bleAuthenticated = false;
volatile uint32_t bleSession = 0;
uint16_t bleConnectionId = UINT16_MAX;
char bleBuffer[kMaxRequest + 1] = {};
uint16_t bleLength = 0;
bool bleOverflow = false;
uint32_t bleLastWrite = 0;
struct BleTx {
  char payload[kMaxResponse];
  uint16_t length = 0;
  uint16_t offset = 0;
  uint32_t session = 0;
  bool newline = false;
  bool active = false;
} bleTx;

String wifiSsid;
String wifiPassword;
String controlToken;
String setupPassword;
String apName;
bool apRunning = false;
bool wifiAttempting = false;
bool candidateAttempt = false;
String candidateSsid;
String candidatePassword;
String previousSsid;
String previousPassword;
String activeAttemptSsid;
String candidateStatus = "idle";
uint32_t wifiDeadline = 0;
uint32_t savedRetryAt = 0;
uint32_t disconnectedAt = 0;
uint32_t apCloseAt = 0;
bool apClosePending = false;
uint32_t httpNonce = 0;
int scanState = -2;

bool timeReached(uint32_t now, uint32_t target) {
  return static_cast<int32_t>(now - target) >= 0;
}

bool timeElapsed(uint32_t now, uint32_t then, uint32_t duration) {
  return static_cast<uint32_t>(now - then) >= duration;
}

uint32_t randomWord() {
  return esp_random();
}

String randomHex(uint8_t bytes) {
  String value;
  value.reserve(bytes * 2);
  for (uint8_t i = 0; i < bytes; ++i) {
    uint8_t byte = static_cast<uint8_t>(esp_random());
    if (byte < 16) value += '0';
    value += String(byte, HEX);
  }
  return value;
}

bool secureEqual(const char *a, const char *b) {
  if (!a || !b) return false;
  size_t alen = strlen(a);
  size_t blen = strlen(b);
  uint8_t diff = static_cast<uint8_t>(alen ^ blen);
  size_t n = alen > blen ? alen : blen;
  for (size_t i = 0; i < n; ++i) {
    const uint8_t av = i < alen ? static_cast<uint8_t>(a[i]) : 0;
    const uint8_t bv = i < blen ? static_cast<uint8_t>(b[i]) : 0;
    diff |= av ^ bv;
  }
  return diff == 0;
}

bool enqueueCommand(Source source, uint8_t client, const uint8_t *data, size_t length, uint32_t sessionOverride = UINT32_MAX) {
  if (!data || length == 0 || length > kMaxRequest) return false;
  portENTER_CRITICAL(&queueMux);
  const uint8_t next = static_cast<uint8_t>((queueHead + 1) % kQueueSize);
  const uint8_t afterNext = static_cast<uint8_t>((next + 1) % kQueueSize);
  if (next == queueTail || afterNext == queueTail) {
    portEXIT_CRITICAL(&queueMux);
    return false;
  }
  QueueItem &item = commandQueue[queueHead];
  item.source = source;
  item.client = client;
  item.length = static_cast<uint16_t>(length);
  item.directResponse = false;
  item.transportSession = source == SOURCE_BLE ? (sessionOverride == UINT32_MAX ? bleSession : sessionOverride) : source == SOURCE_WS ? wsSession[client] : 0;
  memcpy(item.payload, data, length);
  item.payload[length] = '\0';
  queueHead = next;
  portEXIT_CRITICAL(&queueMux);
  return true;
}

bool enqueueDirectError(Source source, uint8_t client, const char *error, uint32_t sessionOverride = UINT32_MAX) {
  JsonDocument response;
  response["ok"] = false;
  response["error"] = error;
  char buffer[kMaxRequest + 1];
  const size_t length = serializeJson(response, buffer, sizeof(buffer));
  if (length >= sizeof(buffer)) return false;
  portENTER_CRITICAL(&queueMux);
  const uint8_t next = static_cast<uint8_t>((queueHead + 1) % kQueueSize);
  if (next == queueTail) {
    portEXIT_CRITICAL(&queueMux);
    return false;
  }
  QueueItem &item = commandQueue[queueHead];
  item.source = source;
  item.client = client;
  item.length = static_cast<uint16_t>(length);
  item.directResponse = true;
  item.transportSession = source == SOURCE_BLE ? (sessionOverride == UINT32_MAX ? bleSession : sessionOverride) : source == SOURCE_WS ? wsSession[client] : 0;
  memcpy(item.payload, buffer, length + 1);
  queueHead = next;
  portEXIT_CRITICAL(&queueMux);
  return true;
}

bool dequeueCommand(QueueItem &out) {
  portENTER_CRITICAL(&queueMux);
  if (queueTail == queueHead) {
    portEXIT_CRITICAL(&queueMux);
    return false;
  }
  out = commandQueue[queueTail];
  queueTail = static_cast<uint8_t>((queueTail + 1) % kQueueSize);
  portEXIT_CRITICAL(&queueMux);
  return true;
}

void enqueueTransportError(Source source, uint8_t client, const char *error, uint32_t sessionOverride = UINT32_MAX) {
  enqueueDirectError(source, client, error, sessionOverride);
}

bool parseUInt(JsonVariantConst value, uint32_t minValue, uint32_t maxValue, uint32_t &out) {
  if (!value.is<uint32_t>()) return false;
  out = value.as<uint32_t>();
  return out >= minValue && out <= maxValue;
}

bool parseByte(JsonVariantConst value, uint8_t &out) {
  uint32_t parsed = 0;
  if (!parseUInt(value, 0, 255, parsed)) return false;
  out = static_cast<uint8_t>(parsed);
  return true;
}

bool parseId(JsonVariantConst value, uint32_t &out) {
  return parseUInt(value, 1, 2147483647UL, out);
}

int findIcon(const char *id) {
  if (!id) return -1;
  for (uint16_t i = 0; i < ICON_COUNT; ++i) {
    if (strcmp(ICONS[i].id, id) == 0) return static_cast<int>(i);
  }
  return -1;
}

bool parseHexColor(const char *text, uint32_t &out) {
  if (!text || text[0] != '#' || strlen(text) != 7) return false;
  ++text;
  uint32_t value = 0;
  for (uint8_t i = 0; i < 6; ++i) {
    char c = text[i];
    uint8_t digit;
    if (c >= '0' && c <= '9') digit = c - '0';
    else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
    else return false;
    value = (value << 4) | digit;
  }
  out = value;
  return true;
}

bool parseColorName(const char *text, uint32_t &out) {
  if (!text) return false;
  struct NamedColor { const char *name; uint32_t color; };
  static const NamedColor names[] = {
    {"red", 0xFF0000}, {"orange", 0xFF8000}, {"yellow", 0xFFFF00},
    {"green", 0x00FF00}, {"cyan", 0x00FFFF}, {"blue", 0x0040FF},
    {"purple", 0xA000FF}, {"pink", 0xFF4080}, {"white", 0xFFFFFF},
    {"off", 0x000000}
  };
  for (const NamedColor &named : names) {
    if (strcasecmp(text, named.name) == 0) {
      out = named.color;
      return true;
    }
  }
  return parseHexColor(text, out);
}

bool parseColor(JsonVariantConst value, bool provided, uint32_t fallback, ColorSpec &out, const char *&error) {
  out = ColorSpec();
  out.values[0] = fallback;
  if (!provided) return true;
  JsonObjectConst object = value.as<JsonObjectConst>();
  if (object.isNull()) { error = "color_object_required"; return false; }
  for (JsonPairConst pair : object) {
    const char *key = pair.key().c_str();
    if (strcmp(key, "mode") && strcmp(key, "values") && strcmp(key, "period_ms") && strcmp(key, "scope")) {
      error = "invalid_color_parameters";
      return false;
    }
  }

  const char *mode = "solid";
  if (object.containsKey("mode")) {
    mode = object["mode"].as<const char *>();
    if (!mode) { error = "invalid_color_mode"; return false; }
  }
  if (strcmp(mode, "solid") == 0) out.mode = COLOR_SOLID;
  else if (strcmp(mode, "step") == 0) out.mode = COLOR_STEP;
  else if (strcmp(mode, "gradient") == 0) out.mode = COLOR_GRADIENT;
  else if (strcmp(mode, "rainbow_cycle") == 0) out.mode = COLOR_RAINBOW_CYCLE;
  else if (strcmp(mode, "rainbow_flow") == 0) out.mode = COLOR_RAINBOW_FLOW;
  else { error = "invalid_color_mode"; return false; }

  if (object.containsKey("period_ms")) {
    if (!parseUInt(object["period_ms"], 100, 60000, out.periodMs)) { error = "invalid_color_period"; return false; }
  }
  const char *scope = "primary";
  if (object.containsKey("scope")) {
    scope = object["scope"].as<const char *>();
    if (!scope) { error = "invalid_color_scope"; return false; }
  }
  if (strcmp(scope, "primary") == 0) out.all = false;
  else if (strcmp(scope, "all") == 0) out.all = true;
  else { error = "invalid_color_scope"; return false; }

  if (object.containsKey("values")) {
    JsonArrayConst values = object["values"].as<JsonArrayConst>();
    if (values.isNull() || values.size() == 0 || values.size() > 8) { error = "invalid_color_values"; return false; }
    out.count = 0;
    for (JsonVariantConst item : values) {
      const char *name = item.as<const char *>();
      if (!name || !parseColorName(name, out.values[out.count])) { error = "invalid_color_value"; return false; }
      ++out.count;
    }
  }
  if (out.mode == COLOR_SOLID && out.count != 1) { error = "solid_requires_one_color"; return false; }
  if ((out.mode == COLOR_STEP || out.mode == COLOR_GRADIENT) && out.count < 2) { error = "color_requires_two_values"; return false; }
  if ((out.mode == COLOR_RAINBOW_CYCLE || out.mode == COLOR_RAINBOW_FLOW) && object.containsKey("values")) {
    error = "rainbow_does_not_accept_values";
    return false;
  }
  return true;
}

bool parseEffect(JsonVariantConst value, bool provided, EffectSpec &out, const char *&error) {
  out = EffectSpec();
  if (!provided) return true;
  JsonObjectConst object = value.as<JsonObjectConst>();
  if (object.isNull()) { error = "effect_object_required"; return false; }
  for (JsonPairConst pair : object) {
    const char *key = pair.key().c_str();
    if (strcmp(key, "type") && strcmp(key, "period_ms") && strcmp(key, "min") && strcmp(key, "max")) {
      error = "invalid_effect_parameters";
      return false;
    }
  }
  const char *type = "none";
  if (object.containsKey("type")) {
    type = object["type"].as<const char *>();
    if (!type) { error = "invalid_effect_type"; return false; }
  }
  if (strcmp(type, "none") == 0) out.type = EFFECT_NONE;
  else if (strcmp(type, "breathe") == 0) out.type = EFFECT_BREATHE;
  else if (strcmp(type, "alternate") == 0) out.type = EFFECT_ALTERNATE;
  else if (strcmp(type, "blink") == 0) out.type = EFFECT_BLINK;
  else { error = "invalid_effect_type"; return false; }
  if (object.containsKey("period_ms") && !parseUInt(object["period_ms"], 100, 60000, out.periodMs)) {
    error = "invalid_effect_period";
    return false;
  }
  if (object.containsKey("min") && !parseByte(object["min"], out.minValue)) { error = "invalid_effect_min"; return false; }
  if (object.containsKey("max") && !parseByte(object["max"], out.maxValue)) { error = "invalid_effect_max"; return false; }
  if (out.type == EFFECT_BLINK && out.minValue != 0) { error = "blink_min_must_be_zero"; return false; }
  if (out.minValue > out.maxValue) { error = "effect_min_gt_max"; return false; }
  return true;
}

bool parseAnimation(JsonVariantConst value, bool provided, const IconDef *icon, AnimationSpec &out, const char *&error) {
  out = AnimationSpec();
  out.enabled = icon && icon->frameCount > 1;
  out.periodMs = icon && icon->period >= 100 && icon->period <= 60000 ? icon->period : 100;
  if (!provided) return true;
  JsonObjectConst object = value.as<JsonObjectConst>();
  if (object.isNull()) { error = "animation_object_required"; return false; }
  for (JsonPairConst pair : object) {
    const char *key = pair.key().c_str();
    if (strcmp(key, "enabled") && strcmp(key, "period_ms") && strcmp(key, "repeat")) {
      error = "invalid_animation_parameters";
      return false;
    }
  }
  if (object.containsKey("enabled") && !object["enabled"].is<bool>()) { error = "invalid_animation_enabled"; return false; }
  out.enabled = object["enabled"] | out.enabled;
  if (object.containsKey("period_ms") && !parseUInt(object["period_ms"], 100, 60000, out.periodMs)) {
    error = "invalid_animation_period";
    return false;
  }
  out.periodProvided = object.containsKey("period_ms");
  if (object.containsKey("enabled") && icon && icon->frameCount <= 1 && object["enabled"].as<bool>()) {
    error = "static_icon_cannot_animate";
    return false;
  }
  if (object.containsKey("repeat")) {
    uint32_t repeat = 0;
    if (!parseUInt(object["repeat"], 0, 65535, repeat)) { error = "invalid_animation_repeat"; return false; }
    out.repeat = static_cast<uint16_t>(repeat);
  }
  return true;
}

bool parseCommon(JsonObjectConst root, uint32_t fallbackColor, ColorSpec &color, EffectSpec &effect,
                 uint8_t &brightness, bool &brightnessProvided, uint32_t &ttl, const char *&error) {
  if (!parseColor(root["color"], root.containsKey("color"), fallbackColor, color, error)) return false;
  if (!parseEffect(root["effect"], root.containsKey("effect"), effect, error)) return false;
  brightnessProvided = root.containsKey("brightness");
  if (brightnessProvided && !parseByte(root["brightness"], brightness)) { error = "invalid_brightness"; return false; }
  ttl = 0;
  if (root.containsKey("duration_ms") && !parseUInt(root["duration_ms"], 0, 86400000UL, ttl)) {
    error = "invalid_duration";
    return false;
  }
  return true;
}

bool parseIdFromRoot(JsonObjectConst root, uint32_t &id, const char *&error) {
  if (!root.containsKey("id") || !parseId(root["id"], id)) { error = "id_required"; return false; }
  return true;
}

uint32_t virtualNow(uint32_t now) {
  if (paused) return phaseVirtualOrigin;
  return phaseVirtualOrigin + static_cast<uint32_t>((now - phaseRealOrigin) * speed);
}

void resetPhase(uint32_t now) {
  phaseRealOrigin = now;
  phaseVirtualOrigin = 0;
}

void setSpeed(float next, uint32_t now) {
  const uint32_t current = virtualNow(now);
  phaseVirtualOrigin = current;
  phaseRealOrigin = now;
  speed = next;
}

bool isActive() { return state.mode == MODE_SHOW || state.mode == MODE_TEXT; }

void enterIdle(uint32_t now, IdleMode mode) {
  const uint8_t currentBrightness = state.brightness;
  state = RenderState();
  state.mode = MODE_IDLE;
  state.brightness = currentBrightness;
  idleMode = mode;
  resetPhase(now);
  state.virtualStarted = 0;
  frameDirty = true;
}

void applyRenderState(RenderState &next, uint32_t now) {
  next.startedAt = now;
  next.deadline = next.ttlMs ? now + next.ttlMs : 0;
  resetPhase(now);
  next.virtualStarted = 0;
  state = next;
  frameDirty = true;
}

bool ensureAuth(const QueueItem &item, JsonObjectConst root) {
  if (item.source == SOURCE_SERIAL) return true;
  if (item.source == SOURCE_WS) return item.client < WEBSOCKETS_SERVER_CLIENT_MAX && item.transportSession == wsSession[item.client] && wsAuthenticated[item.client];
  portENTER_CRITICAL(&queueMux);
  const bool authenticated = bleConnected && item.transportSession == bleSession && bleAuthenticated;
  portEXIT_CRITICAL(&queueMux);
  return authenticated;
}

bool setBleAuthentication(uint32_t session, bool authenticated) {
  portENTER_CRITICAL(&queueMux);
  const bool current = bleConnected && session == bleSession;
  if (current) bleAuthenticated = authenticated;
  portEXIT_CRITICAL(&queueMux);
  return current;
}

void copyResponseId(JsonDocument &response, JsonObjectConst root) {
  if (root.containsKey("id")) response["id"] = root["id"];
}

void dispatchResponse(Source source, uint8_t client, const char *buffer, size_t length, uint32_t session = UINT32_MAX);

void sendResponse(Source source, uint8_t client, JsonDocument &response, uint32_t session = activeResponseSession) {
  char buffer[kMaxResponse];
  size_t length = serializeJson(response, buffer, sizeof(buffer));
  if (length >= sizeof(buffer)) {
    JsonDocument fallback;
    if (response.containsKey("id")) fallback["id"] = response["id"];
    fallback["ok"] = false;
    fallback["error"] = "response_too_large";
    length = serializeJson(fallback, buffer, sizeof(buffer));
  }
  dispatchResponse(source, client, buffer, length, session);
}

void sendError(Source source, uint8_t client, JsonObjectConst root, const char *error, uint32_t session = activeResponseSession) {
  JsonDocument response;
  copyResponseId(response, root);
  response["ok"] = false;
  response["error"] = error;
  sendResponse(source, client, response, session);
}

void sendOk(Source source, uint8_t client, JsonObjectConst root, uint32_t session = activeResponseSession) {
  JsonDocument response;
  copyResponseId(response, root);
  response["ok"] = true;
  sendResponse(source, client, response, session);
}

uint32_t mixChannel(uint8_t a, uint8_t b, float t) {
  return static_cast<uint32_t>(a + (b - a) * t + 0.5f);
}

uint32_t mixColor(uint32_t a, uint32_t b, float t) {
  uint8_t ar = static_cast<uint8_t>(a >> 16), ag = static_cast<uint8_t>(a >> 8), ab = static_cast<uint8_t>(a);
  uint8_t br = static_cast<uint8_t>(b >> 16), bg = static_cast<uint8_t>(b >> 8), bb = static_cast<uint8_t>(b);
  return (mixChannel(ar, br, t) << 16) | (mixChannel(ag, bg, t) << 8) | mixChannel(ab, bb, t);
}

uint32_t rainbowColor(float t) {
  static const uint32_t stops[] = {0xFF0000, 0xFF8000, 0xFFFF00, 0x00FF00, 0x00FFFF, 0x0040FF, 0xA000FF};
  while (t < 0) t += 1.0f;
  t -= floorf(t);
  const float scaled = t * 7.0f;
  const uint8_t index = static_cast<uint8_t>(scaled);
  return mixColor(stops[index % 7], stops[(index + 1) % 7], scaled - floorf(scaled));
}

uint32_t colorAt(const ColorSpec &spec, uint8_t x, uint8_t y, uint32_t phase) {
  if (spec.mode == COLOR_SOLID) return spec.values[0];
  if (spec.mode == COLOR_RAINBOW_CYCLE) {
    return rainbowColor(static_cast<float>(phase % spec.periodMs) / spec.periodMs);
  }
  if (spec.mode == COLOR_RAINBOW_FLOW) {
    return rainbowColor((static_cast<float>(phase % spec.periodMs) / spec.periodMs) + x / 8.0f);
  }
  const float position = static_cast<float>(phase % spec.periodMs) / spec.periodMs;
  if (spec.mode == COLOR_STEP) return spec.values[min<uint8_t>(spec.count - 1, static_cast<uint8_t>(position * spec.count))];
  const float scaled = position * spec.count;
  const uint8_t index = static_cast<uint8_t>(scaled) % spec.count;
  return mixColor(spec.values[index], spec.values[(index + 1) % spec.count], scaled - floorf(scaled));
}

float effectFactor(const EffectSpec &effect, uint32_t phase) {
  if (effect.type == EFFECT_NONE) return 1.0f;
  const float fraction = static_cast<float>(phase % effect.periodMs) / effect.periodMs;
  float wave = 0;
  if (effect.type == EFFECT_BREATHE) wave = (1.0f + cosf(fraction * 2.0f * kPi)) * 0.5f;
  else wave = fraction < 0.5f ? 1.0f : 0.0f;
  return (effect.minValue + (effect.maxValue - effect.minValue) * wave) / 255.0f;
}

uint8_t iconPixel(const IconDef *icon, uint16_t frame, uint16_t logical) {
  if (!icon || !icon->pixels) return 0;
  return pgm_read_byte(icon->pixels + frame * kPixels + logical);
}

uint32_t iconFrameDuration(const IconDef *icon, const AnimationSpec &animation, uint16_t frame) {
  if (!icon || !icon->durations) return max<uint32_t>(1, animation.periodMs / max<uint16_t>(1, icon ? icon->frameCount : 1));
  if (icon->durations) {
    const uint16_t duration = pgm_read_word(icon->durations + frame);
    if (duration >= 20) {
      if (!animation.periodProvided || icon->period == 0) return duration;
      return max<uint32_t>(1, static_cast<uint64_t>(duration) * animation.periodMs / icon->period);
    }
  }
  return animation.periodMs;
}

uint32_t iconTotalDuration(const IconDef *icon, const AnimationSpec &animation) {
  if (!icon || !animation.enabled || icon->frameCount <= 1) return animation.periodMs;
  uint32_t total = 0;
  for (uint16_t i = 0; i < icon->frameCount; ++i) total += iconFrameDuration(icon, animation, i);
  return total;
}

uint16_t iconFrameAt(const IconDef *icon, const AnimationSpec &animation, uint32_t phase, bool &finished) {
  finished = false;
  if (!icon || icon->frameCount == 0) return 0;
  if (!animation.enabled || icon->frameCount == 1) return min<uint16_t>(icon->staticFrame, icon->frameCount - 1);
  const uint32_t total = iconTotalDuration(icon, animation);
  if (animation.repeat && total && phase >= static_cast<uint64_t>(total) * animation.repeat) {
    finished = true;
    return icon->frameCount - 1;
  }
  uint32_t within = total ? phase % total : 0;
  for (uint16_t frame = 0; frame < icon->frameCount; ++frame) {
    const uint32_t duration = iconFrameDuration(icon, animation, frame);
    if (within < duration) return frame;
    within -= duration;
  }
  return icon->frameCount - 1;
}

void drawPet(uint8_t frame[kPixels], uint32_t phase) {
  static const char *ids[] = {"smile", "happy", "wink", "sleepy"};
  const int index = findIcon(ids[(phase / 20000UL) % 4]);
  const IconDef *pet = index >= 0 ? &ICONS[index] : nullptr;
  if (!pet) return;
  AnimationSpec petAnimation;
  petAnimation.enabled = pet->frameCount > 1;
  petAnimation.periodMs = pet->period;
  bool petFinished = false;
  const uint16_t petFrame = iconFrameAt(pet, petAnimation, phase % 20000UL, petFinished);
  for (uint16_t i = 0; i < kPixels; ++i) frame[i] = iconPixel(pet, petFrame, i);
}

void drawText(uint8_t frame[kPixels], const char *text, int16_t originX, uint32_t phase, bool scroll) {
  const uint16_t length = strlen(text);
  const int16_t width = length * 6 - 1;
  int32_t x = originX;
  if (scroll) {
    const uint32_t cycle = width + 8 + 3;
    uint32_t step = phase / state.scrollStepMs;
    if (cycle) step %= cycle;
    x = state.scrollRight ? -width + step : 8 - step;
  }
  for (uint16_t index = 0; index < length; ++index) {
    const char c = text[index];
    const uint8_t glyph = static_cast<uint8_t>(c - 32);
    for (uint8_t col = 0; col < 5; ++col) {
      const int16_t px = x + index * 6 + col;
      if (px < 0 || px >= 8) continue;
      const uint8_t bits = pgm_read_byte(&FONT[glyph][col]);
      for (uint8_t row = 0; row < 7; ++row) {
        if (bits & (1U << row)) frame[row * 8 + px] = 255;
      }
    }
  }
}

void showFrame(uint8_t frame[kPixels], const ColorSpec &color, const EffectSpec &effect, uint8_t brightness, uint32_t phase) {
  float scale = 1.0f;
  uint8_t rounded[kPixels][3] = {};
  uint32_t rgbSum = 0;
  for (uint8_t y = 0; y < 8; ++y) {
    for (uint8_t x = 0; x < 8; ++x) {
      const uint32_t rgb = colorAt(color, x, y, phase);
      const uint8_t red = rgb >> 16, green = rgb >> 8, blue = rgb;
      const uint8_t alpha = frame[y * 8 + x];
      const float effectValue = effectFactor(effect, phase);
      const float level = (alpha / 255.0f) * effectValue * (brightness / 255.0f);
      rounded[y * 8 + x][0] = min<uint16_t>(255, static_cast<uint16_t>(red * level + 0.5f));
      rounded[y * 8 + x][1] = min<uint16_t>(255, static_cast<uint16_t>(green * level + 0.5f));
      rounded[y * 8 + x][2] = min<uint16_t>(255, static_cast<uint16_t>(blue * level + 0.5f));
      rgbSum += rounded[y * 8 + x][0] + rounded[y * 8 + x][1] + rounded[y * 8 + x][2];
    }
  }
  const float variableMa = 20.0f * rgbSum / 255.0f;
  if (variableMa > 436.0f) scale = 436.0f / variableMa;
  lastEstimatedMa = 64.0f + min(variableMa, 436.0f);
  lastPowerLimited = scale < 0.999f;
  for (uint8_t y = 0; y < 8; ++y) {
    for (uint8_t x = 0; x < 8; ++x) {
      const uint16_t logical = y * 8 + x;
      const uint8_t red = static_cast<uint8_t>(rounded[logical][0] * scale);
      const uint8_t green = static_cast<uint8_t>(rounded[logical][1] * scale);
      const uint8_t blue = static_cast<uint8_t>(rounded[logical][2] * scale);
      const uint16_t physical = logical;
      pixels.setPixelColor(physical, pixels.Color(red, green, blue));
    }
  }
  pixels.show();
}

bool textIsScrolling(uint32_t phase, bool &finished) {
  finished = false;
  const uint16_t length = strlen(state.text);
  const uint32_t width = length * 6 - 1;
  const uint32_t cycle = width + 8 + 3;
  if (!state.scrollFinite || cycle == 0) return true;
  const uint64_t totalSteps = static_cast<uint64_t>(cycle) * state.scrollRepeat;
  const uint64_t step = phase / state.scrollStepMs;
  if (step >= totalSteps) {
    finished = true;
    return false;
  }
  return true;
}

bool speedSupports(const RenderState &candidate, float multiplier) {
  if (candidate.mode == MODE_SHOW && candidate.icon && candidate.animation.enabled) {
    for (uint16_t i = 0; i < candidate.icon->frameCount; ++i) {
      if (iconFrameDuration(candidate.icon, candidate.animation, i) / multiplier < 20.0f) return false;
    }
  }
  if (candidate.mode == MODE_TEXT && !candidate.staticText && candidate.scrollStepMs / multiplier < 20.0f) return false;
  if (candidate.color.mode != COLOR_SOLID && candidate.color.periodMs / multiplier < 500.0f) return false;
  if (candidate.effect.type != EFFECT_NONE) {
    const float minimum = candidate.effect.type == EFFECT_BREATHE ? 600.0f : 500.0f;
    if (candidate.effect.periodMs / multiplier < minimum) return false;
  }
  return true;
}

void render(uint32_t now) {
  if (!frameDirty && !timeElapsed(now, lastFrameAt, 20)) return;
  lastFrameAt = now;
  uint8_t frame[kPixels] = {};
  uint32_t phase = virtualNow(now) - state.virtualStarted;
  if (state.mode == MODE_IDLE) {
    if (idleMode == IDLE_PET) {
      static const char *petIds[] = {"smile", "happy", "wink", "sleepy"};
      const int petIndex = findIcon(petIds[(phase / 20000UL) % 4]);
      const IconDef *pet = petIndex >= 0 ? &ICONS[petIndex] : nullptr;
      if (pet) {
        drawPet(frame, phase);
        ColorSpec petColor;
        petColor.values[0] = pet->color & 0xFFFFFFUL;
        showFrame(frame, petColor, EffectSpec(), state.brightness, phase);
      } else {
        showFrame(frame, ColorSpec(), EffectSpec(), state.brightness, phase);
      }
    } else {
      showFrame(frame, ColorSpec(), EffectSpec(), state.brightness, phase);
    }
  } else if (state.mode == MODE_SHOW) {
    bool finished = false;
    const uint16_t frameIndex = iconFrameAt(state.icon, state.animation, phase, finished);
    for (uint16_t i = 0; i < kPixels; ++i) frame[i] = iconPixel(state.icon, frameIndex, i);
    showFrame(frame, state.color, state.effect, state.brightness, phase);
  } else {
    bool finished = false;
    const bool scrolling = state.staticText ? false : textIsScrolling(phase, finished);
    if (finished) {
      enterIdle(now, idleMode);
      return;
    }
    const uint16_t width = strlen(state.text) * 6 - 1;
    const int16_t origin = state.staticText ? (8 - width) / 2 : 0;
    drawText(frame, state.text, origin, phase, scrolling);
    showFrame(frame, state.color, state.effect, state.brightness, phase);
  }
  frameDirty = false;
}

void addState(JsonDocument &response, uint32_t now) {
  JsonObject stateObject = response["state"].to<JsonObject>();
  stateObject["mode"] = state.mode == MODE_SHOW ? "show" : state.mode == MODE_TEXT ? "text" : "idle";
  stateObject["idle"] = idleMode == IDLE_PET ? "pet" : "off";
  stateObject["brightness"] = state.brightness;
  stateObject["speed"] = speed;
  stateObject["paused"] = paused;
  stateObject["estimated_mA"] = lastEstimatedMa;
  stateObject["power_limited"] = lastPowerLimited;
  if (isActive()) {
    stateObject["current_id"] = state.id;
    stateObject["current_type"] = state.mode == MODE_SHOW ? "show" : "text";
    JsonObject content = stateObject["content"].to<JsonObject>();
    content["id"] = state.id;
    content["op"] = state.mode == MODE_SHOW ? "show" : "text";
    if (state.mode == MODE_SHOW && state.icon) {
      content["icon"] = state.icon->id;
      JsonObject animation = content["animation"].to<JsonObject>();
      animation["enabled"] = state.animation.enabled;
      animation["period_ms"] = state.animation.periodMs;
      animation["repeat"] = state.animation.repeat;
      const uint32_t phase = virtualNow(now) - state.virtualStarted;
      stateObject["animation_complete"] = state.animation.enabled && state.animation.repeat &&
        phase >= static_cast<uint64_t>(iconTotalDuration(state.icon, state.animation)) * state.animation.repeat;
    } else {
      content["text"] = state.text;
      JsonObject scroll = content["scroll"].to<JsonObject>();
      scroll["mode"] = state.staticText ? "never" : "always";
      scroll["direction"] = state.scrollRight ? "right" : "left";
      scroll["step_ms"] = state.scrollStepMs;
      scroll["repeat"] = state.scrollRepeat;
      stateObject["animation_complete"] = false;
    }
    JsonObject color = content["color"].to<JsonObject>();
    color["mode"] = state.color.mode == COLOR_SOLID ? "solid" : state.color.mode == COLOR_STEP ? "step" :
      state.color.mode == COLOR_GRADIENT ? "gradient" : state.color.mode == COLOR_RAINBOW_CYCLE ? "rainbow_cycle" : "rainbow_flow";
    color["period_ms"] = state.color.periodMs;
    color["scope"] = state.color.all ? "all" : "primary";
    if (state.color.mode != COLOR_RAINBOW_CYCLE && state.color.mode != COLOR_RAINBOW_FLOW) {
      JsonArray values = color["values"].to<JsonArray>();
      for (uint8_t index = 0; index < state.color.count; ++index) {
        char value[8];
        snprintf(value, sizeof(value), "#%06lx", static_cast<unsigned long>(state.color.values[index] & 0xFFFFFFUL));
        values.add(value);
      }
    }
    JsonObject effect = content["effect"].to<JsonObject>();
    effect["type"] = state.effect.type == EFFECT_NONE ? "none" : state.effect.type == EFFECT_BREATHE ? "breathe" :
      state.effect.type == EFFECT_ALTERNATE ? "alternate" : "blink";
    effect["period_ms"] = state.effect.periodMs;
    effect["min"] = state.effect.minValue;
    effect["max"] = state.effect.maxValue;
    content["brightness"] = state.brightness;
    content["duration_ms"] = state.ttlMs;
    if (state.deadline && !timeReached(now, state.deadline)) stateObject["remaining_ms"] = static_cast<uint32_t>(state.deadline - now);
    else stateObject["remaining_ms"] = nullptr;
  } else {
    stateObject["current_id"] = nullptr;
    stateObject["current_type"] = nullptr;
    stateObject["content"] = nullptr;
    stateObject["remaining_ms"] = nullptr;
    stateObject["animation_complete"] = false;
  }
  stateObject["wifi_connected"] = WiFi.status() == WL_CONNECTED;
  if (WiFi.status() == WL_CONNECTED) stateObject["ip"] = WiFi.localIP().toString();
}

void expireState(uint32_t now) {
  if (!isActive()) return;
  if (state.deadline && timeReached(now, state.deadline)) {
    enterIdle(now, idleMode);
    return;
  }
  if (state.mode == MODE_TEXT && !state.staticText) {
    bool finished = false;
    textIsScrolling(virtualNow(now) - state.virtualStarted, finished);
    if (finished) enterIdle(now, idleMode);
  }
}

bool parseShow(JsonObjectConst root, RenderState &next, const char *&error) {
  const char *id = root["icon"].as<const char *>();
  if (!id || strlen(id) == 0 || strlen(id) > 32) { error = "invalid_icon"; return false; }
  const int index = findIcon(id);
  if (index < 0) { error = "unknown_icon"; return false; }
  const IconDef *icon = &ICONS[index];
  next = RenderState();
  next.mode = MODE_SHOW;
  next.icon = icon;
  if (!parseAnimation(root["animation"], root.containsKey("animation"), icon, next.animation, error)) return false;
  const uint32_t fallback = icon->color & 0xFFFFFFUL;
  bool brightnessProvided = false;
  if (!parseCommon(root, fallback, next.color, next.effect, next.brightness, brightnessProvided, next.ttlMs, error)) return false;
  if (!brightnessProvided) next.brightness = state.brightness;
  return true;
}

bool parseText(JsonObjectConst root, RenderState &next, const char *&error) {
  const JsonString textValue = root["text"].as<JsonString>();
  const char *text = textValue.c_str();
  const size_t textLength = textValue.size();
  if (!text || textLength == 0 || textLength > 64 || strlen(text) != textLength) { error = "invalid_text"; return false; }
  for (size_t i = 0; i < textLength; ++i) {
    if (static_cast<uint8_t>(text[i]) < 32 || static_cast<uint8_t>(text[i]) > 126) { error = "text_ascii_required"; return false; }
  }
  next = RenderState();
  next.mode = MODE_TEXT;
  strncpy(next.text, text, sizeof(next.text) - 1);
  const bool scrollProvided = root.containsKey("scroll");
  JsonObjectConst scroll = root["scroll"].as<JsonObjectConst>();
  if (scrollProvided && scroll.isNull()) { error = "scroll_object_required"; return false; }
  if (!scroll.isNull()) {
    for (JsonPairConst pair : scroll) {
      const char *key = pair.key().c_str();
      if (strcmp(key, "mode") && strcmp(key, "direction") && strcmp(key, "step_ms") && strcmp(key, "repeat")) {
        error = "invalid_scroll_parameters";
        return false;
      }
    }
  }
  const char *scrollMode = "auto";
  if (!scroll.isNull() && scroll.containsKey("mode")) {
    scrollMode = scroll["mode"].as<const char *>();
    if (!scrollMode) { error = "invalid_scroll_mode"; return false; }
  }
  if (strcmp(scrollMode, "auto") != 0 && strcmp(scrollMode, "always") != 0 && strcmp(scrollMode, "never") != 0) { error = "invalid_scroll_mode"; return false; }
  const uint16_t width = strlen(text) * 6 - 1;
  next.staticText = strcmp(scrollMode, "never") == 0 || (strcmp(scrollMode, "auto") == 0 && width <= 8);
  if (strcmp(scrollMode, "never") == 0 && width > 8) { error = "text_too_wide_for_static"; return false; }
  next.scrollRepeat = 1;
  if (!scroll.isNull()) {
    const char *direction = "left";
    if (scroll.containsKey("direction")) {
      direction = scroll["direction"].as<const char *>();
      if (!direction) { error = "invalid_scroll_direction"; return false; }
    }
    if (strcmp(direction, "left") != 0 && strcmp(direction, "right") != 0) { error = "invalid_scroll_direction"; return false; }
    next.scrollRight = strcmp(direction, "right") == 0;
    if (scroll.containsKey("step_ms") && !parseUInt(scroll["step_ms"], 20, 60000, next.scrollStepMs)) { error = "invalid_scroll_step"; return false; }
    if (scroll.containsKey("repeat")) {
      uint32_t repeat = 0;
      if (!parseUInt(scroll["repeat"], 0, 65535, repeat)) { error = "invalid_scroll_repeat"; return false; }
      next.scrollRepeat = static_cast<uint16_t>(repeat);
    }
  }
  if (!next.staticText && next.scrollRepeat > 0) next.scrollFinite = true;
  bool brightnessProvided = false;
  if (!parseCommon(root, 0xFFFFFF, next.color, next.effect, next.brightness, brightnessProvided, next.ttlMs, error)) return false;
  if (!brightnessProvided) next.brightness = state.brightness;
  return true;
}

void startCandidate(const String &ssid, const String &password) {
  previousSsid = wifiSsid;
  previousPassword = wifiPassword;
  candidateSsid = ssid;
  candidatePassword = password;
  activeAttemptSsid = ssid;
  candidateAttempt = true;
  wifiAttempting = true;
  wifiDeadline = millis() + kWifiAttemptMs;
  apClosePending = false;
  candidateStatus = "pending";
  WiFi.disconnect(false, false);
  WiFi.mode(apRunning ? WIFI_AP_STA : WIFI_STA);
  WiFi.begin(candidateSsid.c_str(), candidatePassword.c_str());
}

void startAp() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apName.c_str(), setupPassword.c_str());
  apRunning = true;
  apClosePending = false;
  scanState = -2;
}

void stopAp() {
  WiFi.softAPdisconnect(false);
  apRunning = false;
  apClosePending = false;
  if (WiFi.status() != WL_CONNECTED) WiFi.mode(WIFI_STA);
}

bool requestFromAp() {
  if (!apRunning) return false;
  const IPAddress local = http.client().localIP();
  return local == WiFi.softAPIP();
}

bool requireAp() {
  if (!requestFromAp()) {
    http.send(403, "application/json", "{\"ok\":false,\"error\":\"ap_only\"}");
    return false;
  }
  return true;
}

String htmlEscape(const String &value) {
  String result;
  result.reserve(value.length() + 8);
  for (size_t i = 0; i < value.length(); ++i) {
    const char c = value[i];
    if (c == '&') result += "&amp;";
    else if (c == '<') result += "&lt;";
    else if (c == '>') result += "&gt;";
    else if (c == '"') result += "&quot;";
    else result += c;
  }
  return result;
}

bool checkCsrf() {
  if (!http.hasArg("csrf")) return false;
  char expected[12];
  snprintf(expected, sizeof(expected), "%08lx", static_cast<unsigned long>(httpNonce));
  return secureEqual(http.arg("csrf").c_str(), expected);
}

void handleApRoot() {
  if (!requireAp()) return;
  httpNonce = randomWord();
  char nonce[12];
  snprintf(nonce, sizeof(nonce), "%08lx", static_cast<unsigned long>(httpNonce));
  String page = F("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>IconShow setup</title>");
  page += F("<style>body{font:16px system-ui;max-width:34rem;margin:2rem auto;padding:0 1rem}label{display:block;margin:1rem 0}input,button{font:inherit;padding:.5rem;width:100%}#status{white-space:pre-wrap}</style>");
  page += F("<h1>IconShow Wi-Fi</h1><p id=status>Loading…</p><form method=post action=/api/apply><input type=hidden name=csrf value='");
  page += nonce;
  page += F("'><label>SSID<input id=ssid name=ssid list=networks required maxlength=32 autocomplete=off><datalist id=networks></datalist></label><label>Password<input name=password type=password maxlength=63 autocomplete=off></label><p>Hidden networks: enter the SSID manually.</p><button>Apply</button></form><button id=rescan type=button>Rescan</button><script>");
  page += F("const form=document.querySelector('form'),status=document.querySelector('#status'),ssid=document.querySelector('#ssid'),list=document.querySelector('#networks');async function scan(){status.textContent='Scanning…';try{const j=await (await fetch('/api/scan')).json();if(!j.ok){status.textContent=j.error||'Scan failed';return;}if(j.pending){setTimeout(scan,500);return;}status.textContent='Choose a 2.4 GHz network';list.replaceChildren(...(j.networks||[]).filter(n=>n.ssid).map(n=>{const o=document.createElement('option');o.value=n.ssid;return o}));}catch(x){status.textContent='Scan failed';}}async function apply(e){e.preventDefault();status.textContent='Testing network…';try{const j=await (await fetch('/api/apply',{method:'POST',body:new URLSearchParams(new FormData(form))})).json();if(!j.ok){status.textContent=j.error||'Apply failed';return;}for(let i=0;i<40;i++){await new Promise(x=>setTimeout(x,1000));const s=await (await fetch('/api/status')).json();if(s.candidate_status==='connected'){status.textContent='Connected: '+s.sta_ip;return;}if(s.candidate_status==='save_failed'){status.textContent='Connected, but could not save the network.';return;}if(s.candidate_status==='failed'){status.textContent='Connection failed; old configuration was kept.';return;}}status.textContent='No IP; old configuration was kept.';}catch(x){status.textContent='Apply failed';}}form.onsubmit=apply;document.querySelector('#rescan').onclick=scan;scan();</script>");
  http.send(200, "text/html; charset=utf-8", page);
}

void handleApStatus() {
  if (!requireAp()) return;
  JsonDocument response;
  response["ok"] = true;
  response["ap"] = apName;
  response["ip"] = WiFi.softAPIP().toString();
  response["connected"] = WiFi.status() == WL_CONNECTED;
  if (WiFi.status() == WL_CONNECTED) response["sta_ip"] = WiFi.localIP().toString();
  response["candidate_status"] = candidateStatus;
  String body;
  serializeJson(response, body);
  http.send(200, "application/json", body);
}

void handleApScan() {
  if (!requireAp()) return;
  if (scanState == -2) {
    scanState = WiFi.scanNetworks(true, true);
  }
  JsonDocument response;
  response["ok"] = true;
  JsonArray networks = response["networks"].to<JsonArray>();
  const int complete = WiFi.scanComplete();
  if (complete == WIFI_SCAN_RUNNING) {
    response["pending"] = true;
  } else if (complete == WIFI_SCAN_FAILED) {
    response["ok"] = false;
    response["error"] = "scan_failed";
    WiFi.scanDelete();
    scanState = -2;
  } else {
    for (int i = 0; i < complete; ++i) {
      JsonObject network = networks.add<JsonObject>();
      network["ssid"] = WiFi.SSID(i);
      network["rssi"] = WiFi.RSSI(i);
    }
    response["pending"] = false;
    WiFi.scanDelete();
    scanState = -2;
  }
  String body;
  serializeJson(response, body);
  http.send(200, "application/json", body);
}

void handleApApply() {
  if (!requireAp()) return;
  if (!checkCsrf()) {
    http.send(403, "application/json", "{\"ok\":false,\"error\":\"csrf\"}");
    return;
  }
  const String ssid = http.arg("ssid");
  const String password = http.arg("password");
  if (ssid.length() == 0 || ssid.length() > 32 || password.length() > 63) {
    http.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid_wifi\"}");
    return;
  }
  startCandidate(ssid, password);
  http.send(202, "application/json", "{\"ok\":true,\"pending\":true}");
}

void setupHttp() {
  http.on("/", HTTP_GET, handleApRoot);
  http.on("/api/status", HTTP_GET, handleApStatus);
  http.on("/api/scan", HTTP_GET, handleApScan);
  http.on("/api/apply", HTTP_POST, handleApApply);
  http.onNotFound([]() { http.send(404, "application/json", "{\"ok\":false,\"error\":\"not_found\"}"); });
  http.begin();
}

void wifiTick(uint32_t now) {
  if (wifiAttempting) {
    const bool gotIp = WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0);
    const bool attemptIsCurrent = WiFi.SSID() == activeAttemptSsid;
    if (gotIp && attemptIsCurrent) {
      wifiAttempting = false;
      if (candidateAttempt) {
        JsonDocument saved;
        saved["ssid"] = candidateSsid;
        saved["password"] = candidatePassword;
        String blob;
        serializeJson(saved, blob);
        if (preferences.putString("wifi", blob) != blob.length()) {
          candidateAttempt = false;
          candidateStatus = "save_failed";
          return;
        }
        wifiSsid = candidateSsid;
        wifiPassword = candidatePassword;
        candidateAttempt = false;
        candidateStatus = "connected";
        apClosePending = apRunning;
        apCloseAt = now + kApGraceMs;
      }
    } else if (timeReached(now, wifiDeadline)) {
      wifiAttempting = false;
      if (candidateAttempt) {
        WiFi.disconnect(false, false);
        candidateAttempt = false;
        candidateStatus = "failed";
        if (previousSsid.length()) {
          wifiSsid = previousSsid;
          wifiPassword = previousPassword;
          activeAttemptSsid = wifiSsid;
          WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
          wifiAttempting = true;
          wifiDeadline = now + kWifiAttemptMs;
        } else if (!apRunning) {
          startAp();
        }
      } else if (!apRunning) {
        startAp();
      }
    }
  }
  if (WiFi.status() == WL_CONNECTED) disconnectedAt = 0;
  else if (!disconnectedAt) disconnectedAt = now;
  if (!wifiAttempting && !apRunning && WiFi.status() != WL_CONNECTED && disconnectedAt && wifiSsid.length() && timeElapsed(now, disconnectedAt, kWifiAttemptMs)) {
    startAp();
    savedRetryAt = now;
  }
  if (!wifiAttempting && apRunning && WiFi.status() != WL_CONNECTED && wifiSsid.length() && timeReached(now, savedRetryAt)) {
    savedRetryAt = now + kWifiAttemptMs;
    WiFi.mode(WIFI_AP_STA);
    activeAttemptSsid = wifiSsid;
    WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
    wifiAttempting = true;
    wifiDeadline = now + kWifiAttemptMs;
  }
  if (apClosePending && timeReached(now, apCloseAt)) stopAp();
}

void initWifi() {
  const String blob = preferences.getString("wifi", "");
  if (blob.length()) {
    JsonDocument saved;
    if (!deserializeJson(saved, blob)) {
      wifiSsid = saved["ssid"] | "";
      wifiPassword = saved["password"] | "";
    }
  }
  uint64_t chip = ESP.getEfuseMac();
  char suffix[5];
  snprintf(suffix, sizeof(suffix), "%04llX", static_cast<unsigned long long>(chip & 0xFFFF));
  apName = String("IconShow-") + suffix;
  if (!wifiSsid.length()) startAp();
  else {
    WiFi.mode(WIFI_STA);
    activeAttemptSsid = wifiSsid;
    WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
    wifiAttempting = true;
    wifiDeadline = millis() + kWifiAttemptMs;
    savedRetryAt = wifiDeadline;
  }
}

void notifyBle(const char *payload, size_t length, uint32_t session) {
  if (!bleConnected || !bleNotify || !payload || length >= kMaxResponse || session != bleSession) return;
  memcpy(bleTx.payload, payload, length);
  bleTx.length = static_cast<uint16_t>(length);
  bleTx.offset = 0;
  bleTx.session = session;
  bleTx.newline = false;
  bleTx.active = true;
}

void bleNotifyTick() {
  if (!bleTx.active) return;
  uint16_t connection = UINT16_MAX;
  uint16_t length = 0;
  uint8_t chunk[20];
  bool finish = false;
  portENTER_CRITICAL(&queueMux);
  if (!bleConnected || !bleNotify || !bleServer || bleTx.session != bleSession || bleConnectionId == UINT16_MAX) {
    bleTx.active = false;
    portEXIT_CRITICAL(&queueMux);
    return;
  }
  if (bleTx.offset < bleTx.length) {
    length = min<uint16_t>(20, bleTx.length - bleTx.offset);
    memcpy(chunk, bleTx.payload + bleTx.offset, length);
  } else if (!bleTx.newline) {
    chunk[0] = '\n';
    length = 1;
    finish = true;
  } else {
    bleTx.active = false;
    portEXIT_CRITICAL(&queueMux);
    return;
  }
  connection = bleConnectionId;
  const uint32_t session = bleTx.session;
  portEXIT_CRITICAL(&queueMux);
#if defined(CONFIG_NIMBLE_ENABLED)
  os_mbuf *packet = ble_hs_mbuf_from_flat(chunk, length);
  if (!packet || ble_gatts_notify_custom(connection, bleNotify->getHandle(), packet) != 0) return;
#else
  bleNotify->setValue(chunk, length);
  bleNotify->notify();
#endif
  portENTER_CRITICAL(&queueMux);
  if (bleTx.active && bleConnected && bleTx.session == session && bleSession == session && bleConnectionId == connection) {
    if (finish) bleTx.newline = true;
    else bleTx.offset += length;
  }
  portEXIT_CRITICAL(&queueMux);
}

class BleServerCallbacks : public BLEServerCallbacks {
#if defined(CONFIG_BLUEDROID_ENABLED)
  void onConnect(BLEServer *server, esp_ble_gatts_cb_param_t *param) override {
    const uint16_t connection = param->connect.conn_id;
    portENTER_CRITICAL(&queueMux);
    const bool reject = bleConnected;
    if (!reject) {
      bleConnected = true;
      bleConnectionId = connection;
      bleAuthenticated = false;
      ++bleSession;
      bleLength = 0;
      bleOverflow = false;
    }
    portEXIT_CRITICAL(&queueMux);
    if (reject) server->disconnect(connection);
  }
  void onDisconnect(BLEServer *server, esp_ble_gatts_cb_param_t *param) override {
    portENTER_CRITICAL(&queueMux);
    const bool active = param->disconnect.conn_id == bleConnectionId;
    if (active) {
      bleConnected = false;
      bleConnectionId = UINT16_MAX;
      bleAuthenticated = false;
      bleTx.active = false;
      ++bleSession;
      bleLength = 0;
      bleOverflow = false;
    }
    portEXIT_CRITICAL(&queueMux);
    if (active) server->startAdvertising();
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onConnect(BLEServer *server, ble_gap_conn_desc *desc) override {
    const uint16_t connection = desc->conn_handle;
    portENTER_CRITICAL(&queueMux);
    const bool reject = bleConnected;
    if (!reject) {
      bleConnected = true;
      bleConnectionId = connection;
      bleAuthenticated = false;
      ++bleSession;
      bleLength = 0;
      bleOverflow = false;
    }
    portEXIT_CRITICAL(&queueMux);
    if (reject) server->disconnect(connection);
  }
  void onDisconnect(BLEServer *server, ble_gap_conn_desc *desc) override {
    portENTER_CRITICAL(&queueMux);
    const bool active = desc->conn_handle == bleConnectionId;
    if (active) {
      bleConnected = false;
      bleConnectionId = UINT16_MAX;
      bleAuthenticated = false;
      bleTx.active = false;
      ++bleSession;
      bleLength = 0;
      bleOverflow = false;
    }
    portEXIT_CRITICAL(&queueMux);
    if (active) server->startAdvertising();
  }
#else
  void onConnect(BLEServer *) override {
    if (bleConnected) return;
    bleConnected = true;
    bleAuthenticated = false;
    ++bleSession;
  }
  void onDisconnect(BLEServer *server) override {
    bleConnected = false;
    bleAuthenticated = false;
    bleTx.active = false;
    ++bleSession;
    server->startAdvertising();
  }
#endif
};

class BleWriteCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    String value = characteristic->getValue();
    const uint32_t now = millis();
    portENTER_CRITICAL(&queueMux);
    const uint32_t session = bleSession;
    if (bleLength && timeElapsed(now, bleLastWrite, kBleTimeoutMs)) {
      bleLength = 0;
      bleOverflow = false;
    }
    bleLastWrite = now;
    for (size_t index = 0; index < value.length(); ++index) {
      const uint8_t byte = static_cast<uint8_t>(value[index]);
      if (byte == '\n') {
        const bool lineOverflow = bleOverflow;
        if (lineOverflow || bleLength == 0) {
          bleLength = 0;
          bleOverflow = false;
          portEXIT_CRITICAL(&queueMux);
          enqueueTransportError(SOURCE_BLE, 0, lineOverflow ? "request_too_large" : "empty_request", session);
          portENTER_CRITICAL(&queueMux);
          continue;
        }
        char line[kMaxRequest + 1];
        memcpy(line, bleBuffer, bleLength);
        line[bleLength] = 0;
        const uint16_t length = bleLength;
        bleLength = 0;
        bleOverflow = false;
        portEXIT_CRITICAL(&queueMux);
        if (!enqueueCommand(SOURCE_BLE, 0, reinterpret_cast<uint8_t *>(line), length, session)) {
          enqueueTransportError(SOURCE_BLE, 0, "queue_full", session);
        }
        portENTER_CRITICAL(&queueMux);
      } else if (bleLength < kMaxRequest) {
        bleBuffer[bleLength++] = static_cast<char>(byte);
      } else {
        bleOverflow = true;
      }
    }
    portEXIT_CRITICAL(&queueMux);
  }
};

void setupBle() {
  BLEDevice::init("IconShow");
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new BleServerCallbacks());
  BLEService *service = bleServer->createService("6d8f0000-6f52-4af0-9a2c-7b6143b8e100");
  bleWrite = service->createCharacteristic("6d8f0001-6f52-4af0-9a2c-7b6143b8e100", BLECharacteristic::PROPERTY_WRITE);
  bleNotify = service->createCharacteristic("6d8f0002-6f52-4af0-9a2c-7b6143b8e100", BLECharacteristic::PROPERTY_NOTIFY);
  bleWrite->setCallbacks(new BleWriteCallbacks());
  bleNotify->addDescriptor(new BLE2902());
  service->start();
  bleServer->getAdvertising()->addServiceUUID("6d8f0000-6f52-4af0-9a2c-7b6143b8e100");
  bleServer->getAdvertising()->start();
}

void webSocketEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t length) {
  if (client >= WEBSOCKETS_SERVER_CLIENT_MAX) return;
  if (type == WStype_CONNECTED) {
    ++wsSession[client];
    wsAuthenticated[client] = false;
    wsFragmentLength[client] = 0;
    wsFragmentOverflow[client] = false;
    if (!payload || strcmp(reinterpret_cast<char *>(payload), "/ws") != 0) webSocket.disconnect(client);
  } else if (type == WStype_DISCONNECTED) {
    ++wsSession[client];
    wsAuthenticated[client] = false;
    wsFragmentLength[client] = 0;
    wsFragmentOverflow[client] = false;
  } else if (type == WStype_TEXT) {
    if (length <= kMaxRequest) {
      if (!enqueueCommand(SOURCE_WS, client, payload, length)) enqueueTransportError(SOURCE_WS, client, "queue_full");
    }
    else enqueueTransportError(SOURCE_WS, client, "request_too_large");
  } else if (type == WStype_FRAGMENT_TEXT_START) {
    wsFragmentLength[client] = 0;
    wsFragmentOverflow[client] = false;
    if (length > kMaxRequest) wsFragmentOverflow[client] = true;
    else { memcpy(wsFragments[client], payload, length); wsFragmentLength[client] = length; }
  } else if (type == WStype_FRAGMENT) {
    if (wsFragmentLength[client] + length > kMaxRequest) wsFragmentOverflow[client] = true;
    else { memcpy(wsFragments[client] + wsFragmentLength[client], payload, length); wsFragmentLength[client] += length; }
  } else if (type == WStype_FRAGMENT_FIN) {
    if (wsFragmentLength[client] + length > kMaxRequest) wsFragmentOverflow[client] = true;
    else if (!wsFragmentOverflow[client] && length) {
      memcpy(wsFragments[client] + wsFragmentLength[client], payload, length);
      wsFragmentLength[client] += length;
    }
    if (wsFragmentOverflow[client]) enqueueTransportError(SOURCE_WS, client, "request_too_large");
    else if (wsFragmentLength[client]) {
      if (!enqueueCommand(SOURCE_WS, client, reinterpret_cast<uint8_t *>(wsFragments[client]), wsFragmentLength[client])) enqueueTransportError(SOURCE_WS, client, "queue_full");
    } else enqueueTransportError(SOURCE_WS, client, "empty_request");
    wsFragmentLength[client] = 0;
    wsFragmentOverflow[client] = false;
  }
}

void serialTick() {
  static char buffer[kMaxRequest + 1];
  static uint16_t length = 0;
  static bool overflow = false;
  while (Serial.available()) {
    const uint8_t byte = Serial.read();
    if (byte == '\n') {
      if (!overflow && length && !enqueueCommand(SOURCE_SERIAL, 0, reinterpret_cast<uint8_t *>(buffer), length)) enqueueTransportError(SOURCE_SERIAL, 0, "queue_full");
      else if (overflow) enqueueTransportError(SOURCE_SERIAL, 0, "request_too_large");
      length = 0;
      overflow = false;
    } else if (length < kMaxRequest) buffer[length++] = static_cast<char>(byte);
    else overflow = true;
  }
}

void bleTick(uint32_t now) {
  portENTER_CRITICAL(&queueMux);
  const bool expired = bleLength && timeElapsed(now, bleLastWrite, kBleTimeoutMs);
  if (expired) { bleLength = 0; bleOverflow = false; }
  portEXIT_CRITICAL(&queueMux);
  if (expired) enqueueTransportError(SOURCE_BLE, 0, "ble_request_timeout");
}

void dispatchResponse(Source source, uint8_t client, const char *buffer, size_t length, uint32_t session) {
  if (source == SOURCE_SERIAL) {
    Serial.write(reinterpret_cast<const uint8_t *>(buffer), length);
    Serial.write('\n');
  } else if (source == SOURCE_WS) {
    if (client < WEBSOCKETS_SERVER_CLIENT_MAX && session == wsSession[client] && webSocket.clientIsConnected(client)) webSocket.sendTXT(client, buffer, length);
  } else {
    notifyBle(buffer, length, session);
  }
}

bool onlyCommandKeys(JsonObjectConst root, const char *op) {
  static const char *const auth[] = {"id", "op", "token"};
  static const char *const show[] = {"id", "op", "icon", "animation", "color", "effect", "brightness", "duration_ms"};
  static const char *const text[] = {"id", "op", "text", "scroll", "color", "effect", "brightness", "duration_ms"};
  static const char *const value[] = {"id", "op", "value"};
  static const char *const idle[] = {"id", "op", "mode"};
  static const char *const keepalive[] = {"id", "op", "target_id"};
  static const char *const basic[] = {"id", "op"};
  static const char *const wifi[] = {"id", "op", "ssid", "password"};
  const char *const *allowed = basic;
  size_t count = sizeof(basic) / sizeof(basic[0]);
  if (!strcmp(op, "auth")) { allowed = auth; count = sizeof(auth) / sizeof(auth[0]); }
  else if (!strcmp(op, "show")) { allowed = show; count = sizeof(show) / sizeof(show[0]); }
  else if (!strcmp(op, "text")) { allowed = text; count = sizeof(text) / sizeof(text[0]); }
  else if (!strcmp(op, "brightness") || !strcmp(op, "speed")) { allowed = value; count = sizeof(value) / sizeof(value[0]); }
  else if (!strcmp(op, "idle")) { allowed = idle; count = sizeof(idle) / sizeof(idle[0]); }
  else if (!strcmp(op, "keepalive")) { allowed = keepalive; count = sizeof(keepalive) / sizeof(keepalive[0]); }
  else if (!strcmp(op, "wifi")) { allowed = wifi; count = sizeof(wifi) / sizeof(wifi[0]); }
  for (JsonPairConst pair : root) {
    bool known = false;
    for (size_t index = 0; index < count; ++index) {
      if (!strcmp(pair.key().c_str(), allowed[index])) { known = true; break; }
    }
    if (!known) return false;
  }
  return true;
}

bool hasEmbeddedNul(JsonVariantConst value) {
  if (value.is<JsonString>()) {
    const JsonString text = value.as<JsonString>();
    if (!text.isNull() && strlen(text.c_str()) != text.size()) return true;
  }
  JsonObjectConst object = value.as<JsonObjectConst>();
  if (!object.isNull()) {
    for (JsonPairConst pair : object) {
      const JsonString key = pair.key();
      if (strlen(key.c_str()) != key.size() || hasEmbeddedNul(pair.value())) return true;
    }
  }
  JsonArrayConst array = value.as<JsonArrayConst>();
  if (!array.isNull()) {
    for (JsonVariantConst item : array) if (hasEmbeddedNul(item)) return true;
  }
  return false;
}

bool hasEmbeddedNul(JsonObjectConst object) {
  for (JsonPairConst pair : object) {
    const JsonString key = pair.key();
    if (strlen(key.c_str()) != key.size() || hasEmbeddedNul(pair.value())) return true;
  }
  return false;
}

void handleRequest(const QueueItem &item, uint32_t now) {
  activeResponseSession = item.transportSession;
  JsonDocument rootDoc;
  DeserializationError parseError = deserializeJson(rootDoc, item.payload, item.length);
  if (parseError) {
    JsonDocument response;
    response["ok"] = false;
    response["error"] = "invalid_json";
    sendResponse(item.source, item.client, response);
    return;
  }
  JsonObjectConst root = rootDoc.as<JsonObjectConst>();
  if (root.isNull()) { sendError(item.source, item.client, root, "invalid_command"); return; }
  if (hasEmbeddedNul(root)) { sendError(item.source, item.client, root, "invalid_parameters"); return; }
  const char *op = root["op"].as<const char *>();
  if (!op) { sendError(item.source, item.client, root, "op_required"); return; }
  uint32_t requestId = 0;
  const char *error = nullptr;
  if (!parseIdFromRoot(root, requestId, error)) { sendError(item.source, item.client, root, error); return; }
  if (!onlyCommandKeys(root, op)) { sendError(item.source, item.client, root, "invalid_parameters"); return; }

  if (strcmp(op, "auth") == 0) {
    const char *token = root["token"].as<const char *>();
    const bool accepted = item.source == SOURCE_SERIAL || (token && secureEqual(token, controlToken.c_str()));
    if (!accepted) {
      if (item.source == SOURCE_WS && item.client < WEBSOCKETS_SERVER_CLIENT_MAX && item.transportSession == wsSession[item.client]) wsAuthenticated[item.client] = false;
      if (item.source == SOURCE_BLE && !setBleAuthentication(item.transportSession, false)) return;
      sendError(item.source, item.client, root, "unauthorized");
      return;
    }
    if (item.source == SOURCE_WS) {
      if (item.client >= WEBSOCKETS_SERVER_CLIENT_MAX || item.transportSession != wsSession[item.client]) return;
      wsAuthenticated[item.client] = true;
    }
    if (item.source == SOURCE_BLE && !setBleAuthentication(item.transportSession, true)) return;
    sendOk(item.source, item.client, root);
    return;
  }
  if (!ensureAuth(item, root)) { sendError(item.source, item.client, root, "unauthorized"); return; }

  if (strcmp(op, "get") == 0 || strcmp(op, "status") == 0) {
    JsonDocument response;
    copyResponseId(response, root);
    response["ok"] = true;
    addState(response, now);
    response["ap"] = apRunning;
    response["ap_name"] = apName;
    response["ble_connected"] = bleConnected;
    response["wifi_candidate_status"] = candidateStatus;
    sendResponse(item.source, item.client, response);
    return;
  }
  if (strcmp(op, "off") == 0) {
    enterIdle(now, IDLE_OFF);
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "idle") == 0) {
    const char *mode = "off";
    if (root.containsKey("mode")) {
      mode = root["mode"].as<const char *>();
      if (!mode) { sendError(item.source, item.client, root, "invalid_idle_mode"); return; }
    }
    if (strcmp(mode, "off") != 0 && strcmp(mode, "pet") != 0) { sendError(item.source, item.client, root, "invalid_idle_mode"); return; }
    idleMode = strcmp(mode, "pet") == 0 ? IDLE_PET : IDLE_OFF;
    if (!isActive()) {
      state.mode = MODE_IDLE;
      resetPhase(now);
      state.virtualStarted = 0;
      frameDirty = true;
    }
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "release") == 0) {
    enterIdle(now, idleMode);
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "speed") == 0) {
    if (!root["value"].is<float>()) { sendError(item.source, item.client, root, "invalid_speed"); return; }
    const float next = root["value"].as<float>();
    if (!(next >= 0.25f && next <= 4.0f) || !speedSupports(state, next)) { sendError(item.source, item.client, root, "invalid_speed"); return; }
    setSpeed(next, now);
    frameDirty = true;
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "pause") == 0 || strcmp(op, "resume") == 0) {
    const bool shouldPause = strcmp(op, "pause") == 0;
    if (shouldPause != paused) {
      const uint32_t current = virtualNow(now);
      phaseVirtualOrigin = current;
      phaseRealOrigin = now;
      paused = shouldPause;
    }
    frameDirty = true;
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "brightness") == 0) {
    uint8_t value = 0;
    if (!parseByte(root["value"], value)) { sendError(item.source, item.client, root, "invalid_brightness"); return; }
    state.brightness = value;
    frameDirty = true;
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "keepalive") == 0) {
    uint32_t target = 0;
    if (!parseId(root["target_id"], target)) { sendError(item.source, item.client, root, "invalid_target_id"); return; }
    if (!isActive() || state.id != target || state.ttlMs == 0) { sendError(item.source, item.client, root, "target_not_active"); return; }
    state.deadline = now + state.ttlMs;
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "show") == 0 || strcmp(op, "text") == 0) {
    RenderState next;
    if (strcmp(op, "show") == 0) {
      if (!parseShow(root, next, error)) { sendError(item.source, item.client, root, error); return; }
    } else if (!parseText(root, next, error)) {
      sendError(item.source, item.client, root, error);
      return;
    }
    if (!speedSupports(next, speed)) { sendError(item.source, item.client, root, "speed_period_too_short"); return; }
    next.id = requestId;
    applyRenderState(next, now);
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "provision") == 0) {
    startAp();
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "wifi") == 0) {
    if (item.source != SOURCE_SERIAL) { sendError(item.source, item.client, root, "serial_only"); return; }
    const char *ssid = root["ssid"].as<const char *>();
    const char *password = root["password"].as<const char *>();
    if (!ssid || !password || strlen(ssid) == 0 || strlen(ssid) > 32 || strlen(password) > 63) { sendError(item.source, item.client, root, "invalid_wifi"); return; }
    startCandidate(String(ssid), String(password));
    sendOk(item.source, item.client, root);
    return;
  }
  if (strcmp(op, "secrets") == 0) {
    if (item.source != SOURCE_SERIAL) { sendError(item.source, item.client, root, "serial_only"); return; }
    JsonDocument response;
    copyResponseId(response, root);
    response["ok"] = true;
    response["ap_name"] = apName;
    response["setup_password"] = setupPassword;
    response["control_token"] = controlToken;
    response["wifi_ssid"] = wifiSsid;
    sendResponse(item.source, item.client, response);
    return;
  }
  sendError(item.source, item.client, root, "unknown_op");
}

void loadSecrets() {
  preferences.begin("iconshow", false);
  controlToken = preferences.getString("token", "");
  setupPassword = preferences.getString("ap_pass", "");
  if (!controlToken.length()) { controlToken = randomHex(16); preferences.putString("token", controlToken); }
  if (!setupPassword.length()) { setupPassword = randomHex(10); preferences.putString("ap_pass", setupPassword); }
}

void firmwareSetup() {
  Serial.begin(115200);
  pixels.begin();
  pixels.clear();
  pixels.show();
  state = RenderState();
  state.mode = MODE_IDLE;
  state.brightness = kDefaultBrightness;
  resetPhase(millis());
  loadSecrets();
  initWifi();
  setupHttp();
  setupBle();
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
}

void firmwareLoop() {
  const uint32_t now = millis();
  webSocket.loop();
  http.handleClient();
  serialTick();
  bleTick(now);
  bleNotifyTick();
  wifiTick(now);
  expireState(millis());
  QueueItem item;
  if (!bleTx.active && dequeueCommand(item)) {
    const bool staleBle = item.source == SOURCE_BLE && item.transportSession != bleSession;
    const bool staleWs = item.source == SOURCE_WS && item.client < WEBSOCKETS_SERVER_CLIENT_MAX && item.transportSession != wsSession[item.client];
    if (!staleBle && !staleWs) {
      if (item.directResponse) dispatchResponse(item.source, item.client, item.payload, item.length, item.transportSession);
      else {
        const uint32_t requestNow = millis();
        expireState(requestNow);
        handleRequest(item, requestNow);
      }
    }
  }
  render(millis());
  delay(1);
}

}  // namespace

void setup() { firmwareSetup(); }
void loop() { firmwareLoop(); }
