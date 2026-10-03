# Farm perimeter layer

Fieldwatch (the Android app in this repo) is a receive-only observer: Wi-Fi access-point beacons and Bluetooth LE advertisements, signatures, filters, logs, and an optional TAK/CoT UDP feed. It has no backend and no station protocol.

This directory is the farm adaptation: persistent, solar listening stations on a ~119-acre Ozarks property, a house hub, phone alerts, and a topographic overlay. It does **not** replace the Android app. It sits beside it.

| Piece | Role |
|---|---|
| `app/` (Fieldwatch) | Handheld survey tool + house-hub observer + signature library + TAK feed into ATAK |
| `farm/docs/` | Architecture + deploy notes |
| `farm/schema/` | Shared observation JSON that stations and the hub speak |
| `farm/stations.example.json` | Station registry the map and hub load |
| `farm/firmware/` | ESP32-S3+SX126x scaffold → NDJSON (NOT Meshtastic) |
| `farm/catalog/` | Fieldwatch 1.1.16 catalog 88 subset (RID, DULT, Find Hub, Flock, drones, tags) |
| `farm/hub/` | Long-running hub: MQTT + serial + demo/sim → `ingest_one` + green-phosphor topo HUD (offline GeoJSON parcel map, risk, patterns) |
| `farm/systemd/` | `fieldwatch-hub.service` |
| `farm/mosquitto/` | LAN Mosquitto example (passwd path documented, secret off-git) |

## Hub quick start (Pi)
See `docs/DEPLOY.md`. Demo/sim is **DEFAULT ON** so the HUD is never empty before nodes arrive.

```bash
cd /home/brian/fieldwatch/farm/hub
../venv/bin/python  # use /home/brian/fieldwatch/venv
# or systemctl enable --now fieldwatch-hub
curl http://127.0.0.1:8080/health
```

HUD binds `0.0.0.0:8080` for mobile browsers on LAN.

Do not commit parcel coordinates, family-device MAC allowlists, live observation logs, or MQTT passwords.

Halo collar v1 is a known pet tracker (`halo_collar`): BLE MAC / service UUID on the off-git allowlist, plus a built-in `Halo collar` name signature. No Halo cloud or account API. See `docs/DEPLOY.md`.


## Topo HUD (offline)

The LAN HUD renders a **green-on-black topographic overlay** of the Willow Springs tract from shipped static GeoJSON (`farm/hub/static/map/parcel.geojson`) — no public tile APIs at runtime. Contacts show device type, risk score/reasons, signal vectors (bearing/RSSI), and activity patterns from SQLite history. Approx public-geocode geometry is for HUD demo; precise survey parcels stay off-git under `farm/private/`.

## New-MAC geofence and activity heatmap

Unknown devices (not allowlisted, not trusted farm types such as `halo_collar`, `trail_cam`, `known_farm_node`) record **one SQLite event per MAC per America/Chicago calendar night** in `new_mac_events` (`mac`, `first_seen`, `device_type`, `lat`, `lon`, `night_key`). Suspicious types and `unknown_ble` count. The HUD lists them under **NEW TONIGHT** and does not add them to the rogue-map cap of 3.

`GET /api/heatmap` returns offline dwell/revisit bins. The canvas control **Heatmap: OFF** / **Heatmap: ON** paints them; default is OFF so the sparse rogue map stays the default.

## Quiet hours

Default **OFF**. The live flag is Pi-local JSON (`/home/brian/fieldwatch/quiet-hours.json`, env `FIELDWATCH_QUIET_HOURS`), next to `allowlist.json`, and is not in git. The HUD toggle reads and writes it (`GET`/`POST /api/quiet-hours`) and is labeled **Quiet hours: OFF** or **Quiet hours: ON**.

When armed, unknown contacts that would otherwise stay low or medium (`risk_level` low or watch) become eligible for the suspicious list. Unknown means not trusted farm gear (`halo_collar`, `trail_cam`, `flock_camera`, `known_farm_node`, `allowlisted`, `tracker_near`, `heartbeat`). Trusted gear stays hidden unless Farm gear is ON and is never reclassified as a rogue. The map cap stays **3** (highest `risk_score`, then recency). One `quiet_hours_log` row per MAC per America/Chicago night records the bump (`mac`, `night_key`, `heard_at`, `device_type`, `risk_score`, `risk_level`, `lat`, `lon`, `station_id`, `name`).
