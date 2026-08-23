"""
paper_analytics/trade_analytics.py — Phase 8.2
Trade-level analytics derived from portfolio_performance data.

Computes: win/loss counts, win rate, avg profit/loss, profit factor,
expectancy, streaks, holding time, largest winner/loser, equity curves,
drawdown curve.

READ-ONLY. ADVISORY-ONLY. Never fetches from DB directly.
"""
from __future__ import annotations

import statistics as _stats
from typing import Any, Dict, List


def _load_perf() -> Dict[str, Any]:
    """Load all performance data from portfolio_performance module."""
    from portfolio_performance.performance_engine import load_performance_data
    return load_performance_data()


def _compute_streaks(closed_trades: list) -> Dict[str, int]:
    """Compute longest winning and losing streaks."""
    if not closed_trades:
        return {"longest_win_streak": 0, "longest_loss_streak": 0}

    # Sort by exit timestamp
    sorted_trades = sorted(
        [t for t in closed_trades if t.exit_ts],
        key=lambda t: t.exit_ts or "",
    )

    max_win = max_loss = cur_win = cur_loss = 0
    for t in sorted_trades:
        if t.pnl > 0:
            cur_win += 1
            cur_loss = 0
        elif t.pnl < 0:
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win  = max(max_win,  cur_win)
        max_loss = max(max_loss, cur_loss)

    return {"longest_win_streak": max_win, "longest_loss_streak": max_loss}


def _rolling_returns(daily_pts: list, window: int = 5) -> List[Dict[str, Any]]:
    """Compute rolling N-day return series."""
    if len(daily_pts) < window:
        return []
    rows = []
    for i in range(window, len(daily_pts)):
        start = daily_pts[i - window].get("equity", 0)
        end   = daily_pts[i].get("equity", 0)
        ret   = ((end - start) / start * 100) if start > 0 else 0.0
        rows.append({
            "date":        daily_pts[i].get("timestamp", "")[:10],
            "return_pct":  round(ret, 4),
            "window_days": window,
        })
    return rows


def get_trade_analytics() -> Dict[str, Any]:
    """
    Full trade analytics payload.

    Returns:
        trade_stats, equity_curves, drawdown_curve, rolling_returns,
        streak data, largest winner/loser.
    """
    from portfolio_performance.performance_engine import (
        load_performance_data, _initial_capital,
    )
    from portfolio_performance.equity_curve import (
        build_equity_curves, _points_from_history, _annotate_drawdown,
    )
    from portfolio_performance.drawdown import compute_drawdown_stats
    from portfolio_performance.statistics import (
        compute_trade_statistics, compute_risk_metrics,
    )

    d       = load_performance_data()
    initial_capital = _initial_capital()
    closed  = d["closed_trades"]
    history = d["pnl_history"]

    trade_stats = compute_trade_statistics(closed)
    risk_stats  = compute_risk_metrics(closed)
    streaks     = _compute_streaks(closed)

    # Equity curve
    curves    = build_equity_curves(history)
    daily_pts = _points_from_history(history)
    _annotate_drawdown(daily_pts)
    dd_stats  = compute_drawdown_stats(daily_pts, initial_capital)

    # Drawdown curve for charting
    drawdown_curve = [
        {
            "timestamp":    p.timestamp,
            "equity":       round(p.equity, 2),
            "drawdown":     round(p.drawdown, 2),
            "drawdown_pct": round(p.drawdown_pct, 4),
        }
        for p in daily_pts
    ]

    # Recovery curve: equity trajectory from the max-drawdown trough to end.
    # Only meaningful when a real drawdown exists (drawdown > 0).
    # With monotonically increasing equity the trough has drawdown=0 and
    # pct_recovered would be meaningless (division by ~0), so we omit it.
    recovery_curve: list = []
    if daily_pts:
        trough_idx    = max(range(len(daily_pts)), key=lambda i: daily_pts[i].drawdown)
        trough_dd     = daily_pts[trough_idx].drawdown  # peak - trough equity
        if trough_dd > 0:
            trough_eq = daily_pts[trough_idx].equity
            recovery_curve = [
                {
                    "timestamp":     p.timestamp,
                    "equity":        round(p.equity, 2),
                    "pct_recovered": min(
                        100.0,
                        round(max(0.0, (p.equity - trough_eq) / trough_dd * 100), 2),
                    ),
                }
                for p in daily_pts[trough_idx:]
            ]

    # Largest winner/loser detail
    largest_winner = largest_loser = None
    if closed:
        best  = max(closed, key=lambda t: t.pnl)
        worst = min(closed, key=lambda t: t.pnl)
        largest_winner = {
            "symbol":   best.symbol,
            "strategy": best.strategy_name,
            "pnl":      round(best.pnl, 2),
            "pnl_pct":  round(best.pnl_pct, 4),
            "entry_ts": best.entry_ts,
            "exit_ts":  best.exit_ts,
        }
        largest_loser = {
            "symbol":   worst.symbol,
            "strategy": worst.strategy_name,
            "pnl":      round(worst.pnl, 2),
            "pnl_pct":  round(worst.pnl_pct, 4),
            "entry_ts": worst.entry_ts,
            "exit_ts":  worst.exit_ts,
        }

    daily_pts_dicts = [
        {"timestamp": p.timestamp, "equity": round(p.equity, 2)}
        for p in daily_pts
    ]

    return {
        "available":      True,
        "advisory_only":  True,
        **trade_stats,
        **risk_stats,
        **streaks,
        **dd_stats,
        "largest_winner": largest_winner,
        "largest_loser":  largest_loser,
        "equity_curves":  {
            "daily":       curves["daily"],
            "weekly":      curves["weekly"],
            "monthly":     curves["monthly"],
            "daily_pnl":   curves["daily_pnl"],
            "monthly_pnl": curves["monthly_pnl"],
        },
        "drawdown_curve":   drawdown_curve,
        "recovery_curve":   recovery_curve,
        "rolling_returns":  _rolling_returns(daily_pts_dicts),
        "initial_capital":  initial_capital,
        "total_pnl":        d["realised_pnl"] + d["unrealised_pnl"],
        "realised_pnl":     d["realised_pnl"],
        "unrealised_pnl":   d["unrealised_pnl"],
        "total_value":      d["total_value"],
    }
