"""
brief.py — Phase 7.2
Generates the Daily Intelligence Brief:
  - Today's important events
  - Stocks requiring attention
  - High-risk stocks
  - High-opportunity stocks
  - Sector highlights
  - Potential volatility events
  - Market summary

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List

from .models import (
    EventRecord, event_grade,
    IMPACT_BULLISH, IMPACT_BEARISH, IMPACT_VOLATILE,
    TYPE_CORPORATE, TYPE_REGULATORY, TYPE_NEWS,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def generate_daily_brief(
    all_events: List[EventRecord],
    intelligence_score: float,
    grade: str,
) -> dict:
    """
    Synthesises a Daily Intelligence Brief from all events.
    """
    today = _today()

    # Filter to high-importance events
    today_events = [e for e in all_events if e.event_date == today and e.importance_score >= 50]
    high_imp_all  = sorted(
        [e for e in all_events if e.importance_score >= 65],
        key=lambda x: x.importance_score, reverse=True
    )

    # Stocks requiring attention: any stock with ≥2 events or high-importance event
    from collections import Counter
    stock_event_counts = Counter(e.symbol for e in all_events if e.symbol)
    attention_stocks = [
        {
            "symbol": symbol,
            "event_count": count,
            "top_event": next(
                (e.title for e in high_imp_all if e.symbol == symbol), None
            ),
        }
        for symbol, count in stock_event_counts.most_common(5)
        if count >= 2 or any(e.symbol == symbol and e.importance_score >= 65 for e in all_events)
    ]

    # High-risk stocks: BEARISH + VOLATILE events
    risk_events = [e for e in high_imp_all if e.impact_direction in (IMPACT_BEARISH, IMPACT_VOLATILE)]
    high_risk = [
        {
            "symbol":    e.symbol,
            "sector":    e.sector,
            "risk":      e.trading_risk or e.title,
            "score":     round(e.importance_score, 1),
            "direction": e.impact_direction,
        }
        for e in risk_events if e.symbol
    ][:5]

    # High-opportunity stocks: BULLISH events
    opp_events = [e for e in high_imp_all if e.impact_direction == IMPACT_BULLISH]
    high_opp = [
        {
            "symbol":      e.symbol,
            "sector":      e.sector,
            "opportunity": e.opportunity or e.title,
            "score":       round(e.importance_score, 1),
        }
        for e in opp_events if e.symbol and e.opportunity
    ][:5]

    # Sector highlights: aggregate by sector
    sector_scores: dict = {}
    sector_events: dict = {}
    for e in all_events:
        for s in e.affected_sectors:
            if s and s != "All":
                sector_scores[s] = max(sector_scores.get(s, 0.0), e.importance_score)
                sector_events.setdefault(s, []).append(e.title[:50])

    sector_highlights = sorted(
        [
            {"sector": s, "max_importance": round(v, 1), "event_count": len(sector_events[s]),
             "top_event": sector_events[s][0] if sector_events[s] else ""}
            for s, v in sector_scores.items()
        ],
        key=lambda x: x["max_importance"],
        reverse=True,
    )[:5]

    # Volatility events
    volatility_events = [
        {"symbol": e.symbol, "title": e.title[:60], "expected_volatility": e.expected_volatility,
         "priority": e.priority}
        for e in sorted(all_events, key=lambda x: x.expected_volatility, reverse=True)
        if e.expected_volatility >= 2.0
    ][:5]

    # Market summary
    bullish_count  = sum(1 for e in all_events if e.impact_direction == IMPACT_BULLISH)
    bearish_count  = sum(1 for e in all_events if e.impact_direction == IMPACT_BEARISH)
    volatile_count = sum(1 for e in all_events if e.impact_direction == IMPACT_VOLATILE)
    total          = len(all_events)

    if total > 0 and bullish_count > bearish_count * 1.5:
        market_tone = "BROADLY BULLISH"
    elif total > 0 and bearish_count > bullish_count * 1.5:
        market_tone = "BROADLY BEARISH"
    elif volatile_count > total * 0.3:
        market_tone = "ELEVATED VOLATILITY"
    else:
        market_tone = "MIXED"

    # Critical alerts: any CRITICAL priority event today or upcoming
    critical_alerts = [
        {"title": e.title, "symbol": e.symbol, "event_date": e.event_date, "risk": e.trading_risk}
        for e in all_events
        if e.priority == "CRITICAL" and e.event_date >= today
    ][:5]

    return {
        "available":           True,
        "generated_at":        _now_iso(),
        "date":                today,
        "intelligence_score":  round(intelligence_score, 1),
        "grade":               grade,
        "market_tone":         market_tone,
        "summary": (
            f"Event Intelligence ({grade}): {total} events analysed. "
            f"{bullish_count} bullish, {bearish_count} bearish, {volatile_count} volatile. "
            f"Market tone: {market_tone}. "
            f"{len(critical_alerts)} critical alerts. Advisory only."
        ),
        "today_important_events": [e.to_dict() for e in today_events[:5]],
        "today_event_count":      len(today_events),
        "stocks_requiring_attention": attention_stocks,
        "high_risk_stocks":       high_risk,
        "high_opportunity_stocks": high_opp,
        "sector_highlights":      sector_highlights,
        "volatility_events":      volatility_events,
        "critical_alerts":        critical_alerts,
        "advisory_only":          True,
    }
