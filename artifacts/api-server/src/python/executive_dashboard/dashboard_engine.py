"""
dashboard_engine.py — Phase 5D.5 aggregation engine.

ZERO recalculation. Every metric is consumed from an existing module.
All imports are lazy and individually guarded so one broken module never
blocks the entire dashboard.
"""
from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Safe accessors — each catches all exceptions and returns a typed fallback
# ---------------------------------------------------------------------------

def _safe(fn, fallback: Any = None) -> Any:
    try:
        return fn()
    except Exception as exc:
        return fallback if fallback is not None else {"error": str(exc)}


def _load_strategy() -> dict:
    """Phase 5D.3 — strategy_intelligence.shared_services (direct import)."""
    try:
        from strategy_intelligence.shared_services import (
            get_summary_snapshot,
            get_criterion_rankings,
            get_recommendations,
        )
        snapshot    = get_summary_snapshot()
        criterion   = get_criterion_rankings()
        recs        = get_recommendations()
        return {
            "available": True,
            "snapshot":  snapshot,
            "criterion": criterion,
            "recs":      recs,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_ai() -> dict:
    """Phase 5D.4 — ai_performance.shared_services (direct import)."""
    try:
        from ai_performance.shared_services import (
            get_ai_snapshot,
            get_health_score,
            get_learning_data,
        )
        snapshot   = get_ai_snapshot()
        components = get_health_score()
        learning   = get_learning_data()
        return {
            "available":  True,
            "snapshot":   snapshot,
            "components": components,
            "learning":   learning,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_execution_quality() -> dict:
    """Phase 5D.1 — execution_quality.api (direct import)."""
    try:
        from execution_quality.api import get_summary
        return {"available": True, **get_summary()}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_portfolio() -> dict:
    """Phase 5D.2 — portfolio_performance.api (direct import)."""
    try:
        from portfolio_performance.api import get_summary, get_portfolio
        return {
            "available": True,
            "summary":   get_summary(),
            "portfolio": get_portfolio(),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_preopen() -> dict:
    """Pre-Open Intelligence — preopen_engine (direct import)."""
    try:
        from preopen_engine import get_status, get_rankings, get_sectors
        return {
            "available": True,
            "status":    get_status(),
            "rankings":  get_rankings(),
            "sectors":   get_sectors(),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_risk() -> dict:
    """Portfolio Risk — phase11_risk (direct import)."""
    try:
        from phase11_risk import portfolio_risk, risk_alerts
        return {
            "available": True,
            "risk":      portfolio_risk(),
            "alerts":    risk_alerts(),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_signal_validation() -> dict:
    """Phase 5C — signal_validation_engine (direct import)."""
    try:
        from signal_validation_engine import get_status, get_summary
        return {
            "available": True,
            "status":    get_status(),
            "summary":   get_summary(),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _load_system_health() -> dict:
    """System health — live_health_v2 and scheduler (direct import)."""
    try:
        from phase20_executor import get_scheduler_health
        sched = get_scheduler_health()
    except Exception:
        sched = {}
    try:
        from meta_health import get_meta_health
        meta = get_meta_health()
    except Exception:
        meta = {}
    return {"available": True, "scheduler": sched, "meta": meta}


def _load_readiness() -> dict:
    """Phase 6.5 — live_readiness.shared_services (direct import)."""
    try:
        from live_readiness.shared_services import get_readiness_snapshot
        snap = get_readiness_snapshot()
        return {"available": True, **snap}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Public aggregator
# ---------------------------------------------------------------------------

def load_all() -> dict:
    """
    Aggregate data from all phase modules.
    Returns a dict with one key per section.
    NEVER recalculates — only calls existing shared_services / api functions.
    """
    return {
        "strategy":         _load_strategy(),
        "ai":               _load_ai(),
        "execution_quality": _load_execution_quality(),
        "portfolio":        _load_portfolio(),
        "preopen":          _load_preopen(),
        "risk":             _load_risk(),
        "signals":          _load_signal_validation(),
        "system":           _load_system_health(),
        "readiness":        _load_readiness(),
    }
