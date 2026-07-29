"""
learning_analyser.py — Phase 6.3
Track AI learning progress over time.

Metrics: improvement rate, regression rate, learning velocity,
         consistency trend, confidence trend, adaptive trend.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List


def analyse_learning(records: list) -> dict:
    if len(records) < 5:
        return _empty()

    sorted_recs = sorted(records, key=lambda r: r.timestamp)

    # Split into 4 equal time buckets
    n = len(sorted_recs)
    chunk = max(n // 4, 1)
    buckets = [sorted_recs[i:i + chunk] for i in range(0, n, chunk)]
    if len(buckets) > 4:
        # merge overflow into last bucket
        buckets = buckets[:4]
        buckets[-1] = sorted_recs[chunk * 3:]

    win_rates = [_win_rate(b) for b in buckets]
    confidences = [_avg_conf(b) for b in buckets]

    improvement_rate = _improvement_rate(win_rates)
    regression_rate  = _regression_rate(win_rates)
    velocity         = _velocity(win_rates)
    consistency_trend = _trend_label(win_rates, threshold=0.03)
    confidence_trend  = _trend_label(confidences, threshold=0.02)
    adaptive_trend    = _adaptive(improvement_rate, regression_rate, velocity)

    # Rolling history for chart (per-bucket)
    history = [
        {
            "period": f"Period {i + 1}",
            "win_rate": round(win_rates[i], 4),
            "avg_confidence": round(confidences[i], 4),
            "trade_count": len(buckets[i]),
        }
        for i in range(len(buckets))
    ]

    return {
        "improvement_rate": round(improvement_rate, 4),
        "regression_rate": round(regression_rate, 4),
        "learning_velocity": round(velocity, 4),
        "consistency_trend": consistency_trend,
        "confidence_trend": confidence_trend,
        "adaptive_trend": adaptive_trend,
        "history": history,
        "periods_analysed": len(buckets),
    }


def _win_rate(recs: list) -> float:
    if not recs:
        return 0.0
    return sum(1 for r in recs if (r.pnl or 0) > 0) / len(recs)


def _avg_conf(recs: list) -> float:
    vals = [r.ai_confidence for r in recs if r.ai_confidence is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _improvement_rate(win_rates: List[float]) -> float:
    """Fraction of consecutive period transitions that improved."""
    if len(win_rates) < 2:
        return 0.0
    improvements = sum(1 for i in range(1, len(win_rates)) if win_rates[i] > win_rates[i - 1])
    return improvements / (len(win_rates) - 1)


def _regression_rate(win_rates: List[float]) -> float:
    """Fraction of consecutive period transitions that regressed."""
    if len(win_rates) < 2:
        return 0.0
    regressions = sum(1 for i in range(1, len(win_rates)) if win_rates[i] < win_rates[i - 1])
    return regressions / (len(win_rates) - 1)


def _velocity(win_rates: List[float]) -> float:
    """
    Linear slope of win rates normalised to [-1, +1].
    Positive = improving over time.
    """
    if len(win_rates) < 2:
        return 0.0
    n = len(win_rates)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(win_rates) / n
    num = sum((xs[i] - x_mean) * (win_rates[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    slope = num / den
    # normalise: max expected slope for 4 buckets ≈ 0.33 per step
    normalised = max(-1.0, min(1.0, slope / 0.33))
    return round(normalised, 4)


def _trend_label(values: List[float], threshold: float = 0.03) -> str:
    if len(values) < 2:
        return "INSUFFICIENT_DATA"
    delta = values[-1] - values[0]
    if delta > threshold:
        return "IMPROVING"
    if delta < -threshold:
        return "DECLINING"
    return "STABLE"


def _adaptive(improvement_rate: float, regression_rate: float, velocity: float) -> str:
    if velocity > 0.2 and improvement_rate > 0.6:
        return "IMPROVING"
    if velocity < -0.2 or regression_rate > 0.6:
        return "DECLINING"
    return "STABLE"


def _empty() -> dict:
    return {
        "improvement_rate": 0.0,
        "regression_rate": 0.0,
        "learning_velocity": 0.0,
        "consistency_trend": "INSUFFICIENT_DATA",
        "confidence_trend": "INSUFFICIENT_DATA",
        "adaptive_trend": "INSUFFICIENT_DATA",
        "history": [],
        "periods_analysed": 0,
    }
