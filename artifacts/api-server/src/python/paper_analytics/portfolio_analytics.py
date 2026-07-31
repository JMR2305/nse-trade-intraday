"""
paper_analytics/portfolio_analytics.py — Phase 8.2
Portfolio-level analytics aggregating portfolio_performance,
risk_optimisation, and strategy_intelligence data.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

from typing import Any, Dict, List


def get_portfolio_analytics() -> Dict[str, Any]:
    """
    Portfolio analytics: capital growth, cash utilisation, sector/strategy
    allocation, exposure, concentration, diversification.
    """
    from portfolio_performance.performance_engine import (
        load_performance_data, INITIAL_CAPITAL,
    )
    from portfolio_performance.statistics import (
        compute_sector_allocation,
        compute_strategy_contribution,
    )

    d        = load_performance_data()
    closed   = d["closed_trades"]
    opens    = d["open_positions_raw"]
    cash     = d["cash"]
    invested = d["invested"]
    total    = d["total_value"]
    history  = d["pnl_history"]

    # Capital growth series
    growth_series = [
        {"timestamp": pt.get("timestamp", ""), "value": round(float(pt.get("value", 0)), 2)}
        for pt in history
    ]

    # Returns pct since inception
    total_return_pct = ((total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100) if INITIAL_CAPITAL else 0.0
    utilisation_pct  = (invested / total * 100) if total > 0 else 0.0

    # Sector allocation of open positions
    sector_alloc = compute_sector_allocation(opens, total)

    # Strategy allocation of closed trades (by contribution)
    strat_contrib = compute_strategy_contribution(closed)

    # Concentration: largest single position weight
    position_weights = [float(p.get("weight_pct", 0)) for p in opens]
    max_position_wt  = max(position_weights) if position_weights else 0.0

    # Diversification score (1 - HHI where HHI = sum of weight^2)
    hhi = sum((w / 100) ** 2 for w in position_weights)
    div_score = round((1 - hhi) * 100, 2) if position_weights else 0.0

    # Risk_optimisation capital details
    risk_capital: Dict[str, Any] = {}
    try:
        from risk_optimisation.shared_services import get_capital
        risk_capital = get_capital()
    except Exception:
        pass

    return {
        "available":            True,
        "advisory_only":        True,
        "initial_capital":      INITIAL_CAPITAL,
        "total_value":          round(total, 2),
        "cash":                 round(cash, 2),
        "invested":             round(invested, 2),
        "total_return_pct":     round(total_return_pct, 4),
        "cash_utilisation_pct": round(utilisation_pct, 4),
        "position_concentration_pct": round(max_position_wt, 4),
        "diversification_score": div_score,
        "open_positions_count": len(opens),
        "open_positions":       opens,
        "sector_allocation":    sector_alloc,
        "strategy_allocation":  strat_contrib,
        "capital_growth_series": growth_series,
        "risk_capital_detail":  risk_capital,
    }
