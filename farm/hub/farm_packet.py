"""Farm-packet normalize for serial NDJSON and MQTT.

The hub already ingests station observations (observation.schema.json).
A future LoRa/USB gateway may instead publish a smaller packet. Both shapes
become the same observation dict that MQTT contacts already use. Anything
else — including Meshtastic text or Meshtastic JSON — is not a farm packet.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

# Radios the station schema already speaks, plus lora for a gateway report
# that is not itself Wi-Fi/BLE/RID.
_KNOWN_RADIOS = {
    "wifi_ap",
    "wifi_mgmt",
    "ble_adv",
    "remote_id",
    "heartbeat",
    "lora",
}

_NODE_TELEMETRY = {
    "position",
    "telemetry",
    "node",
    "beacon",
    "gps",
    "status",
    "heartbeat",
    "hb",
    "ping",
}

_MESHTASTIC_TYPES = {
    "nodeinfo",
    "position",
    "text",
    "telemetry",
    "mapreport",
    "neighborinfo",
    "waypoint",
    "traceroute",
    "admin",
    "routing",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _node_id(raw: dict[str, Any]) -> str:
    for key in ("node_id", "node", "nodeId"):
        if key not in raw or raw[key] is None:
            continue
        text = str(raw[key]).strip()
        if text:
            return text[:32]
    return ""


def _first_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in raw or raw[key] is None or raw[key] == "":
            continue
        try:
            return float(raw[key])
        except (TypeError, ValueError):
            continue
    return None


def _first_int(raw: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in raw or raw[key] is None or raw[key] == "":
            continue
        try:
            return int(float(raw[key]))
        except (TypeError, ValueError):
            continue
    return None


def _has_gateway_fields(raw: dict[str, Any]) -> bool:
    keys = (
        "lat",
        "lon",
        "latitude",
        "longitude",
        "payload_lat",
        "payload_lon",
        "bearing",
        "bearing_deg",
        "battery",
        "battery_mv",
        "vbat",
        "vbat_mv",
        "station_vbat_mv",
        "event",
        "evt",
        "mac",
    )
    return any(k in raw and raw[k] not in (None, "") for k in keys)


def _looks_meshtastic(raw: dict[str, Any]) -> bool:
    """Meshtastic JSON has no farm station_id / node_id. Do not ingest it."""
    if raw.get("station_id") or _node_id(raw):
        return False
    kind = str(raw.get("type") or "").strip().lower()
    if kind in _MESHTASTIC_TYPES:
        return True
    if "from" in raw and ("payload" in raw or "channel" in raw or "id" in raw):
        return True
    return False


def _project(node_id: str, bearing_deg: float, dist_m: float = 180.0) -> tuple[float, float]:
    from geo import hub_latlon, station_positions

    positions = station_positions()
    lat0, lon0 = positions.get(node_id) or hub_latlon()
    br = math.radians(bearing_deg % 360.0)
    dlat = (dist_m * math.cos(br)) / 111_320.0
    denom = 111_320.0 * max(0.2, math.cos(math.radians(lat0)))
    dlon = (dist_m * math.sin(br)) / denom
    return lat0 + dlat, lon0 + dlon


def _from_gateway(raw: dict[str, Any], node: str) -> dict[str, Any]:
    event = str(raw.get("event") or raw.get("evt") or "contact").strip().lower() or "contact"
    mac = raw.get("mac")
    mac_s = str(mac).strip() if mac else ""
    radio = raw.get("radio")
    if isinstance(radio, str) and radio.strip():
        radio_s = radio.strip()
    elif event in {"heartbeat", "hb", "ping"}:
        radio_s = "heartbeat"
    else:
        radio_s = "lora"

    out: dict[str, Any] = {
        "v": raw.get("v") if raw.get("v") is not None else 1,
        "station_id": node,
        "node_id": node,
        "heard_at": raw.get("heard_at") or _now(),
        "radio": radio_s,
        "event": event,
        "farm_packet": True,
    }
    if mac_s:
        out["mac"] = mac_s
    if raw.get("name"):
        out["name"] = raw.get("name")
    rssi = _first_int(raw, "rssi")
    if rssi is None:
        rssi = 0 if radio_s == "heartbeat" else -80
    out["rssi"] = rssi

    battery = _first_int(raw, "station_vbat_mv", "battery_mv", "battery", "vbat_mv", "vbat")
    if battery is not None:
        out["station_vbat_mv"] = battery

    lat = _first_number(raw, "payload_lat", "lat", "latitude")
    lon = _first_number(raw, "payload_lon", "lon", "longitude")
    if lat is not None and lon is not None:
        out["payload_lat"] = lat
        out["payload_lon"] = lon
        out["lat"] = lat
        out["lon"] = lon
    else:
        bearing = _first_number(raw, "bearing_deg", "bearing")
        if bearing is not None:
            bearing = bearing % 360.0
            out["reported_bearing_deg"] = round(bearing, 1)
            plat, plon = _project(node, bearing)
            out["lat"] = plat
            out["lon"] = plon

    # Node telemetry without a heard MAC is the station itself, not a rogue.
    if not mac_s and (event in _NODE_TELEMETRY or radio_s == "heartbeat"):
        if radio_s == "heartbeat" or event in {"heartbeat", "hb", "ping"}:
            out["radio"] = "heartbeat"
            out["device_type"] = "heartbeat"
            out["rssi"] = 0
        else:
            out["device_type"] = "known_farm_node"
            out["known_farm_node"] = True
            out["device_label"] = raw.get("device_label") or "Farm node %s" % node

    for key in (
        "mac_kind",
        "channel",
        "freq_mhz",
        "mode",
        "service_uuid",
        "service_data_hex",
        "uas_id",
        "rid_status",
        "rid_heading_deg",
        "dult_mode",
        "find_hub_mode",
        "station_solar_mv",
    ):
        if key in raw and raw[key] is not None and key not in out:
            out[key] = raw[key]
    return out


def normalize_farm_packet(raw: Any) -> dict[str, Any] | None:
    """Return an observation dict, or None if this is not a farm packet.

    Accepted:
    - Existing observation: JSON object with string station_id and radio.
    - Gateway packet: node_id (aliases node, nodeId) plus at least one of
      lat/lon, bearing, battery, event, or mac.

    Rejected: non-objects, Meshtastic frames, and other JSON.
    """
    if not isinstance(raw, dict):
        return None
    if _looks_meshtastic(raw):
        return None

    station = raw.get("station_id")
    radio = raw.get("radio")
    if isinstance(station, str) and station.strip() and isinstance(radio, str) and radio.strip():
        out = dict(raw)
        out["station_id"] = station.strip()[:32]
        out["radio"] = radio.strip()
        if not out.get("heard_at"):
            out["heard_at"] = _now()
        if out.get("v") is None:
            out["v"] = 1
        if "rssi" not in out or out["rssi"] is None:
            out["rssi"] = 0 if out["radio"] == "heartbeat" else -80
        return out

    node = _node_id(raw)
    if not node or not _has_gateway_fields(raw):
        return None
    # Ignore a gateway radio we have never defined unless it is a known one
    # or omitted (we default it). Unknown radio strings still pass when the
    # packet is otherwise a gateway packet — the hub does not schema-reject.
    radio = raw.get("radio")
    if isinstance(radio, str) and radio.strip() and radio.strip() not in _KNOWN_RADIOS:
        # Still a farm packet: keep the radio string so a later enum can land.
        pass
    return _from_gateway(raw, node)


def parse_serial_line(line: str) -> dict[str, Any] | None:
    """One serial line -> observation, or None (Meshtastic / junk)."""
    text = (line or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    return normalize_farm_packet(raw)
