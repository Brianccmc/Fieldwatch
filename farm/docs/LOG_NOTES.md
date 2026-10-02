# Log notes

- Hub logs to journald via systemd: `journalctl -u fieldwatch-hub -f`
- Mosquitto: `/var/log/mosquitto/mosquitto.log`
- Do not commit live observation logs or journal exports with MACs/coords.
- SQLite hears table is local operational data — keep under `/home/brian/fieldwatch/data/` (gitignored).
