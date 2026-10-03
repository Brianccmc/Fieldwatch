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
- Default map: trusted farm gear hidden (trail_cam, flock_camera, known_farm_node, allowlisted, tracker_near, heartbeat, halo_collar).
- Visible: rogue_ap, remote_id_drone, rid_emergency, unknown_phone, visitor_wifi, tracker_separated; unknown_ble only if critical; other non-trusted unknowns if elevated/high/critical.
- Map marker hard cap = 3 (risk_score then recency); overflow as "+N more" badge + panel list.
- Toggle `Farm gear: OFF/ON` to reveal trusted gear; vectors + BLE noise toggles unchanged.
- Demo cast slimmed to suspicious-only (phone, rogue AP, separated tracker, RID); seed ≤3.
- Filter is presentation-only — API still returns device_type / risk_score for all contacts.

## Halo collar known pet (2026-10-02)
- `device_type=halo_collar` for a BLE MAC or `service_uuid` on an allowlist entry with `device_type: halo_collar`, or the built-in name signature `Halo collar`.
- `risk_level` low when matched. Not in `SUSPICIOUS_TYPES`. Hidden with farm gear by default; Farm gear ON shows the short label "Halo collar" and does not use the suspicious 3-marker cap.
- Demo emits one quiet collar contact (placeholder MAC/UUID only). Live allowlist stays on the Pi, off-git.

## Quiet hours (2026-10-02)
- Default OFF. Flag file `/home/brian/fieldwatch/quiet-hours.json` is operational state, not a commit.
- Armed: low/watch unknowns are eligible for the suspicious HUD pool. Cap remains 3.
- `quiet_hours_log` is one row per MAC per America/Chicago night. Trusted farm types are not logged as bumps.
