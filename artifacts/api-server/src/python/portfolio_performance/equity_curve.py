"""
portfolio_performance/equity_curve.py — Equity curve generation.

Derives daily / weekly / monthly equity snapshots from pnl_history and
closed trade P&L.  READ-ONLY — never writes to any table or file.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from .performance_models import EquityPoint

_DAY   = timedelta(days=1)
_WEEK  = timedelta(weeks=1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _isodate(dt: datetime) -> str:
    return dt.date().isoformat()


# ── Drawdown overlay ──────────────────────────────────────────────────────────

def _annotate_drawdown(points: List[EquityPoint]) -> None:
    """Mutate EquityPoint list in-place: compute drawdown from running peak."""
    peak = 0.0
    for p in points:
        if p.equity > peak:
            peak = p.equity
        dd = max(0.0, peak - p.equity)
        p.drawdown = dd
        p.drawdown_pct = (dd / peak * 100) if peak > 0 else 0.0


# ── Raw pnl_history → equity points ──────────────────────────────────────────

def _points_from_history(pnl_history: List[Dict[str, Any]]) -> List[EquityPoint]:
    """
    Convert raw pnl_history rows [{timestamp, value}] → sorted EquityPoint list.
    Deduplicates: keeps the last value per timestamp string.
    """
    seen: Dict[str, float] = {}
    for row in pnl_history:
        ts  = str(row.get("timestamp", "") or "")
        val = float(row.get("value", 0.0) or 0.0)
        if ts:
            seen[ts] = val

    points = sorted(
        [EquityPoint(timestamp=ts, equity=val) for ts, val in seen.items()],
        key=lambda p: p.timestamp,
    )
    return points


# ── Resample helpers ──────────────────────────────────────────────────────────

def _resample_daily(points: List[EquityPoint]) -> List[EquityPoint]:
    """Keep the last equity value per calendar day."""
    by_day: Dict[str, EquityPoint] = {}
    for p in points:
        dt = _parse_ts(p.timestamp)
        if dt is None:
            continue
        key = _isodate(dt)
        # last wins
        by_day[key] = p
    result = sorted(by_day.values(), key=lambda p: p.timestamp)
    _annotate_drawdown(result)
    return result


def _resample_weekly(daily: List[EquityPoint]) -> List[EquityPoint]:
    """Last value per ISO week."""
    by_week: Dict[str, EquityPoint] = {}
    for p in daily:
        dt = _parse_ts(p.timestamp)
        if dt is None:
            continue
        key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        by_week[key] = p
    result = sorted(by_week.values(), key=lambda p: p.timestamp)
    _annotate_drawdown(result)
    return result


def _resample_monthly(daily: List[EquityPoint]) -> List[EquityPoint]:
    """Last value per calendar month."""
    by_month: Dict[str, EquityPoint] = {}
    for p in daily:
        dt = _parse_ts(p.timestamp)
        if dt is None:
            continue
        key = f"{dt.year}-{dt.month:02d}"
        by_month[key] = p
    result = sorted(by_month.values(), key=lambda p: p.timestamp)
    _annotate_drawdown(result)
    return result


# ── Daily P&L bars ────────────────────────────────────────────────────────────

def compute_daily_pnl(daily_points: List[EquityPoint]) -> List[Dict[str, Any]]:
    """
    Return [{date, pnl, pnl_pct}] — change in equity from previous day.
    """
    bars = []
    for i, p in enumerate(daily_points):
        prev_equity = daily_points[i - 1].equity if i > 0 else p.equity
        pnl = p.equity - prev_equity
        pnl_pct = (pnl / prev_equity * 100) if prev_equity > 0 else 0.0
        dt = _parse_ts(p.timestamp)
        date_str = _isodate(dt) if dt else p.timestamp[:10]
        bars.append({
            "date":    date_str,
            "pnl":     round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "equity":  round(p.equity, 2),
        })
    return bars


def compute_monthly_pnl(monthly_points: List[EquityPoint]) -> List[Dict[str, Any]]:
    """Return [{month, pnl, pnl_pct}] bars."""
    bars = []
    for i, p in enumerate(monthly_points):
        prev = monthly_points[i - 1].equity if i > 0 else p.equity
        pnl = p.equity - prev
        pnl_pct = (pnl / prev * 100) if prev > 0 else 0.0
        dt = _parse_ts(p.timestamp)
        month_str = f"{dt.year}-{dt.month:02d}" if dt else p.timestamp[:7]
        bars.append({
            "month":   month_str,
            "pnl":     round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "equity":  round(p.equity, 2),
        })
    return bars


# ── Public entry point ────────────────────────────────────────────────────────

def build_equity_curves(pnl_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build all equity curve variants from raw pnl_history.

    Returns:
        {
          "daily":   [...EquityPoint dicts...],
          "weekly":  [...],
          "monthly": [...],
          "daily_pnl":   [{date, pnl, pnl_pct, equity}],
          "monthly_pnl": [{month, pnl, pnl_pct, equity}],
        }
    """
    raw = _points_from_history(pnl_history)
    _annotate_drawdown(raw)

    daily   = _resample_daily(raw)
    weekly  = _resample_weekly(daily)
    monthly = _resample_monthly(daily)

    return {
        "daily":       [p.to_dict() for p in daily],
        "weekly":      [p.to_dict() for p in weekly],
        "monthly":     [p.to_dict() for p in monthly],
        "daily_pnl":   compute_daily_pnl(daily),
        "monthly_pnl": compute_monthly_pnl(monthly),
    }
