"""
paper_analytics/time_analytics.py — Phase 8.2
Time-of-day and session analytics from closed trade entry timestamps.

Sessions (IST):
  Opening:   09:15–09:30
  Morning:   09:30–11:00
  Mid:       11:00–13:00
  Afternoon: 13:00–14:30
  Closing:   14:30–15:30

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

import statistics as _stats
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

_IST = timezone(timedelta(hours=5, minutes=30))

SESSIONS = [
    ("Opening",   (9, 15), (9, 30)),
    ("Morning",   (9, 30), (11, 0)),
    ("Mid",       (11, 0), (13, 0)),
    ("Afternoon", (13, 0), (14, 30)),
    ("Closing",   (14, 30), (15, 30)),
]


def _to_ist(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST)
    except Exception:
        return None


def _session_of(dt: datetime) -> str:
    h, m = dt.hour, dt.minute
    total = h * 60 + m
    for name, (sh, sm), (eh, em) in SESSIONS:
        if sh * 60 + sm <= total < eh * 60 + em:
            return name
    return "Other"


def _session_row(session: str, trades: list) -> Dict[str, Any]:
    n       = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    pnl_sum = sum(t.pnl for t in trades)
    wr      = len(winners) / n * 100 if n > 0 else 0.0
    avg_ret = _stats.mean(t.pnl for t in trades) if trades else 0.0
    holds   = [t.holding_seconds for t in trades if t.holding_seconds > 0]
    avg_hold = _stats.mean(holds) if holds else 0.0
    return {
        "session":          session,
        "trade_count":      n,
        "win_rate":         round(wr, 2),
        "avg_return":       round(avg_ret, 2),
        "total_pnl":        round(pnl_sum, 2),
        "avg_hold_seconds": round(avg_hold, 1),
    }


def _hour_row(hour: int, trades: list) -> Dict[str, Any]:
    n       = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    wr      = len(winners) / n * 100 if n > 0 else 0.0
    avg_ret = _stats.mean(t.pnl for t in trades) if trades else 0.0
    return {
        "hour":        hour,
        "label":       f"{hour:02d}:00",
        "trade_count": n,
        "win_rate":    round(wr, 2),
        "avg_return":  round(avg_ret, 2),
    }


def get_time_analytics() -> Dict[str, Any]:
    """
    Time-of-day and session performance analytics.
    """
    from portfolio_performance.performance_engine import load_performance_data

    d      = load_performance_data()
    closed = d["closed_trades"]

    by_session: Dict[str, list] = {}
    by_hour:    Dict[int, list]  = {}

    for t in closed:
        dt_ist = _to_ist(t.entry_ts)
        if dt_ist is None:
            continue
        sess = _session_of(dt_ist)
        by_session.setdefault(sess, []).append(t)
        by_hour.setdefault(dt_ist.hour, []).append(t)

    session_rows = [
        _session_row(name, by_session.get(name, []))
        for name, *_ in SESSIONS
        if by_session.get(name)
    ]
    hour_rows = sorted(
        [_hour_row(h, trades) for h, trades in by_hour.items()],
        key=lambda r: r["hour"],
    )

    best_session  = max(session_rows, key=lambda r: r["win_rate"])["session"] if session_rows else "N/A"
    worst_session = min(session_rows, key=lambda r: r["win_rate"])["session"] if session_rows else "N/A"
    best_hour     = max(hour_rows,    key=lambda r: r["win_rate"])["label"]   if hour_rows   else "N/A"
    worst_hour    = min(hour_rows,    key=lambda r: r["win_rate"])["label"]   if hour_rows   else "N/A"

    # Average hold duration
    all_holds = [t.holding_seconds for t in closed if t.holding_seconds > 0]
    avg_hold  = round(_stats.mean(all_holds), 1) if all_holds else 0.0

    return {
        "available":      True,
        "advisory_only":  True,
        "sessions":       session_rows,
        "hours":          hour_rows,
        "best_session":   best_session,
        "worst_session":  worst_session,
        "best_hour":      best_hour,
        "worst_hour":     worst_hour,
        "avg_hold_seconds": avg_hold,
    }
