"""Phase 7.4 – Confidence decomposition across 8 evidence dimensions."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import ConfidenceDecomposition


_DIMENSIONS = [
    ("technical_score",    "Technical Analysis",   "RSI, MACD, Bollinger Bands, moving averages"),
    ("fundamental_score",  "Fundamental Quality",  "earnings, valuation multiples, sector health"),
    ("market_score",       "Market Health",        "breadth, advance-decline, sector rotation"),
    ("event_score",        "Event Risk",           "corporate actions, economic calendar, news"),
    ("macro_score",        "Macro Environment",    "VIX, FII posture, global sentiment, inflation"),
    ("risk_score",         "Risk Profile",         "drawdown, capital efficiency, diversification"),
    ("regime_score",       "Regime Alignment",     "strategy-regime compatibility and historical fit"),
    ("historical_score",   "Historical Pattern",   "similarity to past setups that performed well"),
]


def _weight(signal: Dict[str, Any]) -> Dict[str, float]:
    """Derive per-dimension weights from the available signal fields."""
    explanation = signal.get("explanation", {}) or {}
    # explanation values are human-readable strings — use confidence as proxy
    confidence  = float(signal.get("confidence", 0.5) or 0.5)
    # Normalise confidence to 0-1
    if confidence > 1.0:
        confidence = confidence / 100.0
    regime      = signal.get("regime", "NEUTRAL") or "NEUTRAL"

    # technical: proxy from confidence (signal quality)
    technical   = min(100.0, max(0.0, confidence * 100))
    fundamental = 50.0                         # no fundamental pipeline yet → neutral
    market_raw  = 50.0                         # will be overridden from market snap
    event_raw   = 60.0                         # event feed not wired per-symbol → neutral
    macro_raw   = 55.0                         # will be overridden by caller
    risk_raw    = 65.0                         # will be overridden by caller
    regime_raw  = (
        85.0 if regime in ("TRENDING_UP", "MOMENTUM")
        else 40.0 if regime in ("TRENDING_DOWN", "HIGH_VOLATILITY")
        else 60.0
    )
    historical  = min(100.0, max(0.0, confidence * 100))

    return {
        "technical_score":   round(technical,   1),
        "fundamental_score": round(fundamental, 1),
        "market_score":      round(market_raw,  1),
        "event_score":       round(event_raw,   1),
        "macro_score":       round(macro_raw,   1),
        "risk_score":        round(risk_raw,    1),
        "regime_score":      round(regime_raw,  1),
        "historical_score":  round(historical,  1),
    }


def _narrative(decomp: "ConfidenceDecomposition") -> str:
    dims = sorted(
        [
            ("Technical Analysis",   decomp.technical_score),
            ("Fundamental Quality",  decomp.fundamental_score),
            ("Market Health",        decomp.market_score),
            ("Event Risk",           decomp.event_score),
            ("Macro Environment",    decomp.macro_score),
            ("Risk Profile",         decomp.risk_score),
            ("Regime Alignment",     decomp.regime_score),
            ("Historical Pattern",   decomp.historical_score),
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    top    = dims[0]
    bottom = dims[-1]
    level  = "strong" if decomp.overall_confidence >= 70 else (
             "moderate" if decomp.overall_confidence >= 45 else "weak"
    )
    return (
        f"Overall confidence is {decomp.overall_confidence:.0f}% ({level}). "
        f"The strongest supporting dimension is {top[0]} ({top[1]:.0f}/100) "
        f"while {bottom[0]} ({bottom[1]:.0f}/100) provides the least support. "
        f"Confidence reliability is rated {decomp.reliability_grade}."
    )


def compute_confidence(
    symbol: str,
    signal: Dict[str, Any],
    market_snap: Dict[str, Any],
    macro_snap: Dict[str, Any],
    risk_snap: Dict[str, Any],
) -> ConfidenceDecomposition:
    """Decompose signal confidence into 8 evidence dimensions."""
    scores = _weight(signal)

    # Override with live snapshot data where available
    if market_snap and market_snap.get("available", True):
        scores["market_score"] = round(
            float(market_snap.get("market_health_score", scores["market_score"])), 1
        )
    if macro_snap and macro_snap.get("available", True):
        scores["macro_score"] = round(
            float(macro_snap.get("macro_score", scores["macro_score"])), 1
        )
    if risk_snap and risk_snap.get("available", True):
        scores["risk_score"] = round(
            float(risk_snap.get("risk_optimisation_score", scores["risk_score"])), 1
        )

    weights = [0.20, 0.10, 0.15, 0.10, 0.15, 0.15, 0.10, 0.05]
    overall = sum(
        scores[k] * w
        for k, w in zip(
            [d[0] for d in _DIMENSIONS], weights
        )
    )
    overall = round(min(100.0, max(0.0, overall)), 1)

    if overall >= 75:
        grade = "A"
    elif overall >= 60:
        grade = "B"
    elif overall >= 45:
        grade = "C"
    elif overall >= 30:
        grade = "D"
    else:
        grade = "F"

    decomp = ConfidenceDecomposition(
        symbol=symbol,
        overall_confidence=overall,
        reliability_grade=grade,
        technical_score=scores["technical_score"],
        fundamental_score=scores["fundamental_score"],
        market_score=scores["market_score"],
        event_score=scores["event_score"],
        macro_score=scores["macro_score"],
        risk_score=scores["risk_score"],
        regime_score=scores["regime_score"],
        historical_score=scores["historical_score"],
        narrative="",
        dimension_details=[
            {
                "key":         d[0],
                "label":       d[1],
                "description": d[2],
                "score":       scores[d[0]],
                "weight_pct":  round(w * 100, 0),
            }
            for d, w in zip(_DIMENSIONS, weights)
        ],
    )
    decomp.narrative = _narrative(decomp)
    return decomp
