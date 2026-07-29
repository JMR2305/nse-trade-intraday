"""
watchlist_intelligence.py — Phase 7.1
Per-symbol intelligence: Priority Score, Opportunity Score, Risk Score,
Composite Rank, reason, regime-aware adjustments.

GitHub-inspired enhancements:
  - Regime-aware scoring: scores weighted by current market regime
  - Dynamic prioritisation: recalculated each call, never stale-cached
  - Relative strength: opportunity_score compared to watchlist average

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .hub_models import WatchlistRank, clamp


def analyse_watchlist(scan_items: list, regime: dict) -> dict:
    """
    Generate per-symbol intelligence from scan items.
    Returns ranked list with priority/opportunity/risk/composite scores.
    """
    if not scan_items:
        return _empty_watchlist()

    regime_name = str(regime.get("regime") or "SIDEWAYS").upper()
    adj_buy     = float(regime.get("adj_buy", 1.0) or 1.0)
    adj_sell    = float(regime.get("adj_sell", 1.0) or 1.0)
    is_bull     = "BULL" in regime_name or "TREND" in regime_name
    is_bear     = "BEAR" in regime_name or "HIGH_VOL" in regime_name

    # Compute watchlist average opportunity score for relative strength
    opp_scores = [float(i.get("opportunity_score") or 0.0) for i in scan_items]
    avg_opp    = sum(opp_scores) / len(opp_scores) if opp_scores else 50.0

    ranks: List[WatchlistRank] = []
    for item in scan_items:
        symbol   = str(item.get("stock") or item.get("symbol") or "")
        sector   = str(item.get("sector") or "Unknown")
        price    = float(item.get("price") or 0.0)
        opp_raw  = float(item.get("opportunity_score") or 0.0)
        conf     = float(item.get("confidence") or 0.0)
        action   = str(item.get("final_action") or "IGNORE").upper()
        reason   = str(item.get("signal_reason") or item.get("live_signal") or action)
        atr      = float(item.get("atr") or 0.0)
        adx      = float(item.get("adx") or 20.0)

        # Relative strength vs watchlist average
        rel_strength = (opp_raw - avg_opp + 50.0)
        opp_score = clamp(rel_strength)

        # Priority score: regime-aware
        action_score = {
            "STRONG_BUY": 100.0, "BUY": 75.0,
            "WATCH": 50.0, "IGNORE": 10.0,
        }.get(action, 10.0)
        regime_factor = adj_buy if is_bull else (adj_sell if is_bear else 1.0)
        priority_score = clamp(action_score * regime_factor * (conf / 100) if conf > 0 else action_score * 0.5)

        # Risk score: inverse — higher = riskier
        atr_risk = clamp(atr / max(price, 1.0) * 2000)
        adx_risk = clamp(100.0 - adx)  # low ADX = weak trend = more risk
        risk_score = clamp((atr_risk * 0.6 + adx_risk * 0.4))

        # Composite: balance opportunity and priority, penalise risk
        composite = clamp(opp_score * 0.4 + priority_score * 0.4 - risk_score * 0.2 + 50.0)

        ranks.append(WatchlistRank(
            rank=0,  # set below
            symbol=symbol, sector=sector,
            priority_score=priority_score,
            opportunity_score=opp_score,
            risk_score=risk_score,
            composite_score=composite,
            final_action=action,
            regime_adjusted=(regime_factor != 1.0),
            reason=reason[:200],
            price=price,
        ))

    # Sort by composite score desc, assign ranks
    ranks.sort(key=lambda r: r.composite_score, reverse=True)
    for i, r in enumerate(ranks):
        r.rank = i + 1

    top_opportunities = [r for r in ranks if r.final_action in ("STRONG_BUY", "BUY")][:5]
    highest_risk      = sorted(ranks, key=lambda r: r.risk_score, reverse=True)[:5]

    return {
        "watchlist": [r.to_dict() for r in ranks],
        "total_symbols": len(ranks),
        "top_opportunities": [r.to_dict() for r in top_opportunities],
        "highest_risk": [r.to_dict() for r in highest_risk],
        "regime": regime_name,
        "regime_adjusted": any(r.regime_adjusted for r in ranks),
        "avg_opportunity_score": round(avg_opp, 2),
        "avg_composite_score": round(
            sum(r.composite_score for r in ranks) / len(ranks), 2
        ) if ranks else 0.0,
    }


def _empty_watchlist() -> dict:
    return {
        "watchlist": [], "total_symbols": 0,
        "top_opportunities": [], "highest_risk": [],
        "regime": "UNKNOWN", "regime_adjusted": False,
        "avg_opportunity_score": 0.0, "avg_composite_score": 0.0,
    }
