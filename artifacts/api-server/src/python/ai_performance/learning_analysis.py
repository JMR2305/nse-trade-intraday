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
    """Compute rolling 30-day win rate anchored on each unique exit date.

    Refactored from O(n × d) with repeated strptime calls to O(n log n)
    sorted sliding window:

    - All exit dates are parsed to integer ordinals exactly once.
    - The sorted list is scanned with two monotonic pointers so each signal
      enters and leaves the running window at most once — O(n) total scan.

    Original inner-loop cost at 1000 signals / 200 unique dates:
        200 × 1000 strptime = 200,000 calls  (≈ 2–5 s)
    After refactor:
        1000 strptime (upfront) + O(n) scan   (< 10 ms)
    """
    if not signals:
        return []

    # Parse all dates to ordinals once; drop signals with missing/bad dates
    parsed: List[tuple] = []    # (ordinal, date_str, is_winner)
    for s in signals:
        if not s.exit_date:
            continue
        try:
            ord_ = datetime.strptime(s.exit_date, "%Y-%m-%d").toordinal()
            parsed.append((ord_, s.exit_date, bool(s.is_winner)))
        except ValueError:
            continue

    if not parsed:
        return []

    parsed.sort(key=lambda x: x[0])   # O(n log n)

    # Map ordinal → representative date string (first occurrence)
    ord_to_date: Dict[int, str] = {}
    for ord_, date_str, _ in parsed:
        ord_to_date.setdefault(ord_, date_str)

    unique_ords = sorted(ord_to_date.keys())

    # Two-pointer sliding window — O(n): each element enters/leaves once
    left    = 0   # first index that is still inside the window
    ri      = 0   # next index to consume into the window
    wins    = 0
    total   = 0
    results = []

    for anchor_ord in unique_ords:
        cutoff = anchor_ord - 30    # window is (cutoff, anchor_ord]

        # Advance right pointer: include signals up to anchor_ord
        while ri < len(parsed) and parsed[ri][0] <= anchor_ord:
            wins  += parsed[ri][2]   # True → 1, False → 0
            total += 1
            ri    += 1

        # Advance left pointer: evict signals that fell out of the 30-day window
        while left < ri and parsed[left][0] <= cutoff:
            wins  -= parsed[left][2]
            total -= 1
            left  += 1

        results.append({
            "date":     ord_to_date[anchor_ord],
            "count":    total,
            "wins":     wins,
            "accuracy": round(wins / total * 100, 2) if total > 0 else 0.0,
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
