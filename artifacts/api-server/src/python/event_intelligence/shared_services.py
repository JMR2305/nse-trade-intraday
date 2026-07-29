"""
shared_services.py — Phase 7.2
Stable public interface for the Event & Corporate Intelligence Hub.

All downstream phases (Phase 7.3+, Executive Dashboard, etc.) should
import from here — never directly from sub-modules.

READ-ONLY. ADVISORY-ONLY.
This module NEVER enables live trading, places orders, or modifies any
trading engine, portfolio, strategies, signals, AI models, or risk parameters.
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .models import is_enabled, disabled_response, event_grade


# ---------------------------------------------------------------------------
# Internal: load all events
# ---------------------------------------------------------------------------

def _load_all_events() -> list:
    """Load events from all three intelligence streams. Never raises."""
    from .models import EventRecord
    events: list = []

    try:
        from .corporate_intelligence import get_corporate_events
        corp = get_corporate_events()
        # Reconstruct EventRecord-like objects for impact/timeline/brief
        events.extend(_dicts_to_records(corp.get("events", []), "CORPORATE"))
    except Exception:
        pass

    try:
        from .regulatory_intelligence import get_regulatory_events
        reg = get_regulatory_events()
        events.extend(_dicts_to_records(reg.get("events", []), "REGULATORY"))
    except Exception:
        pass

    try:
        from .news_intelligence import get_news_events
        news = get_news_events()
        events.extend(_dicts_to_records(news.get("events", []), "NEWS"))
    except Exception:
        pass

    return events


def _dicts_to_records(dicts: list, event_type: str) -> list:
    """Lightweight dict-to-EventRecord conversion for aggregation."""
    from .models import EventRecord
    records = []
    for d in dicts:
        try:
            r = EventRecord(
                event_id          = d.get("event_id", ""),
                event_type        = d.get("event_type", event_type),
                sub_type          = d.get("sub_type", ""),
                title             = d.get("title", ""),
                description       = d.get("description", ""),
                symbol            = d.get("symbol"),
                sector            = d.get("sector"),
                event_date        = d.get("event_date"),
                discovered_at     = d.get("discovered_at"),
                importance_score  = float(d.get("importance_score", 50.0)),
                confidence_score  = float(d.get("confidence_score", 50.0)),
                impact_direction  = d.get("impact_direction", "NEUTRAL"),
                expected_volatility = float(d.get("expected_volatility", 0.0)),
                expected_duration = d.get("expected_duration", "1D"),
                priority          = d.get("priority", "MEDIUM"),
                affected_stocks   = d.get("affected_stocks", []),
                affected_sectors  = d.get("affected_sectors", []),
                trading_risk      = d.get("trading_risk"),
                opportunity       = d.get("opportunity"),
                source            = d.get("source", ""),
            )
            records.append(r)
        except Exception:
            continue
    return records


def _compute_intelligence_score(events: list) -> float:
    """
    0–100 score based on:
    - Event count (more coverage = higher score)
    - Average importance
    - Freshness (events from today score higher)
    """
    if not events:
        return 30.0
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    count_score    = min(40.0, len(events) * 2.0)          # up to 40 pts
    avg_importance = sum(e.importance_score for e in events) / len(events)
    importance_score = avg_importance * 0.4                  # up to 40 pts
    today_count    = sum(1 for e in events if e.event_date == today)
    freshness_score = min(20.0, today_count * 3.0)           # up to 20 pts

    return min(100.0, round(count_score + importance_score + freshness_score, 1))


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """Unified Event Intelligence summary — all categories + score."""
    if not is_enabled():
        return disabled_response()
    try:
        events = _load_all_events()
        score  = _compute_intelligence_score(events)
        grade  = event_grade(score)

        from .impact_engine import get_impact_summary
        impact = get_impact_summary(events)

        from .timeline import build_timeline
        timeline = build_timeline(events)

        # Trend: stable by default (future: compare to yesterday's score)
        trend = "STABLE"

        corp_count = sum(1 for e in events if e.event_type == "CORPORATE")
        reg_count  = sum(1 for e in events if e.event_type == "REGULATORY")
        news_count = sum(1 for e in events if e.event_type == "NEWS")

        return {
            "status":               "ENABLED",
            "available":            True,
            "intelligence_score":   score,
            "grade":                grade,
            "trend":                trend,
            "total_events":         len(events),
            "corporate_count":      corp_count,
            "regulatory_count":     reg_count,
            "news_count":           news_count,
            "high_priority_count":  sum(1 for e in events if e.priority in ("CRITICAL", "HIGH")),
            "today_events":         timeline.get("today_count", 0),
            "upcoming_events":      timeline.get("upcoming_count", 0),
            "impact":               impact,
            "top_events":           [
                e.to_dict() for e in
                sorted(events, key=lambda x: x.importance_score, reverse=True)[:5]
            ],
            "advisory_only":        True,
        }
    except Exception as exc:
        import traceback
        return {"status": "ERROR", "error": str(exc), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/corporate
# ---------------------------------------------------------------------------

def get_corporate() -> dict:
    """Corporate events — results, dividends, splits, bulk deals, board meetings."""
    if not is_enabled():
        return disabled_response()
    try:
        from .corporate_intelligence import get_corporate_events
        return {**get_corporate_events(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/regulatory
# ---------------------------------------------------------------------------

def get_regulatory() -> dict:
    """Regulatory events — ASM/GSM/F&O ban, NSE/SEBI circulars."""
    if not is_enabled():
        return disabled_response()
    try:
        from .regulatory_intelligence import get_regulatory_events
        return {**get_regulatory_events(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/news
# ---------------------------------------------------------------------------

def get_news() -> dict:
    """News intelligence — company, sector, market, economic headlines."""
    if not is_enabled():
        return disabled_response()
    try:
        from .news_intelligence import get_news_events
        return {**get_news_events(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/timeline
# ---------------------------------------------------------------------------

def get_timeline() -> dict:
    """Event timeline — today, past 7d, past 30d, upcoming, calendar."""
    if not is_enabled():
        return disabled_response()
    try:
        events = _load_all_events()
        from .timeline import build_timeline
        return {**build_timeline(events), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/event-intelligence/brief
# ---------------------------------------------------------------------------

def get_brief() -> dict:
    """Daily Intelligence Brief — concise advisory summary for operators."""
    if not is_enabled():
        return disabled_response()
    try:
        events = _load_all_events()
        score  = _compute_intelligence_score(events)
        grade  = event_grade(score)
        from .brief import generate_daily_brief
        return {**generate_daily_brief(events, score, grade), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# Flat snapshot for Executive Dashboard
# ---------------------------------------------------------------------------

def get_event_intelligence_snapshot() -> dict:
    """Flat KPI dict for Executive Dashboard / Phase 5D.5. Never raises."""
    try:
        events = _load_all_events()
        score  = _compute_intelligence_score(events)
        grade  = event_grade(score)
        high_priority = sum(1 for e in events if e.priority in ("CRITICAL", "HIGH"))
        bullish = sum(1 for e in events if e.impact_direction == "BULLISH")
        bearish = sum(1 for e in events if e.impact_direction == "BEARISH")
        return {
            "intelligence_score":  score,
            "grade":               grade,
            "total_events":        len(events),
            "high_priority_count": high_priority,
            "bullish_count":       bullish,
            "bearish_count":       bearish,
            "available":           True,
        }
    except Exception:
        return {
            "intelligence_score": 0.0,
            "grade": "D",
            "total_events": 0,
            "high_priority_count": 0,
            "available": False,
        }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_csv() -> str:
    """Export summary as CSV."""
    if not is_enabled():
        return ""
    try:
        import csv, io
        events = _load_all_events()
        output = io.StringIO()
        fields = ["event_id", "event_type", "sub_type", "title", "symbol",
                  "sector", "event_date", "importance_score", "confidence_score",
                  "impact_direction", "priority", "source"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for e in events:
            writer.writerow({k: e.to_dict().get(k, "") for k in fields})
        return output.getvalue()
    except Exception:
        return ""


def export_json() -> str:
    """Export full event list as JSON."""
    if not is_enabled():
        return ""
    try:
        import json
        events = _load_all_events()
        return json.dumps({
            "events": [e.to_dict() for e in events],
            "total": len(events),
            "advisory_only": True,
        }, indent=2, default=str)
    except Exception:
        return ""
