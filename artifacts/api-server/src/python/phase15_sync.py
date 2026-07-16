"""
phase15_sync.py — Canonical scan value synchronisation.

After every fresh canonical scan (Run Fresh Scan / scheduled scan) — and
after the intelligence pipeline regenerates its derived caches — this module
overlays the canonical scan values (entry price, stop loss, target, RR ratio,
opportunity score, confidence, regime) onto the derived caches so that every
page (Dashboard, Trade Decisions, Signals, AI Decision, Broker & Execution,
Performance Analytics, Live Data Health) reads the exact same numbers from
the exact same scan_id. No page recalculates these values independently.

Read/write over local caches only. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

_DIR = os.path.dirname(os.path.abspath(__file__))
AI_DECISIONS_CACHE = os.path.join(_DIR, "ai_decisions_cache.json")
OPPORTUNITY_CACHE = os.path.join(_DIR, "opportunity_cache.json")

# Canonical field → cache field for each derived source.
_AI_FIELDS = {
    "entry_price": "entry_price",
    "stop_loss": "stop_loss",
    "target_price": "target",
    "rr_ratio": "rr_ratio",
    "confidence": "calibrated_confidence",
    "regime": "regime",
}
_OPP_FIELDS = {
    "entry_price": "entry_price",
    "stop_loss": "stop_loss",
    "target_price": "target",
    "rr_ratio": "rr_ratio",
    "opportunity_score": "opportunity_score",
    "confidence": "confidence",
    "regime": "regime",
}

# Canonical final_action → AI Decision engine vocabulary.
ACTION_TO_AI_DECISION = {
    "STRONG BUY": "BUY",
    "BUY": "BUY",
    "WATCH": "WATCH",
    "IGNORE": "NO_TRADE",
}


def _load_list(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _overlay(items: List[Dict[str, Any]], canonical: Dict[str, Dict[str, Any]],
             field_map: Dict[str, str]) -> int:
    """Overwrite mapped fields with canonical values. Returns #items updated."""
    updated = 0
    for item in items:
        sym = str(item.get("stock") or item.get("symbol") or "").upper()
        c = canonical.get(sym)
        if not c:
            continue
        changed = False
        for canon_key, cache_key in field_map.items():
            v = c.get(canon_key)
            if v is None:
                continue
            if item.get(cache_key) != v:
                item[cache_key] = v
                changed = True
        # Recommendation semantics from the canonical scan (no page-level
        # recalculation): AI decision vocabulary + opportunity status.
        action = str(c.get("final_action") or "").upper()
        if action:
            if "decision" in item:
                mapped = ACTION_TO_AI_DECISION.get(action, action)
                if item.get("decision") != mapped:
                    item["decision"] = mapped
                    changed = True
            if "status" in item and item.get("status") != action:
                item["status"] = action
                changed = True
        item["scan_id"] = c.get("scan_id") or item.get("scan_id")
        if changed:
            updated += 1
    return updated


def sync_derived_caches() -> Dict[str, Any]:
    """
    Overlay canonical scan values onto ai_decisions_cache.json and
    opportunity_cache.json. Safe to call anytime; no-op when no canonical
    scan exists. Never raises.
    """
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        if not ctx.get("available"):
            return {"success": True, "synced": False,
                    "reason": ctx.get("reason", "No canonical scan")}
        canonical = dict(ctx.get("symbols") or {})
        scan_id = ctx.get("scan_id")
        for c in canonical.values():
            c["scan_id"] = scan_id

        result: Dict[str, Any] = {"success": True, "synced": True,
                                  "scan_id": scan_id}
        for name, path, fmap in (
            ("ai_decision", AI_DECISIONS_CACHE, _AI_FIELDS),
            ("opportunity_scan", OPPORTUNITY_CACHE, _OPP_FIELDS),
        ):
            items = _load_list(path)
            if not items:
                result[name] = {"updated": 0, "items": 0}
                continue
            updated = _overlay(items, canonical, fmap)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(items, f, default=str)
            os.replace(tmp, path)
            result[name] = {"updated": updated, "items": len(items)}
        return result
    except Exception as exc:  # sync must never break the scan pipeline
        return {"success": False, "error": str(exc)[:200]}
