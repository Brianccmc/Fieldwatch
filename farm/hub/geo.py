"""Parcel / hub geometry helpers for map overlays (static GeoJSON, offline)."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

HUB_DIR = Path(__file__).resolve().parent
MAP_DIR = HUB_DIR / "static" / "map"
META_PATH = MAP_DIR / "meta.json"
GEOJSON_PATH = MAP_DIR / "parcel.geojson"

# Fallback if static assets missing
_DEFAULT_HUB = (37.0457191, -91.9502374)


@lru_cache(maxsize=1)
def load_meta() -> dict[str, Any]:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    lat, lon = _DEFAULT_HUB
    return {
        "address": "264 County Road 1130, Willow Springs, MO",
        "hub_lat": lat,
        "hub_lon": lon,
        "acres_nominal": 119,
        "geojson": "/static/map/parcel.geojson",
        "offline": True,
        "style": "green_phosphor_topo",
    }


@lru_cache(maxsize=1)
def station_positions() -> dict[str, tuple[float, float]]:
    """id -> (lat, lon) from shipped GeoJSON station features."""
    out: dict[str, tuple[float, float]] = {}
    meta = load_meta()
    out["house-hub"] = (float(meta["hub_lat"]), float(meta["hub_lon"]))
    out["house"] = out["house-hub"]
    if not GEOJSON_PATH.exists():
        return out
    doc = json.loads(GEOJSON_PATH.read_text())
    for feat in doc.get("features") or []:
        props = feat.get("properties") or {}
        if props.get("kind") != "station":
            continue
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
            out[props["id"]] = (lat, lon)
    return out


def hub_latlon() -> tuple[float, float]:
    m = load_meta()
    return float(m["hub_lat"]), float(m["hub_lon"])


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 (degrees clockwise from north)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def estimate_contact_latlon(obs: dict[str, Any]) -> tuple[float | None, float | None]:
    """Prefer payload fix, then explicit lat/lon, else station + RSSI ring offset."""
    if obs.get("payload_lat") is not None and obs.get("payload_lon") is not None:
        return float(obs["payload_lat"]), float(obs["payload_lon"])
    if obs.get("lat") is not None and obs.get("lon") is not None:
        return float(obs["lat"]), float(obs["lon"])

    sid = obs.get("station_id") or "house-hub"
    positions = station_positions()
    base = positions.get(sid) or hub_latlon()
    lat0, lon0 = base

    # Deterministic jitter from MAC so markers don't stack
    mac = (obs.get("mac") or obs.get("uas_id") or obs.get("name") or sid).upper()
    h = sum(ord(c) for c in mac) or 1
    rssi = obs.get("rssi")
    # Stronger signal => closer to hearing station
    if isinstance(rssi, int) and rssi < 0:
        dist_m = max(25.0, min(450.0, 10 ** ((-50 - rssi) / 35.0) * 40.0))
    else:
        dist_m = 80.0 + (h % 120)
    brg = (h * 47) % 360
    br = math.radians(brg)
    dlat = (dist_m * math.cos(br)) / 111_320.0
    dlon = (dist_m * math.sin(br)) / (111_320.0 * math.cos(math.radians(lat0)))
    return lat0 + dlat, lon0 + dlon


def enrich_geometry(obs: dict[str, Any]) -> dict[str, Any]:
    """Attach lat/lon/bearing/range relative to hub (and hearing station when known)."""
    out = dict(obs)
    lat, lon = estimate_contact_latlon(out)
    hlat, hlon = hub_latlon()
    if lat is not None and lon is not None:
        out["lat"] = round(lat, 6)
        out["lon"] = round(lon, 6)
        out["bearing_deg"] = round(bearing_deg(hlat, hlon, lat, lon), 1)
        out["range_m"] = round(haversine_m(hlat, hlon, lat, lon), 1)
        # Signal vector strength 0..1 from RSSI
        rssi = out.get("rssi")
        if isinstance(rssi, int) and rssi < 0:
            # -40 => 1.0, -100 => 0.0
            out["signal_strength"] = round(max(0.0, min(1.0, (rssi + 100) / 60.0)), 3)
        else:
            out["signal_strength"] = 0.35
        # Bearing from hearing station if different
        sid = out.get("station_id")
        spos = station_positions().get(sid or "")
        if spos:
            out["from_station_bearing_deg"] = round(bearing_deg(spos[0], spos[1], lat, lon), 1)
    return out
