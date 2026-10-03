"""Farm hub runtime configuration (LAN-only; secrets stay off-git)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # farm/
HUB_DIR = Path(__file__).resolve().parent


def _pick_data_dir() -> Path:
    env = os.environ.get("FIELDWATCH_DATA")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p
    for candidate in (Path("/var/lib/fieldwatch"), Path.home() / "fieldwatch" / "data"):
        try:
            if candidate == Path("/var/lib/fieldwatch"):
                if candidate.exists() and os.access(candidate, os.W_OK):
                    return candidate
                continue
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    p = Path("/tmp/fieldwatch-data")
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA_DIR = _pick_data_dir()
DB_PATH = Path(os.environ.get("FIELDWATCH_DB", str(DATA_DIR / "farm.sqlite")))

ALLOWLIST_PATH = Path(
    os.environ.get(
        "FIELDWATCH_ALLOWLIST",
        str(Path.home() / "fieldwatch" / "allowlist.json"),
    )
)
ALLOWLIST_EXAMPLE = HUB_DIR / "allowlist.example.json"

# Live away-from-home flag. Off-git (next to allowlist.json). Missing file = OFF.
QUIET_HOURS_PATH = Path(
    os.environ.get(
        "FIELDWATCH_QUIET_HOURS",
        str(Path.home() / "fieldwatch" / "quiet-hours.json"),
    )
)

MQTT_HOST = os.environ.get("FIELDWATCH_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("FIELDWATCH_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("FIELDWATCH_MQTT_USER", "hub")
MQTT_PASSWORD = os.environ.get("FIELDWATCH_MQTT_PASSWORD", "")
MQTT_TOPIC = os.environ.get("FIELDWATCH_MQTT_TOPIC", "fieldwatch/station/#")
MQTT_PASSWORD_FILE = Path(
    os.environ.get(
        "FIELDWATCH_MQTT_PASSWORD_FILE",
        str(Path.home() / "fieldwatch" / "mqtt.passwd.env"),
    )
)

SERIAL_PORTS = [
    p
    for p in os.environ.get("FIELDWATCH_SERIAL", "/dev/ttyXIAO,/dev/ttyACM0").split(",")
    if p
]
SERIAL_BAUD = int(os.environ.get("FIELDWATCH_SERIAL_BAUD", "115200"))

# Demo/sim DEFAULT ON so HUD is never empty before nodes arrive.
DEMO_ENABLED = os.environ.get("FIELDWATCH_DEMO", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEMO_INTERVAL_SEC = float(os.environ.get("FIELDWATCH_DEMO_INTERVAL", "8"))

HUD_HOST = os.environ.get("FIELDWATCH_HUD_HOST", "0.0.0.0")
HUD_PORT = int(os.environ.get("FIELDWATCH_HUD_PORT", "8080"))

HEARTBEAT_SEC = float(os.environ.get("FIELDWATCH_HEARTBEAT_SEC", "30"))
NTFY_URL = os.environ.get("FIELDWATCH_NTFY_URL", "")  # stub; empty = no-op

STATIONS_PATH = ROOT / "stations.example.json"
CATALOG_PATH = ROOT / "catalog" / "fieldwatch-signatures-farm.json"
