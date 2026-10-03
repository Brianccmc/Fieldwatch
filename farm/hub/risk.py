"""Device-type inference and risk scoring for farm contacts (device type is a first-class input)."""

from __future__ import annotations

from typing import Any


# device_type -> base score contribution + default label
_TYPE_BASE: dict[str, tuple[int, str]] = {
    "heartbeat": (0, "Hub heartbeat"),
    "known_farm_node": (5, "Known farm node"),
    "allowlisted": (8, "Allowlisted device"),
    "halo_collar": (10, "Halo collar"),
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

# Product phrase only. A bare "Halo" (or random BLE) is not a collar.
_HALO_NAME = "halo collar"


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":")


def _norm_uuid(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch in "0123456789ABCDEF")


def _ble_radio(radio: str | None) -> bool:
    r = radio or ""
    return r == "ble_adv" or r.startswith("ble")


def _halo_name_hit(text: str | None) -> bool:
    return _HALO_NAME in (text or "").lower()


def match_halo_collar(obs: dict[str, Any], allow: Any = None) -> bool:
    """True only for an allowlisted Halo MAC/UUID or the built-in Halo collar signature.

    Unmatched random BLE is not a Halo. No cloud identity.
    """
    if not _ble_radio(obs.get("radio")):
        return False
    mac = _norm_mac(obs.get("mac"))
    uuid = _norm_uuid(obs.get("service_uuid") or obs.get("uuid"))
    halo_macs = getattr(allow, "halo_macs", ()) or ()
    halo_uuids = getattr(allow, "halo_uuids", ()) or ()
    if mac and mac in halo_macs:
        return True
    if uuid and uuid in halo_uuids:
        return True
    if _halo_name_hit(obs.get("name")):
        return True
    for sig in obs.get("signature_names") or []:
        if _halo_name_hit(sig) or str(sig).strip().lower() in {"halo collar", "halo-collar"}:
            return True
    for sig_id in obs.get("signature_ids") or []:
        if str(sig_id).strip().lower() in {"halo-collar", "halo_collar"}:
            return True
    return False


def infer_device_type(obs: dict[str, Any], allow: set[str] | None = None) -> tuple[str, str]:
    """Return (device_type, friendly_label). Prefer explicit demo/station hints."""
    allow = allow or set()
    explicit = (obs.get("device_type") or "").strip()
    if explicit and explicit in _TYPE_BASE:
        label = obs.get("device_label") or _TYPE_BASE[explicit][1]
        return explicit, label

    radio = obs.get("radio") or ""
    name = (obs.get("name") or "").strip()
    mac = _norm_mac(obs.get("mac"))
    ssid_key = f"ssid:{name.lower()}"
    sigs = [s.lower() for s in (obs.get("signature_names") or [])]

    if radio == "heartbeat":
        return "heartbeat", _TYPE_BASE["heartbeat"][1]
    if match_halo_collar(obs, allow):
        return "halo_collar", obs.get("device_label") or _TYPE_BASE["halo_collar"][1]
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

    # Cap and level. Matched Halo stays low — it is a known pet, not a rogue.
    score = max(0, min(100, int(round(score))))
    if dtype == "halo_collar":
        if score > 24:
            reasons.append("halo_collar matched — held low (known pet)")
        score = min(score, 24)
        level = "low"
        reasons.append("known pet tracker (Halo collar)")
    elif score >= 75:
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
