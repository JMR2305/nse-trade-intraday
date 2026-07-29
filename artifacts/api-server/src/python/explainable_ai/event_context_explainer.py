"""Phase 7.4 – Event context explainer (reads Phase 7.2 snapshot, zero re-computation)."""
from __future__ import annotations
from typing import Any, Dict


def explain_event_context(event_snap: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Phase 7.2 event intelligence snapshot into a human-readable narrative."""
    if not event_snap or not event_snap.get("available", True):
        return {
            "available": False,
            "narrative": "Event intelligence data is not available.",
            "bullet_points": [],
            "intelligence_score": None,
            "grade": "N/A",
            "total_events": 0,
            "high_priority_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "net_sentiment": "NEUTRAL",
        }

    score = event_snap.get("intelligence_score", 0)
    grade = event_snap.get("grade", "N/A")
    total = event_snap.get("total_events", 0)
    high_priority = event_snap.get("high_priority_count", 0)
    bullish = event_snap.get("bullish_count", 0)
    bearish = event_snap.get("bearish_count", 0)

    # Derive net sentiment
    if bullish > bearish:
        net_sentiment = "BULLISH"
        sentiment_desc = "leaning bullish"
    elif bearish > bullish:
        net_sentiment = "BEARISH"
        sentiment_desc = "leaning bearish"
    else:
        net_sentiment = "NEUTRAL"
        sentiment_desc = "balanced"

    # Build narrative
    if total == 0:
        narrative = "No significant market events are currently tracked."
    else:
        narrative = (
            f"There are {total} tracked market event(s) today with an event intelligence "
            f"score of {score:.0f}/100 (grade {grade}). "
            f"Sentiment is {sentiment_desc} ({bullish} bullish vs {bearish} bearish events). "
        )
        if high_priority > 0:
            narrative += f"{high_priority} high-priority event(s) warrant close attention."
        else:
            narrative += "No high-priority events require immediate attention."

    bullet_points = [
        f"Event intelligence score: {score:.0f}/100 ({grade})",
        f"Total tracked events: {total}",
        f"High-priority events: {high_priority}",
        f"Bullish / Bearish: {bullish} / {bearish}",
        f"Net event sentiment: {net_sentiment}",
    ]

    return {
        "available": True,
        "narrative": narrative,
        "bullet_points": bullet_points,
        "intelligence_score": score,
        "grade": grade,
        "total_events": total,
        "high_priority_count": high_priority,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "net_sentiment": net_sentiment,
    }
