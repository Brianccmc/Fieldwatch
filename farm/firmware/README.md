# ESP32-S3 + SX126x farm firmware (scaffold)

Target: Seeed XIAO ESP32-S3 (or equivalent) + SX126x LoRa for backhaul — **farm NDJSON protocol**, not Meshtastic.

## Status
Scaffold only. Hub is ready; antenna whip is not on the roof; nodes not deployed yet.
Flash when hardware arrives. Until then, hub **demo/sim** keeps the HUD fed.

## Layout
- `src/main.cpp` — stub that emits fixture NDJSON over USB serial
- `fixtures/example.ndjson` — lines the hub accepts
- `PROTOCOL.md` — wire format

## Build notes (PlatformIO sketch)
Board: `esp32-s3-devkitc-1` or XIAO ESP32S3. Libraries TBD for Wi-Fi scan / BLE / SX126x.
Do not enable public MQTT. LAN MQTT only when Wi-Fi AP/SSID is local.
