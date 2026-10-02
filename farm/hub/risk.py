"""Device-type inference and risk scoring for farm contacts (device type is a first-class input)."""

from __future__ import annotations

from typing import Any


# device_type -> base score contribution + default label
_TYPE_BASE: dict[str, tuple[int, str]] = {
    "heartbeat": (0, "Hub heartbeat"),
    "known_farm_node": (5, "Known farm node"),
    "allowlisted": (8, "Allowlisted device"),
    "trail_cam": (18, "Trail camera"),
    "flock_camera": (22, "Fleet camera (quiet)"),
    "tracker_near": (20, "Tracker near owner"),
    "unknown_ble": (35, "Unknown BLE"),
    "unknown_phone": (48, "Unknown phone / hotspot"),
    "visitor_wifi": (52, "Visitor Wi-Fi AP"),
    "rogue_ap": (72, "Rogue / unexpected AP"),
    "tracker_separated": (78, "Tracker separated"),
    "remote_id_drone": (85, "Remote ID aircraft"),
    "rid_emergency": (95, "RID emergency"),
    "unknown": (40, "Unclassified contact"),
}


def infer_device_type(obs: dict[str, Any], allow: set[str] | None = None) -> tuple[str, str]:
    """Return (device_type, friendly_label). Prefer explicit demo/station hints."""
    allow = allow or set()
    explicit = (obs.get("device_type") or "").strip()
    if explicit and explicit in _TYPE_BASE:
        label = obs.get("device_label") or _TYPE_BASE[explicit][1]
        return explicit, label

    radio = obs.get("radio") or ""
    name = (obs.get("name") or "").strip()
    mac = (obs.get("mac") or "").upper()
    ssid_key = f"ssid:{name.lower()}"
    sigs = [s.lower() for s in (obs.get("signature_names") or [])]

    if radio == "heartbeat":
        return "heartbeat", _TYPE_BASE["heartbeat"][1]
    if mac in allow or ssid_key in allow or obs.get("allowlisted"):
        return "allowlisted", name or _TYPE_BASE["allowlisted"][1]
    if obs.get("station_kind") == "farm_node" or obs.get("known_farm_node"):
        return "known_farm_node", name or _TYPE_BASE["known_farm_node"][1]

    if radio == "remote_id" or obs.get("uas_id") or obs.get("rid_status"):
        if obs.get("rid_status") == "emergency":
            return "rid_emergency", name or f"UAS {obs.get('uas_id') or ''}".strip()
        return "remote_id_drone", name or f"UAS {obs.get('uas_id') or 'unknown'}"

    if obs.get("dult_mode") == "separated" or obs.get("find_hub_mode") == "separated":
        return "tracker_separated", name or "Separated tracker"
    if obs.get("dult_mode") == "near_owner" or obs.get("find_hub_mode") == "nearby":
        return "tracker_near", name or "Tracker near owner"

    if any("flock" in s for s in sigs) or name.lower().startswith("flock"):
        return "flock_camera", name or "Flock camera"
    if "trailcam" in name.lower().replace("_", "") or name.lower().startswith("trail"):
        return "trail_cam", name or "Trail camera"

    if radio.startswith("wifi"):
        low = name.lower()
        if any(x in low for x in ("iphone", "android", "galaxy", "pixel", "visitor", "phone")):
            return "unknown_phone", name or "Phone hotspot"
        if any(x in low for x in ("barnap", "farm", "house", "gate")):
            return "known_farm_node", name or "Farm AP"
        if not name or low in {"", "hidden"}:
            return "rogue_ap", "Hidden / unnamed AP"
        return "visitor_wifi", name or "Wi-Fi AP"

    if radio == "ble_adv":
        if name:
            return "unknown_ble", name
        return "unknown_ble", "Anonymous BLE"

    return "unknown", name or _TYPE_BASE["unknown"][1]


def score_risk(obs: dict[str, Any], device_type: str | None = None) -> dict[str, Any]:
    """Risk assessment that INCLUDES device type in scoring and reasoning."""
    dtype, label = infer_device_type(obs) if not device_type else (
        device_type,
        obs.get("device_label") or _TYPE_BASE.get(device_type, (40, device_type))[1],
    )
    base, _ = _TYPE_BASE.get(dtype, (40, dtype))
    reasons: list[str] = [f"device_type={dtype} (base {base})"]
    score = base

    rssi = obs.get("rssi")
    if isinstance(rssi, int) and rssi != 0:
        if rssi >= -50:
            score += 12
            reasons.append(f"strong RSSI {rssi} dBm (close)")
        elif rssi >= -65:
            score += 6
            reasons.append(f"moderate RSSI {rssi} dBm")
        elif rssi <= -90:
            score -= 4
            reasons.append(f"weak RSSI {rssi} dBm (distant)")

    if obs.get("alert"):
        score += 10
        reasons.append(f"alert={obs.get('alert_reason') or 'yes'}")

    if obs.get("first_seen_event") or obs.get("alert_reason") == "first_seen":
        score += 8
        reasons.append("first_seen / novel contact")

    if obs.get("rid_status") == "airborne":
        score += 8
        reasons.append("RID airborne")

    if obs.get("approach_corridor"):
        score += 7
        reasons.append(f"approach corridor: {obs.get('approach_corridor')}")

    # Cap and level
    score = max(0, min(100, int(round(score))))
    if score >= 75:
        level = "critical"
    elif score >= 55:
        level = "elevated"
    elif score >= 35:
        level = "watch"
    else:
        level = "low"

    return {
        "device_type": dtype,
        "device_label": label,
        "risk_score": score,
        "risk_level": level,
        "risk_reasons": reasons[:8],
    }
