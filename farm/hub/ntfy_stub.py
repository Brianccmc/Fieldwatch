"""Optional ntfy push stub — no-op unless FIELDWATCH_NTFY_URL is set."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

import config

log = logging.getLogger("fieldwatch.ntfy")


def maybe_notify(obs: dict[str, Any]) -> None:
    if not config.NTFY_URL:
        return
    if not obs.get("alert"):
        return
    title = obs.get("alert_reason") or "fieldwatch"
    body = {
        "station": obs.get("station_id"),
        "radio": obs.get("radio"),
        "name": obs.get("name"),
        "mac": obs.get("mac"),
        "rssi": obs.get("rssi"),
        "reason": obs.get("alert_reason"),
    }
    try:
        req = urllib.request.Request(
            config.NTFY_URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Title": str(title)[:80]},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:  # noqa: BLE001
        log.debug("ntfy stub failed: %s", e)
