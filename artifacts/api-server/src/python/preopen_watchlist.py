"""
preopen_watchlist.py — Phase 5A Pre-Open Intelligence watchlist generator.

At 09:15 produces 8 ranked lists. Classification is advisory only.
No trade entries from pre-open data.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from typing import List, Dict, Any
from preopen_data_model import PreOpenSnapshot, WatchlistItem, Classification

# Post-open confirmation criteria required before any entry
_CONFIRMATION_CHECKLIST = [
    "first_5min_candle_close",
    "opening_range_breakout",
    "live_relative_volume",
    "spread_liquidity_check",
    "NIFTY_direction",
    "sector_direction",
    "risk_engine_approval",
    "VWAP_relationship",
    "india_vix_check",
    "stale_data_gate",
]


def _build_risk_flags(s: PreOpenSnapshot) -> List[str]:
    flags = []
    if s.is_stale:
        flags.append("STALE_DATA")
    if s.data_freshness_seconds > 300:
        flags.append("DATA_OLDER_5MIN")
    if abs(s.gap_percent or 0) > 5:
        flags.append("EXTREME_GAP_RISK")
    if s.liquidity_score < 10:
        flags.append("LOW_LIQUIDITY")
    if abs(s.imbalance_percent) < 10:
        flags.append("BALANCED_ORDER_BOOK")
    if s.total_buy_quantity + s.total_sell_quantity < 5000:
        flags.append("THIN_ORDER_BOOK")
    return flags


def _build_explanation(s: PreOpenSnapshot) -> str:
    parts = []
    if s.gap_percent is not None:
        direction = "gap-up" if s.gap_percent > 0 else "gap-down" if s.gap_percent < 0 else "flat open"
        parts.append(f"{abs(s.gap_percent):.2f}% {direction}")
    if abs(s.imbalance_percent) > 20:
        side = "buy" if s.imbalance_percent > 0 else "sell"
        parts.append(f"{abs(s.imbalance_percent):.1f}% {side}-side imbalance")
    if s.final_executed_quantity > 10000:
        parts.append(f"high pre-open participation ({s.final_executed_quantity:,} qty)")
    if s.opportunity_score >= 60:
        parts.append(f"strong opportunity score {s.opportunity_score:.0f}/100")
    if not parts:
        parts.append("watch — limited pre-open data available")
    return "; ".join(parts) + ". Requires post-open confirmation before any entry."


def _to_watchlist_item(rank: int, s: PreOpenSnapshot) -> WatchlistItem:
    return WatchlistItem(
        rank=rank,
        symbol=s.symbol,
        sector=s.sector,
        gap_percent=s.gap_percent or 0.0,
        imbalance_percent=s.imbalance_percent,
        executed_quantity=s.final_executed_quantity,
        liquidity_score=s.liquidity_score,
        opportunity_score=s.opportunity_score,
        classification=s.classification,
        risk_flags=_build_risk_flags(s),
        explanation=_build_explanation(s),
        required_post_open_confirmation=_CONFIRMATION_CHECKLIST[:],
        previous_close=s.previous_close,
        indicative_price=s.indicative_open_price,
    )


def generate_watchlists(snapshots: List[PreOpenSnapshot], top_n: int = 10) -> Dict[str, List[dict]]:
    """
    Generate 8 ranked watchlists from the frozen 09:15 snapshot universe.
    Stale snapshots are excluded from all lists.
    """
    valid = [s for s in snapshots if not s.is_stale and s.validation_status == "VALID"]

    def top(lst: List[PreOpenSnapshot], n: int) -> List[dict]:
        return [_to_watchlist_item(i + 1, s).to_dict() for i, s in enumerate(lst[:n])]

    # Top gap-up: highest positive gap %
    gap_up = sorted([s for s in valid if (s.gap_percent or 0) > 0],
                    key=lambda s: -(s.gap_percent or 0))

    # Top gap-down: most negative gap %
    gap_down = sorted([s for s in valid if (s.gap_percent or 0) < 0],
                      key=lambda s: (s.gap_percent or 0))

    # Buy imbalance: highest positive imbalance %
    buy_imb = sorted([s for s in valid if s.imbalance_percent > 10],
                     key=lambda s: -s.imbalance_percent)

    # Sell imbalance: most negative imbalance %
    sell_imb = sorted([s for s in valid if s.imbalance_percent < -10],
                      key=lambda s: s.imbalance_percent)

    # Highest executed quantity
    high_exec = sorted([s for s in valid if s.final_executed_quantity > 0],
                       key=lambda s: -s.final_executed_quantity)

    # Sector leaders: one per sector, highest avg_gap
    sectors: Dict[str, list] = {}
    for s in valid:
        sectors.setdefault(s.sector, []).append(s)
    sector_leaders = []
    sector_laggards = []
    for sec, syms in sectors.items():
        if not syms:
            continue
        best = sorted(syms, key=lambda s: -(s.gap_percent or 0))[0]
        sector_leaders.append(best)
        worst = sorted(syms, key=lambda s: (s.gap_percent or 0))[0]
        sector_laggards.append(worst)
    sector_leaders.sort(key=lambda s: -(s.gap_percent or 0))
    sector_laggards.sort(key=lambda s: (s.gap_percent or 0))

    # Overall ranked by opportunity score
    overall = sorted(valid, key=lambda s: -(s.opportunity_score or 0))

    return {
        "top_gap_up":           top(gap_up, top_n),
        "top_gap_down":         top(gap_down, top_n),
        "buy_imbalance":        top(buy_imb, top_n),
        "sell_imbalance":       top(sell_imb, top_n),
        "highest_executed_qty": top(high_exec, top_n),
        "sector_leaders":       top(sector_leaders, top_n),
        "sector_laggards":      top(sector_laggards, top_n),
        "overall_ranked":       top(overall, top_n),
    }
