# Deploy farm hub on the house Pi

LAN-only. No public MQTT. Work only under `farm/`.

## Layout on Pi
- Code: `/home/brian/fieldwatch/farm/`
- Venv: `/home/brian/fieldwatch/venv/`
- SQLite: `/home/brian/fieldwatch/data/farm.sqlite` (or `/var/lib/fieldwatch` if writable)
- Allowlist (off-git): `/home/brian/fieldwatch/allowlist.json`
- Quiet hours flag (off-git, default OFF): `/home/brian/fieldwatch/quiet-hours.json`
- MQTT password env (off-git): `/home/brian/fieldwatch/mqtt.passwd.env`
- Mosquitto passwd (off-git): `/etc/mosquitto/fieldwatch.passwd`

## Install
```bash
# from a machine with the tree, or git pull on Pi
rsync -a --delete --exclude 'catalog/fieldwatch-signatures-farm.json' farm/ brian@192.168.0.24:/home/brian/fieldwatch/farm/
# Prefer mgmt IP 192.168.0.24 for SSH if VLAN .4 is unreachable from the iMac.
# Catalog JSON is Pi-local (fetched by install_hub.sh); exclude it from --delete.
ssh brian@192.168.4.24 'bash /home/brian/fieldwatch/farm/scripts/install_hub.sh'
```

`install_hub.sh` creates venv deps, MQTT hub user, empty allowlist, enables `fieldwatch-hub.service`.

## Verify
```bash
curl -s http://192.168.4.24:8080/health
curl -s http://192.168.4.24:8080/api/new-macs
curl -s http://192.168.4.24:8080/api/heatmap
systemctl is-active fieldwatch-hub mosquitto
# HUD
open http://192.168.4.24:8080/
```

XIAO on `/dev/ttyACM0` (symlink `/dev/ttyXIAO`) may still spout Meshtastic noise — hub skips non-JSON until farm firmware NDJSON.

## Halo collar allowlist (off-git)

Live file: `/home/brian/fieldwatch/allowlist.json`. Do not commit it. No Halo cloud, account API, or GPS fetch — v1 is the BLE identity once observed.

Placeholder shape (not a real collar) lives in `farm/hub/allowlist.example.json`. A collar entry:

```json
{
  "mac": "A1:10:C0:11:00:01",
  "service_uuid": "A110C011-0000-4000-8000-000000000001",
  "device_type": "halo_collar",
  "label": "example — replace"
}
```

Fields:

- `mac` — observed BLE MAC (`AA:BB:...` or dashes; case-insensitive).
- `service_uuid` — observed BLE service UUID (128-bit or short). `uuid` is an alias.
- `device_type` — must be `halo_collar`. Without it, a MAC is an ordinary allowlisted radio, not a collar.
- `label` — optional local note.

Either `mac` or `service_uuid` is enough. Unmatched random BLE is not classified as Halo. A built-in quiet signature also matches BLE advertisements whose name contains `Halo collar` (not a bare `Halo`).

## Quiet hours

Flag file (not in git): `/home/brian/fieldwatch/quiet-hours.json` as `{"enabled": false}`. Missing file is OFF. Restart keeps the file.

```bash
curl -s http://192.168.0.24:8080/api/quiet-hours
curl -s -X POST http://192.168.0.24:8080/api/quiet-hours -H 'Content-Type: application/json' -d '{"enabled":true}'
curl -s http://192.168.0.24:8080/api/quiet-hours/log
```

HUD control label is exactly `Quiet hours: OFF` / `Quiet hours: ON`. rsync `farm/` with `--exclude quiet-hours.json` so a local copy cannot be deleted or published.

## Farm packets

See `firmware/PROTOCOL.md`. Serial and MQTT both accept observation JSON and the gateway packet (`node_id`, lat/lon or bearing, battery mV, event). Restart the hub after deploy; do not flash the XIAO from this tree unless a safe flash path is already in use.

## Phone alerts

The unit does **not** set `FIELDWATCH_NTFY_URL`. Missing or blank means the hub sends no ntfy POST and does not pick a public topic. Dedup tables are created in the farm SQLite on first hear. Alerts are critical risk transitions and one new-MAC per America/Chicago night. Trusted farm types and demo rows do not page.

