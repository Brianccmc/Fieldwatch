"""Synthetic heartbeats + typed contacts (DEFAULT ON) so topo HUD is never empty."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import config
from geo import estimate_contact_latlon, station_positions
from state import STATE

log = logging.getLogger("fieldwatch.demo")

DEMO_STATIONS = ("house", "gate-n", "ridge-2", "pond")

# Pass 3: suspicious-only cast (trusted farm gear not spawned — HUD hides them anyway).
# Keep ≤3–4 distinct contacts so map cap (~3) stays readable for demos.
_CAST = [
    {
        "kind": "wifi",
        "name": "VisitorPhone",
        "device_type": "unknown_phone",
        "device_label": "Visitor phone hotspot",
        "station_id": "gate-n",
        "mac": "D2:11:22:33:44:55",
        "approach_corridor": "CR-1130 approach",
        "rssi": (-62, -48),
    },
    {
        "kind": "wifi",
        "name": "",
        "device_type": "rogue_ap",
        "device_label": "Hidden rogue AP",
        "station_id": "gate-n",
        "mac": "DE:AD:BE:EF:00:01",
        "approach_corridor": "CR-1130 approach",
        "rssi": (-85, -70),
    },
    {
        "kind": "tracker",
        "name": "KeyFinder",
        "device_type": "tracker_separated",
        "device_label": "Separated key finder",
        "station_id": "ridge-2",
        "mac": "0E:E3:F2:A8:33:7D",
        "rssi": (-58, -45),
        "separated": True,
    },
    {
        "kind": "rid",
        "name": "demo-rid",
        "device_type": "remote_id_drone",
        "device_label": "Demo Remote ID aircraft",
        "station_id": "ridge-2",
        "mac": "FA:0B:BC:F2:F1:41",
        "uas_id": "DEMO8842",
        "rssi": (-72, -55),
        "approach_corridor": "ridge spur",
    },
]


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mac() -> str:
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def _fix_mac(template: str) -> str:
    # Allow short templates with 'FARM' placeholder
    if "FARM" in template:
        return template.replace("FARM", f"{random.randint(0,255):02X}")
    parts = template.split(":")
    if len(parts) == 6:
        return template
    return _mac()


class DemoSim:
    def __init__(self, on_raw: Callable[[dict[str, Any]], None]):
        self._on_raw = on_raw
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._i = 0
        self._loops = 0

    def start(self) -> None:
        if not config.DEMO_ENABLED:
            STATE.demo_enabled = False
            log.info("Demo/sim disabled")
            return
        STATE.demo_enabled = True
        self._thread = threading.Thread(target=self._run, name="demo-sim", daemon=True)
        self._thread.start()
        log.info("Demo/sim ENABLED (interval=%.1fs)", config.DEMO_INTERVAL_SEC)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        self._emit_heartbeat("house")
        # Seed ≤3 suspicious contacts (map cap); rotate the rest over time
        for _ in range(min(3, len(_CAST))):
            self._emit_cast()
        self._emit_halo()
        while not self._stop.wait(config.DEMO_INTERVAL_SEC):
            self._emit_heartbeat(random.choice(DEMO_STATIONS))
            self._emit_cast()
            self._loops += 1
            # One quiet collar refresh — not a BLE flood, not part of the suspicious cast.
            if self._loops % 4 == 0:
                self._emit_halo()

    def _emit_heartbeat(self, station_id: str) -> None:
        raw = {
            "v": 1,
            "station_id": station_id,
            "heard_at": _iso(),
            "radio": "heartbeat",
            "rssi": 0,
            "station_vbat_mv": random.randint(3600, 4200),
            "station_solar_mv": random.randint(0, 6000),
            "name": "demo-hb",
            "device_type": "heartbeat",
        }
        pos = station_positions().get(station_id)
        if pos:
            raw["station_lat"], raw["station_lon"] = pos
        STATE.demo_count += 1
        self._on_raw(raw)

    def _emit_cast(self) -> None:
        spec = _CAST[self._i % len(_CAST)]
        self._i += 1
        # Occasional one-off unknown BLE — kept sparse so default HUD stays readable
        # Rare BLE noise (hidden by default; not a map contact)
        if random.random() < 0.02:
            self._emit_random()
            return
        lo, hi = spec["rssi"]
        rssi = random.randint(lo, hi)
        station = spec["station_id"]
        raw: dict[str, Any] = {
            "v": 1,
            "station_id": station,
            "heard_at": _iso(),
            "mac": _fix_mac(spec["mac"]),
            "mac_kind": "public",
            "rssi": rssi,
            "name": spec["name"],
            "device_type": spec["device_type"],
            "device_label": spec["device_label"],
        }
        if spec.get("approach_corridor"):
            raw["approach_corridor"] = spec["approach_corridor"]

        kind = spec["kind"]
        if kind == "wifi":
            raw.update({"radio": "wifi_ap", "channel": random.choice([1, 6, 11, 36]), "mode": "ap_scan"})
        elif kind == "tracker":
            raw.update(
                {
                    "radio": "ble_adv",
                    "mode": "ble_scan",
                    "service_uuid": "FCB2",
                    "service_data_hex": "0100AABB",
                    "dult_mode": "separated",
                }
            )
        elif kind == "tracker_near":
            raw.update(
                {
                    "radio": "ble_adv",
                    "mode": "ble_scan",
                    "service_uuid": "FEAA",
                    "find_hub_mode": "nearby",
                }
            )
        elif kind == "rid":
            raw.update(
                {
                    "radio": "remote_id",
                    "uas_id": spec.get("uas_id") or f"DEMO{random.randint(1000,9999)}",
                    "rid_status": random.choice(["airborne", "ground", "undeclared"]),
                    "rid_heading_deg": random.uniform(0, 359),
                    "rid_hspeed_mps": random.uniform(2, 22),
                }
            )
            # Place RID roughly along ridge spur
            hlat, hlon = station_positions().get("ridge-2", station_positions()["house-hub"])
            raw["payload_lat"] = hlat + random.uniform(-0.0015, 0.0015)
            raw["payload_lon"] = hlon + random.uniform(-0.0015, 0.0015)

        # Stable-ish map position for recurring cast members
        lat, lon = estimate_contact_latlon(raw)
        raw["lat"], raw["lon"] = lat, lon
        STATE.demo_count += 1
        self._on_raw(raw)

    def _emit_halo(self) -> None:
        """One known-pet demo contact. device_type is inferred (name signature / allowlist)."""
        station = "house"
        raw: dict[str, Any] = {
            "v": 1,
            "station_id": station,
            "heard_at": _iso(),
            "radio": "ble_adv",
            "mode": "ble_scan",
            "mac": "A1:10:C0:11:00:01",  # placeholder; same shape as allowlist.example.json
            "mac_kind": "public",
            "rssi": random.randint(-84, -74),
            "name": "Halo collar",
            "service_uuid": "A110C011-0000-4000-8000-000000000001",
        }
        lat, lon = estimate_contact_latlon(raw)
        raw["lat"], raw["lon"] = lat, lon
        STATE.demo_count += 1
        self._on_raw(raw)

    # Small fixed pool so transient BLE updates in place instead of flooding unique labels.
    _TRANSIENT_POOL = (
        "AA:BB:CC:10:00:01",
        "AA:BB:CC:10:00:02",
        "AA:BB:CC:10:00:03",
    )

    def _emit_random(self) -> None:
        station = random.choice(DEMO_STATIONS)
        raw = {
            "v": 1,
            "station_id": station,
            "heard_at": _iso(),
            "radio": "ble_adv",
            "mac": random.choice(self._TRANSIENT_POOL),
            "mac_kind": "random",
            "rssi": random.randint(-92, -70),  # low-signal noise band
            "name": "",
            "mode": "ble_scan",
            "device_type": "unknown_ble",
            "device_label": "Transient BLE",
        }
        STATE.demo_count += 1
        self._on_raw(raw)
