"""
strategy_intelligence/api.py — Public facade for Phase 5D.3.

All functions check is_enabled() first and return disabled_response() when off.
READ-ONLY — no order submission, no portfolio mutation, no strategy change.
PAPER TRADING / ADVISORY ONLY.

Phase 5D.4 and 5D.5 should import from shared_services, not this module.
This module is the HTTP API layer only.
"""
from __future__ import annotations

from .strategy_models import is_enabled, disabled_response, _LABEL


def get_summary() -> dict:
    """GET /api/strategy/summary — top-level KPIs + leaderboard."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import _load_all, get_summary_snapshot
        all_data    = _load_all()
        snapshot    = get_summary_snapshot()
        profiles    = all_data["profiles"]
        leaderboard = all_data["leaderboard"]

        return {
            **snapshot,
            "leaderboard": leaderboard[:10],   # top 10
            "total_profiles": len(profiles),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_rankings() -> dict:
    """GET /api/strategy/rankings — full leaderboard + per-criterion rankings."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import _load_all, get_criterion_rankings
        all_data    = _load_all()
        profiles    = all_data["profiles"]

        return {
            "status":              "ENABLED",
            "label":               _LABEL,
            "leaderboard":         all_data["leaderboard"],
            "criterion_rankings":  all_data["crit_ranks"],
            "profiles":            [p.to_dict() for p in profiles],
            "total":               len(profiles),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_regimes() -> dict:
    """GET /api/strategy/regimes — market regime performance matrix."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import get_regime_matrix
        return get_regime_matrix()
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_sectors() -> dict:
    """GET /api/strategy/sectors — sector performance matrix."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import get_sector_matrix
        return get_sector_matrix()
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_timing() -> dict:
    """GET /api/strategy/timing — time-of-day and day-of-week performance."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import get_time_matrix
        return get_time_matrix()
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


def get_recommendations_api() -> dict:
    """GET /api/strategy/recommendations — advisory recommendation matrix."""
    if not is_enabled():
        return disabled_response()
    try:
        from .shared_services import _load_all
        all_data = _load_all()
        return {
            "status":          "ENABLED",
            "label":           _LABEL,
            "recommendations": all_data["rec_matrix"],
            "count":           len(all_data["rec_matrix"]),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}
