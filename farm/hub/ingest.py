"""House ingest: classify → SQLite → alert decision (Fieldwatch 1.1.16 policy)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from classify import classify, is_rotating_unmatched, load_catalog
from dult import alert_worthy_tracker
from rid import plot_rule

ROOT = Path(__file__).resolve().parents[1]
try:
    from config import DB_PATH as DEFAULT_DB, ALLOWLIST_PATH as _ALLOW_PREF, ALLOWLIST_EXAMPLE
    ALLOWLIST = _ALLOW_PREF if _ALLOW_PREF.exists() else ALLOWLIST_EXAMPLE
except Exception:  # noqa: BLE001 — standalone ingest still works
    DEFAULT_DB = Path("/tmp/fieldwatch-farm.sqlite")
    ALLOWLIST = ROOT / "hub" / "allowlist.example.json"


def open_db(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DEFAULT_DB, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS hears (id INTEGER PRIMARY KEY, heard_at TEXT NOT NULL, station_id TEXT NOT NULL, radio TEXT NOT NULL, mac TEXT, name TEXT, rssi INTEGER, json TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS first_seen (key TEXT PRIMARY KEY, first_at TEXT NOT NULL, station_id TEXT NOT NULL)")
    db.commit()
    return db


def _key(obs: dict[str, Any]) -> str:
    if obs.get("uas_id"):
        return f"uas:{obs['uas_id']}"
    if obs.get("mac"):
        return f"mac:{obs['mac'].upper()}"
    return f"anon:{obs.get('station_id')}:{obs.get('heard_at')}"


def load_allowlist(path: Path | None = None) -> set[str]:
    p = path or ALLOWLIST
    if not p.exists():
        return set()
    doc = json.loads(p.read_text())
    keys = set()
    for row in doc.get("radios") or []:
        if row.get("mac"):
            keys.add(row["mac"].upper())
        if row.get("ssid"):
            keys.add(f"ssid:{(row['ssid'] or '').lower()}")
    return keys


def should_alert(obs: dict[str, Any], first: bool, allow: set[str]) -> tuple[bool, str]:
    if obs.get("radio") == "heartbeat":
        return False, "heartbeat"
    if obs.get("rid_status") == "emergency":
        return True, "rid_emergency"
    if obs.get("payload_lat") is not None and obs.get("radio") == "remote_id":
        return True, "rid_fix"
    if alert_worthy_tracker(obs):
        return True, "tracker_separated"
    if obs.get("dult_mode") == "near_owner" or obs.get("find_hub_mode") == "nearby":
        return False, "tracker_quiet"
    if is_rotating_unmatched(obs):
        return False, "rotating_ble"
    mac = (obs.get("mac") or "").upper()
    ssid = f"ssid:{(obs.get('name') or '').lower()}"
    if mac in allow or ssid in allow:
        return False, "allowlist"
    if obs.get("extra_attention"):
        return True, "extra_attention"
    if first and (obs.get("name") or obs.get("mac_kind") == "public" or obs.get("signature_ids")):
        return True, "first_seen"
    return False, "logged"


def ingest_one(raw, db=None, catalog=None, allow=None):
    catalog = catalog or load_catalog()
    allow = allow if allow is not None else load_allowlist()
    obs = classify(raw, catalog)
    obs["plot"] = plot_rule(obs)
    own = db or open_db()
    key = _key(obs)
    first = own.execute("SELECT first_at FROM first_seen WHERE key=?", (key,)).fetchone() is None
    if first:
        own.execute("INSERT INTO first_seen(key, first_at, station_id) VALUES (?,?,?)", (key, obs.get("heard_at"), obs.get("station_id")))
    alert, reason = should_alert(obs, first, allow)
    obs["alert"], obs["alert_reason"] = alert, reason
    own.execute("INSERT INTO hears(heard_at, station_id, radio, mac, name, rssi, json) VALUES (?,?,?,?,?,?,?)", (obs.get("heard_at"), obs.get("station_id"), obs.get("radio"), obs.get("mac"), obs.get("name"), obs.get("rssi"), json.dumps(obs)))
    own.commit()
    if db is None:
        own.close()
    return obs
