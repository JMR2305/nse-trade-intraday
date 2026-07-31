"""
paper_analytics/sector_analytics.py — Phase 8.2
Sector-level trade analytics grouped from portfolio_performance closed trades.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import Any, Dict, List

KNOWN_SECTORS = [
    "Banking", "IT", "Auto", "Energy", "Pharma",
    "FMCG", "Metal", "Infra", "Finance", "Other",
]


def _normalise_sector(raw: str) -> str:
    """Map raw sector strings to one of the known categories."""
    if not raw:
        return "Other"
    lower = raw.lower()
    mapping = {
        "bank":     "Banking",
        "financial": "Finance",
        "finance":   "Finance",
        "informat":  "IT",
        "tech":      "IT",
        "software":  "IT",
        "auto":      "Auto",
        "automobile":"Auto",
        "energy":    "Energy",
        "oil":       "Energy",
        "gas":       "Energy",
        "pharma":    "Pharma",
        "health":    "Pharma",
        "fmcg":      "FMCG",
        "consumer":  "FMCG",
        "metal":     "Metal",
        "steel":     "Metal",
        "infra":     "Infra",
        "construct": "Infra",
    }
    for key, canonical in mapping.items():
        if key in lower:
            return canonical
    return "Other"


def _sector_row(sector: str, trades: list, total_pnl: float) -> Dict[str, Any]:
    n       = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    pnl_sum = sum(t.pnl for t in trades)
    wr      = len(winners) / n * 100 if n > 0 else 0.0
    avg_ret = _stats.mean(t.pnl for t in trades) if trades else 0.0
    contrib = (pnl_sum / total_pnl * 100) if total_pnl != 0 else 0.0
    return {
        "sector":           sector,
        "trade_count":      n,
        "winning_trades":   len(winners),
        "win_rate":         round(wr, 2),
        "avg_return":       round(avg_ret, 2),
        "total_pnl":        round(pnl_sum, 2),
        "contribution_pct": round(contrib, 2),
    }


def get_sector_analytics() -> Dict[str, Any]:
    """
    Per-sector breakdown from closed trades.
    Sectors not in KNOWN_SECTORS are bucketed into 'Other'.
    """
    from portfolio_performance.performance_engine import load_performance_data

    d      = load_performance_data()
    closed = d["closed_trades"]

    total_pnl = sum(t.pnl for t in closed) if closed else 0.0

    by_sector: Dict[str, list] = {}
    for t in closed:
        sec = _normalise_sector(t.sector or "")
        by_sector.setdefault(sec, []).append(t)

    rows = [_sector_row(sec, trades, total_pnl) for sec, trades in by_sector.items()]
    rows = sorted(rows, key=lambda r: -r["total_pnl"])

    best  = rows[0]["sector"]  if rows else "N/A"
    worst = rows[-1]["sector"] if rows else "N/A"

    # Best by win rate
    best_wr = max(rows, key=lambda r: r["win_rate"])["sector"] if rows else "N/A"

    return {
        "available":       True,
        "advisory_only":   True,
        "sectors":         rows,
        "best_sector":     best,
        "worst_sector":    worst,
        "best_win_rate_sector": best_wr,
        "total_sectors_traded": len(rows),
    }
