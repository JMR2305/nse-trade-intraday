"""
time_analyser.py — Phase 6.2
Intraday time window performance analysis.

Windows (IST, NSE hours):
  Opening Hour : 09:15 – 10:15
  Morning      : 10:15 – 11:30
  Mid Session  : 11:30 – 13:00
  Afternoon    : 13:00 – 14:30
  Closing Hour : 14:30 – 15:30
"""
from __future__ import annotations
import sys, os
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .optimisation_models import TimeWindowRow

# (window_name, start_hhmm, end_hhmm) — IST = UTC+05:30
WINDOWS = [
    ("Opening Hour",  "09:15", "10:15"),
    ("Morning",       "10:15", "11:30"),
    ("Mid Session",   "11:30", "13:00"),
    ("Afternoon",     "13:00", "14:30"),
    ("Closing Hour",  "14:30", "15:30"),
]


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _hhmm(dt: datetime) -> str:
    # Convert to IST (UTC+5:30)
    ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
    return f"{ist.hour:02d}:{ist.minute:02d}"


def _in_window(hhmm: str, start: str, end: str) -> bool:
    return start <= hhmm < end


def _estimate_entry_time(rec) -> Optional[datetime]:
    """Approximate entry = exit_ts - holding_time_minutes."""
    exit_ts = _parse_ts(rec.timestamp)
    if exit_ts is None:
        return None
    try:
        return exit_ts - timedelta(minutes=float(rec.holding_time_minutes))
    except Exception:
        return None


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def analyse_time_windows(records: list) -> List[TimeWindowRow]:
    """Build one TimeWindowRow per window using estimated entry times."""
    by_window: dict = defaultdict(list)

    for rec in records:
        entry_dt = _estimate_entry_time(rec)
        if entry_dt is None:
            continue
        hhmm = _hhmm(entry_dt)
        for wname, wstart, wend in WINDOWS:
            if _in_window(hhmm, wstart, wend):
                by_window[wname].append(rec)
                break

    rows: List[TimeWindowRow] = []
    for wname, wstart, wend in WINDOWS:
        recs = by_window.get(wname, [])
        wr = sum(1 for r in recs if r.pnl > 0) / len(recs) if recs else 0.0
        rows.append(TimeWindowRow(
            window=wname,
            start_time=wstart,
            end_time=wend,
            trades=len(recs),
            win_rate=round(wr, 4),
            avg_return_pct=round(_avg([r.pnl_pct for r in recs]), 4),
            net_pnl=round(sum(r.pnl for r in recs), 2),
            avg_holding_minutes=round(_avg([r.holding_time_minutes for r in recs]), 1),
        ))

    # Rank non-empty windows by win_rate desc; empty windows go to the bottom
    non_empty = [r for r in rows if r.trades > 0]
    empty = [r for r in rows if r.trades == 0]
    non_empty.sort(key=lambda r: r.win_rate, reverse=True)
    for i, row in enumerate(non_empty):
        row.rank = i + 1
    for i, row in enumerate(empty):
        row.rank = len(non_empty) + i + 1
    return non_empty + empty
