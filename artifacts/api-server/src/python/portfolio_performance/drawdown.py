"""
portfolio_performance/drawdown.py — Drawdown analytics.

READ-ONLY.  PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from typing import List, Dict, Any

from .performance_models import EquityPoint


def compute_drawdown_stats(
    points: List[EquityPoint],
    initial_capital: float = 0.0,
) -> Dict[str, Any]:
    """
    Compute max drawdown, current drawdown, and recovery percentage from an
    annotated EquityPoint list (drawdown fields must already be set).

    Args:
        points:          Annotated daily equity points (drawdown already computed).
        initial_capital: Starting capital — used when history is empty.

    Returns dict with:
        max_drawdown, max_drawdown_pct, max_drawdown_start, max_drawdown_end,
        current_drawdown, current_drawdown_pct, current_equity,
        all_time_peak, recovery_pct
    """
    if not points:
        return {
            "max_drawdown":         0.0,
            "max_drawdown_pct":     0.0,
            "max_drawdown_start":   None,
            "max_drawdown_end":     None,
            "current_drawdown":     0.0,
            "current_drawdown_pct": 0.0,
            "current_equity":       initial_capital,
            "all_time_peak":        initial_capital,
            "recovery_pct":         100.0,
        }

    # All-time peak equity
    peak_value   = max(p.equity for p in points)
    current      = points[-1]
    current_eq   = current.equity
    current_dd   = current.drawdown
    current_dd_pct = current.drawdown_pct

    # Find max drawdown and its timestamps
    max_dd      = 0.0
    max_dd_pct  = 0.0
    max_dd_start: str | None = None
    max_dd_end:   str | None = None

    running_peak = 0.0
    running_peak_ts: str | None = None

    for p in points:
        if p.equity >= running_peak:
            running_peak    = p.equity
            running_peak_ts = p.timestamp
        dd     = running_peak - p.equity
        dd_pct = (dd / running_peak * 100) if running_peak > 0 else 0.0
        if dd > max_dd:
            max_dd       = dd
            max_dd_pct   = dd_pct
            max_dd_start = running_peak_ts
            max_dd_end   = p.timestamp

    # Recovery: how much of the max drawdown has been recovered
    # If currently at a new high → 100 %.  Otherwise, proportion recovered.
    if max_dd <= 0:
        recovery_pct = 100.0
    else:
        already_recovered = max_dd - current_dd
        recovery_pct = min(100.0, max(0.0, already_recovered / max_dd * 100))

    return {
        "max_drawdown":         round(max_dd, 2),
        "max_drawdown_pct":     round(max_dd_pct, 4),
        "max_drawdown_start":   max_dd_start,
        "max_drawdown_end":     max_dd_end,
        "current_drawdown":     round(current_dd, 2),
        "current_drawdown_pct": round(current_dd_pct, 4),
        "current_equity":       round(current_eq, 2),
        "all_time_peak":        round(peak_value, 2),
        "recovery_pct":         round(recovery_pct, 4),
    }
