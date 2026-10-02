# Deploy farm hub on the house Pi

LAN-only. No public MQTT. Work only under `farm/`.

## Layout on Pi
- Code: `/home/brian/fieldwatch/farm/`
- Venv: `/home/brian/fieldwatch/venv/`
- SQLite: `/home/brian/fieldwatch/data/farm.sqlite` (or `/var/lib/fieldwatch` if writable)
- Allowlist (off-git): `/home/brian/fieldwatch/allowlist.json`
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
systemctl is-active fieldwatch-hub mosquitto
# HUD
open http://192.168.4.24:8080/
```

XIAO on `/dev/ttyACM0` (symlink `/dev/ttyXIAO`) may still spout Meshtastic noise — hub skips non-JSON until farm firmware NDJSON.
