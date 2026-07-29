"""Phase 7.4 – Macro context explainer (reads Phase 7.3 snapshot, zero re-computation)."""
from __future__ import annotations
from typing import Any, Dict


def explain_macro_context(macro_snap: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Phase 7.3 macro intelligence snapshot into a human-readable narrative."""
    if not macro_snap or not macro_snap.get("available", True):
        return {
            "available": False,
            "narrative": "Macro intelligence data is not available.",
            "bullet_points": [],
            "macro_score": None,
            "grade": "N/A",
            "trend": "UNKNOWN",
            "vix_regime": "UNKNOWN",
            "fii_posture": "UNKNOWN",
            "inflation_risk": "UNKNOWN",
        }

    score = macro_snap.get("macro_score", 0)
    grade = macro_snap.get("grade", "N/A")
    trend = macro_snap.get("trend", "NEUTRAL")
    global_sentiment = macro_snap.get("global_sentiment_score", 50)
    sentiment_label = macro_snap.get("sentiment_label", "NEUTRAL")
    india_vix = macro_snap.get("india_vix", None)
    vix_regime = macro_snap.get("vix_regime", "NORMAL")
    vix_risk = macro_snap.get("vix_risk_level", "LOW")
    fii_posture = macro_snap.get("fii_posture", "NEUTRAL")
    upcoming_events = macro_snap.get("upcoming_events", 0)
    inflation_risk = macro_snap.get("inflation_risk", "LOW")

    # Build narrative
    vix_desc = ""
    if india_vix is not None:
        vix_desc = f" India VIX stands at {india_vix:.1f} ({vix_regime} regime, {vix_risk} risk)."

    fii_map = {
        "BUYING": "net buyers",
        "SELLING": "net sellers",
        "NEUTRAL": "broadly neutral",
    }
    fii_desc = fii_map.get(fii_posture, fii_posture.lower())

    narrative = (
        f"Macro conditions score {score:.0f}/100 (grade {grade}) with a {trend} trend. "
        f"Global sentiment reads {global_sentiment:.0f}/100 ({sentiment_label}).{vix_desc} "
        f"FIIs are {fii_desc} in the current session. "
        f"Inflation risk is assessed as {inflation_risk.lower()}."
    )
    if upcoming_events > 0:
        narrative += f" {upcoming_events} macro event(s) are scheduled in the near term."

    bullet_points = [
        f"Macro score: {score:.0f}/100 ({grade})",
        f"Macro trend: {trend}",
        f"Global sentiment: {global_sentiment:.0f}/100 ({sentiment_label})",
    ]
    if india_vix is not None:
        bullet_points.append(f"India VIX: {india_vix:.1f} ({vix_regime}, {vix_risk} risk)")
    bullet_points += [
        f"FII posture: {fii_posture}",
        f"Inflation risk: {inflation_risk}",
        f"Upcoming macro events: {upcoming_events}",
    ]

    return {
        "available": True,
        "narrative": narrative,
        "bullet_points": bullet_points,
        "macro_score": score,
        "grade": grade,
        "trend": trend,
        "global_sentiment_score": global_sentiment,
        "sentiment_label": sentiment_label,
        "india_vix": india_vix,
        "vix_regime": vix_regime,
        "vix_risk_level": vix_risk,
        "fii_posture": fii_posture,
        "upcoming_events": upcoming_events,
        "inflation_risk": inflation_risk,
    }
