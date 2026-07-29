"""
sector_analyser.py — Phase 6.2
Sector ranking by win rate, net P&L, risk, and consistency.
"""
from __future__ import annotations
import sys, os
from typing import List
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import SectorRow


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _consistency(records: list) -> float:
    """Simple consistency: proportion of 5-trade windows that are net positive."""
    if len(records) < 5:
        wr = sum(1 for r in records if r.pnl > 0) / max(len(records), 1)
        return round(wr * 0.8, 4)
    sorted_recs = sorted(records, key=lambda x: x.timestamp)
    pos = sum(
        1 for i in range(len(sorted_recs) - 4)
        if sum(r.pnl for r in sorted_recs[i:i + 5]) > 0
    )
    return round(pos / (len(sorted_recs) - 4), 4)


def analyse_sectors(records: list) -> List[SectorRow]:
    """Build one SectorRow per sector, ranked by composite score."""
    by_sector: dict = defaultdict(list)
    for r in records:
        by_sector[r.sector or "Unknown"].append(r)

    rows: List[SectorRow] = []
    for sector, recs in by_sector.items():
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
        rows.append(SectorRow(
            sector=sector,
            trades=len(recs),
            win_rate=round(wr, 4),
            net_pnl=round(sum(r.pnl for r in recs), 2),
            avg_return_pct=round(_avg([r.pnl_pct for r in recs]), 4),
            avg_risk_score=round(_avg([r.risk_score for r in recs]), 4),
            consistency_score=_consistency(recs),
        ))

    # Composite rank: win_rate × 0.4 + net_pnl_norm × 0.3 + consistency × 0.3
    if rows:
        max_abs_pnl = max(abs(r.net_pnl) for r in rows) or 1.0
        rows.sort(
            key=lambda r: r.win_rate * 0.4 + (r.net_pnl / max_abs_pnl) * 0.3 + r.consistency_score * 0.3,
            reverse=True,
        )
    for i, row in enumerate(rows):
        row.rank = i + 1

    return rows
