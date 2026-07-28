"""
execution_quality/fill_analysis.py — Fill delay analytics.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics
from typing import List

from .models import ExecutionRecord

_INSTANT_THRESHOLD  = 5.0     # seconds — considered "instant"
_DELAYED_THRESHOLD  = 60.0    # seconds — above this is "delayed"


def compute_fill_stats(records: List[ExecutionRecord]) -> dict:
    if not records:
        return {
            "avg_delay_seconds":    None,
            "median_delay_seconds": None,
            "max_delay_seconds":    None,
            "min_delay_seconds":    None,
            "instant_fills":  0,
            "delayed_fills":  0,
            "missed_fills":   0,
            "total_fills":    0,
            "instant_pct":    None,
            "delayed_pct":    None,
        }

    delays  = [r.fill_delay_seconds for r in records]
    instant = sum(1 for d in delays if d < _INSTANT_THRESHOLD)
    delayed = sum(1 for d in delays if d >= _DELAYED_THRESHOLD)
    # "missed" = no fill recorded at all (fill_delay = 0 AND trade not linked to a signal)
    missed  = 0   # In paper trading all orders fill; this is a placeholder for future live integration

    n = len(delays)
    return {
        "avg_delay_seconds":    round(statistics.mean(delays),   2),
        "median_delay_seconds": round(statistics.median(delays), 2),
        "max_delay_seconds":    round(max(delays), 2),
        "min_delay_seconds":    round(min(delays), 2),
        "instant_fills": instant,
        "delayed_fills": delayed,
        "missed_fills":  missed,
        "total_fills":   n,
        "instant_pct": round(instant / n * 100, 1) if n else None,
        "delayed_pct": round(delayed / n * 100, 1) if n else None,
    }
