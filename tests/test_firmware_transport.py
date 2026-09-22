#!/usr/bin/env python3
"""Host-check the real Wi-Fi fallback and BLE-session helpers from the sketch."""
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "firmware/IconShow/IconShow.ino").read_text()


def block(signature):
    start = SOURCE.index(signature)
    brace = SOURCE.index("{", start)
    depth = 0
    for index in range(brace, len(SOURCE)):
        if SOURCE[index] == "{":
            depth += 1
        elif SOURCE[index] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start:index + 1]
    raise AssertionError(signature)


def main():
    assert SOURCE.index("#define WEBSOCKETS_SERVER_CLIENT_MAX") < SOURCE.index("#include <WebSocketsServer.h>")
    assert SOURCE.count("!enqueueCommand(") == 4
    assert "afterNext == queueTail" in SOURCE
    cpp = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
using std::size_t;
struct String {
  std::string value;
  String() = default; String(const char *v) : value(v ? v : "") {}
  size_t length() const { return value.size(); } const char *c_str() const { return value.c_str(); }
  String &operator=(const char *v) { value = v ? v : ""; return *this; }
  bool operator==(const String &other) const { return value == other.value; }
};
struct IPAddress { int value; IPAddress(int a=0,int b=0,int c=0,int d=0) : value(a|b|c|d) {} bool operator!=(const IPAddress &o) const { return value != o.value; } };
enum { WL_CONNECTED = 3, WIFI_STA = 1, WIFI_AP_STA = 2 };
struct WiFiStub {
  int statusValue = 0, apStarts = 0, beginCalls = 0; String ssid;
  int status() const { return statusValue; } IPAddress localIP() const { return IPAddress(statusValue == WL_CONNECTED); }
  String SSID() const { return ssid; } void disconnect(bool,bool) {} void mode(int) {} void begin(const char *s,const char*) { ++beginCalls; ssid = s; }
  void softAP(const char*,const char*) { ++apStarts; }
} WiFi;
struct Slot { Slot &operator=(const String &) { return *this; } };
struct JsonDocument { Slot operator[](const char*) { return {}; } };
void serializeJson(JsonDocument &, String &out) { out = "{}"; }
struct Preferences { size_t putString(const char*, const String &s) { return s.length(); } } preferences;
constexpr uint32_t kWifiAttemptMs = 30000, kApGraceMs = 15000;
String wifiSsid, wifiPassword, candidateSsid, candidatePassword, previousSsid, previousPassword, activeAttemptSsid, candidateStatus, apName("ap"), setupPassword("pass");
bool apRunning = false, wifiAttempting = false, candidateAttempt = false, apClosePending = false;
uint32_t wifiDeadline = 0, savedRetryAt = 0, disconnectedAt = 0, apCloseAt = 0;
int scanState = -2;
uint32_t millis() { return 0; }
''' + block("bool timeReached(") + "\n" + block("bool timeElapsed(") + r'''
void startAp() { WiFi.mode(WIFI_AP_STA); WiFi.softAP(apName.c_str(), setupPassword.c_str()); apRunning = true; apClosePending = false; scanState = -2; }
void stopAp() { apRunning = false; }
enum Source : uint8_t { SOURCE_SERIAL, SOURCE_WS, SOURCE_BLE };
constexpr uint8_t WEBSOCKETS_SERVER_CLIENT_MAX = 4;
struct QueueItem { Source source; uint8_t client; uint32_t transportSession; };
struct JsonObjectConst {};
bool wsAuthenticated[4] = {}; uint32_t wsSession[4] = {}; bool bleConnected = false, bleAuthenticated = false; uint32_t bleSession = 0;
int queueMux;
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
''' + block("bool ensureAuth(") + "\n" + block("bool setBleAuthentication(") + "\n" + block("void wifiTick(") + r'''
int main() {
  wifiSsid = "saved"; wifiPassword = "pw"; WiFi.statusValue = WL_CONNECTED; WiFi.ssid = "saved";
  wifiTick(31000); assert(WiFi.apStarts == 0);
  WiFi.statusValue = 0; apRunning = false; wifiAttempting = false; disconnectedAt = 100; savedRetryAt = 999999;
  wifiTick(30099); assert(WiFi.apStarts == 0);
  wifiTick(30100); assert(WiFi.apStarts == 1);
  bleConnected = true; bleSession = 7; bleAuthenticated = false;
  assert(!setBleAuthentication(6, true)); assert(!bleAuthenticated);
  assert(setBleAuthentication(7, true));
  QueueItem old{SOURCE_BLE, 0, 6}, current{SOURCE_BLE, 0, 7}; JsonObjectConst root;
  assert(!ensureAuth(old, root)); assert(ensureAuth(current, root));
}
'''
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "transport.cpp"
        binary = Path(directory) / "transport"
        path.write_text(cpp)
        subprocess.run(["c++", "-std=c++17", str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS firmware transport helpers: client limit, queue backpressure, online AP guard, offline fallback, BLE session isolation")


if __name__ == "__main__":
    main()
