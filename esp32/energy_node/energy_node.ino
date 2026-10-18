/*
  Smart Campus Energy Saver - ESP32 node
  Reads AC current (ACS712), estimates power, posts it to the server every 2 s,
  and switches the relay according to the server's reply.

  Wiring (ESP32 DevKit):
    ACS712 OUT -> voltage divider -> GPIO34   (ACS712 outputs up to 5 V, ESP32 pin tolerates 3.3 V!)
                  use 10k (top, from OUT) + 20k (bottom, to GND): the pin sees 2/3 of OUT
    ACS712 VCC -> 5 V (VIN),  GND -> GND
    Relay IN   -> GPIO26,     relay VCC -> 5 V,  GND -> GND
    Load (bulb/fan) wire goes through ACS712 and the relay's COM / NO terminals.

  SAFETY: mains voltage can kill. For demos use a single bulb in an insulated, enclosed box
  or a ready-made relay extension board, keep all mains joints covered, and have a senior
  or lab technician check the wiring before you plug it in.

  Library needed: none beyond the ESP32 board package (WiFi, HTTPClient).
*/
#include <WiFi.h>
#include <HTTPClient.h>

// ---- EDIT THESE -------------------------------------------------------------
const char* WIFI_SSID   = "YOUR_WIFI";
const char* WIFI_PASS   = "YOUR_PASSWORD";
const char* SERVER_URL  = "http://192.168.1.10:8000/api/telemetry";   // your laptop's IP
const char* ROOM_ID     = "LAB-101";
const char* ROOM_NAME   = "Lab 101";

const int   CURRENT_PIN = 34;
const int   RELAY_PIN   = 26;
const bool  RELAY_ACTIVE_LOW = true;       // most cheap relay boards switch ON when the pin is LOW

const float MAINS_VOLTS   = 230.0;
const float POWER_FACTOR  = 0.9;           // rough value for fans/lights; use a PZEM for exact watts
const float SENSITIVITY   = 0.100;         // ACS712-20A = 100 mV/A (5A: 185, 30A: 66 mV/A -> 0.185 / 0.066)
const float DIVIDER_RATIO = 2.0 / 3.0;     // 20k / (10k + 20k)
// ------------------------------------------------------------------------------

bool relayOn = true;

void setRelay(bool on) {
  relayOn = on;
  digitalWrite(RELAY_PIN, (on ^ RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

// RMS current over ~10 mains cycles (200 ms at 50 Hz)
float readCurrentRms() {
  const int N = 1000;
  static float buf[N];
  double sum = 0;
  for (int i = 0; i < N; i++) {
    unsigned long t = micros();
    buf[i] = analogReadMilliVolts(CURRENT_PIN) / 1000.0;
    sum += buf[i];
    while (micros() - t < 200) {}          // 200 us per sample -> 1000 samples = 200 ms
  }
  float mean = sum / N;                    // DC offset (about half of the supply)
  double sq = 0;
  for (int i = 0; i < N; i++) sq += (buf[i] - mean) * (buf[i] - mean);
  float vrms = sqrt(sq / N) / DIVIDER_RATIO;   // undo the divider
  float irms = vrms / SENSITIVITY;
  return irms < 0.05 ? 0.0 : irms;         // ignore sensor noise
}

void connectWifi() {
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println("\nConnected: " + WiFi.localIP().toString());
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(CURRENT_PIN, ADC_11db);
  setRelay(true);
  connectWifi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();

  float amps  = readCurrentRms();
  float watts = amps * MAINS_VOLTS * POWER_FACTOR;
  Serial.printf("I = %.2f A  P = %.0f W  relay=%s\n", amps, watts, relayOn ? "ON" : "OFF");

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  String body = String("{\"room_id\":\"") + ROOM_ID + "\",\"name\":\"" + ROOM_NAME +
                "\",\"watts\":" + String(watts, 1) + "}";
  int code = http.POST(body);
  if (code == 200) {
    String reply = http.getString();                 // {"relay":true}
    bool want = reply.indexOf("\"relay\":true") >= 0;
    if (want != relayOn) {
      setRelay(want);
      Serial.println(want ? "Relay -> ON" : "Relay -> OFF (room empty)");
    }
  } else {
    Serial.printf("POST failed: %d (relay stays as is)\n", code);
  }
  http.end();
  delay(1800);
}
