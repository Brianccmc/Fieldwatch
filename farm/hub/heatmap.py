"""Offline activity heatmap bins from SQLite hear positions.

Dwell is hear count in a lat/lon cell. Revisit is distinct Chicago nights
(and distinct MACs) in that cell. No tile APIs — the HUD paints the bins.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from geofence import night_key_for

# ~60 m at the Willow Springs latitude. Parcel span is about 1 km.
DEFAULT_CELL_DEG = 0.00055


def _cell(lat: float, lon: float, cell: float) -> tuple[int, int]:
    return (int(round(lat / cell)), int(round(lon / cell)))


def compute_heatmap(
    db: sqlite3.Connection,
    cell_deg: float = DEFAULT_CELL_DEG,
    limit_hears: int = 8000,
    max_bins: int = 400,
) -> dict[str, Any]:
    cell = float(cell_deg) if cell_deg and cell_deg > 0 else DEFAULT_CELL_DEG
    limit_hears = max(1, min(int(limit_hears), 20000))
    max_bins = max(1, min(int(max_bins), 800))
    rows = db.execute(
        "SELECT lat, lon, mac, heard_at, radio, device_type FROM hears "
        "WHERE lat IS NOT NULL AND lon IS NOT NULL AND radio != 'heartbeat' "
        "ORDER BY id DESC LIMIT ?",
        (limit_hears,),
    ).fetchall()

    bins: dict[tuple[int, int], dict[str, Any]] = {}
    used = 0
    for lat, lon, mac, heard_at, radio, dtype in rows:
        if radio == "heartbeat" or dtype == "heartbeat":
            continue
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        used += 1
        key = _cell(lat_f, lon_f, cell)
        slot = bins.get(key)
        if slot is None:
            slot = {
                "lat_sum": 0.0,
                "lon_sum": 0.0,
                "count": 0,
                "macs": set(),
                "nights": set(),
            }
            bins[key] = slot
        slot["lat_sum"] += lat_f
        slot["lon_sum"] += lon_f
        slot["count"] += 1
        if mac:
            slot["macs"].add(str(mac).upper())
        slot["nights"].add(night_key_for(heard_at))

    out = []
    for slot in bins.values():
        n = slot["count"]
        nights = len(slot["nights"])
        macs = len(slot["macs"])
        # Dwell (hears) plus revisit (extra nights and extra devices).
        weight = n + max(0, nights - 1) * 2 + max(0, macs - 1)
        out.append(
            {
                "lat": round(slot["lat_sum"] / n, 6),
                "lon": round(slot["lon_sum"] / n, 6),
                "count": n,
                "revisit_nights": nights,
                "macs": macs,
                "weight": weight,
            }
        )
    out.sort(key=lambda b: (-b["weight"], -b["count"]))
    clipped = out[:max_bins]
    max_weight = clipped[0]["weight"] if clipped else 0
    return {
        "offline": True,
        "cell_deg": cell,
        "hears_scanned": used,
        "bin_count": len(clipped),
        "max_weight": max_weight,
        "bins": clipped,
    }
