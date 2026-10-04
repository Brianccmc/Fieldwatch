"""Phone alerts via ntfy. No-op unless FIELDWATCH_NTFY_URL is set.

No default topic. Empty or unset URL sends nothing and does not raise.
Pages only for:
- a transition into risk_level critical (not every later hear while it stays critical)
- one new MAC per America/Chicago night (new_mac_tonight)

Trusted farm types never page. Demo seeding never pages. Dedup rows live in
SQLite (phone_alerts). A failed POST is logged and does not crash the hub.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

import config

log = logging.getLogger("fieldwatch.ntfy")

TRUSTED_NO_PAGE = frozenset(
    {
        "heartbeat",
        "halo_collar",
        "trail_cam",
        "flock_camera",
        "known_farm_node",
        "allowlisted",
        "tracker_near",
    }
)


def _url() -> str:
    return (getattr(config, "NTFY_URL", "") or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _contact_key(obs: dict[str, Any]) -> str:
    if obs.get("uas_id"):
        return "uas:%s" % obs["uas_id"]
    mac = (obs.get("mac") or "").strip().upper()
    if mac:
        return "mac:%s" % mac
    name = (obs.get("name") or "").strip().lower()
    return "anon:%s:%s:%s" % (obs.get("station_id") or "", obs.get("radio") or "", name)


def _trusted(obs: dict[str, Any]) -> bool:
    dtype = (obs.get("device_type") or "").strip().lower()
    if dtype in TRUSTED_NO_PAGE:
        return True
    if (obs.get("radio") or "") == "heartbeat":
        return True
    try:
        from risk import match_halo_collar

        if match_halo_collar(obs):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS contact_risk_state ("
        "contact_key TEXT PRIMARY KEY, risk_level TEXT NOT NULL, updated_at TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS phone_alerts ("
        "id INTEGER PRIMARY KEY,"
        "dedup_key TEXT NOT NULL UNIQUE,"
        "kind TEXT NOT NULL,"
        "sent_at TEXT NOT NULL,"
        "night_key TEXT,"
        "contact_key TEXT,"
        "detail TEXT)"
    )


def _claim(db: sqlite3.Connection, dedup_key: str, kind: str, obs: dict[str, Any], night: str | None) -> bool:
    cur = db.execute(
        "INSERT OR IGNORE INTO phone_alerts"
        "(dedup_key, kind, sent_at, night_key, contact_key, detail) VALUES (?,?,?,?,?,?)",
        (
            dedup_key,
            kind,
            _now(),
            night,
            _contact_key(obs),
            json.dumps(
                {
                    "mac": obs.get("mac"),
                    "device_type": obs.get("device_type"),
                    "risk_level": obs.get("risk_level"),
                    "heard_at": obs.get("heard_at"),
                }
            ),
        ),
    )
    return cur.rowcount == 1


def plan_phone_alert(obs: dict[str, Any], db: sqlite3.Connection | None) -> dict[str, Any] | None:
    """Decide and reserve a phone alert. No network. None means send nothing.

    Risk state is updated even when the URL is empty so a later URL does not
    replay history. Dedup rows are inserted only when a send will be attempted.
    """
    if not isinstance(obs, dict) or obs.get("demo"):
        return None
    if db is None:
        return None
    ensure_schema(db)
    trusted = _trusted(obs)
    key = _contact_key(obs)
    level = (obs.get("risk_level") or "").strip().lower()
    prev_row = db.execute(
        "SELECT risk_level FROM contact_risk_state WHERE contact_key=?", (key,)
    ).fetchone()
    prev = (prev_row[0] if prev_row else "") or ""
    db.execute(
        "INSERT INTO contact_risk_state(contact_key, risk_level, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(contact_key) DO UPDATE SET risk_level=excluded.risk_level, updated_at=excluded.updated_at",
        (key, level or prev or "unknown", _now()),
    )

    url = _url()
    if not url or trusted:
        db.commit()
        return None

    kinds: list[str] = []
    night = None
    if level == "critical" and prev != "critical":
        dedup = "crit:%s:%s" % (key, obs.get("heard_at") or _now())
        if _claim(db, dedup, "critical_transition", obs, None):
            kinds.append("critical_transition")

    if obs.get("new_mac_tonight"):
        mac = (obs.get("mac") or "").strip().upper()
        if mac:
            try:
                from geofence import night_key_for

                night = night_key_for(obs.get("heard_at"))
            except Exception:  # noqa: BLE001
                night = (obs.get("heard_at") or "")[:10]
            dedup = "newmac:%s:%s" % (mac, night)
            if _claim(db, dedup, "new_mac", obs, night):
                kinds.append("new_mac")

    db.commit()
    if not kinds:
        return None
    return {
        "url": url,
        "title": _title(obs, kinds),
        "body": _body(obs, kinds, night),
        "priority": "high" if "critical_transition" in kinds else "default",
        "kinds": kinds,
    }


def _title(obs: dict[str, Any], kinds: list[str]) -> str:
    dtype = obs.get("device_type") or "contact"
    if "critical_transition" in kinds and "new_mac" in kinds:
        title = "Fieldwatch critical + new MAC %s" % dtype
    elif "critical_transition" in kinds:
        title = "Fieldwatch critical %s" % dtype
    else:
        title = "Fieldwatch new MAC %s" % dtype
    return str(title)[:80]


def _body(obs: dict[str, Any], kinds: list[str], night: str | None) -> str:
    lines = [
        "kinds=%s" % ",".join(kinds),
        "device_type=%s" % (obs.get("device_type") or ""),
        "risk=%s %s" % (obs.get("risk_score"), obs.get("risk_level") or ""),
        "mac=%s" % (obs.get("mac") or ""),
        "name=%s" % (obs.get("name") or ""),
        "station=%s" % (obs.get("station_id") or ""),
        "radio=%s" % (obs.get("radio") or ""),
        "event=%s" % (obs.get("event") or ""),
        "heard_at=%s" % (obs.get("heard_at") or ""),
    ]
    if night:
        lines.append("night=%s" % night)
    if obs.get("lat") is not None and obs.get("lon") is not None:
        lines.append("lat=%s" % obs.get("lat"))
        lines.append("lon=%s" % obs.get("lon"))
    return "\n".join(lines)


def deliver_phone_alert(
    planned: dict[str, Any] | None,
    sender: Callable[[str, str, str, str], None] | None = None,
) -> bool:
    """POST a planned alert. False on empty plan, empty URL, or HTTP failure."""
    if not planned:
        return False
    url = (planned.get("url") or "").strip()
    if not url:
        return False
    title = str(planned.get("title") or "fieldwatch")[:80]
    body = planned.get("body") or ""
    priority = str(planned.get("priority") or "default")
    if sender is not None:
        try:
            sender(url, title, body, priority)
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("ntfy sender failed: %s", e)
            return False
    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Title": title,
                "Priority": priority,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("ntfy failed: %s", e)
        return False


def maybe_notify(
    obs: dict[str, Any],
    db: sqlite3.Connection | None = None,
    sender: Callable[[str, str, str, str], None] | None = None,
) -> bool:
    """Plan + deliver. Returns True only if a POST was attempted successfully."""
    planned = plan_phone_alert(obs, db)
    if not planned:
        return False
    return deliver_phone_alert(planned, sender=sender)
