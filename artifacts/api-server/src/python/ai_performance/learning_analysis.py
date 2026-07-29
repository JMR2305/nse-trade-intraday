"""
ai_performance/learning_analysis.py — AI learning / improvement tracking.

Groups trades by exit date and computes accuracy over time windows:
  • Daily accuracy (win rate per trading day)
  • Weekly accuracy (win rate per ISO week)
  • Monthly accuracy (win rate per calendar month)
  • Rolling 30-day accuracy (sliding window)
  • Trend direction: Improving / Stable / Declining

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any

from .ai_models import AISignalRecord, TREND_IMPROVING, TREND_STABLE, TREND_DECLINING


def _group_accuracy(signals: List[AISignalRecord], key_fn) -> List[Dict[str, Any]]:
    groups: Dict[str, List[AISignalRecord]] = defaultdict(list)
    for s in signals:
        k = key_fn(s)
        if k:
            groups[k].append(s)
    rows = []
    for period, group in sorted(groups.items()):
        wins = sum(1 for g in group if g.is_winner)
        n    = len(group)
        rows.append({
            "period":    period,
            "count":     n,
            "wins":      wins,
            "accuracy":  round(wins / n * 100, 2) if n > 0 else 0.0,
            "net_pnl":   round(sum(g.pnl for g in group), 2),
        })
    return rows


def _rolling_30d(signals: List[AISignalRecord]) -> List[Dict[str, Any]]:
    """Compute rolling 30-day win rate anchored on each unique exit date."""
    if not signals:
        return []

    dated = [(s.exit_date, s) for s in signals if s.exit_date]
    if not dated:
        return []

    by_date: Dict[str, List[AISignalRecord]] = defaultdict(list)
    for d, s in dated:
        by_date[d].append(s)

    unique_dates = sorted(by_date.keys())
    results      = []

    for i, anchor_date in enumerate(unique_dates):
        try:
            anchor_dt = datetime.strptime(anchor_date, "%Y-%m-%d")
        except ValueError:
            continue
        cutoff = anchor_dt - timedelta(days=30)

        window = [
            s for d, ss in by_date.items()
            for s in ss
            if datetime.strptime(d, "%Y-%m-%d") > cutoff
            and datetime.strptime(d, "%Y-%m-%d") <= anchor_dt
        ]
        wins  = sum(1 for s in window if s.is_winner)
        n     = len(window)
        results.append({
            "date":     anchor_date,
            "count":    n,
            "wins":     wins,
            "accuracy": round(wins / n * 100, 2) if n > 0 else 0.0,
        })

    return results


def compute_trend_direction(rolling: List[Dict[str, Any]], min_samples: int = 5) -> str:
    """
    Compare last 30 days vs prior 30 days from the rolling series.
    Returns Improving / Stable / Declining.
    Requires at least min_samples data points in each half.
    """
    if len(rolling) < 2:
        return TREND_STABLE

    mid  = len(rolling) // 2
    old  = [r["accuracy"] for r in rolling[:mid] if r["count"] > 0]
    new  = [r["accuracy"] for r in rolling[mid:] if r["count"] > 0]

    if len(old) < min_samples or len(new) < min_samples:
        return TREND_STABLE

    avg_old = _stats.mean(old)
    avg_new = _stats.mean(new)
    delta   = avg_new - avg_old

    if delta > 5.0:
        return TREND_IMPROVING
    elif delta < -5.0:
        return TREND_DECLINING
    return TREND_STABLE


def compute_learning_analysis(signals: List[AISignalRecord]) -> Dict[str, Any]:
    """Full learning analysis — daily, weekly, monthly, rolling, trend."""
    if not signals:
        return {
            "daily":          [],
            "weekly":         [],
            "monthly":        [],
            "rolling_30d":    [],
            "trend_direction": TREND_STABLE,
            "recent_accuracy": 0.0,
            "prior_accuracy":  0.0,
            "accuracy_delta":  0.0,
        }

    daily   = _group_accuracy(signals, lambda s: s.exit_date)
    weekly  = _group_accuracy(signals, lambda s: s.exit_week)
    monthly = _group_accuracy(signals, lambda s: s.exit_month)
    rolling = _rolling_30d(signals)
    trend   = compute_trend_direction(rolling)

    # Recent vs prior accuracy for headline delta
    mid   = len(rolling) // 2
    old   = [r["accuracy"] for r in rolling[:mid] if r["count"] > 0]
    new   = [r["accuracy"] for r in rolling[mid:] if r["count"] > 0]
    prior = round(_stats.mean(old), 2) if old else 0.0
    recent= round(_stats.mean(new), 2) if new else 0.0

    return {
        "daily":           daily,
        "weekly":          weekly,
        "monthly":         monthly,
        "rolling_30d":     rolling,
        "trend_direction": trend,
        "recent_accuracy": recent,
        "prior_accuracy":  prior,
        "accuracy_delta":  round(recent - prior, 2),
    }
