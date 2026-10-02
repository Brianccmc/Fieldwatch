# Farm architecture (summary)

House Pi hub on LAN: Mosquitto (auth) + `fieldwatch-hub` (MQTT subscriber, XIAO serial NDJSON, demo/sim, SQLite ingest, FastAPI HUD).

Edge: ESP32-S3 listen stations + SX126x backhaul speaking `observation.schema.json` NDJSON — **not** Meshtastic as the farm protocol.

Legal/physics/coverage details stay in private notes; this tree holds schemas, hub code, and firmware scaffold only.
