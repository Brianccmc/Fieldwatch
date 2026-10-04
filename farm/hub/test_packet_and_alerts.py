"""Unit tests for farm-packet ingest and phone-alert policy. No network."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import config
from farm_packet import normalize_farm_packet, parse_serial_line
from ingest import ingest_one, open_db
from ntfy_stub import maybe_notify, plan_phone_alert


def _db() -> sqlite3.Connection:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    return open_db(Path(tmp.name))


class FarmPacketTests(unittest.TestCase):
    def test_meshtastic_text_and_json_are_junk(self):
        self.assertIsNone(parse_serial_line("INFO  | 12:00:00 1234 [Radio] Received packet"))
        self.assertIsNone(parse_serial_line('{"from":1234,"id":9,"channel":0,"payload":"hi"}'))
        self.assertIsNone(parse_serial_line('{"type":"nodeinfo","from":1,"id":2}'))
        self.assertIsNone(normalize_farm_packet(["not", "a", "dict"]))
        self.assertIsNone(normalize_farm_packet({"foo": 1}))

    def test_observation_ndjson_accepted(self):
        line = (
            '{"v":1,"station_id":"xiao-lab","heard_at":"2026-10-02T16:00:01Z",'
            '"radio":"wifi_ap","rssi":-62,"mac":"02:11:22:33:44:55","name":"FixtureCam"}'
        )
        obs = parse_serial_line(line)
        self.assertIsNotNone(obs)
        self.assertEqual(obs["station_id"], "xiao-lab")
        self.assertEqual(obs["radio"], "wifi_ap")
        self.assertNotIn("farm_packet", obs)

    def test_gateway_position_is_known_node_contact(self):
        raw = {
            "node_id": "gate-n",
            "event": "position",
            "battery": 3900,
            "bearing": 210,
        }
        obs = normalize_farm_packet(raw)
        self.assertEqual(obs["station_id"], "gate-n")
        self.assertEqual(obs["device_type"], "known_farm_node")
        self.assertEqual(obs["station_vbat_mv"], 3900)
        self.assertEqual(obs["reported_bearing_deg"], 210.0)
        self.assertIsInstance(obs["lat"], float)
        self.assertIsInstance(obs["lon"], float)
        self.assertTrue(obs["farm_packet"])
        db = _db()
        try:
            stored = ingest_one(obs, db=db, catalog={"fleets": []}, allow=set())
            self.assertEqual(stored["device_type"], "known_farm_node")
            n = db.execute("SELECT COUNT(*) FROM hears WHERE radio!='heartbeat'").fetchone()[0]
            # radio is lora, counted
            self.assertEqual(n, 1)
            row = db.execute("SELECT station_id, radio, json FROM hears").fetchone()
            self.assertEqual(row[0], "gate-n")
            self.assertEqual(row[1], "lora")
        finally:
            db.close()

    def test_gateway_mac_contact_not_dropped(self):
        raw = {
            "node": "ridge-2",
            "event": "contact",
            "lat": 37.046,
            "lon": -91.951,
            "battery_mv": 3700,
            "mac": "AA:BB:CC:DD:EE:10",
            "rssi": -74,
            "radio": "ble_adv",
            "name": "GateTag",
        }
        obs = normalize_farm_packet(raw)
        self.assertEqual(obs["mac"], "AA:BB:CC:DD:EE:10")
        self.assertEqual(obs["radio"], "ble_adv")
        self.assertNotEqual(obs.get("device_type"), "known_farm_node")
        db = _db()
        try:
            stored = ingest_one(obs, db=db, catalog={"fleets": []}, allow=set())
            self.assertEqual(stored["mac"], "AA:BB:CC:DD:EE:10")
            self.assertTrue(stored.get("lat"))
            self.assertNotEqual(stored["device_type"], "heartbeat")
        finally:
            db.close()


class PhoneAlertTests(unittest.TestCase):
    def setUp(self):
        self._url = config.NTFY_URL
        config.NTFY_URL = ""

    def tearDown(self):
        config.NTFY_URL = self._url

    def _obs(self, **kw):
        base = {
            "device_type": "rogue_ap",
            "risk_level": "critical",
            "risk_score": 90,
            "mac": "AA:BB:CC:DD:EE:FF",
            "heard_at": "2026-10-04T03:00:00Z",
            "station_id": "gate-n",
            "radio": "wifi_ap",
            "name": "Hidden",
            "new_mac_tonight": False,
            "lat": 37.04,
            "lon": -91.95,
        }
        base.update(kw)
        return base

    def test_empty_url_sends_nothing(self):
        sent = []
        db = _db()
        try:
            for url in ("", "   ", None):
                config.NTFY_URL = url
                ok = maybe_notify(self._obs(), db, sender=lambda *a: sent.append(a))
                self.assertFalse(ok)
            self.assertEqual(sent, [])
            # state recorded so a later URL does not replay this as a new transition
            config.NTFY_URL = "https://ntfy.example/farm-private"
            ok = maybe_notify(
                self._obs(heard_at="2026-10-04T03:05:00Z"),
                db,
                sender=lambda *a: sent.append(a),
            )
            self.assertFalse(ok)
            self.assertEqual(sent, [])
        finally:
            db.close()

    def test_critical_transition_dedup_and_reentry(self):
        config.NTFY_URL = "https://ntfy.example/farm-private"
        sent = []
        db = _db()
        try:
            obs = self._obs()
            self.assertTrue(maybe_notify(obs, db, sender=lambda *a: sent.append(a)))
            self.assertFalse(maybe_notify(dict(obs, heard_at="2026-10-04T03:01:00Z"), db, sender=lambda *a: sent.append(a)))
            self.assertEqual(len(sent), 1)
            self.assertIn("critical", sent[0][1].lower())
            # leave critical, then return — a new transition may page
            mid = self._obs(risk_level="watch", heard_at="2026-10-04T03:02:00Z")
            self.assertFalse(maybe_notify(mid, db, sender=lambda *a: sent.append(a)))
            again = self._obs(heard_at="2026-10-04T03:03:00Z")
            self.assertTrue(maybe_notify(again, db, sender=lambda *a: sent.append(a)))
            self.assertEqual(len(sent), 2)
        finally:
            db.close()

    def test_trusted_and_demo_do_not_page(self):
        config.NTFY_URL = "https://ntfy.example/farm-private"
        sent = []
        db = _db()
        try:
            for dtype in (
                "trail_cam",
                "flock_camera",
                "known_farm_node",
                "allowlisted",
                "tracker_near",
                "heartbeat",
                "halo_collar",
            ):
                obs = self._obs(device_type=dtype, radio="ble_adv" if dtype == "halo_collar" else "wifi_ap", mac="B1:00:00:00:00:%02d" % (len(dtype)))
                if dtype == "heartbeat":
                    obs["radio"] = "heartbeat"
                self.assertFalse(maybe_notify(obs, db, sender=lambda *a: sent.append(a)))
            demo = self._obs(demo=True, new_mac_tonight=True)
            self.assertFalse(maybe_notify(demo, db, sender=lambda *a: sent.append(a)))
            self.assertEqual(sent, [])
        finally:
            db.close()

    def test_new_mac_once_per_night(self):
        config.NTFY_URL = "https://ntfy.example/farm-private"
        sent = []
        db = _db()
        try:
            obs = self._obs(risk_level="watch", new_mac_tonight=True, heard_at="2026-10-04T04:00:00Z")
            self.assertTrue(maybe_notify(obs, db, sender=lambda *a: sent.append(a)))
            again = self._obs(risk_level="watch", new_mac_tonight=True, heard_at="2026-10-04T05:00:00Z")
            # same Chicago night (CDT, UTC-5): 04:00Z and 05:00Z are both Oct 3 evening... 
            # 2026-10-04T04:00:00Z is Oct 3 23:00 Chicago (UTC-5). 05:00Z is Oct 4 00:00 Chicago.
            # Use two timestamps on the same Chicago date.
            self.assertFalse(
                maybe_notify(
                    self._obs(risk_level="watch", new_mac_tonight=True, heard_at="2026-10-04T04:30:00Z"),
                    db,
                    sender=lambda *a: sent.append(a),
                )
            )
            self.assertEqual(len(sent), 1)
            self.assertIn("new MAC", sent[0][1])
            # plan directly also refuses a second claim
            self.assertIsNone(plan_phone_alert(
                self._obs(risk_level="elevated", new_mac_tonight=True, heard_at="2026-10-04T04:40:00Z"),
                db,
            ))
        finally:
            db.close()

    def test_sender_failure_does_not_raise(self):
        config.NTFY_URL = "https://ntfy.example/farm-private"
        db = _db()
        try:
            def boom(*_a):
                raise OSError("down")
            self.assertFalse(maybe_notify(self._obs(), db, sender=boom))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
