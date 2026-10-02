#!/usr/bin/env python3
"""CLI: fieldwatch-status — print hub /health JSON or local DB summary."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

import config


def main() -> int:
    ap = argparse.ArgumentParser(description="Fieldwatch farm hub status")
    ap.add_argument("--url", default=f"http://127.0.0.1:{config.HUD_PORT}/health")
    ap.add_argument("--db", action="store_true", help="Summarize local SQLite instead of HTTP")
    args = ap.parse_args()
    if args.db:
        path = config.DB_PATH
        if not path.exists():
            print(f"no db at {path}", file=sys.stderr)
            return 1
        con = sqlite3.connect(path)
        hears = con.execute("SELECT COUNT(*) FROM hears").fetchone()[0]
        alerts = con.execute(
            "SELECT COUNT(*) FROM hears WHERE json LIKE '%\"alert\": true%'"
        ).fetchone()[0]
        recent = con.execute(
            "SELECT heard_at, station_id, radio, name, rssi FROM hears ORDER BY id DESC LIMIT 8"
        ).fetchall()
        print(json.dumps({"db": str(path), "hears": hears, "alerts_approx": alerts, "recent": recent}, indent=2))
        return 0
    try:
        with urllib.request.urlopen(args.url, timeout=5) as r:
            print(r.read().decode())
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"health fetch failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
