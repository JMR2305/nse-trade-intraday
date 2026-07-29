"""Phase 7.4 – Market context explainer (reads Phase 7.1 snapshot, zero re-computation)."""
from __future__ import annotations
from typing import Any, Dict


def explain_market_context(market_snap: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Phase 7.1 market intelligence snapshot into a human-readable narrative."""
    if not market_snap or not market_snap.get("available", True):
        return {
            "available": False,
            "narrative": "Market intelligence data is not available.",
            "bullet_points": [],
            "health_score": None,
            "grade": "N/A",
            "trend": "UNKNOWN",
            "outlook": "UNAVAILABLE",
        }

    score = market_snap.get("market_health_score", 0)
    grade = market_snap.get("grade", "N/A")
    trend = market_snap.get("trend", "NEUTRAL")
    outlook = market_snap.get("overall_outlook", "NEUTRAL")
    top_opportunity = market_snap.get("top_opportunity", "")

    # Build narrative
    trend_map = {
        "BULLISH": "showing bullish momentum",
        "BEARISH": "under bearish pressure",
        "NEUTRAL": "trading in a neutral range",
        "SIDEWAYS": "moving sideways",
        "VOLATILE": "experiencing elevated volatility",
    }
    trend_desc = trend_map.get(trend, "in an undefined trend")

    narrative = (
        f"The broader market is currently {trend_desc} with a health score of "
        f"{score:.0f}/100 (grade {grade}). "
    )
    if outlook in ("BULLISH", "VERY_BULLISH"):
        narrative += "Overall conditions favour buyers."
    elif outlook in ("BEARISH", "VERY_BEARISH"):
        narrative += "Overall conditions favour caution."
    else:
        narrative += "No clear directional bias is present."

    bullet_points = [
        f"Market health score: {score:.0f}/100 ({grade})",
        f"Current trend: {trend}",
        f"Overall outlook: {outlook}",
    ]
    if top_opportunity:
        bullet_points.append(f"Top opportunity: {top_opportunity}")

    return {
        "available": True,
        "narrative": narrative,
        "bullet_points": bullet_points,
        "health_score": score,
        "grade": grade,
        "trend": trend,
        "outlook": outlook,
        "top_opportunity": top_opportunity,
    }
