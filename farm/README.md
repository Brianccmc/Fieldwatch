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


## Topo HUD (offline)

The LAN HUD renders a **green-on-black topographic overlay** of the Willow Springs tract from shipped static GeoJSON (`farm/hub/static/map/parcel.geojson`) — no public tile APIs at runtime. Contacts show device type, risk score/reasons, signal vectors (bearing/RSSI), and activity patterns from SQLite history. Approx public-geocode geometry is for HUD demo; precise survey parcels stay off-git under `farm/private/`.
