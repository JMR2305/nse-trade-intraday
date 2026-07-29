"""Phase 7.4 – Risk explainer (reads Phase 6.4 snapshot, zero re-computation)."""
from __future__ import annotations
from typing import Any, Dict, List


_RISK_DIMENSIONS = [
    ("max_drawdown", "Maximum Drawdown", "downside risk from peak to trough"),
    ("capital_efficiency", "Capital Efficiency", "utilisation of deployed capital"),
    ("diversification_score", "Diversification", "spread of risk across positions"),
    ("correlation_risk", "Correlation Risk", "degree of portfolio correlated movement"),
    ("risk_optimisation_score", "Overall Risk Score", "aggregate risk optimisation level"),
]


def _score_to_level(score: object) -> str:
    try:
        s = float(score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        s = 0.0
    if s >= 80:
        return "LOW"
    if s >= 60:
        return "MODERATE"
    if s >= 40:
        return "ELEVATED"
    return "HIGH"


def _f(value: object, default: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def explain_risk(risk_snap: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Phase 6.4 risk optimisation snapshot into a human-readable risk breakdown."""
    if not risk_snap or not risk_snap.get("available", True):
        return {
            "available": False,
            "narrative": "Risk optimisation data is not available.",
            "dimensions": [],
            "overall_risk_level": "UNKNOWN",
            "grade": "N/A",
        }

    overall_score = _f(risk_snap.get("risk_optimisation_score", 0))
    grade = risk_snap.get("grade", "N/A")
    max_drawdown = _f(risk_snap.get("max_drawdown", 0))
    capital_eff = _f(risk_snap.get("capital_efficiency", 0))
    diversification = _f(risk_snap.get("diversification_score", 0))
    correlation = _f(risk_snap.get("correlation_risk", 0))

    overall_level = _score_to_level(overall_score)

    # Build dimension cards
    raw: Dict[str, float] = {
        "max_drawdown":          max_drawdown,
        "capital_efficiency":    capital_eff,
        "diversification_score": diversification,
        "correlation_risk":      correlation,
        "risk_optimisation_score": overall_score,
    }
    dimensions: List[Dict[str, Any]] = []
    for key, label, description in _RISK_DIMENSIONS:
        val = raw.get(key, 0)
        level = _score_to_level(val)
        dimensions.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "score": val,
                "risk_level": level,
            }
        )

    # Build narrative
    dd_pct = max_drawdown if max_drawdown > 1 else max_drawdown * 100
    narrative = (
        f"Overall risk score is {overall_score:.0f}/100 (grade {grade}, {overall_level} risk). "
        f"Maximum portfolio drawdown is {dd_pct:.1f}%. "
        f"Capital efficiency scores {capital_eff:.0f}/100 and diversification "
        f"scores {diversification:.0f}/100. "
        f"Correlation risk within the portfolio is rated {_score_to_level(correlation).lower()}."
    )

    return {
        "available": True,
        "narrative": narrative,
        "dimensions": dimensions,
        "overall_risk_level": overall_level,
        "overall_score": overall_score,
        "grade": grade,
        "max_drawdown": max_drawdown,
        "capital_efficiency": capital_eff,
        "diversification_score": diversification,
        "correlation_risk": correlation,
    }
