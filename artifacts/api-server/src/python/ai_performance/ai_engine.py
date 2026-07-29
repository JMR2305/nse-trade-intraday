"""
ai_performance/ai_engine.py — Core data builder for Phase 5D.4.

Converts strategy_intelligence ClosedTrade objects → AISignalRecord objects,
adding AI-specific classification fields (TP/FP/TN/FN, confidence bucket,
date fields for learning analysis).

Reuses strategy_intelligence.strategy_engine.load_all_data() — does NOT
re-implement FIFO matching or sector lookup.

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any

from .ai_models import (
    AISignalRecord, CONFIDENCE_BUCKETS, CONFIDENCE_THRESHOLD,
)

_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST)
    except Exception:
        return None


def _confidence_bucket(conf: float) -> str:
    for label, lo, hi in CONFIDENCE_BUCKETS:
        if lo <= conf < hi:
            return label
    return "Below 60"


def _iso_week(dt: datetime) -> str:
    # ISO year-week: YYYY-Www
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def build_ai_signals(
    rec_map: Optional[Dict[str, str]] = None,
) -> List[AISignalRecord]:
    """
    Load closed trades from strategy_intelligence and enrich each one
    with AI classification fields.

    rec_map: optional {strategy_name: recommendation} from 5D.3 for tagging.
    """
    from strategy_intelligence.strategy_engine import load_all_data

    data   = load_all_data()
    closed = data["closed_trades"]

    if rec_map is None:
        rec_map = {}

    signals: List[AISignalRecord] = []

    for ct in closed:
        conf   = ct.signal_confidence        # 0–1 float
        winner = ct.pnl > 0
        high   = conf >= CONFIDENCE_THRESHOLD

        # Binary classification using confidence threshold
        is_tp = high and winner
        is_fp = high and not winner
        is_tn = not high and not winner
        is_fn = not high and winner

        ist_dt = _to_ist(ct.exit_ts)
        exit_date  = ist_dt.strftime("%Y-%m-%d") if ist_dt else ""
        exit_week  = _iso_week(ist_dt)            if ist_dt else ""
        exit_month = ist_dt.strftime("%Y-%m")     if ist_dt else ""

        sig = AISignalRecord(
            trade_id            = ct.trade_id,
            symbol              = ct.symbol,
            sector              = ct.sector,
            strategy_name       = ct.strategy_name,
            entry_ts            = ct.entry_ts or "",
            exit_ts             = ct.exit_ts  or "",
            exit_date           = exit_date,
            exit_week           = exit_week,
            exit_month          = exit_month,
            pnl                 = ct.pnl,
            pnl_pct             = ct.pnl_pct,
            signal_confidence   = conf,
            confidence_bucket   = _confidence_bucket(conf),
            quality_score       = ct.quality_score,
            market_regime       = ct.market_regime,
            exit_type           = ct.exit_type,
            stop_loss           = ct.stop_loss,
            target              = ct.target,
            entry_price         = ct.entry_price,
            exit_price          = ct.exit_price,
            is_high_confidence  = high,
            is_winner           = winner,
            is_tp               = is_tp,
            is_fp               = is_fp,
            is_tn               = is_tn,
            is_fn               = is_fn,
            strategy_recommendation = rec_map.get(ct.strategy_name, ""),
        )
        signals.append(sig)

    return signals


def load_all_data() -> Dict[str, Any]:
    """
    Authoritative data load for all ai_performance sub-modules.

    Reuses 5D.3 strategy_intelligence profiles for regime/sector context,
    and builds AISignalRecord list for AI-specific analytics.
    """
    from strategy_intelligence.shared_services import (
        get_all_strategy_profiles,
        get_recommendations,
    )

    # Build recommendation map {strategy_name: recommendation}
    try:
        recs    = get_recommendations()
        rec_map = {r["strategy_name"]: r["recommendation"] for r in recs}
    except Exception:
        rec_map = {}

    # Build AI signal records (wraps 5D.3 ClosedTrade with AI fields)
    signals = build_ai_signals(rec_map)

    # Reuse 5D.3 profiles (already ranked + recommended) for regime/sector/timing context
    try:
        profiles = get_all_strategy_profiles()
    except Exception:
        profiles = []

    return {
        "signals":  signals,
        "profiles": profiles,
        "rec_map":  rec_map,
    }
