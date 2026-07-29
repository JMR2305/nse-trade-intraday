"""
portfolio_performance/api.py — Public facade for Phase 5D.2.

All functions check is_enabled() first and return disabled_response() when off.
READ-ONLY — no order submission, no portfolio mutation, no strategy change.
PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from .performance_models import is_enabled, disabled_response, _LABEL


# ── /api/performance/summary ──────────────────────────────────────────────────

def get_summary() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_engine import build_summary
        return build_summary()
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


# ── /api/performance/equity ───────────────────────────────────────────────────

def get_equity(period: str = "daily") -> dict:
    """
    period: "daily" | "weekly" | "monthly" | "all"
    """
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_engine import load_performance_data
        from .equity_curve import build_equity_curves

        d       = load_performance_data()
        curves  = build_equity_curves(d["pnl_history"])

        if period == "weekly":
            series = curves["weekly"]
        elif period == "monthly":
            series = curves["monthly"]
        elif period == "all":
            series = curves["daily"]
        else:
            series = curves["daily"]

        return {
            "status":      "ENABLED",
            "label":       _LABEL,
            "period":      period,
            "count":       len(series),
            "series":      series,
            "daily_pnl":   curves["daily_pnl"],
            "monthly_pnl": curves["monthly_pnl"],
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


# ── /api/performance/drawdown ─────────────────────────────────────────────────

def get_drawdown() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_engine import load_performance_data, INITIAL_CAPITAL
        from .equity_curve import _points_from_history, _annotate_drawdown, build_equity_curves
        from .drawdown import compute_drawdown_stats

        d       = load_performance_data()
        pts     = _points_from_history(d["pnl_history"])
        _annotate_drawdown(pts)
        stats   = compute_drawdown_stats(pts, INITIAL_CAPITAL)

        curves  = build_equity_curves(d["pnl_history"])

        return {
            "status":  "ENABLED",
            "label":   _LABEL,
            "series":  curves["daily"],     # full annotated daily series
            **stats,
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


# ── /api/performance/statistics ───────────────────────────────────────────────

def get_statistics() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_engine import load_performance_data
        from .statistics import (
            compute_trade_statistics, compute_risk_metrics,
            compute_period_pnl, compute_strategy_contribution,
        )

        d      = load_performance_data()
        closed = d["closed_trades"]

        trade  = compute_trade_statistics(closed)
        risk   = compute_risk_metrics(closed)
        period = compute_period_pnl(closed)
        strat  = compute_strategy_contribution(closed)

        tops   = sorted(closed, key=lambda t: -t.pnl)
        top_winners = [t.to_dict() for t in tops[:10]]
        top_losers  = [t.to_dict() for t in sorted(closed, key=lambda t: t.pnl)[:10]]

        return {
            "status":            "ENABLED",
            "label":             _LABEL,
            "trade_statistics":  trade,
            "risk_metrics":      risk,
            "period_pnl":        period,
            "strategy_contribution": strat,
            "top_winners":       top_winners,
            "top_losers":        top_losers,
            "total_closed":      len(closed),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}


# ── /api/performance/portfolio ────────────────────────────────────────────────

def get_portfolio() -> dict:
    if not is_enabled():
        return disabled_response()
    try:
        from .performance_engine import load_performance_data, INITIAL_CAPITAL
        from .statistics import compute_sector_allocation

        d         = load_performance_data()
        opens_raw = d["open_positions_raw"]
        total     = d["total_value"]
        sectors   = compute_sector_allocation(opens_raw, total)

        # Symbol exposure
        sym_exposure = [
            {
                "symbol": p["symbol"],
                "sector": p["sector"],
                "value":  p["current_value"],
                "pct":    p["weight_pct"],
                "unrealised_pnl": p["unrealised_pnl"],
            }
            for p in opens_raw
        ]

        return {
            "status":          "ENABLED",
            "label":           _LABEL,
            "total_value":     round(total, 2),
            "cash":            round(d["cash"], 2),
            "invested":        round(d["invested"], 2),
            "unrealised_pnl":  round(d["unrealised_pnl"], 2),
            "realised_pnl":    round(d["realised_pnl"], 2),
            "utilisation_pct": round((d["invested"] / total * 100) if total > 0 else 0.0, 2),
            "initial_capital": round(INITIAL_CAPITAL, 2),
            "open_positions":  opens_raw,
            "sector_allocation": sectors,
            "symbol_exposure":   sym_exposure,
            "position_count":    len(opens_raw),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR", "label": _LABEL}
