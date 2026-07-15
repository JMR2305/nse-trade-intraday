"""
market_hours.py — Phase 11 Live Data Foundation
Asia/Kolkata NSE market-hours calendar and session state machine.

States:
  PRE_OPEN  : 09:00–09:15 IST on a trading day
  OPEN      : 09:15–15:30 IST on a trading day
  POST_CLOSE: 15:30–16:00 IST on a trading day
  CLOSED    : outside session hours on a trading day
  WEEKEND   : Saturday / Sunday
  HOLIDAY   : NSE trading holiday (from nse_holidays.json)

All timestamps honest: derived from the real clock in Asia/Kolkata.
PAPER TRADING ONLY — this module never places orders.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, date, time as dtime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

PRE_OPEN_START = dtime(9, 0)
MARKET_OPEN    = dtime(9, 15)
MARKET_CLOSE   = dtime(15, 30)
POST_CLOSE_END = dtime(16, 0)

_HOLIDAY_FILE = os.path.join(os.path.dirname(__file__), "nse_holidays.json")

# Fallback list (NSE 2026 trading holidays, best-effort static list).
_DEFAULT_HOLIDAYS: Dict[str, str] = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-21": "Id-Ul-Fitr (Ramzan Id)",
    "2026-04-01": "Annual Bank Closing",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-09": "Diwali (Laxmi Pujan)",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}


def _load_holidays() -> Dict[str, str]:
    try:
        with open(_HOLIDAY_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return dict(_DEFAULT_HOLIDAYS)


def now_ist() -> datetime:
    return datetime.now(IST)


def is_holiday(d: date, holidays: Optional[Dict[str, str]] = None) -> Optional[str]:
    hols = holidays if holidays is not None else _load_holidays()
    return hols.get(d.isoformat())


def is_trading_day(d: date, holidays: Optional[Dict[str, str]] = None) -> bool:
    if d.weekday() >= 5:
        return False
    return is_holiday(d, holidays) is None


def market_state(ts: Optional[datetime] = None) -> str:
    """Return the market session state for the given IST timestamp."""
    t = (ts.astimezone(IST) if ts else now_ist())
    d = t.date()
    if d.weekday() >= 5:
        return "WEEKEND"
    if is_holiday(d) is not None:
        return "HOLIDAY"
    tod = t.time()
    if PRE_OPEN_START <= tod < MARKET_OPEN:
        return "PRE_OPEN"
    if MARKET_OPEN <= tod < MARKET_CLOSE:
        return "OPEN"
    if MARKET_CLOSE <= tod < POST_CLOSE_END:
        return "POST_CLOSE"
    return "CLOSED"


def next_transition(ts: Optional[datetime] = None) -> Dict[str, Any]:
    """Next session boundary (open or close) from the given time."""
    t = (ts.astimezone(IST) if ts else now_ist())
    holidays = _load_holidays()
    state = market_state(t)

    if state == "OPEN":
        target = datetime.combine(t.date(), MARKET_CLOSE, tzinfo=IST)
        label = "market_close"
    elif state == "PRE_OPEN":
        target = datetime.combine(t.date(), MARKET_OPEN, tzinfo=IST)
        label = "market_open"
    else:
        # Find the next trading day's open (could be today if before pre-open).
        d = t.date()
        if not (is_trading_day(d, holidays) and t.time() < MARKET_OPEN):
            d = d + timedelta(days=1)
            for _ in range(30):
                if is_trading_day(d, holidays):
                    break
                d = d + timedelta(days=1)
        target = datetime.combine(d, MARKET_OPEN, tzinfo=IST)
        label = "market_open"

    seconds = max(0, int((target - t).total_seconds()))
    return {
        "event": label,
        "at_ist": target.isoformat(),
        "seconds_until": seconds,
    }


def market_status(ts: Optional[datetime] = None) -> Dict[str, Any]:
    """Full market-status payload used by API / SSE."""
    t = (ts.astimezone(IST) if ts else now_ist())
    state = market_state(t)
    holidays = _load_holidays()
    holiday_name = is_holiday(t.date(), holidays)
    upcoming: List[Dict[str, str]] = []
    for iso, name in sorted(holidays.items()):
        try:
            hd = date.fromisoformat(iso)
        except ValueError:
            continue
        if hd >= t.date() and len(upcoming) < 3:
            upcoming.append({"date": iso, "name": name})

    return {
        "state": state,
        "is_open": state == "OPEN",
        "now_ist": t.isoformat(),
        "timezone": "Asia/Kolkata",
        "session": {
            "pre_open": "09:00",
            "open": "09:15",
            "close": "15:30",
            "post_close": "16:00",
        },
        "holiday_today": holiday_name,
        "next_transition": next_transition(t),
        "upcoming_holidays": upcoming,
        "label": "PAPER / RESEARCH ONLY",
    }
