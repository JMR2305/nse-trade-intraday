"""
timeline.py — Phase 7.2
Organises events into a temporal timeline:
  upcoming (next 30 days), today, past 7 days, past 30 days, future calendar.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from .models import EventRecord


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_date(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def build_timeline(events: List[EventRecord]) -> dict:
    """
    Partition events into timeline buckets.
    Returns structured timeline dict.
    """
    now    = datetime.now(timezone.utc)
    today  = now.strftime("%Y-%m-%d")
    cutoff_7   = now - timedelta(days=7)
    cutoff_30  = now - timedelta(days=30)
    future_30  = now + timedelta(days=30)

    buckets: Dict[str, List[dict]] = {
        "today":      [],
        "past_7_days":  [],
        "past_30_days": [],
        "upcoming":   [],
        "future_calendar": [],
    }

    for event in events:
        if not event.event_date:
            continue

        ed = _parse_date(event.event_date)
        d  = event.to_dict()

        if event.event_date == today:
            buckets["today"].append(d)
        elif ed < now and ed >= cutoff_7:
            buckets["past_7_days"].append(d)
        elif ed < cutoff_7 and ed >= cutoff_30:
            buckets["past_30_days"].append(d)
        elif ed > now and ed <= future_30:
            buckets["upcoming"].append(d)
            buckets["future_calendar"].append(d)
        elif ed > future_30:
            buckets["future_calendar"].append(d)

    # Sort each bucket: today/upcoming ascending, past descending
    for bucket in ("today", "upcoming", "future_calendar"):
        buckets[bucket].sort(key=lambda x: x.get("event_date", ""), reverse=False)
    for bucket in ("past_7_days", "past_30_days"):
        buckets[bucket].sort(key=lambda x: x.get("event_date", ""), reverse=True)

    # Build daily calendar for next 7 days
    daily_calendar = {}
    for day_offset in range(7):
        day_str = (now + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        daily_events = [
            {"title": e.get("title", ""), "symbol": e.get("symbol"), "priority": e.get("priority")}
            for e in buckets["upcoming"] + buckets["today"]
            if e.get("event_date") == day_str
        ]
        if daily_events:
            daily_calendar[day_str] = daily_events

    return {
        "available":        True,
        "today":            buckets["today"],
        "today_count":      len(buckets["today"]),
        "past_7_days":      buckets["past_7_days"],
        "past_7_count":     len(buckets["past_7_days"]),
        "past_30_days":     buckets["past_30_days"],
        "past_30_count":    len(buckets["past_30_days"]),
        "upcoming":         buckets["upcoming"],
        "upcoming_count":   len(buckets["upcoming"]),
        "future_calendar":  buckets["future_calendar"],
        "daily_calendar":   daily_calendar,
        "total_events":     len(events),
        "advisory_only":    True,
    }
