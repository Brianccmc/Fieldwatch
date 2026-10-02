# Log notes

- Hub logs to journald via systemd: `journalctl -u fieldwatch-hub -f`
- Mosquitto: `/var/log/mosquitto/mosquitto.log`
- Do not commit live observation logs or journal exports with MACs/coords.
- SQLite hears table is local operational data — keep under `/home/brian/fieldwatch/data/` (gitignored).

## HUD declutter pass 2 (2026-10-02)
- Default: no hub→contact vector spokes; toggle `Vectors: OFF/ON` on map.
- Default markers: small risk-colored dots; short labels only for ALWAYS_SHOW device types + high/critical risk, with simple de-overlap.
- BLE noise clustering + BLE noise toggle unchanged.
