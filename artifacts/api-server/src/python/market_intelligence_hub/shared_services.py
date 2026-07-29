"""
shared_services.py — Phase 7.1
Stable public interface for market_intelligence_hub.

Endpoints:
  get_summary()   → /api/market-intelligence/summary
  get_sectors()   → /api/market-intelligence/sectors
  get_watchlist() → /api/market-intelligence/watchlist
  get_breadth()   → /api/market-intelligence/breadth
  get_overview()  → /api/market-intelligence/overview
  export_csv()    / export_json()
  get_market_intelligence_snapshot()  → flat KPIs for downstream

READ-ONLY. ADVISORY-ONLY.
This module NEVER modifies orders, portfolio, strategies, AI, risk engine or signals.
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .hub_models import is_enabled, disabled_response


# ---------------------------------------------------------------------------
# GET /api/market-intelligence/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """Unified intelligence summary: health score, top opportunities, sectors, outlook."""
    if not is_enabled():
        return disabled_response()
    try:
        regime    = _get_regime()
        items     = _get_scan_items()
        sectors   = _analyse_sectors(items)
        breadth   = _analyse_breadth(items, regime)
        volatility = _analyse_volatility(items, regime)
        watchlist = _analyse_watchlist(items, regime)
        timeframes = _get_timeframes()

        from .intelligence_summary import generate_summary
        summary = generate_summary(regime, sectors, breadth, volatility, watchlist, timeframes)

        return {
            "status": "ENABLED",
            **summary,
            "total_symbols_analysed": len(items),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/market-intelligence/sectors
# ---------------------------------------------------------------------------

def get_sectors() -> dict:
    """Sector intelligence: ranking, heat, rotation, leadership."""
    if not is_enabled():
        return disabled_response()
    try:
        items   = _get_scan_items()
        regime  = _get_regime()
        sectors = _analyse_sectors(items)
        return {
            "status": "ENABLED",
            **sectors,
            "regime": regime.get("regime", "UNKNOWN"),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/market-intelligence/watchlist
# ---------------------------------------------------------------------------

def get_watchlist() -> dict:
    """Watchlist intelligence: priority, opportunity, risk, composite rank per symbol."""
    if not is_enabled():
        return disabled_response()
    try:
        items    = _get_scan_items()
        regime   = _get_regime()
        from .watchlist_intelligence import analyse_watchlist
        result   = analyse_watchlist(items, regime)
        return {
            "status": "ENABLED",
            **result,
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/market-intelligence/breadth
# ---------------------------------------------------------------------------

def get_breadth() -> dict:
    """Market breadth: advancers, decliners, sector participation, breadth strength."""
    if not is_enabled():
        return disabled_response()
    try:
        items  = _get_scan_items()
        regime = _get_regime()
        breadth = _analyse_breadth(items, regime)
        return {
            "status": "ENABLED",
            **breadth,
            "regime": regime.get("regime", "UNKNOWN"),
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/market-intelligence/overview
# ---------------------------------------------------------------------------

def get_overview() -> dict:
    """
    Market overview: regime analysis + multi-timeframe alignment.
    Also exposes volatility and sector heat at a glance.
    """
    if not is_enabled():
        return disabled_response()
    try:
        regime     = _get_regime()
        timeframes = _get_timeframes()
        items      = _get_scan_items()
        volatility = _analyse_volatility(items, regime)
        sectors    = _analyse_sectors(items)

        return {
            "status": "ENABLED",
            "regime": regime,
            "multi_timeframe": timeframes,
            "volatility": volatility,
            "sector_heat": {
                "leader": sectors.get("leadership_sector"),
                "strongest": sectors.get("strongest_sector"),
                "weakest":   sectors.get("weakest_sector"),
                "avg_strength": sectors.get("avg_sector_strength"),
            },
            "advisory_only": True,
            "available": True,
        }
    except Exception as e:
        import traceback
        return {"status": "ERROR", "error": str(e), "trace": traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_summary_csv() -> str:
    if not is_enabled():
        return ""
    try:
        import csv, io
        summary = get_summary()
        if summary.get("status") != "ENABLED":
            return ""
        skip = {"status", "top_opportunities", "highest_risk_areas", "evidence",
                "advisory_only", "available", "strongest_sectors", "weakest_sectors"}
        keys = [k for k in summary if k not in skip and not isinstance(summary[k], (dict, list))]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({k: summary[k] for k in keys})
        return output.getvalue()
    except Exception:
        return ""


def export_full_json() -> str:
    if not is_enabled():
        return ""
    try:
        import json
        regime     = _get_regime()
        items      = _get_scan_items()
        sectors    = _analyse_sectors(items)
        breadth    = _analyse_breadth(items, regime)
        volatility = _analyse_volatility(items, regime)
        watchlist  = _analyse_watchlist(items, regime)
        timeframes = _get_timeframes()
        from .intelligence_summary import generate_summary
        summary = generate_summary(regime, sectors, breadth, volatility, watchlist, timeframes)
        payload = {
            "generated_at": _now_iso(),
            "summary": summary,
            "regime": regime,
            "multi_timeframe": timeframes,
            "sectors": sectors,
            "breadth": breadth,
            "volatility": volatility,
            "watchlist": watchlist,
            "advisory_only": True,
        }
        return json.dumps(payload, indent=2, default=str)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Flat snapshot for downstream (Executive Dashboard, Live Readiness, etc.)
# ---------------------------------------------------------------------------

def get_market_intelligence_snapshot() -> dict:
    """Flat KPI dict. Never raises."""
    try:
        summary = get_summary()
        if summary.get("status") != "ENABLED":
            return {
                "market_health_score": 0.0, "grade": "D",
                "trend": "STABLE", "overall_outlook": "Disabled.",
                "top_opportunity": None,
            }
        top_opp = None
        if summary.get("top_opportunities"):
            top_opp = summary["top_opportunities"][0].get("symbol")
        return {
            "market_health_score": summary.get("market_health_score", 0.0),
            "grade": summary.get("grade", "D"),
            "trend": summary.get("trend", "STABLE"),
            "overall_outlook": summary.get("overall_outlook", ""),
            "top_opportunity": top_opp,
        }
    except Exception:
        return {
            "market_health_score": 0.0, "grade": "D",
            "trend": "STABLE", "overall_outlook": "Error.",
            "top_opportunity": None,
        }


# ---------------------------------------------------------------------------
# Private data-loading helpers
# ---------------------------------------------------------------------------

def _get_scan_items() -> list:
    """
    Load scan items from the best available source (Postgres → JSON cache → empty).
    Never triggers a full expensive scan.
    """
    # 1. Postgres scan snapshot
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()
        if snap:
            items = snap.get("items") or snap.get("watchlist") or []
            if items:
                return items
    except Exception:
        pass

    # 2. Intelligence cache JSON
    try:
        import json
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in ("intelligence_cache.json", "scan_cache.json"):
            path = os.path.join(base, fname)
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                items = (
                    data.get("items") or
                    data.get("watchlist") or
                    data.get("scan_items") or []
                )
                if items:
                    return items
    except Exception:
        pass

    return []


def _get_regime() -> dict:
    try:
        from .regime_analyser import analyse_regime
        return analyse_regime()
    except Exception:
        return {
            "regime": "SIDEWAYS", "sub_regime": "NORMAL",
            "trend_strength": 0.0, "confidence": 50.0,
            "nifty_price": 0.0, "nifty_change_pct": 0.0, "nifty_trend": "SIDEWAYS",
            "banknifty_price": 0.0, "banknifty_change_pct": 0.0, "banknifty_trend": "SIDEWAYS",
            "vix_value": 18.0, "vix_status": "MODERATE",
            "high_volatility": False, "adj_buy": 1.0, "adj_sell": 1.0,
            "description": "Regime data unavailable.", "advisory_only": True,
        }


def _get_timeframes() -> dict:
    try:
        from .multi_timeframe_analyser import analyse_timeframes
        return analyse_timeframes()
    except Exception:
        return {
            "timeframes": [], "alignment_score": 50.0,
            "agreement": "INSUFFICIENT_DATA", "primary_trend": "NEUTRAL",
            "up_count": 0, "down_count": 0, "neutral_count": 0,
            "available_count": 0, "total_timeframes": 7, "elapsed_ms": 0.0,
        }


def _analyse_sectors(items: list) -> dict:
    try:
        from .sector_intelligence import analyse_sectors
        return analyse_sectors(items)
    except Exception:
        return {
            "sectors": [], "total_sectors": 0,
            "strongest_sector": "N/A", "weakest_sector": "N/A",
            "avg_sector_strength": 0.0, "sector_heat_leader": "N/A",
            "leadership_sector": "N/A", "rotation_leaders": [], "rotation_laggards": [],
        }


def _analyse_breadth(items: list, regime: dict) -> dict:
    try:
        from .breadth_analyser import analyse_breadth
        return analyse_breadth(items, regime)
    except Exception:
        from .breadth_analyser import _empty_breadth
        return _empty_breadth()


def _analyse_volatility(items: list, regime: dict) -> dict:
    try:
        from .volatility_analyser import analyse_volatility
        return analyse_volatility(items, regime)
    except Exception:
        return {
            "vix_value": 18.0, "vix_status": "MODERATE",
            "volatility_regime": "NORMAL_VOLATILITY", "volatility_score": 55.0,
            "atr_avg": 0.0, "atr_pct": 0.0, "atr_trend": "STABLE",
            "expansion": "STABLE", "gap_risk": "MODERATE", "gap_risk_score": 30.0,
            "symbol_volatility": [], "high_vol_symbols": 0, "total_symbols": 0,
        }


def _analyse_watchlist(items: list, regime: dict) -> dict:
    try:
        from .watchlist_intelligence import analyse_watchlist
        return analyse_watchlist(items, regime)
    except Exception:
        return {
            "watchlist": [], "total_symbols": 0,
            "top_opportunities": [], "highest_risk": [],
            "regime": "UNKNOWN", "regime_adjusted": False,
            "avg_opportunity_score": 0.0, "avg_composite_score": 0.0,
        }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
