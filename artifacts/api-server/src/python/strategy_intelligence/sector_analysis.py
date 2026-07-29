"""
strategy_intelligence/sector_analysis.py — Sector-based performance analysis.

Analyses strategy performance across market sectors.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .strategy_models import ClosedTrade

KNOWN_SECTORS = [
    "Banking", "IT", "Pharma", "Auto", "FMCG",
    "Energy", "Metal", "Realty", "Financial Services",
]


def compute_sector_matrix(closed_trades: List[ClosedTrade]) -> Dict[str, Any]:
    """
    Build sector-level performance matrix.
    Returns overall sector stats + per-strategy breakdown per sector.
    """
    by_sector: Dict[str, List[ClosedTrade]] = {}
    for t in closed_trades:
        s = (t.sector or "Unknown").strip()
        by_sector.setdefault(s, []).append(t)

    matrix: Dict[str, Any] = {}

    for sector, trades in by_sector.items():
        wins  = [t for t in trades if t.is_winner()]
        n     = len(trades)
        pnl   = sum(t.pnl for t in trades)
        wr    = len(wins) / n * 100 if n > 0 else 0.0
        avg_pnl = _stats.mean(t.pnl for t in trades) if trades else 0.0

        by_strat: Dict[str, List[ClosedTrade]] = {}
        for t in trades:
            by_strat.setdefault(t.strategy_name, []).append(t)

        strat_rows = []
        for sname, strades in by_strat.items():
            sw   = [t for t in strades if t.is_winner()]
            spnl = sum(t.pnl for t in strades)
            swr  = len(sw) / len(strades) * 100 if strades else 0.0
            strat_rows.append({
                "strategy_name": sname,
                "trades":        len(strades),
                "win_rate":      round(swr, 2),
                "net_pnl":       round(spnl, 2),
            })
        strat_rows.sort(key=lambda r: -r["net_pnl"])

        matrix[sector] = {
            "trades":             n,
            "winning_trades":     len(wins),
            "win_rate":           round(wr, 2),
            "net_pnl":            round(pnl, 2),
            "avg_pnl":            round(avg_pnl, 2),
            "strategy_breakdown": strat_rows,
        }

    # Derived highlights
    if matrix:
        best_sector  = max(matrix, key=lambda s: matrix[s]["net_pnl"])
        worst_sector = min(matrix, key=lambda s: matrix[s]["net_pnl"])
        best_wr      = max(matrix, key=lambda s: matrix[s]["win_rate"])
        best_return  = best_sector   # same as best_pnl for now
    else:
        best_sector = worst_sector = best_wr = best_return = None

    return {
        "matrix":       matrix,
        "best_sector":  best_sector,
        "worst_sector": worst_sector,
        "highest_win_rate_sector": best_wr,
        "highest_return_sector":   best_return,
        "sectors_seen": sorted(matrix.keys()),
    }


def get_sector_summary(sector_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flat list of sector rows for table display, sorted by net P&L desc."""
    matrix = sector_data.get("matrix", {})
    rows = []
    for sector, stats in matrix.items():
        rows.append({
            "sector":   sector,
            "trades":   stats["trades"],
            "win_rate": stats["win_rate"],
            "net_pnl":  stats["net_pnl"],
            "avg_pnl":  stats["avg_pnl"],
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])
