"""
shared_services.py — Stable public interface for Phase 5D.5.

Future phases (Live Trading, ML Engine, Options, Swing Trading) should import
from here — never from dashboard_engine or widgets directly.
"""
from __future__ import annotations
from .dashboard_models import is_enabled, disabled_response, _LABEL
from .dashboard_engine import load_all
from .widgets import (
    widget_header,
    widget_system_health,
    widget_portfolio_overview,
    widget_ai_health,
    widget_strategy_overview,
    widget_execution_quality,
    widget_preopen,
    widget_portfolio_risk,
    widget_live_alerts,
    widget_market_snapshot,
)
from .layout import compute_executive_score, SECTIONS, QUICK_ACTIONS


def _build_widgets(data: dict) -> dict:
    return {
        "header":              widget_header(data),
        "system_health":       widget_system_health(data),
        "portfolio_overview":  widget_portfolio_overview(data),
        "ai_health":           widget_ai_health(data),
        "strategy_overview":   widget_strategy_overview(data),
        "execution_quality":   widget_execution_quality(data),
        "preopen_intelligence": widget_preopen(data),
        "portfolio_risk":      widget_portfolio_risk(data),
        "live_alerts":         widget_live_alerts(data),
        "market_snapshot":     widget_market_snapshot(data),
    }


def get_executive_summary() -> dict:
    """Full executive dashboard — all sections, executive score, header."""
    if not is_enabled():
        return disabled_response()
    try:
        data    = load_all()
        widgets = _build_widgets(data)
        score   = compute_executive_score(widgets)
        return {
            "status":         "ENABLED",
            "label":          _LABEL,
            "executive_score": score.to_dict(),
            "sections":       SECTIONS,
            "quick_actions":  QUICK_ACTIONS,
            **widgets,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "label": _LABEL}


def get_system_health() -> dict:
    """System health only — fast endpoint for the health section."""
    if not is_enabled():
        return disabled_response()
    try:
        data = load_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **widget_system_health(data),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "label": _LABEL}


def get_all_widgets() -> dict:
    """All widget data without the executive score — for lazy-load patterns."""
    if not is_enabled():
        return disabled_response()
    try:
        data = load_all()
        return {
            "status": "ENABLED",
            "label":  _LABEL,
            **_build_widgets(data),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "label": _LABEL}


def get_executive_snapshot() -> dict:
    """
    Minimal flat dict for embedding in future super-dashboards.
    Returns top-level KPIs only — no nested sections.
    """
    if not is_enabled():
        return disabled_response()
    try:
        data    = load_all()
        widgets = _build_widgets(data)
        score   = compute_executive_score(widgets)
        ai      = widgets.get("ai_health", {})
        port    = widgets.get("portfolio_overview", {})
        eq      = widgets.get("execution_quality", {})
        return {
            "status":              "ENABLED",
            "label":               _LABEL,
            "executive_score":     score.total,
            "executive_label":     score.label,
            "portfolio_value":     port.get("portfolio_value", 0.0),
            "net_pnl":             port.get("net_pnl", 0.0),
            "win_rate":            port.get("win_rate", 0.0),
            "ai_health_score":     ai.get("health_score", 0.0),
            "ai_trend":            ai.get("trend_direction", "Stable"),
            "execution_score":     eq.get("execution_score", 0.0),
            "open_positions":      port.get("open_positions", 0),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "label": _LABEL}
