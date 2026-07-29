"""
shared_services.py — Phase 7.3
Stable public interface for the Economic & Macro Intelligence Hub.

All downstream phases (Executive Dashboard, Phase 7.4 Explainable AI,
Phase 7.5 Research Lab) should import from here — never from sub-modules.

READ-ONLY. ADVISORY-ONLY.
This module NEVER enables live trading, places orders, or modifies any
trading engine, portfolio, strategies, signals, AI models, or risk parameters.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .models import is_enabled, disabled_response, macro_grade, trend_label


# ---------------------------------------------------------------------------
# Internal: load all macro events (from economic calendar only — macro events
# are static; the live data is in the module-specific endpoints)
# ---------------------------------------------------------------------------

def _load_all_events() -> list:
    """Load MacroEvent objects from the economic calendar. Never raises."""
    try:
        from .economic_calendar import get_economic_calendar
        cal = get_economic_calendar()
        # Convert dicts back to MacroEvent-like objects for impact engine
        return _dicts_to_events(cal.get("events", []))
    except Exception:
        return []


def _dicts_to_events(dicts: list) -> list:
    """Reconstruct MacroEvent objects from calendar dict output."""
    from .models import MacroEvent
    events = []
    for d in dicts:
        try:
            events.append(MacroEvent(
                event_id            = d.get("event_id", ""),
                category            = d.get("category", "ECONOMIC"),
                sub_type            = d.get("sub_type", ""),
                title               = d.get("title", ""),
                description         = d.get("description", ""),
                event_date          = d.get("event_date"),
                discovered_at       = d.get("discovered_at"),
                importance_score    = float(d.get("importance_score", 50.0)),
                confidence_score    = float(d.get("confidence_score", 50.0)),
                direction           = d.get("direction", "NEUTRAL"),
                expected_volatility = d.get("expected_volatility", "MEDIUM"),
                expected_duration   = d.get("expected_duration", "1D"),
                priority            = d.get("priority", "MEDIUM"),
                affected_sectors    = d.get("affected_sectors", []),
                affected_industries = d.get("affected_industries", []),
                historical_context  = d.get("historical_context"),
                trading_risk        = d.get("trading_risk"),
                opportunity         = d.get("opportunity"),
                source              = d.get("source", ""),
                is_upcoming         = d.get("is_upcoming", False),
            ))
        except Exception:
            continue
    return events


def _compute_macro_score(calendar: dict, global_data: dict,
                         vix_data: dict, flows_data: dict) -> float:
    """
    0–100 macro intelligence score:
    - Calendar coverage (upcoming critical events) — 25 pts
    - Global sentiment                              — 25 pts
    - VIX score (low VIX = high score)              — 25 pts
    - Flow quality (FII inflow)                     — 25 pts
    """
    # Calendar: reward having upcoming events to track (coverage)
    upcoming = calendar.get("upcoming_count", 0)
    cal_score = min(25.0, upcoming * 0.8)

    # Global
    global_raw = float(global_data.get("global_sentiment_score", 50.0))
    global_score = global_raw / 100 * 25

    # VIX (100 = low VIX = good)
    vix_raw = float(vix_data.get("vix_score", 50.0))
    vix_score = vix_raw / 100 * 25

    # Flows
    fii_flow = flows_data.get("fii", {}).get("flow", "NEUTRAL")
    if fii_flow == "NET_BUYER":   flow_score = 25.0
    elif fii_flow == "NET_SELLER": flow_score = 5.0
    else:                         flow_score = 12.5

    return round(min(100.0, cal_score + global_score + vix_score + flow_score), 1)


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """Unified Macro Intelligence summary — score, grade, trend, key highlights."""
    if not is_enabled():
        return disabled_response()
    try:
        calendar      = _load_calendar_safe()
        global_data   = _load_global_safe()
        vix_data      = _load_vix_safe()
        flows_data    = _load_flows_safe()
        commodity_data= _load_commodity_safe()
        currency_data = _load_currency_safe()

        score = _compute_macro_score(calendar, global_data, vix_data, flows_data)
        grade = macro_grade(score)

        return {
            "status":                  "ENABLED",
            "available":               True,
            "advisory_only":           True,
            "macro_score":             score,
            "grade":                   grade,
            "trend":                   "STABLE",   # future: compare to yesterday
            "global_sentiment_score":  global_data.get("global_sentiment_score", 50.0),
            "sentiment_label":         global_data.get("sentiment_label", "NEUTRAL"),
            "india_vix":               vix_data.get("india_vix", {}).get("current", 18.0),
            "vix_regime":              vix_data.get("regime", "STABLE"),
            "vix_risk_level":          vix_data.get("risk_level", "MEDIUM"),
            "fii_posture":             flows_data.get("fii", {}).get("flow", "NEUTRAL"),
            "dii_posture":             flows_data.get("dii", {}).get("flow", "NEUTRAL"),
            "crude_change_pct":        commodity_data.get("crude_oil", {}).get("change_pct", 0.0),
            "usd_inr_change_pct":      currency_data.get("usd_inr", {}).get("change_pct", 0.0),
            "upcoming_events":         calendar.get("upcoming_count", 0),
            "next_critical_event":     calendar.get("next_critical"),
            "currency_volatility":     currency_data.get("currency_volatility", "LOW"),
            "commodity_risk_score":    commodity_data.get("commodity_risk_score", 50.0),
            "inflation_risk":          commodity_data.get("inflation_risk", "LOW"),
        }
    except Exception as exc:
        import traceback
        return {"status": "ERROR", "error": str(exc),
                "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/calendar
# ---------------------------------------------------------------------------

def get_calendar() -> dict:
    """Economic calendar — RBI meetings, inflation, GDP, IIP, PMI, budget, global events."""
    if not is_enabled():
        return disabled_response()
    try:
        from .economic_calendar import get_economic_calendar
        return {**get_economic_calendar(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/global
# ---------------------------------------------------------------------------

def get_global() -> dict:
    """Global market intelligence — major indices + sentiment score."""
    if not is_enabled():
        return disabled_response()
    try:
        from .global_markets import get_global_markets
        return {**get_global_markets(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/flows
# ---------------------------------------------------------------------------

def get_flows() -> dict:
    """Market flow intelligence — FII/DII, sector rotation, liquidity."""
    if not is_enabled():
        return disabled_response()
    try:
        from .market_flows import get_market_flows
        return {**get_market_flows(), "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/commodities
# (combined commodities + currency as spec requested both in same endpoint)
# ---------------------------------------------------------------------------

def get_commodities() -> dict:
    """Commodity + currency intelligence."""
    if not is_enabled():
        return disabled_response()
    try:
        from .commodity_intelligence import get_commodity_intelligence
        from .currency_intelligence  import get_currency_intelligence
        from .volatility_intelligence import get_volatility_intelligence
        comm = get_commodity_intelligence()
        curr = get_currency_intelligence()
        vix  = get_volatility_intelligence()
        return {
            "status":          "ENABLED",
            "available":       True,
            "advisory_only":   True,
            "commodities":     comm,
            "currency":        curr,
            "volatility":      vix,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/macro-intelligence/brief
# ---------------------------------------------------------------------------

def get_brief() -> dict:
    """Daily Macro Brief — full operator-facing macro intelligence narrative."""
    if not is_enabled():
        return disabled_response()
    try:
        events         = _load_all_events()
        global_data    = _load_global_safe()
        vix_data       = _load_vix_safe()
        flows_data     = _load_flows_safe()
        commodity_data = _load_commodity_safe()
        currency_data  = _load_currency_safe()

        global_score   = float(global_data.get("global_sentiment_score", 50.0))
        sector_rotation = flows_data.get("sector_rotation", [])

        from .macro_brief import generate_daily_brief
        brief = generate_daily_brief(
            events          = events,
            global_score    = global_score,
            vix_data        = vix_data,
            fii_data        = flows_data,
            commodity_data  = commodity_data,
            currency_data   = currency_data,
            sector_rotation = sector_rotation,
        )
        return {**brief, "status": "ENABLED"}
    except Exception as exc:
        import traceback
        return {"status": "ERROR", "error": str(exc),
                "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# Flat snapshot for Executive Dashboard / Phase 7.4 / Phase 7.5
# ---------------------------------------------------------------------------

def get_macro_intelligence_snapshot() -> dict:
    """
    Flat KPI dict for Executive Dashboard and downstream phases.
    Never raises — returns safe defaults on any error.

    Phase 7.4 (Explainable AI) and Phase 7.5 (Research Lab) can call this
    without any changes to this module — the contract is stable.
    """
    try:
        calendar     = _load_calendar_safe()
        global_data  = _load_global_safe()
        vix_data     = _load_vix_safe()
        flows_data   = _load_flows_safe()
        commodity_data = _load_commodity_safe()

        score = _compute_macro_score(calendar, global_data, vix_data, flows_data)
        grade = macro_grade(score)

        return {
            "macro_score":            score,
            "grade":                  grade,
            "trend":                  "STABLE",
            "global_sentiment_score": float(global_data.get("global_sentiment_score", 50.0)),
            "sentiment_label":        global_data.get("sentiment_label", "NEUTRAL"),
            "india_vix":              float(vix_data.get("india_vix", {}).get("current", 18.0)),
            "vix_regime":             vix_data.get("regime", "STABLE"),
            "vix_risk_level":         vix_data.get("risk_level", "MEDIUM"),
            "fii_posture":            flows_data.get("fii", {}).get("flow", "NEUTRAL"),
            "upcoming_events":        calendar.get("upcoming_count", 0),
            "inflation_risk":         commodity_data.get("inflation_risk", "LOW"),
            "available":              True,
        }
    except Exception:
        return {
            "macro_score": 0.0, "grade": "D", "trend": "STABLE",
            "global_sentiment_score": 50.0, "sentiment_label": "NEUTRAL",
            "india_vix": 18.0, "vix_regime": "STABLE", "vix_risk_level": "MEDIUM",
            "fii_posture": "NEUTRAL", "upcoming_events": 0,
            "inflation_risk": "LOW", "available": False,
        }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_csv() -> str:
    if not is_enabled():
        return ""
    try:
        import csv, io
        events = _load_all_events()
        output = io.StringIO()
        fields = ["event_id", "category", "sub_type", "title", "event_date",
                  "importance_score", "confidence_score", "direction",
                  "priority", "source", "is_upcoming"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for e in events:
            writer.writerow({k: e.to_dict().get(k, "") for k in fields})
        return output.getvalue()
    except Exception:
        return ""


def export_json() -> str:
    if not is_enabled():
        return ""
    try:
        import json
        events = _load_all_events()
        payload = {
            "events":       [e.to_dict() for e in events],
            "total":        len(events),
            "advisory_only": True,
        }
        return json.dumps(payload, indent=2, default=str)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Private safe-loaders (never raise)
# ---------------------------------------------------------------------------

def _load_calendar_safe() -> dict:
    try:
        from .economic_calendar import get_economic_calendar
        return get_economic_calendar()
    except Exception:
        return {"upcoming_count": 0, "recent_count": 0, "events": [],
                "upcoming": [], "recent": [], "next_critical": None, "next_event": None}


def _load_global_safe() -> dict:
    try:
        from .global_markets import get_global_markets
        return get_global_markets()
    except Exception:
        return {"global_sentiment_score": 50.0, "sentiment_label": "NEUTRAL", "indices": []}


def _load_vix_safe() -> dict:
    try:
        from .volatility_intelligence import get_volatility_intelligence
        return get_volatility_intelligence()
    except Exception:
        return {"india_vix": {"current": 18.0}, "regime": "STABLE",
                "risk_level": "MEDIUM", "vix_score": 50.0,
                "interpretation": "", "trading_implication": ""}


def _load_flows_safe() -> dict:
    try:
        from .market_flows import get_market_flows
        return get_market_flows()
    except Exception:
        return {"fii": {"flow": "NEUTRAL", "score": 50.0},
                "dii": {"flow": "NEUTRAL", "score": 50.0},
                "sector_rotation": [], "liquidity": {"trend": "NORMAL_LIQUIDITY"}}


def _load_commodity_safe() -> dict:
    try:
        from .commodity_intelligence import get_commodity_intelligence
        return get_commodity_intelligence()
    except Exception:
        return {"commodities": [], "crude_oil": {"change_pct": 0.0},
                "commodity_risk_score": 50.0, "inflation_risk": "LOW",
                "crude_impact": "", "gold_signal": ""}


def _load_currency_safe() -> dict:
    try:
        from .currency_intelligence import get_currency_intelligence
        return get_currency_intelligence()
    except Exception:
        return {"pairs": [], "usd_inr": {"price": 84.0, "change_pct": 0.0},
                "dollar_index": {}, "currency_volatility": "LOW",
                "usd_inr_impact": "", "dxy_impact": ""}
