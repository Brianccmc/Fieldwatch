"""New-MAC / new-contact geofence: one event per MAC per local night.

Unknown means not allowlisted and not a trusted farm type (halo_collar,
trail_cam, known_farm_node, and the rest of the trusted set). Suspicious
types and unknown_ble first-seen contacts are recorded. Night is the
America/Chicago calendar date.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

try:
    CHI = ZoneInfo("America/Chicago")
except Exception:  # noqa: BLE001 — box without tzdata
    CHI = timezone(timedelta(hours=-6))

# Matches HUD trusted set. These never open a geofence event.
TRUSTED_FARM_TYPES = frozenset(
    {
        "heartbeat",
        "halo_collar",
        "trail_cam",
        "flock_camera",
        "known_farm_node",
        "allowlisted",
        "tracker_near",
    }
)

# Suspicious classes plus unknown BLE / unclassified first appearances.
GEOFENCE_TYPES = frozenset(
    {
        "rogue_ap",
        "remote_id_drone",
        "rid_emergency",
        "unknown_phone",
        "visitor_wifi",
        "tracker_separated",
        "unknown_ble",
        "transient_ble",
        "unknown",
    }
)


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS new_mac_events ("
        "id INTEGER PRIMARY KEY,"
        "mac TEXT NOT NULL,"
        "night_key TEXT NOT NULL,"
        "first_seen TEXT NOT NULL,"
        "device_type TEXT,"
        "lat REAL,"
        "lon REAL,"
        "station_id TEXT,"
        "name TEXT,"
        "UNIQUE(mac, night_key))"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_new_mac_night ON new_mac_events(night_key)"
    )


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":").strip()


def night_key_for(heard_at: str | None = None, now: datetime | None = None) -> str:
    """America/Chicago calendar date for heard_at (UTC Z) or now."""
    if heard_at:
        try:
            t = datetime.fromisoformat(heard_at.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            t = now or datetime.now(timezone.utc)
    else:
        t = now or datetime.now(timezone.utc)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(CHI).date().isoformat()


def night_key_now() -> str:
    return night_key_for(None)


def is_geofence_candidate(obs: dict[str, Any], allow: Any = None) -> bool:
    """True for an unknown / suspicious contact that should mark the parcel."""
    allow = allow or set()
    if (obs.get("radio") or "") == "heartbeat":
        return False
    mac = _norm_mac(obs.get("mac"))
    if not mac or mac.count(":") < 5:
        return False
    if mac in allow:
        return False
    name = (obs.get("name") or "").strip()
    if name and f"ssid:{name.lower()}" in allow:
        return False
    dtype = (obs.get("device_type") or "unknown").strip().lower()
    if dtype in TRUSTED_FARM_TYPES:
        return False
    # Allowlist-classified halo stays trusted even if a hint said otherwise.
    try:
        from risk import match_halo_collar

        if match_halo_collar(obs, allow):
            return False
    except Exception:
        pass
    return dtype in GEOFENCE_TYPES


def record_new_mac(db: sqlite3.Connection, obs: dict[str, Any], allow: Any = None) -> bool:
    """Insert one row per MAC per Chicago night. Returns True if newly stored."""
    if not is_geofence_candidate(obs, allow):
        return False
    ensure_schema(db)
    mac = _norm_mac(obs.get("mac"))
    night = night_key_for(obs.get("heard_at"))
    seen = obs.get("heard_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = db.execute(
        "INSERT OR IGNORE INTO new_mac_events"
        "(mac, night_key, first_seen, device_type, lat, lon, station_id, name) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            mac,
            night,
            seen,
            obs.get("device_type"),
            obs.get("lat"),
            obs.get("lon"),
            obs.get("station_id"),
            (obs.get("name") or None),
        ),
    )
    return cur.rowcount == 1


def list_new_macs(
    db: sqlite3.Connection, night_key: str | None = None, limit: int = 40
) -> dict[str, Any]:
    ensure_schema(db)
    nk = (night_key or night_key_now()).strip()
    limit = max(1, min(int(limit), 200))
    total = db.execute(
        "SELECT COUNT(*) FROM new_mac_events WHERE night_key=?", (nk,)
    ).fetchone()[0]
    rows = db.execute(
        "SELECT mac, first_seen, device_type, lat, lon, night_key, station_id, name "
        "FROM new_mac_events WHERE night_key=? ORDER BY first_seen ASC, id ASC LIMIT ?",
        (nk, limit),
    ).fetchall()
    events = [
        {
            "mac": r[0],
            "first_seen": r[1],
            "device_type": r[2],
            "lat": r[3],
            "lon": r[4],
            "night_key": r[5],
            "station_id": r[6],
            "name": r[7],
        }
        for r in rows
    ]
    return {
        "night_key": nk,
        "tz": "America/Chicago",
        "rule": "one_per_mac_per_night",
        "count": int(total),
        "events": events,
    }
