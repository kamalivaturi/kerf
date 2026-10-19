"""Entitlements. Community edition: every feature is free and unlocked.

Paid plans, two ways (both leave free features free):
  1. Built-in licence keys (Lemon Squeezy): the user pastes a key in Settings → Licence; Kerf activates it once,
     re-validates weekly, and keeps working offline for 14 days. Set KERF_LS_PRODUCT to your product id so keys
     from other stores are refused. Mark paid features with tier="pro" in features.py.
  2. Your own provider: KERF_LICENSE_PROVIDER=my_module with entitled(name, tier) -> bool and status() -> dict.

Anything in an open-source client can be patched out: keep the real value (hosted AI, cloud renders, premium
packs) behind your server as well. See docs/MONETIZATION.md.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import time
import urllib.error
import urllib.parse
import urllib.request

from . import media

TIERS = ("free", "pro")
LS = "https://api.lemonsqueezy.com/v1/licenses"
CACHE = media.HOME / "license.json"
WEEK = 7 * 86400


def _provider():
    mod = os.environ.get("KERF_LICENSE_PROVIDER")
    return importlib.import_module(mod) if mod else None


def _ls(action, **data):
    req = urllib.request.Request(f"{LS}/{action}", data=urllib.parse.urlencode(data).encode(),
                                 headers={"Accept": "application/json", "User-Agent": "kerf"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:  # Lemon Squeezy answers errors with a JSON body
        return json.loads(e.read() or b"{}")


def _check_product(meta):
    want = os.environ.get("KERF_LS_PRODUCT")
    if want and str(meta.get("product_id")) != str(want):
        raise PermissionError("this licence key is for a different product")


def _cached():
    try:
        return json.loads(CACHE.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def activate(key):
    r = _ls("activate", license_key=key.strip(), instance_name=platform.node() or "kerf")
    if not r.get("activated"):
        raise PermissionError(r.get("error") or "licence key not accepted")
    _check_product(r.get("meta", {}))
    lic = dict(key=key.strip(), instance=r["instance"]["id"], plan=r["meta"].get("variant_name", "Pro"),
               product=r["meta"].get("product_name", "Kerf"), expires=r["license_key"].get("expires_at"),
               status=r["license_key"].get("status", "active"), checked=time.time())
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(lic), "utf-8")
    return status()


def deactivate():
    lic = _cached()
    if lic:
        _ls("deactivate", license_key=lic["key"], instance_id=lic["instance"])
        CACHE.unlink(missing_ok=True)
    return status()


def _active():
    lic = _cached()
    if not lic:
        return False
    if time.time() - lic.get("checked", 0) > WEEK:  # weekly re-validation; offline grace of two weeks
        try:
            r = _ls("validate", license_key=lic["key"], instance_id=lic["instance"])
            lic.update(status=r.get("license_key", {}).get("status", "invalid") if r.get("valid") else "invalid",
                       checked=time.time())
            CACHE.write_text(json.dumps(lic), "utf-8")
        except OSError:
            return time.time() - lic.get("checked", 0) < 2 * WEEK
    return lic.get("status") in ("active", "on-trial")


def entitled(feature):
    if feature.tier == "free":
        return True
    p = _provider()
    return bool(p.entitled(feature.name, feature.tier)) if p else _active()


def status():
    p = _provider()
    if p:
        return p.status()
    lic = _cached()
    if lic and _active():
        return dict(edition=lic["product"], plan=lic["plan"], expires=lic.get("expires"),
                    key=lic["key"][:4] + "…" + lic["key"][-4:], all_features=True)
    return dict(edition="Community", plan="free", all_features=True)


def check(feature):
    if not entitled(feature):
        raise PermissionError(f"'{feature.title}' needs the {feature.tier} plan")
