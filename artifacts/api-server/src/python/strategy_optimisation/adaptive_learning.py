"""
adaptive_learning.py — Phase 6.2
Performance trend, improvement, regression, and stability trend tracking.

GitHub-inspired: adaptive strategy ranking via lifecycle monitoring —
tracks EMERGING → ACTIVE → DECLINING → DORMANT states.
"""
from __future__ import annotations
import sys, os
from datetime import datetime, date
from typing import List, Dict, Optional
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_date(ts: str) -> Optional[date]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
    except Exception:
        return None


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _rolling_win_rate(records: list, window: int = 10) -> List[dict]:
    """Rolling win rate over the last `window` trades."""
    if not records:
        return []
    sorted_recs = sorted(records, key=lambda r: r.timestamp)
    result = []
    for i in range(window - 1, len(sorted_recs)):
        chunk = sorted_recs[max(0, i - window + 1): i + 1]
        wr = sum(1 for r in chunk if r.pnl > 0) / len(chunk)
        result.append({
            "index": i + 1,
            "trade_id": sorted_recs[i].trade_id,
            "win_rate": round(wr, 4),
            "timestamp": sorted_recs[i].timestamp,
        })
    return result


def _trend_direction(series: List[float]) -> str:
    """Simple linear trend: IMPROVING / DECLINING / STABLE."""
    if len(series) < 3:
        return "INSUFFICIENT_DATA"
    n = len(series)
    x_mean = (n - 1) / 2.0
    y_mean = _avg(series)
    numerator = sum((i - x_mean) * (series[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return "STABLE"
    slope = numerator / denominator
    if slope > 0.01:
        return "IMPROVING"
    if slope < -0.01:
        return "DECLINING"
    return "STABLE"


def _lifecycle_state(records: list) -> str:
    """
    GitHub-inspired lifecycle monitoring.
    EMERGING: < 5 trades, promising early signal
    ACTIVE: consistent recent performance
    DECLINING: recent win rate falling
    DORMANT: no trades in last 14 days
    """
    if not records:
        return "DORMANT"
    sorted_recs = sorted(records, key=lambda r: r.timestamp)
    last_trade_ts = _parse_date(sorted_recs[-1].timestamp)
    if last_trade_ts is None:
        return "UNKNOWN"
    days_since = (date.today() - last_trade_ts).days

    if len(records) < 5:
        return "EMERGING"
    if days_since > 14:
        return "DORMANT"

    recent_10 = sorted_recs[-10:]
    recent_wr = sum(1 for r in recent_10 if r.pnl > 0) / len(recent_10)
    overall_wr = sum(1 for r in records if r.pnl > 0) / len(records)

    if recent_wr < overall_wr - 0.15:
        return "DECLINING"
    return "ACTIVE"


def compute_adaptive_learning(records: list) -> dict:
    """
    Compute adaptive learning signals per strategy.
    Returns overall trend + per-strategy lifecycle states.
    """
    if not records:
        return {
            "overall_trend": "INSUFFICIENT_DATA",
            "improvement_trend": "INSUFFICIENT_DATA",
            "regression_trend": "INSUFFICIENT_DATA",
            "stability_trend": "INSUFFICIENT_DATA",
            "strategies": [],
            "rolling_win_rate": [],
            "available": True,
        }

    from collections import defaultdict
    by_strategy: dict = defaultdict(list)
    for r in records:
        by_strategy[r.strategy].append(r)

    # Overall rolling win rate (all strategies combined, last 20 trades)
    overall_sorted = sorted(records, key=lambda r: r.timestamp)
    rolling = _rolling_win_rate(overall_sorted, window=min(10, len(overall_sorted)))

    # Improvement trend: slope of rolling win rate
    wr_series = [x["win_rate"] for x in rolling]
    overall_trend = _trend_direction(wr_series)

    # P&L trend
    pnl_series = [r.pnl for r in overall_sorted]
    pnl_trend = _trend_direction(pnl_series)

    # Stability: variance of rolling win rate
    import math
    if len(wr_series) >= 3:
        mean_wr = _avg(wr_series)
        variance = sum((x - mean_wr) ** 2 for x in wr_series) / len(wr_series)
        std_wr = math.sqrt(variance)
        stability = "STABLE" if std_wr < 0.1 else "VOLATILE" if std_wr > 0.2 else "MODERATE"
    else:
        stability = "INSUFFICIENT_DATA"

    # Per-strategy lifecycle
    strategy_states = []
    for strategy, recs in by_strategy.items():
        strat_rolling = _rolling_win_rate(recs, window=min(5, len(recs)))
        strat_wr_series = [x["win_rate"] for x in strat_rolling]
        strat_trend = _trend_direction(strat_wr_series)
        lifecycle = _lifecycle_state(recs)

        strategy_states.append({
            "strategy": strategy,
            "total_trades": len(recs),
            "lifecycle": lifecycle,
            "performance_trend": strat_trend,
            "current_win_rate": round(sum(1 for r in recs if r.pnl > 0) / len(recs), 4),
            "recent_win_rate": round(
                sum(1 for r in sorted(recs, key=lambda x: x.timestamp)[-5:] if r.pnl > 0)
                / min(5, len(recs)), 4,
            ),
            "rolling_win_rate": strat_rolling[-5:],
        })

    strategy_states.sort(key=lambda s: (
        {"ACTIVE": 0, "EMERGING": 1, "DECLINING": 2, "DORMANT": 3, "UNKNOWN": 4}.get(s["lifecycle"], 4)
    ))

    return {
        "overall_trend": overall_trend,
        "improvement_trend": pnl_trend,
        "regression_trend": "DECLINING" if overall_trend == "DECLINING" else "NONE",
        "stability_trend": stability,
        "strategies": strategy_states,
        "rolling_win_rate": rolling[-20:],
        "available": True,
    }
