# Farm station → hub protocol (NOT Meshtastic)

Stations and a future LoRa gateway send **one JSON object per line** (serial) or one JSON payload (MQTT). The hub ingests both shapes into the same SQLite `hears` path and HUD contacts as any other station hear.

Meshtastic text and Meshtastic JSON (`from` / `payload` / `type` such as `nodeinfo`, with no `station_id` or `node_id`) are **ignored**. They increment serial `junk_skipped` and are not contacts.

## Transport
1. **Serial USB** (XIAO on hub): `/dev/ttyACM0` or `/dev/ttyXIAO` @ 115200 8N1 — one JSON object per line.
2. **MQTT LAN** (preferred for a solar node or a gateway that bridges SX126x): the hub subscribes to `fieldwatch/station/#` (env `FIELDWATCH_MQTT_TOPIC`). Publish to `fieldwatch/station/<station_id>/obs`. Payload is the same JSON. No public broker.

Unrecognized MQTT JSON is not ingested.

## 1. Observation (what the listener already accepts)
Schema: `farm/schema/observation.schema.json`. Required on the wire for this shape: `station_id` and `radio` (plus the schema's `v`, `heard_at`, `rssi` when the station sends a full object).

```json
{"v":1,"station_id":"gate-n","heard_at":"2026-10-02T16:00:00Z","radio":"wifi_ap","rssi":-67,"mac":"AA:BB:CC:DD:EE:FF","name":"Cam7"}
```

`radio` is `wifi_ap`, `wifi_mgmt`, `ble_adv`, `remote_id`, or `heartbeat`. A real object of this shape is a contact (heartbeats are stored but are not HUD contacts and do not page).

### Heartbeat
```json
{"v":1,"station_id":"gate-n","heard_at":"2026-10-02T16:00:00Z","radio":"heartbeat","rssi":0,"station_vbat_mv":3900,"station_solar_mv":5100}
```

## 2. Gateway farm packet (plug in a later radio)
Use this when the gateway has a node id, a fix **or** a bearing, battery, and an event — and may not fill the whole observation schema. The hub normalizes it before `ingest_one`.

Topic: `fieldwatch/station/<node_id>/obs` (same subscription).

```json
{"node_id":"gate-n","heard_at":"2026-10-02T16:05:00Z","lat":37.046,"lon":-91.951,"battery":3900,"event":"position"}
```

```json
{"node_id":"ridge-2","event":"contact","bearing":210,"battery":3700,"mac":"AA:BB:CC:DD:EE:10","rssi":-74,"radio":"ble_adv","name":"GateTag"}
```

| Field | Aliases | Meaning |
|---|---|---|
| `node_id` | `node`, `nodeId` | Station / radio id. Becomes `station_id`. |
| `lat`,`lon` | `latitude`,`longitude`,`payload_lat`,`payload_lon` | Heard fix. Both required. Preferred over bearing. |
| `bearing` | `bearing_deg` | Degrees clockwise from north **from that node** when lat/lon are absent. Hub places the contact 180 m along that bearing so the HUD can plot it, and keeps `reported_bearing_deg`. |
| `battery` | `battery_mv`, `vbat`, `vbat_mv`, `station_vbat_mv` | Integer millivolts. |
| `event` | `evt` | `contact` (default), `position` / `telemetry` / `node` / `beacon`, or `heartbeat`. |
| `mac` | | Heard device. Omit for a node-only report. |
| `radio` | | Optional. `ble_adv`, `wifi_ap`, `wifi_mgmt`, `remote_id`, `heartbeat`, or `lora` (default when omitted and this is not a heartbeat). |
| `rssi`,`name`,`heard_at` | | Optional. Missing `heard_at` is filled with UTC now. |

Node-only events (`position`, `telemetry`, `beacon`, …) with no `mac` are `device_type=known_farm_node` (trusted: hidden unless Farm gear is ON, not a phone page). A packet with `mac` is a real contact and is classified like any other hear. `event=heartbeat` is a heartbeat, not a contact.

No parcel coordinates, family MACs, or live logs in firmware defaults committed to git.
