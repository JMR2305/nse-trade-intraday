"""
strategy_intelligence/time_analysis.py — Time-of-day and day-of-week analysis.

Analyses trading performance by IST time slot and day of week.
READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .strategy_models import ClosedTrade, TIME_SLOTS, DAYS_OF_WEEK


def _slot_stats(trades: List[ClosedTrade]) -> Dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "avg_pnl": 0.0}
    wins = [t for t in trades if t.is_winner()]
    pnl  = sum(t.pnl for t in trades)
    wr   = len(wins) / len(trades) * 100
    return {
        "trades":   len(trades),
        "wins":     len(wins),
        "win_rate": round(wr, 2),
        "net_pnl":  round(pnl, 2),
        "avg_pnl":  round(_stats.mean(t.pnl for t in trades), 2),
    }


def compute_time_analysis(closed_trades: List[ClosedTrade]) -> Dict[str, Any]:
    """
    Break down performance by:
      - IST time slot (09:15–10:00, etc.)
      - Day of week (Monday–Friday)
      - Hour (9–15)
    Also returns best/worst day and best/worst hour.
    """
    # ── Time slots ────────────────────────────────────────────────────────────
    by_slot: Dict[str, List[ClosedTrade]] = {s: [] for s in TIME_SLOTS}
    for t in closed_trades:
        slot = t.time_slot or "09:15–10:00"
        by_slot.setdefault(slot, []).append(t)

    slot_matrix = {slot: _slot_stats(trades) for slot, trades in by_slot.items()}

    # ── Day of week ───────────────────────────────────────────────────────────
    by_day: Dict[str, List[ClosedTrade]] = {d: [] for d in DAYS_OF_WEEK}
    for t in closed_trades:
        day = t.day_of_week or ""
        if day in DAYS_OF_WEEK:
            by_day[day].append(t)

    day_matrix = {day: _slot_stats(trades) for day, trades in by_day.items()}

    # ── Hour ──────────────────────────────────────────────────────────────────
    by_hour: Dict[int, List[ClosedTrade]] = {}
    for t in closed_trades:
        h = t.hour_ist or 9
        by_hour.setdefault(h, []).append(t)

    hour_matrix = {str(h): _slot_stats(trades) for h, trades in sorted(by_hour.items())}

    # ── Best / worst highlights ───────────────────────────────────────────────
    days_with_trades  = [(d, day_matrix[d]) for d in DAYS_OF_WEEK if day_matrix[d]["trades"] > 0]
    hours_with_trades = [(h, s) for h, s in hour_matrix.items() if s["trades"] > 0]
    slots_with_trades = [(s, slot_matrix[s]) for s in TIME_SLOTS if slot_matrix[s]["trades"] > 0]

    best_day  = max(days_with_trades,  key=lambda x: x[1]["net_pnl"])[0]  if days_with_trades  else None
    worst_day = min(days_with_trades,  key=lambda x: x[1]["net_pnl"])[0]  if days_with_trades  else None
    best_hour = max(hours_with_trades, key=lambda x: x[1]["net_pnl"])[0]  if hours_with_trades else None
    worst_hour= min(hours_with_trades, key=lambda x: x[1]["net_pnl"])[0]  if hours_with_trades else None
    best_slot = max(slots_with_trades, key=lambda x: x[1]["net_pnl"])[0]  if slots_with_trades else None
    worst_slot= min(slots_with_trades, key=lambda x: x[1]["net_pnl"])[0]  if slots_with_trades else None

    return {
        "slot_matrix":  slot_matrix,
        "day_matrix":   day_matrix,
        "hour_matrix":  hour_matrix,
        "best_day":     best_day,
        "worst_day":    worst_day,
        "best_hour":    best_hour,
        "worst_hour":   worst_hour,
        "best_slot":    best_slot,
        "worst_slot":   worst_slot,
    }
