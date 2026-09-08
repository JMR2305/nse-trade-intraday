"""
paper_analytics/risk_analytics.py — Phase 8.2
Risk analytics derived from risk_optimisation and portfolio_performance.

Computes: Sharpe, Sortino, Calmar, max/avg drawdown, recovery time,
risk/reward, reward/loss distribution, volatility.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

import math
import statistics as _stats
from typing import Any, Dict, List


_TRADING_DAYS = 252
_RISK_FREE_RATE = 0.065  # 6.5% annualised (approx RBI repo rate)


def _daily_returns(daily_pts: list) -> List[float]:
    """Compute daily percentage returns from equity points."""
    returns = []
    for i in range(1, len(daily_pts)):
        prev = daily_pts[i - 1].equity
        curr = daily_pts[i].equity
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


def _sharpe(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    daily_rf = _RISK_FREE_RATE / _TRADING_DAYS
    excess   = [r - daily_rf for r in returns]
    try:
        mean = _stats.mean(excess)
        sd   = _stats.stdev(excess)
        return round((mean / sd) * math.sqrt(_TRADING_DAYS), 4) if sd > 0 else 0.0
    except Exception:
        return 0.0


def _sortino(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    daily_rf   = _RISK_FREE_RATE / _TRADING_DAYS
    excess     = [r - daily_rf for r in returns]
    mean       = _stats.mean(excess)
    downside   = [r for r in excess if r < 0]
    if not downside:
        return 999.0
    try:
        dd_std = math.sqrt(_stats.mean(d ** 2 for d in downside))
        return round((mean / dd_std) * math.sqrt(_TRADING_DAYS), 4) if dd_std > 0 else 0.0
    except Exception:
        return 0.0


def _calmar(total_return_pct: float, max_dd_pct: float) -> float:
    if max_dd_pct <= 0:
        return 0.0
    return round(total_return_pct / max_dd_pct, 4)


def _volatility(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    try:
        return round(_stats.stdev(returns) * math.sqrt(_TRADING_DAYS) * 100, 4)
    except Exception:
        return 0.0


def _distribution(pnl_vals: List[float], buckets: int = 10) -> List[Dict[str, Any]]:
    """Simple histogram of PnL values."""
    if not pnl_vals:
        return []
    min_v = min(pnl_vals)
    max_v = max(pnl_vals)
    if min_v == max_v:
        return [{"bucket": f"{min_v:.0f}", "count": len(pnl_vals)}]
    width = (max_v - min_v) / buckets
    hist: Dict[str, int] = {}
    for v in pnl_vals:
        idx = min(int((v - min_v) / width), buckets - 1)
        label = f"{min_v + idx * width:.0f}–{min_v + (idx + 1) * width:.0f}"
        hist[label] = hist.get(label, 0) + 1
    return [{"bucket": k, "count": v} for k, v in hist.items()]


def _recovery_time_days(daily_pts: list) -> int:
    """
    Count trading days from the max-drawdown trough to full recovery.

    Algorithm (index-based, avoids timestamp parsing issues):
    1. Find trough_idx = index where p.drawdown is maximised.
    2. Find peak_equity = max equity in daily_pts[0 .. trough_idx] (the
       actual high-water mark that preceded the trough — not derived from
       timestamp strings which may be absent or misaligned).
    3. Count forward from trough_idx until equity >= peak_equity.

    Returns:
      0  — no drawdown or the trough IS the first point (nothing to recover)
     >0  — number of trading days to recover
     -1  — not yet recovered by the last data point
    """
    if not daily_pts:
        return 0
    try:
        trough_idx = max(range(len(daily_pts)), key=lambda i: daily_pts[i].drawdown)
        if trough_idx == 0:
            return 0  # started at trough — nothing before it

        # Peak = highest equity strictly before the trough
        peak_equity = max(daily_pts[i].equity for i in range(trough_idx))

        # Count days from trough to recovery
        for offset, p in enumerate(daily_pts[trough_idx:]):
            if p.equity >= peak_equity:
                return offset  # 0 means trough itself recovered immediately
        return -1  # still in recovery at end of series
    except Exception:
        return 0


def get_risk_analytics() -> Dict[str, Any]:
    """
    Comprehensive risk analytics for the paper portfolio.
    Reuses risk_optimisation snapshot + portfolio_performance equity data.
    """
    from portfolio_performance.performance_engine import (
        load_performance_data, _initial_capital,
    )
    from portfolio_performance.equity_curve import (
        _points_from_history, _annotate_drawdown,
    )
    from portfolio_performance.drawdown import compute_drawdown_stats
    from portfolio_performance.statistics import compute_risk_metrics

    d       = load_performance_data()
    initial_capital = _initial_capital()
    closed  = d["closed_trades"]
    history = d["pnl_history"]

    daily_pts = _points_from_history(history)
    _annotate_drawdown(daily_pts)
    dd_stats  = compute_drawdown_stats(daily_pts, initial_capital)
    risk_stats = compute_risk_metrics(closed)

    returns   = _daily_returns(daily_pts)
    sharpe    = _sharpe(returns)
    sortino   = _sortino(returns)

    total_ret_pct = ((d["total_value"] - initial_capital) / initial_capital * 100) if initial_capital else 0.0
    calmar   = _calmar(total_ret_pct, dd_stats["max_drawdown_pct"])
    vol      = _volatility(returns)

    # Recovery time in days (index-based, see _recovery_time_days docstring)
    recovery_days = _recovery_time_days(daily_pts)

    # Reward/loss distributions from closed trades
    winner_pnls = [t.pnl for t in closed if t.pnl > 0]
    loser_pnls  = [t.pnl for t in closed if t.pnl < 0]

    # Avg drawdown: mean of all positive drawdown values
    all_dd = [p.drawdown for p in daily_pts if p.drawdown > 0]
    avg_dd = round(_stats.mean(all_dd), 2) if all_dd else 0.0

    # Drawdown curve for chart rendering (date + drawdown_pct series)
    drawdown_curve = [
        {
            "timestamp":    p.timestamp,
            "equity":       round(p.equity, 2),
            "drawdown_pct": round(p.drawdown_pct, 4),
        }
        for p in daily_pts
    ]

    # Daily returns series for chart
    daily_return_series = [
        {
            "timestamp": daily_pts[i].timestamp,
            "return_pct": round(returns[i - 1] * 100, 4),
        }
        for i in range(1, min(len(daily_pts), len(returns) + 1))
    ]

    # Reuse risk_optimisation snapshot for additional metrics
    ro_snap: Dict[str, Any] = {}
    try:
        from risk_optimisation.shared_services import get_risk_optimisation_snapshot
        ro_snap = get_risk_optimisation_snapshot()
    except Exception:
        pass

    return {
        "available":            True,
        "advisory_only":        True,
        "sharpe_ratio":         sharpe,
        "sortino_ratio":        sortino,
        "calmar_ratio":         calmar,
        "volatility_pct":       vol,
        "risk_free_rate":       _RISK_FREE_RATE,
        **dd_stats,
        "avg_drawdown":         avg_dd,
        "recovery_time_days":   recovery_days,
        **risk_stats,
        "total_return_pct":     round(total_ret_pct, 4),
        "reward_distribution":  _distribution(winner_pnls),
        "loss_distribution":    _distribution(loser_pnls),
        "daily_returns_count":  len(returns),
        "drawdown_curve":       drawdown_curve,
        "daily_return_series":  daily_return_series,
        "risk_optimisation":    ro_snap,
    }
