"""
metrics_engine.py — Phase 6.1
Computes validation metrics: daily, weekly, monthly, rolling 30/90/180 days.
All computation is from TradeRecord objects — zero raw data re-reads.
"""
from __future__ import annotations
import sys, os
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .validation_models import TradeRecord, DailyMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(ts: str) -> Optional[date]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.date()
    except Exception:
        return None


def _avg(values: list) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _win_rate(records: List[TradeRecord]) -> float:
    if not records:
        return 0.0
    winners = sum(1 for r in records if r.pnl > 0)
    return winners / len(records)


def _net_pnl(records: List[TradeRecord]) -> float:
    return sum(r.pnl for r in records)


def _max_drawdown(records: List[TradeRecord]) -> float:
    """Simple peak-to-trough drawdown on running P&L."""
    if not records:
        return 0.0
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in records:
        running += r.pnl
        if running > peak:
            peak = running
        dd = (peak - running) / abs(peak) if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _group_by_date(records: List[TradeRecord]) -> Dict[date, List[TradeRecord]]:
    groups: Dict[date, List[TradeRecord]] = {}
    for r in records:
        d = _parse_date(r.timestamp)
        if d:
            groups.setdefault(d, []).append(r)
    return groups


# ---------------------------------------------------------------------------
# Daily metrics
# ---------------------------------------------------------------------------

def compute_daily_metrics(records: List[TradeRecord], target_date: Optional[date] = None) -> DailyMetrics:
    if target_date is None:
        target_date = date.today()
    day_records = [r for r in records if _parse_date(r.timestamp) == target_date]
    return _make_daily(target_date.isoformat(), day_records)


def _make_daily(date_str: str, records: List[TradeRecord]) -> DailyMetrics:
    winners = [r for r in records if r.pnl > 0]
    losers = [r for r in records if r.pnl <= 0]
    net = _net_pnl(records)
    gross = sum(r.pnl for r in records if r.pnl > 0)
    return DailyMetrics(
        date=date_str,
        trade_count=len(records),
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=_win_rate(records),
        net_pnl=net,
        gross_pnl=gross,
        drawdown=_max_drawdown(records),
        avg_holding_time_minutes=_avg([r.holding_time_minutes for r in records]),
        avg_slippage=_avg([abs(r.pnl_pct) for r in records]),
        avg_ai_confidence=_avg([r.ai_confidence for r in records]),
        avg_execution_score=_avg([r.execution_quality_score for r in records]),
        avg_executive_score=_avg([r.executive_score_snapshot for r in records]),
    )


# ---------------------------------------------------------------------------
# Period aggregates
# ---------------------------------------------------------------------------

def compute_period_metrics(records: List[TradeRecord], period: str) -> dict:
    """
    period: 'weekly' | 'monthly' | 'rolling_30' | 'rolling_90' | 'rolling_180'
    Returns a dict summary for that period.
    """
    today = date.today()

    if period == "weekly":
        start = today - timedelta(days=today.weekday())  # Monday
    elif period == "monthly":
        start = today.replace(day=1)
    elif period == "rolling_30":
        start = today - timedelta(days=30)
    elif period == "rolling_90":
        start = today - timedelta(days=90)
    elif period == "rolling_180":
        start = today - timedelta(days=180)
    else:
        start = today - timedelta(days=30)

    period_records = [r for r in records if _parse_date(r.timestamp) and _parse_date(r.timestamp) >= start]

    if not period_records:
        return {
            "period": period,
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "trade_count": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "drawdown": 0.0,
            "avg_holding_time_minutes": 0.0,
            "avg_ai_confidence": 0.0,
            "avg_execution_score": 0.0,
            "avg_executive_score": 0.0,
            "best_day": None,
            "worst_day": None,
            "available": True,
            "note": "No trades in period.",
        }

    # Per-day breakdown
    by_date = _group_by_date(period_records)
    daily_pnls = {d.isoformat(): _net_pnl(recs) for d, recs in by_date.items()}
    best_day = max(daily_pnls, key=daily_pnls.get) if daily_pnls else None
    worst_day = min(daily_pnls, key=daily_pnls.get) if daily_pnls else None

    return {
        "period": period,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "trade_count": len(period_records),
        "winning_trades": sum(1 for r in period_records if r.pnl > 0),
        "losing_trades": sum(1 for r in period_records if r.pnl <= 0),
        "win_rate": round(_win_rate(period_records), 4),
        "net_pnl": round(_net_pnl(period_records), 2),
        "gross_pnl": round(sum(r.pnl for r in period_records if r.pnl > 0), 2),
        "drawdown": round(_max_drawdown(period_records), 4),
        "avg_holding_time_minutes": round(_avg([r.holding_time_minutes for r in period_records]), 1),
        "avg_ai_confidence": round(_avg([r.ai_confidence for r in period_records]), 4),
        "avg_execution_score": round(_avg([r.execution_quality_score for r in period_records]), 4),
        "avg_executive_score": round(_avg([r.executive_score_snapshot for r in period_records]), 4),
        "best_day": best_day,
        "worst_day": worst_day,
        "available": True,
    }


# ---------------------------------------------------------------------------
# Full historical view: all daily rows + period roll-ups
# ---------------------------------------------------------------------------

def compute_history(records: List[TradeRecord]) -> dict:
    """All daily rows sorted descending, plus 5 period aggregates."""
    by_date = _group_by_date(records)
    daily_rows = [
        _make_daily(d.isoformat(), recs).to_dict()
        for d, recs in sorted(by_date.items(), reverse=True)
    ]
    return {
        "daily": daily_rows,
        "weekly": compute_period_metrics(records, "weekly"),
        "monthly": compute_period_metrics(records, "monthly"),
        "rolling_30": compute_period_metrics(records, "rolling_30"),
        "rolling_90": compute_period_metrics(records, "rolling_90"),
        "rolling_180": compute_period_metrics(records, "rolling_180"),
        "total_trading_days": len(by_date),
        "available": True,
    }


# ---------------------------------------------------------------------------
# Dataset growth over time
# ---------------------------------------------------------------------------

def compute_dataset_growth(records: List[TradeRecord]) -> dict:
    """Cumulative trade count and cumulative P&L by date — for the growth chart."""
    by_date = _group_by_date(records)
    rows = []
    cumulative_count = 0
    cumulative_pnl = 0.0
    for d in sorted(by_date.keys()):
        day_recs = by_date[d]
        cumulative_count += len(day_recs)
        cumulative_pnl += _net_pnl(day_recs)
        rows.append({
            "date": d.isoformat(),
            "trades_that_day": len(day_recs),
            "cumulative_trades": cumulative_count,
            "daily_pnl": round(_net_pnl(day_recs), 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
        })
    return {"growth": rows, "total_records": len(records), "available": True}


# ---------------------------------------------------------------------------
# Validation statistics summary
# ---------------------------------------------------------------------------

def compute_statistics(records: List[TradeRecord]) -> dict:
    """Overall statistics across all collected records."""
    if not records:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "avg_ai_confidence": 0.0,
            "avg_execution_score": 0.0,
            "avg_executive_score": 0.0,
            "avg_holding_time_minutes": 0.0,
            "max_drawdown": 0.0,
            "best_trade_pnl": 0.0,
            "worst_trade_pnl": 0.0,
            "strategies": [],
            "sectors": [],
            "exit_reasons": {},
            "available": True,
            "note": "No completed trades yet.",
        }

    # Strategy breakdown
    from collections import Counter
    strat_counter: Counter = Counter(r.strategy for r in records)
    strat_stats = []
    for strat, count in strat_counter.most_common():
        strat_recs = [r for r in records if r.strategy == strat]
        strat_stats.append({
            "strategy": strat,
            "trades": count,
            "win_rate": round(_win_rate(strat_recs), 4),
            "net_pnl": round(_net_pnl(strat_recs), 2),
        })

    # Sector breakdown
    sector_counter: Counter = Counter(r.sector for r in records)
    sector_stats = []
    for sector, count in sector_counter.most_common():
        sector_recs = [r for r in records if r.sector == sector]
        sector_stats.append({
            "sector": sector,
            "trades": count,
            "win_rate": round(_win_rate(sector_recs), 4),
            "net_pnl": round(_net_pnl(sector_recs), 2),
        })

    # Exit reasons
    exit_counter: Counter = Counter(r.exit_reason for r in records)

    pnls = [r.pnl for r in records]

    return {
        "total_trades": len(records),
        "winning_trades": sum(1 for r in records if r.pnl > 0),
        "losing_trades": sum(1 for r in records if r.pnl <= 0),
        "win_rate": round(_win_rate(records), 4),
        "net_pnl": round(_net_pnl(records), 2),
        "avg_ai_confidence": round(_avg([r.ai_confidence for r in records]), 4),
        "avg_execution_score": round(_avg([r.execution_quality_score for r in records]), 4),
        "avg_executive_score": round(_avg([r.executive_score_snapshot for r in records]), 4),
        "avg_holding_time_minutes": round(_avg([r.holding_time_minutes for r in records]), 1),
        "max_drawdown": round(_max_drawdown(records), 4),
        "best_trade_pnl": round(max(pnls), 2),
        "worst_trade_pnl": round(min(pnls), 2),
        "strategies": strat_stats,
        "sectors": sector_stats,
        "exit_reasons": dict(exit_counter),
        "available": True,
    }
