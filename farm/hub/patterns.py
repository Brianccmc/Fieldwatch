"""Activity pattern aggregates from hears history (dwell, revisit, time-of-day, corridors)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


def _parse_hour(heard_at: str | None) -> int | None:
    if not heard_at:
        return None
    try:
        # 2026-10-02T16:35:46Z
        t = heard_at.replace("Z", "+00:00")
        return datetime.fromisoformat(t).hour
    except Exception:
        return None


def _contact_key(doc: dict[str, Any], mac: str | None, name: str | None) -> str:
    if doc.get("uas_id"):
        return f"uas:{doc['uas_id']}"
    if mac:
        return f"mac:{mac.upper()}"
    if name:
        return f"name:{name.lower()}"
    return f"anon:{doc.get('station_id')}:{doc.get('heard_at')}"


def compute_patterns(db: sqlite3.Connection, limit_hears: int = 2000) -> dict[str, Any]:
    rows = db.execute(
        "SELECT heard_at, station_id, radio, mac, name, rssi, json FROM hears ORDER BY id DESC LIMIT ?",
        (limit_hears,),
    ).fetchall()

    by_key: dict[str, dict[str, Any]] = {}
    hour_global: Counter[int] = Counter()
    station_hits: Counter[str] = Counter()

    for heard_at, station_id, radio, mac, name, rssi, raw in rows:
        if radio == "heartbeat":
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            doc = {}
        key = _contact_key(doc, mac, name)
        hour = _parse_hour(heard_at)
        if hour is not None:
            hour_global[hour] += 1
        if station_id:
            station_hits[station_id] += 1

        slot = by_key.get(key)
        if not slot:
            slot = {
                "key": key,
                "mac": mac,
                "name": name or doc.get("name"),
                "device_type": doc.get("device_type"),
                "device_label": doc.get("device_label"),
                "risk_score": doc.get("risk_score"),
                "risk_level": doc.get("risk_level"),
                "hear_count": 0,
                "stations": Counter(),
                "hours": Counter(),
                "first_seen": heard_at,
                "last_seen": heard_at,
                "rssi_min": rssi,
                "rssi_max": rssi,
                "days": set(),
            }
            by_key[key] = slot
        slot["hear_count"] += 1
        if station_id:
            slot["stations"][station_id] += 1
        if hour is not None:
            slot["hours"][hour] += 1
        # rows are DESC — first row is newest
        if heard_at and (slot["last_seen"] is None or heard_at > slot["last_seen"]):
            slot["last_seen"] = heard_at
        if heard_at and (slot["first_seen"] is None or heard_at < slot["first_seen"]):
            slot["first_seen"] = heard_at
        if isinstance(rssi, int):
            slot["rssi_min"] = rssi if slot["rssi_min"] is None else min(slot["rssi_min"], rssi)
            slot["rssi_max"] = rssi if slot["rssi_max"] is None else max(slot["rssi_max"], rssi)
        if heard_at and len(heard_at) >= 10:
            slot["days"].add(heard_at[:10])
        # Prefer latest enrichment fields
        for fld in ("device_type", "device_label", "risk_score", "risk_level", "lat", "lon"):
            if doc.get(fld) is not None:
                slot[fld] = doc.get(fld)

    contacts = []
    for slot in by_key.values():
        stations = slot["stations"]
        hours = slot["hours"]
        days = slot["days"]
        primary = stations.most_common(3)
        peak_hours = [h for h, _ in hours.most_common(3)]
        revisit_days = len(days)
        # dwell proxy: hears / unique hours (higher => lingering)
        dwell = round(slot["hear_count"] / max(1, len(hours)), 2)
        corridor = primary[0][0] if primary else None
        pattern_tags = []
        if revisit_days >= 2:
            pattern_tags.append("revisit")
        if dwell >= 3:
            pattern_tags.append("dwell")
        if peak_hours:
            pattern_tags.append(f"tod:{','.join(f'{h:02d}h' for h in peak_hours[:2])}")
        if corridor:
            pattern_tags.append(f"corridor:{corridor}")
        contacts.append(
            {
                "key": slot["key"],
                "mac": slot["mac"],
                "name": slot["name"],
                "device_type": slot.get("device_type"),
                "device_label": slot.get("device_label"),
                "risk_score": slot.get("risk_score"),
                "risk_level": slot.get("risk_level"),
                "hear_count": slot["hear_count"],
                "revisit_days": revisit_days,
                "dwell_score": dwell,
                "peak_hours_utc": peak_hours,
                "approach_stations": [{"id": s, "count": c} for s, c in primary],
                "first_seen": slot["first_seen"],
                "last_seen": slot["last_seen"],
                "rssi_min": slot["rssi_min"],
                "rssi_max": slot["rssi_max"],
                "pattern_tags": pattern_tags,
                "lat": slot.get("lat"),
                "lon": slot.get("lon"),
            }
        )

    contacts.sort(key=lambda c: (-(c.get("risk_score") or 0), -c["hear_count"]))

    # Global recurring corridors / busy hours
    tod = [{"hour_utc": h, "count": n} for h, n in sorted(hour_global.items())]
    corridors = [
        {"station_id": s, "hear_count": n, "label": f"approach/{s}"}
        for s, n in station_hits.most_common(6)
    ]

    return {
        "contacts": contacts[:40],
        "time_of_day": tod,
        "approach_corridors": corridors,
        "summary": {
            "unique_contacts": len(contacts),
            "hears_scanned": len(rows),
            "top_corridor": corridors[0]["station_id"] if corridors else None,
        },
    }


def latest_contacts(db: sqlite3.Connection, limit: int = 40) -> list[dict[str, Any]]:
    """Latest non-heartbeat contact per key with map/risk fields for HUD overlay."""
    rows = db.execute(
        "SELECT id, heard_at, station_id, radio, mac, name, rssi, json FROM hears ORDER BY id DESC LIMIT ?",
        (max(limit * 20, 400),),
    ).fetchall()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        radio = r[3]
        if radio == "heartbeat":
            continue
        try:
            doc = json.loads(r[7])
        except Exception:
            doc = {}
        key = _contact_key(doc, r[4], r[5])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": r[0],
                "key": key,
                "heard_at": r[1],
                "station_id": r[2],
                "radio": radio,
                "mac": r[4],
                "name": r[5] or doc.get("name"),
                "rssi": r[6],
                "alert": doc.get("alert"),
                "alert_reason": doc.get("alert_reason"),
                "device_type": doc.get("device_type"),
                "device_label": doc.get("device_label"),
                "risk_score": doc.get("risk_score"),
                "risk_level": doc.get("risk_level"),
                "risk_reasons": doc.get("risk_reasons") or [],
                "lat": doc.get("lat"),
                "lon": doc.get("lon"),
                "bearing_deg": doc.get("bearing_deg"),
                "range_m": doc.get("range_m"),
                "signal_strength": doc.get("signal_strength"),
                "from_station_bearing_deg": doc.get("from_station_bearing_deg"),
                "signature_names": doc.get("signature_names") or [],
                "rid_status": doc.get("rid_status"),
                "uas_id": doc.get("uas_id"),
            }
        )
        if len(out) >= limit:
            break
    return out
