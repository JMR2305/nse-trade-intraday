"""
regime_analyser.py — Phase 6.2
Market regime performance analysis.
Regimes: Bull, Bear, Sideways, High Volatility, Low Volatility, Trending, Gap Days, Expiry Days.
"""
from __future__ import annotations
import sys, os
from typing import List
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import RegimeRow

KNOWN_REGIMES = [
    "Bull", "Bear", "Sideways", "High Volatility", "Low Volatility",
    "Trending", "Gap Days", "Expiry Days",
]

# Normalise regime labels from trade metadata to canonical names
_NORM: dict = {
    "bullish": "Bull", "bull": "Bull",
    "bearish": "Bear", "bear": "Bear",
    "sideways": "Sideways", "ranging": "Sideways", "neutral": "Sideways",
    "high volatility": "High Volatility", "high_volatility": "High Volatility", "volatile": "High Volatility",
    "low volatility": "Low Volatility", "low_volatility": "Low Volatility", "calm": "Low Volatility",
    "trending": "Trending", "trend": "Trending",
    "gap": "Gap Days", "gap_up": "Gap Days", "gap_down": "Gap Days", "gap days": "Gap Days",
    "expiry": "Expiry Days", "expiry days": "Expiry Days", "weekly expiry": "Expiry Days",
}


def _norm_regime(raw: str) -> str:
    return _NORM.get(raw.lower().strip(), raw.title())


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def analyse_regimes(records: list) -> List[RegimeRow]:
    """Build one RegimeRow per regime, ranked by win rate × avg_return."""
    by_regime: dict = defaultdict(list)
    for r in records:
        regime = _norm_regime(r.market_regime or "Unknown")
        by_regime[regime].append(r)

    rows: List[RegimeRow] = []
    for regime, recs in by_regime.items():
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs)
        rows.append(RegimeRow(
            regime=regime,
            trades=len(recs),
            win_rate=round(wr, 4),
            avg_return_pct=round(_avg([r.pnl_pct for r in recs]), 4),
            net_pnl=round(sum(r.pnl for r in recs), 2),
            avg_confidence=round(_avg([r.ai_confidence for r in recs]), 4),
        ))

    # Rank by composite: win_rate × 0.6 + min(avg_return_pct / 5, 1) × 0.4
    rows.sort(
        key=lambda r: r.win_rate * 0.6 + min(abs(r.avg_return_pct) / 5.0, 1.0) * (0.4 if r.avg_return_pct > 0 else -0.4),
        reverse=True,
    )
    for i, row in enumerate(rows):
        row.rank = i + 1

    return rows
