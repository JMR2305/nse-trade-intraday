"""
portfolio_performance/shared_services.py — Phase 5D.2 shared service interface.

THIS IS THE CANONICAL ENTRY POINT for cross-phase aggregation
(Research Lab, Executive Dashboard, etc.).

Stable public API:
  get_portfolio_performance_snapshot() → dict   (flat KPIs for embedding)

All functions check is_enabled() and return disabled_response() when off.
All functions are read-only and advisory-only.
"""
from __future__ import annotations

from typing import Any, Dict

from .performance_models import is_enabled, disabled_response, _LABEL


# ── String coercion guard ─────────────────────────────────────────────────────

def _as_str(v: Any, fallback: str = "N/A") -> str:
    """Coerce *v* to a non-empty string, using *fallback* for None/dict/list.

    Guards against upstream sources returning a dict or None where a plain
    string KPI label is expected (e.g. ``grade``, ``trend``).
    """
    if isinstance(v, str):
        return v or fallback
    return fallback


# ── Grade / trend helpers ─────────────────────────────────────────────────────

def _portfolio_grade(win_rate: float) -> str:
    """Convert a 0–100 win-rate percentage to a letter grade."""
    if win_rate >= 65:
        return "A"
    if win_rate >= 55:
        return "B"
    if win_rate >= 45:
        return "C"
    if win_rate >= 35:
        return "D"
    return "F"


def _portfolio_trend(weekly_pnl: float, monthly_pnl: float) -> str:
    """Derive a trend label from recent vs longer-period P&L.

    A positive weekly P&L that is meaningful relative to the monthly figure
    signals improvement; a negative weekly P&L signals weakening.
    """
    if weekly_pnl > 0:
        return "IMPROVING"
    if weekly_pnl < 0:
        return "WEAKENING"
    return "STABLE"


# ── Public API ────────────────────────────────────────────────────────────────

def get_portfolio_performance_snapshot() -> Dict[str, Any]:
    """
    Flat KPI snapshot for embedding in cross-phase aggregators
    (Research Lab, Executive Dashboard, etc.).

    All string fields pass through ``_as_str()`` so they can never emit
    a dict/list/None to downstream callers.
    """
    if not is_enabled():
        return disabled_response()

    try:
        from .api import get_summary
        summary = get_summary()

        if summary.get("status") != "ENABLED":
            return disabled_response()

        win_rate   = float(summary.get("win_rate",   0.0) or 0.0)
        weekly_pnl = float(summary.get("weekly_pnl", 0.0) or 0.0)
        monthly_pnl = float(summary.get("monthly_pnl", 0.0) or 0.0)
        total_ret  = float(summary.get("total_return_pct", 0.0) or 0.0)
        net_pnl    = float(summary.get("total_net_pnl",    0.0) or 0.0)

        raw_grade = _portfolio_grade(win_rate)
        raw_trend = _portfolio_trend(weekly_pnl, monthly_pnl)

        return {
            "status":              "ENABLED",
            "label":               _LABEL,
            "grade":               _as_str(raw_grade, fallback="N/A"),
            "trend":               _as_str(raw_trend, fallback="STABLE"),
            "win_rate":            round(win_rate, 4),
            "total_net_pnl":       round(net_pnl, 2),
            "total_return_pct":    round(total_ret, 4),
            "weekly_pnl":          round(weekly_pnl, 2),
            "monthly_pnl":         round(monthly_pnl, 2),
            "total_trades":        int(summary.get("total_trades",   0) or 0),
            "open_trades":         int(summary.get("open_trades",    0) or 0),
            "advisory_only":       True,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "label": _LABEL}
