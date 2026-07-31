"""
paper_analytics/ai_insights.py — Phase 8.2
Advisory AI observations derived from combined analytics datasets.

Generates: most profitable trading window, highest-performing regime,
most reliable strategy, most reliable pre-open score band,
recommended research areas, overall confidence score.

All outputs are INFORMATIONAL ONLY. No trading decisions or modifications
are made by this module.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _best_window(time_data: dict) -> str:
    sessions = time_data.get("sessions", [])
    if not sessions:
        return "N/A"
    best = max(sessions, key=lambda s: s.get("win_rate", 0))
    return best.get("session", "N/A")


def _most_reliable_strategy(strat_data: dict) -> str:
    strategies = strat_data.get("strategies", [])
    qualified  = [s for s in strategies if s.get("total_trades", 0) >= 3]
    if not qualified:
        return strategies[0]["strategy_name"] if strategies else "N/A"
    # Most reliable = highest profit factor among qualified
    best = max(qualified, key=lambda s: s.get("profit_factor", 0))
    return best.get("strategy_name", "N/A")


def _most_reliable_preopen_band(preopen_data: dict) -> str:
    bands = preopen_data.get("score_band_accuracy", [])
    if not bands:
        return "N/A"
    qualified = [b for b in bands if b.get("count", 0) >= 2]
    if not qualified:
        return bands[0]["band"] if bands else "N/A"
    best = max(qualified, key=lambda b: b.get("accuracy", 0))
    return best.get("band", "N/A")


def _research_areas(learning_data: dict, risk_data: dict) -> List[str]:
    areas = []
    if learning_data.get("worst_strategy", "N/A") != "N/A":
        areas.append(f"Investigate underperformance of {learning_data['worst_strategy']} strategy")
    if learning_data.get("worst_sector", "N/A") != "N/A":
        areas.append(f"Review exposure to {learning_data['worst_sector']} sector")
    max_dd = risk_data.get("max_drawdown_pct", 0)
    if max_dd > 10:
        areas.append(f"Drawdown of {max_dd:.1f}% warrants tighter stop-loss review")
    sharpe = risk_data.get("sharpe_ratio", 0)
    if sharpe < 1.0:
        areas.append("Sharpe ratio below 1.0 — consider reducing position size or improving entries")
    if not areas:
        areas.append("Continue monitoring — no critical areas identified with current data")
    return areas


def _overall_confidence(ai_snap: dict, risk_data: dict, trade_data: dict) -> float:
    """Composite advisory confidence score (0–100)."""
    ai_score  = float(ai_snap.get("health_score", 50))
    win_rate  = float(trade_data.get("win_rate", 0))
    sharpe    = float(risk_data.get("sharpe_ratio", 0))
    # Normalise sharpe to 0–100 range (clamp)
    sharpe_n  = min(max(sharpe * 20, 0), 100)
    score = (ai_score * 0.4) + (win_rate * 0.4) + (sharpe_n * 0.2)
    return round(score, 1)


def get_ai_insights(
    time_data: dict,
    strategy_data: dict,
    preopen_data: dict,
    learning_data: dict,
    risk_data: dict,
) -> Dict[str, Any]:
    """
    Generate advisory AI observations from pre-computed analytics dicts.

    All parameters should be the outputs of the corresponding get_*() functions.
    Accepts pre-loaded dicts to avoid redundant computation.
    """
    # AI performance snapshot
    ai_snap: Dict[str, Any] = {}
    try:
        from ai_performance.shared_services import get_ai_snapshot
        ai_snap = get_ai_snapshot()
    except Exception:
        pass

    best_window  = _best_window(time_data)
    best_regime  = learning_data.get("best_market_condition", "N/A")
    best_strat   = _most_reliable_strategy(strategy_data)
    best_band    = _most_reliable_preopen_band(preopen_data)
    research     = _research_areas(learning_data, risk_data)
    confidence   = _overall_confidence(ai_snap, risk_data, {
        "win_rate": strategy_data.get("strategies", [{}])[0].get("win_rate", 0) if strategy_data.get("strategies") else 0
    })

    return {
        "available":                  True,
        "advisory_only":              True,
        "most_profitable_window":     best_window,
        "highest_performing_regime":  best_regime,
        "most_reliable_strategy":     best_strat,
        "most_reliable_preopen_band": best_band,
        "recommended_research_areas": research,
        "confidence_score":           confidence,
        "ai_health_score":            ai_snap.get("health_score"),
        "ai_health_label":            ai_snap.get("health_label"),
        "ai_prediction_accuracy":     ai_snap.get("prediction_accuracy"),
        "ai_trend_direction":         ai_snap.get("trend_direction"),
        "note": (
            "All observations are informational only and do not constitute "
            "trading advice. Advisory / Paper Trading mode only."
        ),
    }
