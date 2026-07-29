"""
macro_impact_engine.py — Phase 7.3
Per-event macro impact analysis: scoring, affected sectors/industries,
historical comparisons, risks and opportunities.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List, Dict, Any

from .models import MacroEvent, PRI_CRITICAL, PRI_HIGH, PRI_MEDIUM, PRI_LOW


# ── Historical pattern database ───────────────────────────────────────────────

_HISTORICAL_PATTERNS: Dict[str, dict] = {
    "RBI_POLICY": {
        "avg_move_pct": 0.9,
        "max_move_pct": 2.5,
        "typical_duration": "2D",
        "historical_note": (
            "RBI rate decisions average 0.9% Nifty move. Surprises (vs expectation) "
            "cause 1.5–2.5% moves. IT and Banking lead in either direction."
        ),
    },
    "CPI": {
        "avg_move_pct": 0.4,
        "max_move_pct": 1.2,
        "typical_duration": "1D",
        "historical_note": (
            "CPI prints historically move Banking/NBFC by 0.5–1.2%. "
            "Above 6% → hawkish rate expectations → Banking sell-off."
        ),
    },
    "GDP": {
        "avg_move_pct": 0.7,
        "max_move_pct": 2.0,
        "typical_duration": "2D",
        "historical_note": (
            "GDP surprises > ±0.5 pp drive 1–2% Nifty move. "
            "Strong GDP favours Capital Goods, Infrastructure, Banking."
        ),
    },
    "GOVT_BUDGET": {
        "avg_move_pct": 2.5,
        "max_move_pct": 5.0,
        "typical_duration": "5D",
        "historical_note": (
            "Union Budget is the year's highest-volatility event. "
            "Sector-specific announcements drive 5–15% moves in affected stocks."
        ),
    },
    "GLOBAL_EVENT": {
        "avg_move_pct": 0.6,
        "max_move_pct": 1.8,
        "typical_duration": "2D",
        "historical_note": (
            "US Fed surprises cause 0.5–1.5% GIFT Nifty gap. "
            "Rate hike → FII outflow; rate cut → EM inflow rally."
        ),
    },
    "IIP": {
        "avg_move_pct": 0.3,
        "max_move_pct": 0.8,
        "typical_duration": "1D",
        "historical_note": "IIP above consensus favours Capital Goods, Metals, Manufacturing stocks.",
    },
    "PMI": {
        "avg_move_pct": 0.4,
        "max_move_pct": 1.0,
        "typical_duration": "1D",
        "historical_note": "PMI > 55 correlates with 2–3% market outperformance over subsequent month.",
    },
    "TRADE_BALANCE": {
        "avg_move_pct": 0.2,
        "max_move_pct": 0.6,
        "typical_duration": "1D",
        "historical_note": "Trade deficit widening pressures INR; bearish for importers, bullish for exporters.",
    },
    "WPI": {
        "avg_move_pct": 0.2,
        "max_move_pct": 0.5,
        "typical_duration": "1D",
        "historical_note": "WPI divergence from CPI signals supply-chain pressure; metals and chemicals affected.",
    },
}

_DEFAULT_PATTERN = {
    "avg_move_pct": 0.3,
    "max_move_pct": 0.8,
    "typical_duration": "1D",
    "historical_note": "No specific historical pattern available for this event type.",
}


def _get_pattern(sub_type: str) -> dict:
    return _HISTORICAL_PATTERNS.get(sub_type, _DEFAULT_PATTERN)


def _volatility_impact_label(importance: float, historical_avg: float) -> str:
    expected_move = importance / 100 * historical_avg * 1.5
    if expected_move >= 2.0:   return "EXTREME"
    if expected_move >= 1.0:   return "HIGH"
    if expected_move >= 0.4:   return "MEDIUM"
    return "LOW"


def _risk_description(event: MacroEvent, pattern: dict) -> str:
    risks = []
    if event.importance_score >= 80:
        risks.append(f"High-impact event — average Nifty move {pattern['avg_move_pct']}%.")
    if event.expected_volatility in ("HIGH", "EXTREME"):
        risks.append("Options IV likely to spike before announcement.")
    if event.direction == "BEARISH":
        risks.append("Bearish expected direction — consider reducing long exposure.")
    if event.priority == PRI_CRITICAL:
        risks.append("Critical event — position sizing reduction advisable.")
    return " ".join(risks) if risks else "Moderate risk — standard management applies."


def _opportunity_description(event: MacroEvent, pattern: dict) -> str:
    opps = []
    if event.direction == "BULLISH":
        opps.append(f"Bullish catalyst — {', '.join(event.affected_sectors[:3])} expected to benefit.")
    if event.importance_score >= 80:
        opps.append("High-importance: post-announcement momentum trade possible.")
    if event.sub_type == "RBI_POLICY" and event.direction != "BEARISH":
        opps.append("RBI event: watch Banking/NBFC for breakout on rate cut.")
    return " ".join(opps) if opps else "Monitor for post-event sector rotation."


def generate_impact_analysis(events: List[MacroEvent]) -> List[dict]:
    """
    Generate full impact analysis for a list of MacroEvents.
    Returns sorted by importance (highest first).
    """
    results = []
    for event in sorted(events, key=lambda e: e.importance_score, reverse=True):
        pattern  = _get_pattern(event.sub_type)
        vol_lbl  = _volatility_impact_label(event.importance_score, pattern["avg_move_pct"])
        risk_txt = event.trading_risk or _risk_description(event, pattern)
        opp_txt  = event.opportunity  or _opportunity_description(event, pattern)

        results.append({
            **event.to_dict(),
            "impact_summary": {
                "expected_move_avg_pct":  pattern["avg_move_pct"],
                "expected_move_max_pct":  pattern["max_move_pct"],
                "volatility_impact":      vol_lbl,
                "typical_duration":       pattern["typical_duration"],
            },
            "historical_context": event.historical_context or pattern["historical_note"],
            "risk_description":   risk_txt,
            "opportunity_text":   opp_txt,
            "advisory_only":      True,
        })
    return results


def get_impact_summary(events: List[MacroEvent]) -> dict:
    """Aggregated impact summary across all events."""
    if not events:
        return {
            "total_events":     0,
            "direction_counts": {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0, "VOLATILE": 0},
            "avg_importance":   0.0,
            "max_importance":   0.0,
            "sector_heat":      {},
            "high_risk_events": [],
            "top_opportunities":[],
            "available":        True,
        }

    direction_counts: Dict[str, int] = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0, "VOLATILE": 0}
    sector_heat: Dict[str, List[float]] = {}

    for e in events:
        d = e.direction
        direction_counts[d] = direction_counts.get(d, 0) + 1
        for sector in e.affected_sectors:
            sector_heat.setdefault(sector, []).append(e.importance_score)

    avg_imp = sum(e.importance_score for e in events) / len(events)
    max_imp = max(e.importance_score for e in events)

    sector_avg = {
        s: round(sum(scores) / len(scores), 1)
        for s, scores in sector_heat.items()
    }

    high_risk = [
        e.to_dict() for e in events
        if e.priority in (PRI_CRITICAL, PRI_HIGH) and
           e.direction in ("BEARISH", "VOLATILE")
    ][:5]

    top_opps = [
        e.to_dict() for e in sorted(events, key=lambda x: x.importance_score, reverse=True)
        if e.direction == "BULLISH"
    ][:5]

    return {
        "total_events":      len(events),
        "direction_counts":  direction_counts,
        "avg_importance":    round(avg_imp, 1),
        "max_importance":    round(max_imp, 1),
        "sector_heat":       sector_avg,
        "high_risk_events":  high_risk,
        "top_opportunities": top_opps,
        "available":         True,
    }
