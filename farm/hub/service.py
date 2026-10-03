#!/usr/bin/env python3
"""Long-running Fieldwatch farm hub: MQTT + serial + demo → ingest_one + fighter-jet HUD."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from demo import DemoSim
from geo import load_meta, station_positions
from mqtt_ingest import MqttIngest
from ntfy_stub import maybe_notify
from patterns import compute_patterns, latest_contacts
from geofence import list_new_macs
from heatmap import compute_heatmap
from serial_ingest import SerialIngest
from state import STATE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fieldwatch.hub")

_db_lock = threading.Lock()
_db: sqlite3.Connection | None = None
_catalog = None
_allow: set[str] | None = None
_subscribers: list = []
_sub_lock = threading.Lock()


def _open_db() -> sqlite3.Connection:
    global _db
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    from ingest import open_db

    _db = open_db(config.DB_PATH)
    return _db


def _load_deps() -> None:
    global _catalog, _allow
    from classify import load_catalog
    from ingest import load_allowlist

    _catalog = load_catalog()
    _allow = load_allowlist(config.ALLOWLIST_PATH if config.ALLOWLIST_PATH.exists() else None)


def handle_raw(raw: dict[str, Any]) -> None:
    from ingest import ingest_one

    with _db_lock:
        obs = ingest_one(raw, db=_db, catalog=_catalog, allow=_allow)
    STATE.ingest_count += 1
    if obs.get("alert"):
        STATE.alert_count += 1
    STATE.last_obs = {
        "heard_at": obs.get("heard_at"),
        "station_id": obs.get("station_id"),
        "radio": obs.get("radio"),
        "name": obs.get("name"),
        "mac": obs.get("mac"),
        "rssi": obs.get("rssi"),
        "alert": obs.get("alert"),
        "alert_reason": obs.get("alert_reason"),
        "rid_status": obs.get("rid_status"),
        "dult_mode": obs.get("dult_mode"),
        "find_hub_mode": obs.get("find_hub_mode"),
        "signature_names": obs.get("signature_names"),
        "device_type": obs.get("device_type"),
        "device_label": obs.get("device_label"),
        "risk_score": obs.get("risk_score"),
        "risk_level": obs.get("risk_level"),
        "risk_reasons": obs.get("risk_reasons"),
        "lat": obs.get("lat"),
        "lon": obs.get("lon"),
        "new_mac_tonight": obs.get("new_mac_tonight"),
        "bearing_deg": obs.get("bearing_deg"),
        "range_m": obs.get("range_m"),
        "signal_strength": obs.get("signal_strength"),
    }
    STATE.touch_station(obs.get("station_id"))
    maybe_notify(obs)
    _broadcast({"type": "obs", "obs": STATE.last_obs, "status": STATE.snapshot()})


def _broadcast(msg: dict[str, Any]) -> None:
    data = json.dumps(msg, default=str)
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.wait(config.HEARTBEAT_SEC):
        STATE.last_heartbeat_at = time.time()
        STATE.hub_ok = True
        raw = {
            "v": 1,
            "station_id": "house-hub",
            "heard_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "radio": "heartbeat",
            "rssi": 0,
            "name": "hub",
            "device_type": "heartbeat",
        }
        try:
            handle_raw(raw)
        except Exception as e:  # noqa: BLE001
            log.exception("hub heartbeat ingest failed: %s", e)
        _broadcast({"type": "heartbeat", "status": STATE.snapshot()})


def _row_to_hear(r) -> dict[str, Any]:
    try:
        doc = json.loads(r[7])
    except Exception:
        doc = {}
    return {
        "id": r[0],
        "heard_at": r[1],
        "station_id": r[2],
        "radio": r[3],
        "mac": r[4],
        "name": r[5],
        "rssi": r[6],
        "alert": doc.get("alert"),
        "alert_reason": doc.get("alert_reason"),
        "rid_status": doc.get("rid_status"),
        "dult_mode": doc.get("dult_mode"),
        "find_hub_mode": doc.get("find_hub_mode"),
        "signature_names": doc.get("signature_names"),
        "device_type": doc.get("device_type"),
        "device_label": doc.get("device_label"),
        "risk_score": doc.get("risk_score"),
        "risk_level": doc.get("risk_level"),
        "risk_reasons": doc.get("risk_reasons"),
        "lat": doc.get("lat"),
        "lon": doc.get("lon"),
        "bearing_deg": doc.get("bearing_deg"),
        "range_m": doc.get("range_m"),
        "signal_strength": doc.get("signal_strength"),
    }


def create_app():
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    import asyncio
    import queue

    stop_hb = threading.Event()
    workers: list[Any] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _open_db()
        _load_deps()
        mqtt = MqttIngest(handle_raw)
        serial = SerialIngest(handle_raw)
        demo = DemoSim(handle_raw)
        mqtt.start()
        serial.start()
        demo.start()
        hb = threading.Thread(target=_heartbeat_loop, args=(stop_hb,), name="hub-hb", daemon=True)
        hb.start()
        workers.extend([mqtt, serial, demo])
        log.info(
            "Hub up DB=%s HUD=%s:%s demo=%s",
            config.DB_PATH,
            config.HUD_HOST,
            config.HUD_PORT,
            config.DEMO_ENABLED,
        )
        yield
        stop_hb.set()
        for w in workers:
            try:
                w.stop()
            except Exception:  # noqa: BLE001
                pass
        if _db:
            _db.close()

    app = FastAPI(title="Fieldwatch Farm Hub", lifespan=lifespan)
    static = Path(__file__).resolve().parent / "static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/health")
    def health():
        snap = STATE.snapshot()
        ok = snap["hub_ok"]
        meta = load_meta()
        return JSONResponse(
            {
                "ok": ok,
                "service": "fieldwatch-hub",
                "db": str(config.DB_PATH),
                "demo": snap["demo"],
                "mqtt": snap["mqtt"]["connected"],
                "xiao": snap["xiao"]["connected"],
                "ingest_count": snap["ingest_count"],
                "uptime_sec": snap["uptime_sec"],
                "map": {
                    "address": meta.get("address"),
                    "offline": True,
                    "style": meta.get("style"),
                    "geojson": meta.get("geojson"),
                },
            },
            status_code=200 if ok else 503,
        )

    @app.get("/api/status")
    def api_status():
        snap = STATE.snapshot()
        snap["map"] = load_meta()
        return snap

    @app.get("/api/hears")
    def api_hears(limit: int = 50):
        limit = max(1, min(limit, 500))
        with _db_lock:
            rows = _db.execute(
                "SELECT id, heard_at, station_id, radio, mac, name, rssi, json FROM hears ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_hear(r) for r in rows]

    @app.get("/api/alerts")
    def api_alerts(limit: int = 30):
        hears = api_hears(limit=200)
        return [h for h in hears if h.get("alert")][:limit]

    @app.get("/api/contacts")
    def api_contacts(limit: int = 40):
        limit = max(1, min(limit, 100))
        with _db_lock:
            return latest_contacts(_db, limit=limit)

    @app.get("/api/patterns")
    def api_patterns():
        with _db_lock:
            return compute_patterns(_db)

    @app.get("/api/new-macs")
    def api_new_macs(night: str | None = None, limit: int = 40):
        """Unknown / suspicious first appearance, one row per MAC per Chicago night."""
        with _db_lock:
            return list_new_macs(_db, night_key=night or None, limit=limit)

    @app.get("/api/heatmap")
    def api_heatmap(cell_deg: float = 0.00055, limit: int = 8000):
        """Dwell / revisit bins for the offline HUD overlay. Painting is opt-in."""
        with _db_lock:
            return compute_heatmap(_db, cell_deg=cell_deg, limit_hears=limit)

    @app.get("/api/quiet-hours")
    def api_quiet_hours():
        from quiet_hours import enabled, label_for

        on = enabled()
        return {"enabled": on, "label": label_for(on)}

    @app.post("/api/quiet-hours")
    def api_quiet_hours_set(body: dict):
        """Flip the Pi-local flag. Body: {"enabled": true|false}. Default remains OFF.

        `body` is a builtin annotation so FastAPI binds JSON even though this
        route is nested under create_app (from __future__ import annotations).
        """
        from quiet_hours import label_for, set_enabled

        if not isinstance(body, dict) or "enabled" not in body:
            return JSONResponse({"error": "enabled required"}, status_code=400)
        on = set_enabled(bool(body.get("enabled")))
        return {"enabled": on, "label": label_for(on)}

    @app.get("/api/quiet-hours/log")
    def api_quiet_hours_log(night: str | None = None, limit: int = 40):
        """Low/medium unknowns logged while quiet hours was armed. One MAC per Chicago night."""
        from quiet_hours import list_log

        with _db_lock:
            return list_log(_db, night_key=night or None, limit=limit)

    @app.get("/api/map")
    def api_map():
        meta = load_meta()
        positions = station_positions()
        return {
            **meta,
            "stations": [
                {"id": sid, "lat": lat, "lon": lon} for sid, (lat, lon) in positions.items()
            ],
        }

    @app.get("/api/stations")
    def api_stations():
        path = config.STATIONS_PATH
        registry = {}
        if path.exists():
            try:
                registry = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                registry = {}
        seen = STATE.snapshot()["stations_seen"]
        positions = station_positions()
        stations = []
        for s in registry.get("stations") or []:
            sid = s.get("id")
            latlon = positions.get(sid)
            row = {
                **{k: s.get(k) for k in ("id", "kind", "platform", "role", "radios")},
                "last_heard_at": seen.get(sid),
                "online": bool(seen.get(sid) and time.time() - seen[sid] < 120),
            }
            if latlon:
                row["lat"], row["lon"] = latlon
            elif s.get("lat") is not None:
                row["lat"], row["lon"] = s.get("lat"), s.get("lon")
            stations.append(row)
        for sid, ts in seen.items():
            if not any(x["id"] == sid for x in stations):
                latlon = positions.get(sid)
                row = {
                    "id": sid,
                    "kind": "ephemeral",
                    "last_heard_at": ts,
                    "online": time.time() - ts < 120,
                }
                if latlon:
                    row["lat"], row["lon"] = latlon
                stations.append(row)
        prop = registry.get("property") or {}
        meta = load_meta()
        return {
            "property": prop.get("name") or "Willow Springs tract",
            "address": meta.get("address"),
            "stations": stations,
        }

    @app.get("/api/events")
    async def api_events():
        q: queue.Queue = queue.Queue(maxsize=64)
        with _sub_lock:
            _subscribers.append(q)

        async def gen():
            try:
                yield f"data: {json.dumps({'type': 'hello', 'status': STATE.snapshot()}, default=str)}\n\n"
                while True:
                    try:
                        item = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=15))
                        yield f"data: {item}\n\n"
                    except Exception:
                        yield f"data: {json.dumps({'type': 'ping', 'status': STATE.snapshot()}, default=str)}\n\n"
            finally:
                with _sub_lock:
                    if q in _subscribers:
                        _subscribers.remove(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        q: queue.Queue = queue.Queue(maxsize=64)
        with _sub_lock:
            _subscribers.append(q)
        try:
            await ws.send_text(json.dumps({"type": "hello", "status": STATE.snapshot()}, default=str))
            while True:
                try:
                    item = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=20))
                    await ws.send_text(item)
                except Exception:
                    await ws.send_text(json.dumps({"type": "ping", "status": STATE.snapshot()}, default=str))
        except WebSocketDisconnect:
            pass
        finally:
            with _sub_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return app


def main() -> None:
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=config.HUD_HOST, port=config.HUD_PORT, log_level="info")


if __name__ == "__main__":
    main()
