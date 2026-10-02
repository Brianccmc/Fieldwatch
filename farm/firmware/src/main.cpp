// Fieldwatch farm station scaffold — ESP32-S3 (+ SX126x later)
// Emits NDJSON observations over USB serial (NOT Meshtastic).
// Replace stubs with Wi-Fi/BLE listen + LoRa backhaul when hardware arrives.

#include <Arduino.h>

#ifndef STATION_ID
#define STATION_ID "xiao-lab"
#endif

static uint32_t last_hb_ms = 0;

static void emit_heartbeat() {
  // ISO-ish UTC not critical for fixture; hub demo uses proper timestamps.
  Serial.printf(
      "{\"v\":1,\"station_id\":\"%s\",\"heard_at\":\"1970-01-01T00:00:00Z\","
      "\"radio\":\"heartbeat\",\"rssi\":0,\"station_vbat_mv\":4000,\"name\":\"fw-scaffold\"}\n",
      STATION_ID);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("{\"v\":1,\"station_id\":\"" STATION_ID "\",\"heard_at\":\"1970-01-01T00:00:00Z\",\"radio\":\"heartbeat\",\"rssi\":0,\"name\":\"boot\"}");
}

void loop() {
  uint32_t now = millis();
  if (now - last_hb_ms > 15000) {
    last_hb_ms = now;
    emit_heartbeat();
  }
  // Future: scan Wi-Fi/BLE, pack observation.schema.json, send Serial + LoRa.
}
