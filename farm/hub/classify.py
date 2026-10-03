"""Match a hear against the farm catalog subset (Fieldwatch 1.1.16 / catalog 88)."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from dult import decode_fcb2

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "fieldwatch-signatures-farm.json"
QUIET_FLEETS = {"Flock Safety Cameras", "LiteOn camera radio"}


def _norm_mac(mac: str | None) -> str:
    return (mac or "").upper().replace("-", ":")


def _oui(mac: str | None) -> str:
    parts = _norm_mac(mac).split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 else ""


def _radio_ok(rule_radio: str | None, obs_radio: str) -> bool:
    rr = (rule_radio or "").upper()
    if not rr or rr == "NONE":
        return True
    if rr == "WIFI":
        return obs_radio.startswith("wifi") or obs_radio == "remote_id"
    if rr == "BLE":
        return obs_radio in {"ble_adv", "remote_id"}
    return True


def _name_hit(kind: str, text: str, name: str) -> bool:
    if not text:
        return False
    n, t = name or "", text
    if kind == "NAME_CONTAINS":
        return t.lower() in n.lower()
    if kind == "NAME_GLOB":
        return fnmatch.fnmatch(n, t) or fnmatch.fnmatch(n.lower(), t.lower())
    return False


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or CATALOG
    if not p.exists() or p.stat().st_size == 0:
        return {"fleets": []}
    with p.open() as f:
        return json.load(f)


def classify(obs: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    cat = catalog or load_catalog()
    name = obs.get("name") or ""
    mac = _norm_mac(obs.get("mac"))
    oui = obs.get("oui") or _oui(mac)
    radio = obs.get("radio") or ""
    svc = (obs.get("service_uuid") or "").upper()
    svc_data = (obs.get("service_data_hex") or "").upper()
    vendor_ie = (obs.get("vendor_ie_oui") or "").upper()
    ids, names, extra, extra_fam = [], [], False, []
    for fleet in cat.get("fleets") or []:
        if not fleet.get("enabled", True):
            continue
        hit = False
        for rule in fleet.get("rules") or []:
            if not rule.get("enabled", True) or not _radio_ok(rule.get("radio"), radio):
                continue
            kind, text = rule.get("kind"), rule.get("text") or ""
            if kind == "OUI" and oui and oui.upper() == text.upper():
                hit = True
            elif kind in {"NAME_CONTAINS", "NAME_GLOB"} and _name_hit(kind, text, name):
                hit = True
            elif kind == "SERVICE_UUID" and svc and svc.upper() == text.upper():
                hit = bool(svc_data) if text.upper() == "FCB2" else True
            elif kind == "SERVICE_DATA" and svc == "FCB2" and svc_data:
                hit = True
            elif kind == "VENDOR_IE_OUI" and vendor_ie.replace("-", ":") == text.upper():
                hit = True
            if hit:
                break
        if not hit:
            continue
        fid = fleet.get("id") or fleet.get("name")
        ids.append(fid)
        names.append(fleet.get("name") or fid)
        if fleet.get("attentionNote") and fleet.get("name") not in QUIET_FLEETS:
            extra = True
            extra_fam.append(fleet.get("name"))
    # Built-in Halo collar signature (catalog-style NAME hit). Product phrase
    # only — bare "Halo" and unnamed random BLE do not match. Quiet: not extra attention.
    if radio == "ble_adv" or radio.startswith("ble"):
        if "halo collar" in name.lower() and "halo-collar" not in ids:
            ids.append("halo-collar")
            names.append("Halo Collar")
    out = dict(obs)
    out["signature_ids"] = ids[:8]
    out["signature_names"] = names[:8]
    out["extra_attention"] = extra
    out["extra_attention_families"] = extra_fam[:8]
    if svc == "FCB2" and svc_data:
        dec = decode_fcb2(svc_data)
        if dec:
            out.update(dec)
    return out


def is_rotating_unmatched(obs: dict[str, Any]) -> bool:
    if obs.get("signature_ids") or obs.get("name"):
        return False
    return obs.get("mac_kind") == "random"
