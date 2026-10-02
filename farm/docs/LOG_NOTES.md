# Log notes

- Hub logs to journald via systemd: `journalctl -u fieldwatch-hub -f`
- Mosquitto: `/var/log/mosquitto/mosquitto.log`
- Do not commit live observation logs or journal exports with MACs/coords.
- SQLite hears table is local operational data — keep under `/home/brian/fieldwatch/data/` (gitignored).

## HUD declutter pass 2 (2026-10-02)
- Default: no hub→contact vector spokes; toggle `Vectors: OFF/ON` on map.
- Default markers: small risk-colored dots; short labels only for ALWAYS_SHOW device types + high/critical risk, with simple de-overlap.
- BLE noise clustering + BLE noise toggle unchanged.

## HUD suspicious-only pass 3 (2026-10-02)
- Default map: trusted farm gear hidden (trail_cam, flock_camera, known_farm_node, allowlisted, tracker_near, heartbeat).
- Visible: rogue_ap, remote_id_drone, rid_emergency, unknown_phone, visitor_wifi, tracker_separated, plus high/critical/elevated unknowns (never trusted types).
- Map marker hard cap = 3 (risk_score then recency); overflow as "+N more" badge + panel list.
- Toggle `Farm gear: OFF/ON` to reveal trusted gear; vectors + BLE noise toggles unchanged.
- Demo cast slimmed to suspicious-only (phone, rogue AP, separated tracker, RID); seed ≤3.
- Filter is presentation-only — API still returns device_type / risk_score for all contacts.
