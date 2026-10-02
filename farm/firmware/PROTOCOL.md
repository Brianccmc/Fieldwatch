# Farm station → hub protocol (NOT Meshtastic)

Stations send **one NDJSON object per line** matching `farm/schema/observation.schema.json`.

## Transport
1. **Serial USB** (XIAO on hub): `/dev/ttyACM0` or `/dev/ttyXIAO` @ 115200 8N1 — NDJSON lines.
2. **MQTT LAN** (preferred for solar nodes via SX126x bridge or Wi-Fi hop): topic `fieldwatch/station/<station_id>/obs` — JSON payload (same schema).

Meshtastic frames/noise on the serial port are **ignored** by the hub until a valid farm observation JSON appears.

## Minimal observation
```json
{"v":1,"station_id":"gate-n","heard_at":"2026-10-02T16:00:00Z","radio":"wifi_ap","rssi":-67,"mac":"AA:BB:CC:DD:EE:FF","name":"Cam7"}
```

## Heartbeat
```json
{"v":1,"station_id":"gate-n","heard_at":"2026-10-02T16:00:00Z","radio":"heartbeat","rssi":0,"station_vbat_mv":3900,"station_solar_mv":5100}
```

No parcel coordinates, family MACs, or live logs in firmware defaults committed to git.
