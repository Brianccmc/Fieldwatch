"""OpenDroneID / ASTM Remote ID helpers (Fieldwatch 1.1.14-1.1.16)."""

from __future__ import annotations

from typing import Any

WIFI_RID_OUI = "FA:0B:BC"
BLE_RID_UUID = "FFFA"
RID_MSG_LEN = 25

RID_STATUS = {
    0: "undeclared",
    1: "ground",
    2: "airborne",
    3: "emergency",
    4: "rid_failure",
}


def heading_deg(direction_0_179: int, east_west: bool) -> float:
    d = int(direction_0_179) & 0xFF
    if d > 179:
        d = 179
    return float(d + (180 if east_west else 0))


def hspeed_mps(raw: int, speed_mult: bool) -> float:
    v = max(0, int(raw))
    if speed_mult:
        return v * 0.75 + 63.75
    return v * 0.25


def frame_wifi_type13(ie_payload: bytes) -> bytes:
    return bytes([0x0D, 0x00]) + ie_payload


def split_odid_messages(framed: bytes) -> list[bytes]:
    body = framed[2:] if len(framed) >= 2 and framed[0] == 0x0D else framed
    return [body[i : i + RID_MSG_LEN] for i in range(0, len(body), RID_MSG_LEN) if len(body[i : i + RID_MSG_LEN]) == RID_MSG_LEN]


def decode_location_message(msg: bytes) -> dict[str, Any] | None:
    if len(msg) < 25:
        return None
    msg_type = (msg[0] >> 4) & 0x0F
    if msg_type != 1:
        return None
    status = (msg[1] >> 4) & 0x0F
    flags = msg[1] & 0x0F
    return {
        "rid_status": RID_STATUS.get(status, "undeclared"),
        "rid_heading_deg": heading_deg(msg[2], bool(flags & 0x1)),
        "rid_hspeed_mps": hspeed_mps(msg[3], bool(flags & 0x2)),
    }


def plot_rule(obs: dict[str, Any], max_km_from_station: float = 2.0) -> str:
    import math

    plat, plon = obs.get("payload_lat"), obs.get("payload_lon")
    slat, slon = obs.get("station_lat"), obs.get("station_lon")
    if plat is None or plon is None:
        return "listener"
    if slat is None or slon is None:
        return "advertised_fix"
    dy = (plat - slat) * 111.32
    dx = (plon - slon) * 111.32 * math.cos(math.radians(slat))
    km = math.hypot(dx, dy)
    return "advertised_far" if km > max_km_from_station else "advertised_fix"
