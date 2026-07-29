"""
drawdown_analyser.py — Phase 6.4
Maximum drawdown, average drawdown, recovery time, recovery efficiency,
worst period, and drawdown frequency.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List, Optional

DEFAULT_CAPITAL = 500_000.0


def analyse_drawdown(records: list, starting_capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Compute drawdown metrics from a sorted-by-timestamp list of TradeRecord dicts.
    """
    if not records:
        return _empty_drawdown()

    # Sort by timestamp (best effort)
    sorted_records = sorted(records, key=lambda r: r.get("timestamp", "") or "")

    # Build cumulative P&L equity curve
    equity = starting_capital
    equity_curve: List[float] = [equity]
    for r in sorted_records:
        equity += (r.get("pnl") or 0.0)
        equity_curve.append(equity)

    # Compute drawdown series
    peak = equity_curve[0]
    max_drawdown = 0.0
    drawdown_periods: list = []
    in_drawdown = False
    drawdown_start_idx = 0
    drawdown_start_peak = equity_curve[0]

    for i, e in enumerate(equity_curve):
        if e > peak:
            if in_drawdown:
                # Recovered
                dd_pct = (drawdown_start_peak - min(equity_curve[drawdown_start_idx:i])) / drawdown_start_peak
                recovery_bars = i - drawdown_start_idx
                drawdown_periods.append({
                    "drawdown_pct": round(dd_pct, 4),
                    "duration_trades": i - drawdown_start_idx,
                    "recovery_trades": recovery_bars,
                    "start_equity": round(drawdown_start_peak, 2),
                    "trough_equity": round(min(equity_curve[drawdown_start_idx:i]), 2),
                })
                in_drawdown = False
            peak = e
        else:
            dd = (peak - e) / peak if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            if dd > 0.005 and not in_drawdown:  # > 0.5% threshold
                in_drawdown = True
                drawdown_start_idx = i
                drawdown_start_peak = peak

    # Close open drawdown if still in one
    if in_drawdown:
        trough = min(equity_curve[drawdown_start_idx:])
        dd_pct = (drawdown_start_peak - trough) / drawdown_start_peak if drawdown_start_peak > 0 else 0.0
        drawdown_periods.append({
            "drawdown_pct": round(dd_pct, 4),
            "duration_trades": len(equity_curve) - drawdown_start_idx,
            "recovery_trades": None,   # still in drawdown
            "start_equity": round(drawdown_start_peak, 2),
            "trough_equity": round(trough, 2),
        })

    n_dd = len(drawdown_periods)
    avg_drawdown = sum(d["drawdown_pct"] for d in drawdown_periods) / n_dd if n_dd > 0 else 0.0

    # Recovery efficiency: fraction of drawdowns that recovered
    recovered = [d for d in drawdown_periods if d["recovery_trades"] is not None]
    recovery_efficiency = len(recovered) / n_dd if n_dd > 0 else 1.0

    avg_recovery = (
        sum(d["recovery_trades"] for d in recovered) / len(recovered)
        if recovered else 0.0
    )

    # Worst period
    worst = max(drawdown_periods, key=lambda d: d["drawdown_pct"]) if drawdown_periods else None

    # Drawdown frequency: drawdowns per 10 trades
    n_trades = len(sorted_records)
    dd_frequency = (n_dd / n_trades * 10) if n_trades > 0 else 0.0

    # Drawdown severity 0–1 (for health score)
    severity = min(1.0, max_drawdown * 3.0)  # 33% DD = severity 1.0

    return {
        "total_trades": n_trades,
        "starting_capital": starting_capital,
        "final_equity": round(equity_curve[-1], 2),
        "total_pnl": round(equity_curve[-1] - starting_capital, 2),
        "max_drawdown": round(max_drawdown, 4),
        "avg_drawdown": round(avg_drawdown, 4),
        "drawdown_frequency_per_10": round(dd_frequency, 2),
        "recovery_efficiency": round(recovery_efficiency, 4),
        "avg_recovery_trades": round(avg_recovery, 2),
        "worst_drawdown_period": worst,
        "drawdown_periods": drawdown_periods[-5:],   # last 5
        "total_drawdown_periods": n_dd,
        "drawdown_severity": round(severity, 4),
        "equity_curve_head": [round(e, 2) for e in equity_curve[:20]],
    }


def _empty_drawdown() -> dict:
    return {
        "total_trades": 0,
        "starting_capital": DEFAULT_CAPITAL,
        "final_equity": DEFAULT_CAPITAL,
        "total_pnl": 0.0,
        "max_drawdown": 0.0,
        "avg_drawdown": 0.0,
        "drawdown_frequency_per_10": 0.0,
        "recovery_efficiency": 1.0,
        "avg_recovery_trades": 0.0,
        "worst_drawdown_period": None,
        "drawdown_periods": [],
        "total_drawdown_periods": 0,
        "drawdown_severity": 0.0,
        "equity_curve_head": [],
    }
