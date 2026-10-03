"""House ingest: classify → risk/geo enrich → SQLite → alert decision (Fieldwatch 1.1.16 policy)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from classify import classify, is_rotating_unmatched, load_catalog
from dult import alert_worthy_tracker
from geo import enrich_geometry
from rid import plot_rule
from risk import infer_device_type, match_halo_collar, score_risk

ROOT = Path(__file__).resolve().parents[1]
try:
    from config import DB_PATH as DEFAULT_DB, ALLOWLIST_PATH as _ALLOW_PREF, ALLOWLIST_EXAMPLE
    ALLOWLIST = _ALLOW_PREF if _ALLOW_PREF.exists() else ALLOWLIST_EXAMPLE
except Exception:  # noqa: BLE001 — standalone ingest still works
    DEFAULT_DB = Path("/tmp/fieldwatch-farm.sqlite")
    ALLOWLIST = ROOT / "hub" / "allowlist.example.json"


def open_db(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DEFAULT_DB, check_same_thread=False)
    db.execute(
        "CREATE TABLE IF NOT EXISTS hears ("
        "id INTEGER PRIMARY KEY, heard_at TEXT NOT NULL, station_id TEXT NOT NULL, "
        "radio TEXT NOT NULL, mac TEXT, name TEXT, rssi INTEGER, json TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS first_seen ("
        "key TEXT PRIMARY KEY, first_at TEXT NOT NULL, station_id TEXT NOT NULL)"
    )
    # Safe additive migration for map/risk HUD (existing DBs keep working).
    cols = {r[1] for r in db.execute("PRAGMA table_info(hears)").fetchall()}
    for col, decl in (
        ("device_type", "TEXT"),
        ("risk_score", "INTEGER"),
        ("lat", "REAL"),
        ("lon", "REAL"),
    ):
        if col not in cols:
            db.execute(f"ALTER TABLE hears ADD COLUMN {col} {decl}")
    db.commit()
    return db


def _key(obs: dict[str, Any]) -> str:
    if obs.get("uas_id"):
        return f"uas:{obs['uas_id']}"
    if obs.get("mac"):
        return f"mac:{obs['mac'].upper()}"
    return f"anon:{obs.get('station_id')}:{obs.get('heard_at')}"


class Allowlist(set):
    """Membership set of MAC, ssid:, and uuid: keys.

    halo_macs / halo_uuids are normalized identities whose entry set
    device_type to halo_collar. A plain MAC stays a normal allowlist hit.
    """

    def __init__(self, iterable=()):
        super().__init__(iterable)
        self.halo_macs: set[str] = set()
        self.halo_uuids: set[str] = set()


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":")


def _norm_uuid(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch in "0123456789ABCDEF")


def load_allowlist(path: Path | None = None) -> Allowlist:
    allow = Allowlist()
    p = path or ALLOWLIST
    if not p.exists():
        return allow
    doc = json.loads(p.read_text())
    for row in doc.get("radios") or []:
        if not isinstance(row, dict):
            continue
        dtype = (row.get("device_type") or "").strip().lower()
        mac = _norm_mac(row.get("mac") or "")
        if mac:
            allow.add(mac)
            if dtype == "halo_collar":
                allow.halo_macs.add(mac)
        if row.get("ssid"):
            allow.add(f"ssid:{(row['ssid'] or '').lower()}")
        raw_uuid = row.get("service_uuid") or row.get("uuid") or ""
        uuid = _norm_uuid(str(raw_uuid))
        if uuid:
            allow.add(f"uuid:{uuid}")
            if dtype == "halo_collar":
                allow.halo_uuids.add(uuid)
    return allow


def should_alert(obs: dict[str, Any], first: bool, allow: set[str]) -> tuple[bool, str]:
    if obs.get("radio") == "heartbeat":
        return False, "heartbeat"
    if match_halo_collar(obs, allow):
        return False, "halo_collar"
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
        own.execute(
            "INSERT INTO first_seen(key, first_at, station_id) VALUES (?,?,?)",
            (key, obs.get("heard_at"), obs.get("station_id")),
        )
        obs["first_seen_event"] = True
    alert, reason = should_alert(obs, first, allow)
    obs["alert"], obs["alert_reason"] = alert, reason

    dtype, dlabel = infer_device_type(obs, allow)
    obs["device_type"] = dtype
    obs["device_label"] = obs.get("device_label") or dlabel
    risk = score_risk(obs, device_type=dtype)
    obs.update(risk)
    obs = enrich_geometry(obs)

    own.execute(
        "INSERT INTO hears(heard_at, station_id, radio, mac, name, rssi, json, device_type, risk_score, lat, lon) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            obs.get("heard_at"),
            obs.get("station_id"),
            obs.get("radio"),
            obs.get("mac"),
            obs.get("name"),
            obs.get("rssi"),
            json.dumps(obs),
            obs.get("device_type"),
            obs.get("risk_score"),
            obs.get("lat"),
            obs.get("lon"),
        ),
    )
    own.commit()
    if db is None:
        own.close()
    return obs
