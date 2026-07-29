"""
impact_engine.py — Phase 7.2
Generates event impact analysis: importance score, confidence score,
expected duration, bullish/bearish/neutral classification,
expected volatility, affected stocks/sectors, historical comparison,
trading risk, and opportunity summary.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List, Optional

from .models import (
    EventRecord, EventRecord,
    TYPE_CORPORATE, TYPE_REGULATORY, TYPE_NEWS,
    CORP_RESULTS, CORP_DIVIDEND, CORP_SPLIT, CORP_BULK_DEAL,
    REG_ASM, REG_FO_BAN,
    NEWS_MARKET, NEWS_ECONOMIC,
    IMPACT_BULLISH, IMPACT_BEARISH, IMPACT_NEUTRAL, IMPACT_VOLATILE,
    priority_from_score, event_grade,
)


# ── Historical comparisons (static advisory database) ────────────────────────

_HISTORICAL_PATTERNS = {
    CORP_RESULTS: {
        "positive": "Historically, positive earnings surprises for NSE large-caps "
                    "produce +2–5% next-session gains, fading within 3 days.",
        "negative": "Negative earnings surprises typically cause -3 to -8% corrections "
                    "sustained over 5 trading sessions.",
        "neutral":  "In-line results show <1% movement in 80% of historical NSE cases.",
    },
    CORP_DIVIDEND: {
        "positive": "Dividend announcements above ₹5/share historically create +0.5–1.5% "
                    "moves on announcement day; price corrects on ex-date.",
        "neutral":  "Regular dividends have minimal price impact; primarily income events.",
    },
    CORP_SPLIT: {
        "positive": "Stock splits historically improve liquidity by 40–60% in first 30 days "
                    "and attract retail participation.",
    },
    CORP_BULK_DEAL: {
        "volatile": "Bulk deals exceeding 2% of equity often create 1–3 day directional "
                    "moves aligned with deal direction.",
    },
    REG_ASM: {
        "bearish": "ASM-listed stocks historically lose 5–15% over 30 days as "
                   "institutional selling pressure increases.",
    },
    REG_FO_BAN: {
        "volatile": "F&O ban periods historically show lower liquidity and higher "
                    "intraday volatility as positions unwind.",
    },
    NEWS_ECONOMIC: {
        "volatile": "RBI rate decisions impact Banking sector ±2–4% on announcement day.",
    },
}


def _get_historical_context(event: EventRecord) -> Optional[str]:
    patterns = _HISTORICAL_PATTERNS.get(event.sub_type, {})
    if not patterns:
        return None
    direction_key = event.impact_direction.lower()
    # Map directions to pattern keys
    key_map = {
        IMPACT_BULLISH: "positive",
        IMPACT_BEARISH: "negative",
        IMPACT_NEUTRAL: "neutral",
        IMPACT_VOLATILE: "volatile",
    }
    return patterns.get(key_map.get(event.impact_direction, "neutral"))


def _get_risk_opportunity(event: EventRecord) -> tuple[str, Optional[str]]:
    """Return (risk_label, opportunity_label) based on event characteristics."""
    risk = event.trading_risk or "Monitor position sizing around this event."
    opp  = event.opportunity

    if event.expected_volatility > 2.0 and not opp:
        if event.impact_direction == IMPACT_BULLISH:
            opp = f"Momentum entry opportunity post-confirmation in {', '.join(event.affected_stocks[:2]) or 'affected stocks'}"
        elif event.impact_direction == IMPACT_BEARISH:
            opp = "Hedging opportunity; consider reducing exposure"

    if not risk:
        risk = "Standard position-sizing rules apply. Advisory only."

    return risk, opp


def generate_impact_analysis(events: List[EventRecord]) -> List[dict]:
    """
    Enrich a list of EventRecord objects with full impact analysis.
    Returns list of impact analysis dicts.
    """
    results = []
    for event in events:
        historical = _get_historical_context(event)
        risk, opp = _get_risk_opportunity(event)

        results.append({
            **event.to_dict(),
            "historical_context":    historical,
            "trading_risk":          risk,
            "opportunity":           opp,
            "impact_summary": {
                "direction":          event.impact_direction,
                "expected_volatility": event.expected_volatility,
                "expected_duration":  event.expected_duration,
                "importance_grade":   event_grade(event.importance_score),
                "confidence_label":   (
                    "HIGH" if event.confidence_score >= 70
                    else "MEDIUM" if event.confidence_score >= 45
                    else "LOW"
                ),
            },
            "advisory_only": True,
        })

    # Sort by importance
    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results


def get_impact_summary(all_events: List[EventRecord]) -> dict:
    """
    Aggregate impact across all events: counts by direction, sector heat,
    top risks, top opportunities.
    """
    if not all_events:
        return {
            "available": True,
            "total_events": 0,
            "direction_counts": {},
            "top_risks": [],
            "top_opportunities": [],
            "sector_heat": {},
            "advisory_only": True,
        }

    direction_counts = {
        IMPACT_BULLISH:  sum(1 for e in all_events if e.impact_direction == IMPACT_BULLISH),
        IMPACT_BEARISH:  sum(1 for e in all_events if e.impact_direction == IMPACT_BEARISH),
        IMPACT_NEUTRAL:  sum(1 for e in all_events if e.impact_direction == IMPACT_NEUTRAL),
        IMPACT_VOLATILE: sum(1 for e in all_events if e.impact_direction == IMPACT_VOLATILE),
    }

    # Sector heat: average importance score per sector
    sector_scores: dict = {}
    sector_counts: dict = {}
    for e in all_events:
        for sector in e.affected_sectors:
            if sector and sector != "All":
                sector_scores[sector] = sector_scores.get(sector, 0) + e.importance_score
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

    sector_heat = {
        s: round(sector_scores[s] / sector_counts[s], 1)
        for s in sector_scores
    }

    # Top risks + opportunities
    top_risks = [
        {"symbol": e.symbol, "title": e.title[:60], "risk": e.trading_risk}
        for e in sorted(all_events, key=lambda x: x.importance_score, reverse=True)
        if e.trading_risk and e.importance_score >= 65
    ][:5]

    top_opps = [
        {"symbol": e.symbol, "title": e.title[:60], "opportunity": e.opportunity}
        for e in sorted(all_events, key=lambda x: x.importance_score, reverse=True)
        if e.opportunity and e.impact_direction == IMPACT_BULLISH
    ][:5]

    return {
        "available":         True,
        "total_events":      len(all_events),
        "direction_counts":  direction_counts,
        "top_risks":         top_risks,
        "top_opportunities": top_opps,
        "sector_heat":       sector_heat,
        "high_importance_count": sum(1 for e in all_events if e.importance_score >= 70),
        "advisory_only":     True,
    }
