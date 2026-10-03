"""Quiet-hours (away-from-home) flag. Default OFF. The flag file stays off git.

When armed, unknown contacts that are only low or medium (watch) become
eligible for the suspicious HUD list. Trusted farm gear is never bumped.
Map selection stays cap 3 (highest risk_score, then recency) — that cap
lives in the HUD. This module decides eligibility and writes at most one
SQLite row per MAC per America/Chicago night.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geofence import TRUSTED_FARM_TYPES, night_key_for

# Mirrors farm/hub/static/index.html. Do not widen trusted into rogues.
SUSPICIOUS_TYPES = frozenset(
    {
        "rogue_ap",
        "remote_id_drone",
        "rid_emergency",
        "unknown_phone",
        "visitor_wifi",
        "tracker_separated",
    }
)
NOISE_TYPES = frozenset({"unknown_ble", "transient_ble"})
# Elevated / high / critical already surface (BLE noise only if critical).
HIGH_RISK = frozenset({"high", "critical", "elevated"})
# low = risk_level low (score < 35). medium = watch (35–54). No "medium" label exists.
LOW_MEDIUM = frozenset({"low", "watch", "medium"})

_lock = threading.Lock()


def quiet_hours_path() -> Path:
    try:
        import config

        return Path(config.QUIET_HOURS_PATH)
    except Exception:
        env = os.environ.get("FIELDWATCH_QUIET_HOURS")
        if env:
            return Path(env)
        return Path.home() / "fieldwatch" / "quiet-hours.json"


def enabled(path: Path | None = None) -> bool:
    """Missing, unreadable, or malformed file => OFF."""
    p = path or quiet_hours_path()
    try:
        doc = json.loads(p.read_text())
    except Exception:
        return False
    if not isinstance(doc, dict):
        return False
    return bool(doc.get("enabled"))


def set_enabled(on: bool, path: Path | None = None) -> bool:
    """Persist the flag atomically. Returns the value written."""
    p = path or quiet_hours_path()
    value = bool(on)
    payload = json.dumps({"enabled": value}, indent=2) + "\n"
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(payload)
        os.replace(tmp, p)
    return value


def label_for(on: bool) -> str:
    return "Quiet hours: ON" if on else "Quiet hours: OFF"


def _level(obs: dict[str, Any]) -> str:
    return (obs.get("risk_level") or "").strip().lower()


def _dtype(obs: dict[str, Any]) -> str:
    return (obs.get("device_type") or "").strip().lower()


def is_trusted_farm(obs: dict[str, Any], allow: Any = None) -> bool:
    """Trusted farm gear, allowlisted radios, heartbeats, and Halo collars.

    These stay hidden unless Farm gear is ON. Quiet hours must not turn
    them into rogues.
    """
    if (obs.get("radio") or "") == "heartbeat":
        return True
    dtype = _dtype(obs)
    if dtype in TRUSTED_FARM_TYPES:
        return True
    allow = allow or set()
    mac = (obs.get("mac") or "").upper().replace("-", ":").strip()
    if mac and mac in allow:
        return True
    name = (obs.get("name") or "").strip()
    if name and f"ssid:{name.lower()}" in allow:
        return True
    try:
        from risk import match_halo_collar

        if match_halo_collar(obs, allow):
            return True
    except Exception:
        pass
    return False


def hud_suspicious(obs: dict[str, Any], quiet: bool) -> bool:
    """Whether the HUD treats this contact as suspicious.

    quiet=False is the pass-3 rule. quiet=True also admits low/medium
    unknowns (not trusted). Trusted types always return False.
    """
    if _dtype(obs) in TRUSTED_FARM_TYPES or (obs.get("radio") or "") == "heartbeat":
        return False
    dtype = _dtype(obs) or "unknown"
    level = _level(obs)
    if dtype in SUSPICIOUS_TYPES:
        return True
    if dtype in NOISE_TYPES:
        if level == "critical":
            return True
        return bool(quiet) and level in LOW_MEDIUM
    if level in HIGH_RISK:
        return True
    if quiet and level in LOW_MEDIUM:
        return True
    return False


def should_bump(obs: dict[str, Any], allow: Any = None) -> bool:
    """True when quiet hours newly makes a low/medium unknown eligible.

    Already-suspicious contacts are not "bumped". Trusted gear never is.
    """
    if is_trusted_farm(obs, allow):
        return False
    return hud_suspicious(obs, True) and not hud_suspicious(obs, False)


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS quiet_hours_log ("
        "id INTEGER PRIMARY KEY,"
        "mac TEXT NOT NULL,"
        "night_key TEXT NOT NULL,"
        "heard_at TEXT NOT NULL,"
        "device_type TEXT,"
        "risk_score INTEGER,"
        "risk_level TEXT,"
        "lat REAL,"
        "lon REAL,"
        "station_id TEXT,"
        "name TEXT,"
        "UNIQUE(mac, night_key))"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_quiet_hours_night ON quiet_hours_log(night_key)"
    )


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":").strip()


def maybe_log(db: sqlite3.Connection, obs: dict[str, Any], allow: Any = None) -> bool:
    """One row per MAC per Chicago night, and only while the flag is ON.

    Returns True if a new row was inserted. No-op when disarmed, trusted,
    already suspicious, or not low/medium.
    """
    if not enabled():
        return False
    if not should_bump(obs, allow):
        return False
    mac = _norm_mac(obs.get("mac"))
    if not mac or mac.count(":") < 5:
        return False
    ensure_schema(db)
    night = night_key_for(obs.get("heard_at"))
    seen = obs.get("heard_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = db.execute(
        "INSERT OR IGNORE INTO quiet_hours_log"
        "(mac, night_key, heard_at, device_type, risk_score, risk_level, lat, lon, station_id, name) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            mac,
            night,
            seen,
            obs.get("device_type"),
            obs.get("risk_score"),
            obs.get("risk_level"),
            obs.get("lat"),
            obs.get("lon"),
            obs.get("station_id"),
            (obs.get("name") or None),
        ),
    )
    return cur.rowcount == 1


def list_log(
    db: sqlite3.Connection, night_key: str | None = None, limit: int = 40
) -> dict[str, Any]:
    from geofence import night_key_now

    ensure_schema(db)
    nk = (night_key or night_key_now()).strip()
    limit = max(1, min(int(limit), 200))
    total = db.execute(
        "SELECT COUNT(*) FROM quiet_hours_log WHERE night_key=?", (nk,)
    ).fetchone()[0]
    rows = db.execute(
        "SELECT mac, heard_at, device_type, risk_score, risk_level, lat, lon, night_key, station_id, name "
        "FROM quiet_hours_log WHERE night_key=? ORDER BY heard_at ASC, id ASC LIMIT ?",
        (nk, limit),
    ).fetchall()
    events = [
        {
            "mac": r[0],
            "heard_at": r[1],
            "device_type": r[2],
            "risk_score": r[3],
            "risk_level": r[4],
            "lat": r[5],
            "lon": r[6],
            "night_key": r[7],
            "station_id": r[8],
            "name": r[9],
        }
        for r in rows
    ]
    return {
        "night_key": nk,
        "tz": "America/Chicago",
        "rule": "one_per_mac_per_night",
        "enabled": enabled(),
        "count": int(total),
        "events": events,
    }
