"""LAN MQTT subscriber → ingest_one (station JSON per observation.schema.json)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import config
from state import STATE

log = logging.getLogger("fieldwatch.mqtt")


class MqttIngest:
    def __init__(self, on_raw: Callable[[dict[str, Any]], None]):
        self._on_raw = on_raw
        self._client = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="mqtt-ingest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._client:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _password(self) -> str:
        if config.MQTT_PASSWORD:
            return config.MQTT_PASSWORD
        pf = config.MQTT_PASSWORD_FILE
        if pf.exists():
            for line in pf.read_text().splitlines():
                line = line.strip()
                if line.startswith("FIELDWATCH_MQTT_PASSWORD="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
                if line and not line.startswith("#") and "=" not in line:
                    return line
        return ""

    def _run(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            STATE.mqtt_error = "paho-mqtt not installed"
            log.error(STATE.mqtt_error)
            return

        backoff = 1.0
        while not self._stop.is_set():
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id="fieldwatch-hub",
                    protocol=mqtt.MQTTv311,
                )
            except Exception:
                client = mqtt.Client(client_id="fieldwatch-hub")

            pw = self._password()
            if config.MQTT_USER:
                client.username_pw_set(config.MQTT_USER, pw or None)

            def on_connect(client, userdata, flags, reason_code, properties=None):
                rc = reason_code
                try:
                    ok = int(rc) == 0
                except Exception:
                    ok = getattr(rc, "is_failure", False) is False
                STATE.mqtt_connected = bool(ok)
                STATE.mqtt_error = "" if ok else f"connect rc={rc}"
                if ok:
                    client.subscribe(config.MQTT_TOPIC, qos=0)
                    log.info("MQTT connected; subscribed %s", config.MQTT_TOPIC)
                    backoff_reset()

            def on_disconnect(client, userdata, flags, reason_code, properties=None):
                STATE.mqtt_connected = False
                STATE.mqtt_error = f"disconnected rc={reason_code}"

            def on_message(client, userdata, msg):
                try:
                    raw = json.loads(msg.payload.decode("utf-8", errors="replace"))
                except Exception:
                    log.debug("MQTT non-JSON on %s", msg.topic)
                    return
                if not isinstance(raw, dict):
                    return
                STATE.mqtt_last_msg_at = time.time()
                STATE.mqtt_msg_count += 1
                try:
                    self._on_raw(raw)
                except Exception as e:  # noqa: BLE001
                    log.exception("ingest from MQTT failed: %s", e)

            def backoff_reset():
                nonlocal backoff
                backoff = 1.0

            try:
                client.on_connect = on_connect
                client.on_disconnect = on_disconnect
                client.on_message = on_message
            except Exception:
                pass

            self._client = client
            try:
                log.info("MQTT connecting %s:%s", config.MQTT_HOST, config.MQTT_PORT)
                client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
                client.loop_start()
                while not self._stop.is_set():
                    time.sleep(1)
                    if not STATE.mqtt_connected and self._stop.wait(0.1):
                        break
                client.loop_stop()
                client.disconnect()
            except Exception as e:  # noqa: BLE001
                STATE.mqtt_connected = False
                STATE.mqtt_error = str(e)
                log.warning("MQTT error: %s; retry in %.0fs", e, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60)
