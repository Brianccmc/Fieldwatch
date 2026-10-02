"""Synthetic heartbeats + station observations (DEFAULT ON) so HUD is never empty."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import config
from state import STATE

log = logging.getLogger("fieldwatch.demo")

DEMO_STATIONS = ("house", "gate-n", "ridge-2", "pond")
DEMO_RADIOS = ("wifi_ap", "ble_adv", "remote_id", "heartbeat")


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mac() -> str:
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


class DemoSim:
    def __init__(self, on_raw: Callable[[dict[str, Any]], None]):
        self._on_raw = on_raw
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
        # Immediate seed so HUD fills on first paint.
        self._emit_heartbeat("house")
        self._emit_obs()
        while not self._stop.wait(config.DEMO_INTERVAL_SEC):
            self._emit_heartbeat(random.choice(DEMO_STATIONS))
            self._emit_obs()

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
        }
        STATE.demo_count += 1
        self._on_raw(raw)

    def _emit_obs(self) -> None:
        kind = random.choice(["wifi", "ble", "rid", "tracker"])
        station = random.choice(DEMO_STATIONS)
        if kind == "wifi":
            raw = {
                "v": 1,
                "station_id": station,
                "heard_at": _iso(),
                "radio": "wifi_ap",
                "mac": _mac(),
                "mac_kind": "public",
                "rssi": random.randint(-90, -40),
                "channel": random.choice([1, 6, 11, 36, 149]),
                "name": random.choice(["TrailCam_7", "Flock_ABC", "VisitorPhone", "BarnAP"]),
                "mode": "ap_scan",
            }
        elif kind == "ble":
            raw = {
                "v": 1,
                "station_id": station,
                "heard_at": _iso(),
                "radio": "ble_adv",
                "mac": _mac(),
                "mac_kind": random.choice(["public", "random"]),
                "rssi": random.randint(-95, -45),
                "name": random.choice(["Tile", "AirTag?", "KeyFinder", ""]),
                "mode": "ble_scan",
                "service_uuid": "FCB2",
                "service_data_hex": "01" + ("00" if random.random() < 0.3 else "01") + "AABB",
            }
        elif kind == "rid":
            raw = {
                "v": 1,
                "station_id": station,
                "heard_at": _iso(),
                "radio": "remote_id",
                "mac": "FA:0B:BC:" + _mac()[9:],
                "mac_kind": "public",
                "rssi": random.randint(-85, -50),
                "uas_id": f"DEMO{random.randint(1000,9999)}",
                "rid_status": random.choice(["airborne", "ground", "undeclared"]),
                "rid_heading_deg": random.uniform(0, 359),
                "rid_hspeed_mps": random.uniform(0, 25),
                "name": "demo-rid",
            }
        else:
            raw = {
                "v": 1,
                "station_id": station,
                "heard_at": _iso(),
                "radio": "ble_adv",
                "mac": _mac(),
                "mac_kind": "public",
                "rssi": random.randint(-90, -55),
                "name": "FindHubDemo",
                "service_uuid": "FEAA",
                "find_hub_mode": random.choice(["nearby", "separated"]),
                "mode": "ble_scan",
            }
        STATE.demo_count += 1
        self._on_raw(raw)
