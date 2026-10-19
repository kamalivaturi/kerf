"""Entitlements hook. Community edition: every feature is free and unlocked.

To sell a subscription later, ship a separate (closed) module and point KERF_LICENSE_PROVIDER at it:

    # my_license.py
    def entitled(feature_name: str, tier: str) -> bool: ...   # e.g. validate a key against your server
    def status() -> dict: return {"edition": "Pro", "plan": "monthly", "expires": "2027-01-01"}

Features declare a `tier` ("free" / "pro") in features.py; the server refuses runs that aren't entitled.
"""
from __future__ import annotations

import importlib
import os

TIERS = ("free", "pro")


def _provider():
    mod = os.environ.get("KERF_LICENSE_PROVIDER")
    return importlib.import_module(mod) if mod else None


def entitled(feature):
    p = _provider()
    return True if p is None or feature.tier == "free" else bool(p.entitled(feature.name, feature.tier))


def status():
    p = _provider()
    return p.status() if p else dict(edition="Community", plan="free", all_features=True)


def check(feature):
    if not entitled(feature):
        raise PermissionError(f"'{feature.title}' needs the {feature.tier} plan")
