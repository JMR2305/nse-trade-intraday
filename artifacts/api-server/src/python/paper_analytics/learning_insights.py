"""
paper_analytics/learning_insights.py — Phase 8.2
Auto-identified learning insights derived from aggregated analytics data.

Identifies: best/worst strategy, best/worst sector, most consistent strategy,
highest-risk strategy, best/worst market condition, common winning/losing
characteristics.

READ-ONLY. ADVISORY-ONLY. All outputs are advisory text observations only.
"""
from __future__ import annotations

import statistics as _stats
from typing import Any, Dict, List


def _strategy_groups(closed_trades: list) -> Dict[str, list]:
    groups: Dict[str, list] = {}
    for t in closed_trades:
        name = t.strategy_name or "Unknown"
        groups.setdefault(name, []).append(t)
    return groups


def _sector_groups(closed_trades: list) -> Dict[str, list]:
    groups: Dict[str, list] = {}
    for t in closed_trades:
        sec = t.sector or "Unknown"
        groups.setdefault(sec, []).append(t)
    return groups


def _win_rate(trades: list) -> float:
    if not trades:
        return 0.0
    return len([t for t in trades if t.pnl > 0]) / len(trades) * 100


def _profit_factor(trades: list) -> float:
    winners = [t.pnl for t in trades if t.pnl > 0]
    losers  = [abs(t.pnl) for t in trades if t.pnl < 0]
    gp = sum(winners)
    gl = sum(losers)
    if gl == 0:
        return 999.0 if gp > 0 else 0.0
    return min(gp / gl, 999.0)


def _avg_return(trades: list) -> float:
    if not trades:
        return 0.0
    return _stats.mean(t.pnl for t in trades)


def _consistency(trades: list) -> float:
    """Consistency = inverse of PnL standard deviation (lower stdev = more consistent)."""
    if len(trades) < 2:
        return 0.0
    try:
        sd = _stats.stdev(t.pnl for t in trades)
        return round(max(0.0, 100 - sd / 10), 2)  # advisory normalisation
    except Exception:
        return 0.0


def _max_dd_for_group(trades: list) -> float:
    sorted_t = sorted(trades, key=lambda t: t.exit_ts or "")
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted_t:
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _common_characteristics(trades: list) -> List[str]:
    """Advisory: identify the most common strategy/sector/session in these trades."""
    if not trades:
        return []
    strats: Dict[str, int] = {}
    secs:   Dict[str, int] = {}
    for t in trades:
        strats[t.strategy_name or "Unknown"] = strats.get(t.strategy_name or "Unknown", 0) + 1
        secs[t.sector or "Unknown"]          = secs.get(t.sector or "Unknown", 0) + 1
    top_strat = max(strats, key=strats.__getitem__) if strats else "N/A"
    top_sec   = max(secs,   key=secs.__getitem__)   if secs   else "N/A"
    return [
        f"Most common strategy: {top_strat} ({strats.get(top_strat, 0)} trades)",
        f"Most common sector: {top_sec} ({secs.get(top_sec, 0)} trades)",
    ]


def get_learning_insights() -> Dict[str, Any]:
    """
    Auto-identified learning insights from the full paper trade dataset.
    """
    from portfolio_performance.performance_engine import load_performance_data

    d      = load_performance_data()
    closed = d["closed_trades"]

    if not closed:
        return {
            "available":     True,
            "advisory_only": True,
            "has_data":      False,
            "message":       "No completed paper trades to analyse yet.",
        }

    strat_groups = _strategy_groups(closed)
    sec_groups   = _sector_groups(closed)

    # Best/worst strategy by win rate (min 2 trades)
    qualified_strats = {k: v for k, v in strat_groups.items() if len(v) >= 2}
    best_strategy    = max(qualified_strats, key=lambda k: _win_rate(qualified_strats[k])) if qualified_strats else "N/A"
    worst_strategy   = min(qualified_strats, key=lambda k: _win_rate(qualified_strats[k])) if qualified_strats else "N/A"

    # Best/worst sector by avg return
    best_sector  = max(sec_groups, key=lambda k: _avg_return(sec_groups[k])) if sec_groups else "N/A"
    worst_sector = min(sec_groups, key=lambda k: _avg_return(sec_groups[k])) if sec_groups else "N/A"

    # Most consistent strategy (lowest PnL stdev with ≥2 trades)
    most_consistent = max(qualified_strats, key=lambda k: _consistency(qualified_strats[k])) if qualified_strats else "N/A"

    # Highest-risk strategy (highest max drawdown)
    highest_risk = max(qualified_strats, key=lambda k: _max_dd_for_group(qualified_strats[k])) if qualified_strats else "N/A"

    # Best/worst market condition from strategy_intelligence regime matrix
    best_regime = worst_regime = "N/A"
    try:
        from strategy_intelligence.shared_services import get_regime_matrix
        rm = get_regime_matrix()
        matrix = rm.get("matrix", {})
        if matrix:
            best_regime  = max(matrix, key=lambda k: matrix[k].get("net_pnl", 0))
            worst_regime = min(matrix, key=lambda k: matrix[k].get("net_pnl", 0))
    except Exception:
        pass

    # Common winning/losing characteristics
    winners = [t for t in closed if t.pnl > 0]
    losers  = [t for t in closed if t.pnl < 0]
    winning_chars = _common_characteristics(winners)
    losing_chars  = _common_characteristics(losers)

    # AI-derived features if available
    ai_features: List[str] = []
    try:
        from ai_performance.shared_services import get_ai_snapshot
        snap = get_ai_snapshot()
        if snap.get("status") == "ENABLED":
            ai_features = [
                f"AI health score: {snap.get('health_score', 'N/A')}",
                f"Prediction accuracy: {snap.get('prediction_accuracy', 'N/A')}%",
                f"Trend direction: {snap.get('trend_direction', 'N/A')}",
            ]
    except Exception:
        pass

    return {
        "available":        True,
        "advisory_only":    True,
        "has_data":         True,
        "total_trades":     len(closed),
        "best_strategy":    best_strategy,
        "worst_strategy":   worst_strategy,
        "best_sector":      best_sector,
        "worst_sector":     worst_sector,
        "most_consistent_strategy": most_consistent,
        "highest_risk_strategy":    highest_risk,
        "best_market_condition":    best_regime,
        "worst_market_condition":   worst_regime,
        "winning_characteristics":  winning_chars,
        "losing_characteristics":   losing_chars,
        "ai_derived_features":      ai_features,
        "strategy_metrics": {
            name: {
                "win_rate":       round(_win_rate(trades), 2),
                "profit_factor":  round(_profit_factor(trades), 4),
                "avg_return":     round(_avg_return(trades), 2),
                "consistency":    _consistency(trades),
                "max_drawdown":   _max_dd_for_group(trades),
                "trade_count":    len(trades),
            }
            for name, trades in qualified_strats.items()
        },
        "sector_metrics": {
            sec: {
                "win_rate":   round(_win_rate(trades), 2),
                "avg_return": round(_avg_return(trades), 2),
                "count":      len(trades),
            }
            for sec, trades in sec_groups.items()
        },
    }
