# Farm perimeter layer

Fieldwatch (the Android app in this repo) is a receive-only observer: Wi-Fi access-point beacons and Bluetooth LE advertisements, signatures, filters, logs, and an optional TAK/CoT UDP feed. It has no backend and no station protocol.

This directory is the farm adaptation: persistent, solar listening stations on a ~119-acre Ozarks property, a house hub, phone alerts, and a topographic overlay. It does **not** replace the Android app. It sits beside it.

| Piece | Role |
|---|---|
| `app/` (Fieldwatch) | Handheld survey tool + house-hub observer + signature library + TAK feed into ATAK |
| `farm/docs/ARCHITECTURE.md` | Physics, coverage, hardware, legal bounds, phased build |
| `farm/schema/` | Shared observation JSON that stations and the hub speak |
| `farm/stations.example.json` | Station registry the map and hub load |
| `farm/firmware/` | ESP32-S3 edge firmware notes (listen → compact report) |
| `farm/catalog/` | Fieldwatch 1.1.16 catalog 88 subset (RID, DULT, Find Hub, Flock, drones, tags) |
| `farm/hub/ingest.py` | Classify + SQLite + ntfy policy from 1.1.15/1.1.16 |

Start with `farm/docs/ARCHITECTURE.md`. Do not commit parcel coordinates, family-device MAC allowlists, or live observation logs to a public remote.
