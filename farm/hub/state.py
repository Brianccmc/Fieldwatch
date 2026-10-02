"""Shared hub runtime status for HUD / CLI / health."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HubState:
    started_at: float = field(default_factory=time.time)
    hub_ok: bool = True
    last_heartbeat_at: float | None = None
    mqtt_connected: bool = False
    mqtt_last_msg_at: float | None = None
    mqtt_msg_count: int = 0
    mqtt_error: str = ""
    serial_port: str | None = None
    serial_connected: bool = False
    serial_last_line_at: float | None = None
    serial_json_count: int = 0
    serial_junk_count: int = 0
    serial_error: str = ""
    demo_enabled: bool = True
    demo_count: int = 0
    ingest_count: int = 0
    alert_count: int = 0
    last_obs: dict[str, Any] | None = None
    stations_seen: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def touch_station(self, station_id: str | None) -> None:
        if not station_id:
            return
        with self._lock:
            self.stations_seen[station_id] = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "hub_ok": self.hub_ok,
                "uptime_sec": round(now - self.started_at, 1),
                "last_heartbeat_at": self.last_heartbeat_at,
                "mqtt": {
                    "connected": self.mqtt_connected,
                    "last_msg_at": self.mqtt_last_msg_at,
                    "msg_count": self.mqtt_msg_count,
                    "error": self.mqtt_error or None,
                },
                "xiao": {
                    "port": self.serial_port,
                    "connected": self.serial_connected,
                    "last_line_at": self.serial_last_line_at,
                    "json_count": self.serial_json_count,
                    "junk_skipped": self.serial_junk_count,
                    "error": self.serial_error or None,
                },
                "demo": {"enabled": self.demo_enabled, "count": self.demo_count},
                "ingest_count": self.ingest_count,
                "alert_count": self.alert_count,
                "stations_seen": dict(self.stations_seen),
                "last_obs": self.last_obs,
            }


STATE = HubState()
