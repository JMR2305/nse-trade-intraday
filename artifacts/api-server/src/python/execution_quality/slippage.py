"""
execution_quality/slippage.py — Slippage analytics engine.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics
from typing import List, Dict, Any

from .models import ExecutionRecord


def _stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"avg": None, "median": None, "worst": None, "best": None, "count": 0}
    return {
        "avg":    round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "worst":  round(max(values), 4),
        "best":   round(min(values), 4),
        "count":  len(values),
    }


def compute_slippage_stats(records: List[ExecutionRecord]) -> dict:
    """Overall slippage stats (entry + exit) in ₹ and %."""
    entry_rs  = [r.entry_slippage_rs  for r in records]
    entry_pct = [r.entry_slippage_pct for r in records]
    completed = [r for r in records if r.is_complete]
    exit_rs   = [r.exit_slippage_rs   for r in completed]
    exit_pct  = [r.exit_slippage_pct  for r in completed]

    return {
        "entry_rs":  _stats(entry_rs),
        "entry_pct": _stats(entry_pct),
        "exit_rs":   _stats(exit_rs),
        "exit_pct":  _stats(exit_pct),
        "by_symbol":   _by_dim(records, "symbol"),
        "by_strategy": _by_dim(records, "strategy_name"),
        "by_sector":   _by_dim(records, "sector"),
        "by_regime":   _by_dim(records, "regime"),
        "by_time_of_day": _by_time(records),
    }


def _by_dim(records: List[ExecutionRecord], attr: str) -> List[dict]:
    bucket: Dict[str, List[float]] = {}
    for r in records:
        key = str(getattr(r, attr, "") or "Unknown")
        bucket.setdefault(key, []).append(r.entry_slippage_rs)
    return [
        {"label": k, **_stats(v)}
        for k, v in sorted(bucket.items(), key=lambda x: -(statistics.mean(x[1]) if x[1] else 0))
    ]


def _by_time(records: List[ExecutionRecord]) -> List[dict]:
    """Group by IST hour of entry."""
    from datetime import timezone, timedelta
    _IST = timezone(timedelta(hours=5, minutes=30))
    bucket: Dict[str, List[float]] = {}
    for r in records:
        label = "Unknown"
        if r.entry_ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(r.entry_ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ist_dt = dt.astimezone(_IST)
                label = f"{ist_dt.hour:02d}:00"
            except Exception:
                pass
        bucket.setdefault(label, []).append(r.entry_slippage_rs)
    return [
        {"label": k, **_stats(v)}
        for k, v in sorted(bucket.items())
    ]
