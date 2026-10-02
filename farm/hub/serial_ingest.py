"""Serial NDJSON from XIAO (/dev/ttyACM0 or /dev/ttyXIAO).

Skips Meshtastic / non-JSON junk until farm firmware speaks NDJSON observations.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import config
from state import STATE

log = logging.getLogger("fieldwatch.serial")


def _looks_like_json_obj(line: str) -> bool:
    s = line.strip()
    return s.startswith("{") and s.endswith("}")


class SerialIngest:
    def __init__(self, on_raw: Callable[[dict[str, Any]], None]):
        self._on_raw = on_raw
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="serial-ingest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _open_port(self):
        import serial

        last_err = None
        for path in config.SERIAL_PORTS:
            try:
                ser = serial.Serial(path, config.SERIAL_BAUD, timeout=1)
                STATE.serial_port = path
                STATE.serial_connected = True
                STATE.serial_error = ""
                log.info("Serial open %s @ %s", path, config.SERIAL_BAUD)
                return ser
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise OSError(last_err or "no serial port")

    def _run(self) -> None:
        try:
            import serial  # noqa: F401
        except ImportError:
            STATE.serial_error = "pyserial not installed"
            log.error(STATE.serial_error)
            return

        backoff = 1.0
        while not self._stop.is_set():
            ser = None
            try:
                ser = self._open_port()
                backoff = 1.0
                buf = ""
                while not self._stop.is_set():
                    chunk = ser.read(256)
                    if not chunk:
                        continue
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_line(line)
            except Exception as e:  # noqa: BLE001
                STATE.serial_connected = False
                STATE.serial_error = str(e)
                log.warning("Serial: %s; retry in %.0fs", e, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                try:
                    if ser:
                        ser.close()
                except Exception:  # noqa: BLE001
                    pass
                STATE.serial_connected = False

    def _handle_line(self, line: str) -> None:
        STATE.serial_last_line_at = time.time()
        if not _looks_like_json_obj(line):
            STATE.serial_junk_count += 1
            return
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            STATE.serial_junk_count += 1
            return
        if not isinstance(raw, dict) or "station_id" not in raw or "radio" not in raw:
            STATE.serial_junk_count += 1
            return
        STATE.serial_json_count += 1
        try:
            self._on_raw(raw)
        except Exception as e:  # noqa: BLE001
            log.exception("ingest from serial failed: %s", e)
