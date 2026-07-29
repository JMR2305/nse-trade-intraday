"""
portfolio_performance/statistics.py — Trade and risk statistics.

READ-ONLY.  PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from .performance_models import ClosedTrade


# ── Date helpers ──────────────────────────────────────────────────────────────

def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _now_ist() -> datetime:
    """Current time in IST (UTC+5:30)."""
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_offset)


def _period_pnl(trades: List[ClosedTrade], since: datetime) -> float:
    total = 0.0
    for t in trades:
        dt = _parse_ts(t.exit_ts)
        if dt and (dt.tzinfo is None
                   and dt.replace(tzinfo=timezone.utc) >= since
                   or dt is not None and dt.tzinfo is not None and dt >= since):
            total += t.pnl
    return total


def _period_pnl_since(trades: List[ClosedTrade], since: datetime) -> float:
    """Sum P&L for trades exited on or after `since`."""
    total = 0.0
    for t in trades:
        dt = _parse_ts(t.exit_ts)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= since:
            total += t.pnl
    return total


# ── P&L period cuts ───────────────────────────────────────────────────────────

def compute_period_pnl(closed_trades: List[ClosedTrade]) -> Dict[str, float]:
    now = _now_ist()
    today_start   = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start    = today_start - timedelta(days=today_start.weekday())   # Mon
    month_start   = today_start.replace(day=1)

    return {
        "today_pnl":   round(_period_pnl_since(closed_trades, today_start), 2),
        "weekly_pnl":  round(_period_pnl_since(closed_trades, week_start), 2),
        "monthly_pnl": round(_period_pnl_since(closed_trades, month_start), 2),
    }


# ── Trade statistics ──────────────────────────────────────────────────────────

def compute_trade_statistics(closed_trades: List[ClosedTrade]) -> Dict[str, Any]:
    """Win rate, avg winner/loser, holding time, etc."""
    if not closed_trades:
        return {
            "total_trades":       0,
            "winning_trades":     0,
            "losing_trades":      0,
            "breakeven_trades":   0,
            "win_rate":           0.0,
            "loss_rate":          0.0,
            "avg_winner":         0.0,
            "avg_loser":          0.0,
            "largest_profit":     0.0,
            "largest_loss":       0.0,
            "avg_holding_seconds": 0.0,
            "avg_holding_human":  "—",
        }

    winners  = [t for t in closed_trades if t.pnl > 0]
    losers   = [t for t in closed_trades if t.pnl < 0]
    n        = len(closed_trades)

    win_rate  = len(winners) / n * 100 if n > 0 else 0.0
    loss_rate = len(losers)  / n * 100 if n > 0 else 0.0

    avg_winner = _stats.mean(t.pnl for t in winners) if winners else 0.0
    avg_loser  = _stats.mean(t.pnl for t in losers)  if losers  else 0.0

    largest_profit = max((t.pnl for t in closed_trades), default=0.0)
    largest_loss   = min((t.pnl for t in closed_trades), default=0.0)

    holding_times = [t.holding_seconds for t in closed_trades if t.holding_seconds > 0]
    avg_hold = _stats.mean(holding_times) if holding_times else 0.0

    # Human-readable holding time
    def _human(sec: float) -> str:
        if sec <= 0:
            return "—"
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {int(sec % 60)}s"
        return f"{int(sec)}s"

    return {
        "total_trades":        n,
        "winning_trades":      len(winners),
        "losing_trades":       len(losers),
        "breakeven_trades":    n - len(winners) - len(losers),
        "win_rate":            round(win_rate, 4),
        "loss_rate":           round(loss_rate, 4),
        "avg_winner":          round(avg_winner, 2),
        "avg_loser":           round(avg_loser, 2),
        "largest_profit":      round(largest_profit, 2),
        "largest_loss":        round(largest_loss, 2),
        "avg_holding_seconds": round(avg_hold, 1),
        "avg_holding_human":   _human(avg_hold),
    }


# ── Risk metrics ──────────────────────────────────────────────────────────────

def compute_risk_metrics(closed_trades: List[ClosedTrade]) -> Dict[str, Any]:
    """Profit factor, expectancy, risk/reward, avg R-multiple."""
    winners = [t for t in closed_trades if t.pnl > 0]
    losers  = [t for t in closed_trades if t.pnl < 0]
    n       = len(closed_trades)

    gross_profit = sum(t.pnl for t in winners)
    gross_loss   = abs(sum(t.pnl for t in losers))

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    # Cap at 999 for JSON sanity
    if profit_factor == float("inf"):
        profit_factor = 999.0

    avg_winner = _stats.mean(t.pnl for t in winners) if winners else 0.0
    avg_loser  = _stats.mean(t.pnl for t in losers)  if losers  else 0.0

    win_rate = len(winners) / n if n > 0 else 0.0
    expectancy = (win_rate * avg_winner) + ((1 - win_rate) * avg_loser)

    rr_ratio = (avg_winner / abs(avg_loser)) if avg_loser != 0 else 0.0

    # R-multiple: pnl / stop-loss-distance per trade
    r_multiples = []
    for t in closed_trades:
        if t.stop_loss > 0 and t.entry_price > 0:
            risk = abs(t.entry_price - t.stop_loss)
            if risk > 0:
                r_multiples.append(t.pnl / (risk * t.quantity))
    avg_r = _stats.mean(r_multiples) if r_multiples else 0.0

    return {
        "profit_factor":    round(profit_factor, 4),
        "gross_profit":     round(gross_profit, 2),
        "gross_loss":       round(gross_loss, 2),
        "expectancy":       round(expectancy, 2),
        "risk_reward_ratio": round(rr_ratio, 4),
        "avg_r_multiple":   round(avg_r, 4),
    }


# ── Strategy contribution ─────────────────────────────────────────────────────

def compute_strategy_contribution(closed_trades: List[ClosedTrade]) -> List[Dict[str, Any]]:
    """Aggregate performance by strategy_name."""
    by_strategy: Dict[str, List[ClosedTrade]] = {}
    for t in closed_trades:
        name = t.strategy_name or "Unknown"
        by_strategy.setdefault(name, []).append(t)

    rows = []
    for name, trades in by_strategy.items():
        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        total_pnl = sum(t.pnl for t in trades)
        wr = len(wins) / len(trades) * 100 if trades else 0.0
        rows.append({
            "strategy_name": name,
            "total_trades":  len(trades),
            "winning_trades": len(wins),
            "losing_trades":  len(losses),
            "win_rate":      round(wr, 2),
            "total_pnl":     round(total_pnl, 2),
            "avg_pnl":       round(_stats.mean(t.pnl for t in trades), 2) if trades else 0.0,
        })
    return sorted(rows, key=lambda r: -abs(r["total_pnl"]))


# ── Sector analytics ──────────────────────────────────────────────────────────

def compute_sector_allocation(
    open_positions: List[Dict[str, Any]],
    total_value: float,
) -> List[Dict[str, Any]]:
    """Return sector breakdown of open positions."""
    by_sector: Dict[str, float] = {}
    for pos in open_positions:
        sector = pos.get("sector") or "Unknown"
        value  = float(pos.get("current_value", 0.0))
        by_sector[sector] = by_sector.get(sector, 0.0) + value

    rows = []
    for sector, value in sorted(by_sector.items(), key=lambda x: -x[1]):
        pct = (value / total_value * 100) if total_value > 0 else 0.0
        rows.append({
            "sector": sector,
            "value":  round(value, 2),
            "pct":    round(pct, 2),
        })
    return rows
