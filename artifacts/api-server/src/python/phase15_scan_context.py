"""
phase15_scan_context.py — Phase 15: Unified Scan Context (single source of truth)

Every module/page must consume the exact same scan snapshot. This module reads
the canonical Phase 7 scan cache and exposes ONE consistent context:
scan_id, snapshot_ts, market regime, and per-symbol canonical values
(score, confidence, indicators, sector rank, risk metrics, sizing, strategy).

Read-only: never triggers a scan. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_CACHE = os.path.join(_DIR, "phase7_scan_cache.json")
P13_CACHE = os.path.join(_DIR, "phase13_cache.json")

STALE_AFTER_S = 90 * 60  # 90 minutes — aligned with phase13 stale gate


def _today_ist() -> str:
    """Return today's date in IST (UTC+5:30) as YYYY-MM-DD."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _snapshot_date_ist(snapshot_ts: str) -> Optional[str]:
    """Return the IST date of a snapshot timestamp as YYYY-MM-DD, or None."""
    try:
        dt = _parse_ts(snapshot_ts)
        if dt is None:
            return None
        ist_dt = dt + timedelta(hours=5, minutes=30)
        return ist_dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _load_scan() -> Optional[Dict[str, Any]]:
    """
    Phase 19B: load the canonical scan from the durable shared store
    (Postgres on Autoscale) so every instance sees the same latest snapshot.
    Falls back to the local phase7_scan_cache.json file.
    Reading via the store also refreshes the local file, keeping legacy
    file-based readers in this process consistent.
    """
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()
        if snap:
            return snap
    except Exception:
        pass
    return _load(SCAN_CACHE)


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def canonical_regime() -> str:
    """
    Regime from the canonical Phase 7 scan snapshot itself (majority vote over
    its recommendations). Phase 13's cached regime is only used as a fallback
    when the scan carries no regime information, since it may come from a
    different snapshot time.
    """
    scan = _load_scan() or {}
    regimes: Dict[str, int] = {}
    for r in scan.get("recommendations", []):
        if r.get("regime"):
            regimes[r["regime"]] = regimes.get(r["regime"], 0) + 1
    if regimes:
        return max(regimes, key=lambda k: regimes[k])
    p13 = _load(P13_CACHE) or {}
    reg = (p13.get("last_regime") or {}).get("regime")
    return str(reg) if reg else "UNKNOWN"


def _sector_ranks(recs: List[Dict[str, Any]]) -> Dict[str, int]:
    by_sector: Dict[str, List[float]] = {}
    for r in recs:
        if r.get("error"):
            continue
        by_sector.setdefault(r.get("sector") or "Other", []).append(
            float(r.get("opportunity_score") or 0))
    avg = {s: (sum(v) / len(v) if v else 0.0) for s, v in by_sector.items()}
    ranked = sorted(avg, key=lambda s: avg[s], reverse=True)
    return {s: i + 1 for i, s in enumerate(ranked)}


def scan_age_seconds(scan: Optional[Dict[str, Any]] = None) -> Optional[float]:
    scan = scan if scan is not None else (_load_scan() or {})
    ts = _parse_ts(scan.get("snapshot_ts") or "")
    if ts is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def build_scan_context() -> Dict[str, Any]:
    """The ONE canonical context consumed by all pages."""
    scan = _load_scan()
    if not scan:
        return {"available": False, "reason": "No canonical scan cache found",
                "label": "PAPER / RESEARCH ONLY"}

    recs = scan.get("recommendations", [])
    age_s = scan_age_seconds(scan)
    stale = age_s is None or age_s > STALE_AFTER_S
    ranks = _sector_ranks(recs)
    regime = canonical_regime()

    symbols: Dict[str, Dict[str, Any]] = {}
    for r in recs:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        entry = float(r.get("entry_price") or 0)
        stop = float(r.get("stop_loss") or 0)
        target = float(r.get("target_price") or 0)
        risk_pct = round((entry - stop) / entry * 100, 2) if entry > 0 and stop > 0 else None
        reward_pct = round((target - entry) / entry * 100, 2) if entry > 0 and target > 0 else None
        symbols[sym] = {
            "symbol": sym,
            "sector": r.get("sector"),
            "sector_rank": ranks.get(r.get("sector") or "Other"),
            "final_action": r.get("final_action"),
            "effective_action": ("WATCH" if stale and r.get("final_action") in ("STRONG BUY", "BUY")
                                 else r.get("final_action")),
            "opportunity_score": r.get("opportunity_score"),
            "technical_score": r.get("technical_score"),
            "confidence": r.get("calibrated_confidence"),
            "strategy_id": r.get("strategy_id"),
            "strategy_name": r.get("strategy_name"),
            "regime": r.get("regime"),
            "entry_price": entry, "stop_loss": stop, "target_price": target,
            "rr_ratio": r.get("rr_ratio"),
            "risk_pct": risk_pct, "reward_pct": reward_pct,
            "expected_holding_days": r.get("expected_holding_days"),
            "indicators": {
                "adx": r.get("adx"), "rsi": r.get("rsi"),
                "volume_ratio": r.get("volume_ratio"),
                "above_ema20": r.get("above_ema20"),
                "above_ema50": r.get("above_ema50"),
            },
            "data_quality": r.get("data_quality"),
            "data_age_days": r.get("data_age_days"),
            "bars_available": r.get("bars_available"),
            "gates": {
                "price": r.get("gate_price"), "data_quality": r.get("gate_data_quality"),
                "rr": r.get("gate_rr"), "volume": r.get("gate_volume"),
            },
            "all_gates_passed": r.get("all_gates_passed"),
            "rank": r.get("rank"),
            "error": r.get("error"),
        }

    snap_ts = scan.get("snapshot_ts") or ""
    _snap_date_ist = _snapshot_date_ist(snap_ts)
    _today = _today_ist()
    is_today_session = bool(_snap_date_ist and _snap_date_ist == _today)

    return {
        "available": True,
        "scan_id": scan.get("scan_id"),
        "snapshot_ts": snap_ts,
        "snapshot_date_ist": _snap_date_ist,
        "scan_age_seconds": round(age_s, 0) if age_s is not None else None,
        "stale": stale,
        "stale_after_seconds": STALE_AFTER_S,
        "is_today_session": is_today_session,
        "buy_recommendations_disabled": stale or not is_today_session,
        "market_regime": regime,
        "universe_size": scan.get("universe_size"),
        "duration_s": scan.get("duration_s"),
        "summary": scan.get("summary", {}),
        "scan_audit": scan.get("scan_audit", {}),
        "sector_ranks": ranks,
        "symbols": symbols,
        "label": "PAPER / RESEARCH ONLY",
    }


def symbol_context(symbol: str) -> Dict[str, Any]:
    ctx = build_scan_context()
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}
    sym = symbol.upper()
    item = ctx["symbols"].get(sym)
    if not item:
        return {"available": False, "reason": f"{sym} not in canonical scan {ctx['scan_id']}"}
    return {
        "available": True,
        "scan_id": ctx["scan_id"], "snapshot_ts": ctx["snapshot_ts"],
        "stale": ctx["stale"], "market_regime": ctx["market_regime"],
        "buy_recommendations_disabled": ctx["buy_recommendations_disabled"],
        **item,
        "label": "PAPER / RESEARCH ONLY",
    }
