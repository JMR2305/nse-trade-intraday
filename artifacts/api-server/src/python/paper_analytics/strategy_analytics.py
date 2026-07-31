"""
paper_analytics/strategy_analytics.py — Phase 8.2
Per-strategy performance analytics derived from portfolio_performance
and strategy_intelligence data.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import Any, Dict, List


def _group_by_strategy(closed_trades: list) -> Dict[str, list]:
    groups: Dict[str, list] = {}
    for t in closed_trades:
        name = t.strategy_name or "Unknown"
        groups.setdefault(name, []).append(t)
    return groups


def _strategy_row(name: str, trades: list, total_pnl: float) -> Dict[str, Any]:
    n       = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    losers  = [t for t in trades if t.pnl < 0]
    pnl_vals = [t.pnl for t in trades]

    win_rate = len(winners) / n * 100 if n > 0 else 0.0
    avg_ret  = _stats.mean(pnl_vals) if pnl_vals else 0.0

    gross_p = sum(t.pnl for t in winners)
    gross_l = abs(sum(t.pnl for t in losers))
    pf      = (gross_p / gross_l) if gross_l > 0 else (999.0 if gross_p > 0 else 0.0)
    pf      = min(pf, 999.0)

    wr_frac = len(winners) / n if n > 0 else 0.0
    avg_w   = _stats.mean(t.pnl for t in winners) if winners else 0.0
    avg_l   = _stats.mean(t.pnl for t in losers)  if losers  else 0.0
    exp     = (wr_frac * avg_w) + ((1 - wr_frac) * avg_l)

    strat_pnl = sum(pnl_vals)
    contribution_pct = (strat_pnl / total_pnl * 100) if total_pnl != 0 else 0.0

    # Drawdown: compute from running cumulative PnL
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.exit_ts or ""):
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    return {
        "strategy_name":    name,
        "total_trades":     n,
        "winning_trades":   len(winners),
        "losing_trades":    len(losers),
        "win_rate":         round(win_rate, 2),
        "avg_return":       round(avg_ret, 2),
        "total_pnl":        round(strat_pnl, 2),
        "profit_factor":    round(pf, 4),
        "expectancy":       round(exp, 2),
        "max_drawdown":     round(max_dd, 2),
        "contribution_pct": round(contribution_pct, 2),
    }


def get_strategy_analytics() -> Dict[str, Any]:
    """
    Per-strategy breakdown using closed trades + strategy intelligence profiles.
    """
    from portfolio_performance.performance_engine import load_performance_data

    d      = load_performance_data()
    closed = d["closed_trades"]

    total_pnl = sum(t.pnl for t in closed) if closed else 0.0
    groups    = _group_by_strategy(closed)
    rows      = [_strategy_row(name, trades, total_pnl) for name, trades in groups.items()]
    rows      = sorted(rows, key=lambda r: -r["total_pnl"])

    # Normalise contribution so all strategies sum to 100%
    total_abs = sum(abs(r["contribution_pct"]) for r in rows)
    if total_abs > 0:
        for r in rows:
            r["contribution_pct"] = round(r["contribution_pct"], 2)

    # Enrich with confidence from strategy_intelligence if available
    try:
        from strategy_intelligence.shared_services import get_all_strategy_profiles
        profiles = {p.strategy_name: p for p in get_all_strategy_profiles()}
        for r in rows:
            prof = profiles.get(r["strategy_name"])
            r["confidence"] = round(prof.confidence_score * 100, 1) if prof else None
            r["rank_score"] = round(prof.rank_score, 2) if prof else None
    except Exception:
        for r in rows:
            r["confidence"] = None
            r["rank_score"] = None

    # Summary snapshot from strategy_intelligence
    si_snap: Dict[str, Any] = {}
    try:
        from strategy_intelligence.shared_services import get_summary_snapshot
        si_snap = get_summary_snapshot()
    except Exception:
        pass

    return {
        "available":      True,
        "advisory_only":  True,
        "strategies":     rows,
        "total_strategies": len(rows),
        "best_strategy":  rows[0]["strategy_name"] if rows else "N/A",
        "worst_strategy": rows[-1]["strategy_name"] if rows else "N/A",
        "si_snapshot":    si_snap,
        "regime_matrix":  _load_regime_matrix(),
        "sector_matrix":  _load_sector_matrix(),
    }


def _load_regime_matrix() -> dict:
    try:
        from strategy_intelligence.shared_services import get_regime_matrix
        return get_regime_matrix()
    except Exception:
        return {}


def _load_sector_matrix() -> dict:
    try:
        from strategy_intelligence.shared_services import get_sector_matrix
        return get_sector_matrix()
    except Exception:
        return {}
