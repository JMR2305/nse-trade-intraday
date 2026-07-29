"""
strategy_intelligence/market_regime_analysis.py — Regime-based performance analysis.

Analyses which strategies perform best in each market regime.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .strategy_models import ClosedTrade, REGIMES


def _regime_key(t: ClosedTrade) -> str:
    r = (t.market_regime or "Unknown").strip()
    return r if r else "Unknown"


def compute_regime_matrix(closed_trades: List[ClosedTrade]) -> Dict[str, Any]:
    """
    Build a matrix: {regime: {overall_stats, per_strategy_breakdown}}.
    Also returns best_strategy_per_regime.
    """
    # Group trades by regime
    by_regime: Dict[str, List[ClosedTrade]] = {}
    for t in closed_trades:
        r = _regime_key(t)
        by_regime.setdefault(r, []).append(t)

    matrix: Dict[str, Any] = {}
    best_per_regime: Dict[str, str] = {}

    for regime, trades in by_regime.items():
        wins = [t for t in trades if t.is_winner()]
        n    = len(trades)
        pnl  = sum(t.pnl for t in trades)
        wr   = len(wins) / n * 100 if n > 0 else 0.0

        # Per-strategy breakdown within this regime
        by_strat: Dict[str, List[ClosedTrade]] = {}
        for t in trades:
            by_strat.setdefault(t.strategy_name, []).append(t)

        strat_rows = []
        for sname, strades in by_strat.items():
            sw = [t for t in strades if t.is_winner()]
            spnl = sum(t.pnl for t in strades)
            swr  = len(sw) / len(strades) * 100 if strades else 0.0
            strat_rows.append({
                "strategy_name": sname,
                "trades":        len(strades),
                "win_rate":      round(swr, 2),
                "net_pnl":       round(spnl, 2),
            })
        strat_rows.sort(key=lambda r: -r["net_pnl"])

        matrix[regime] = {
            "trades":             n,
            "winning_trades":     len(wins),
            "win_rate":           round(wr, 2),
            "net_pnl":            round(pnl, 2),
            "avg_pnl":            round(_stats.mean(t.pnl for t in trades), 2),
            "strategy_breakdown": strat_rows,
        }

        if strat_rows:
            best_per_regime[regime] = strat_rows[0]["strategy_name"]

    return {
        "matrix":            matrix,
        "best_per_regime":   best_per_regime,
        "regimes_seen":      sorted(matrix.keys()),
        "total_regimes":     len(matrix),
    }


def get_regime_summary(regime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flat list of regime rows for table display, sorted by net P&L desc."""
    matrix = regime_data.get("matrix", {})
    best   = regime_data.get("best_per_regime", {})
    rows = []
    for regime, stats in matrix.items():
        rows.append({
            "regime":          regime,
            "trades":          stats["trades"],
            "win_rate":        stats["win_rate"],
            "net_pnl":         stats["net_pnl"],
            "avg_pnl":         stats["avg_pnl"],
            "best_strategy":   best.get(regime, "—"),
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])
