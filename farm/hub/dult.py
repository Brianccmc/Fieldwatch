"""IETF DULT (FCB2) and Google Find Hub mode bits.

Fieldwatch 1.1.15–1.1.16 CatalogDecodes:
  Byte 0 = Network ID
  LSB of byte 1 = near-owner (1) vs separated (0)

A bare FCB2 UUID in the UUID *list* is not a hit. Service data must be present.
Separated is the alert chip. Near-owner stays quiet.
"""

from __future__ import annotations

from typing import Any


def decode_fcb2(service_data_hex: str) -> dict[str, Any] | None:
    h = (service_data_hex or "").replace(" ", "").replace(":", "")
    if len(h) < 4:
        return None
    try:
        raw = bytes.fromhex(h)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    network_id = raw[0]
    near_owner = bool(raw[1] & 0x01)
    return {
        "dult_network_id": network_id,
        "dult_mode": "near_owner" if near_owner else "separated",
    }


def find_hub_mode_from_feaa(frame_type: int) -> str | None:
    if frame_type == 0x41:
        return "separated"
    if frame_type == 0x40:
        return "nearby"
    return None


def alert_worthy_tracker(obs: dict[str, Any]) -> bool:
    if obs.get("dult_mode") == "separated":
        return True
    if obs.get("find_hub_mode") == "separated":
        return True
    return False
