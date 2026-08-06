"""
widgets.py — Phase 5D.5 widget data formatters.

Each widget function receives the aggregated data dict from dashboard_engine.load_all()
and returns a clean, flat dict ready for the frontend.
ZERO calculation — only reads, reshapes, and defaults.
"""
from __future__ import annotations
from typing import Any


def _g(d: dict, *keys, default=None) -> Any:
    """Safe nested get."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)  # type: ignore[assignment]
    return d


def _as_str(v: Any, fallback: str = "N/A") -> str:
    """Coerce *v* to a non-empty string, using *fallback* for None/dict/list.

    Guards against the backend accidentally returning a dict or None where a
    plain string KPI label is expected (e.g. ``best_regime``).
    """
    if isinstance(v, str):
        return v or fallback
    return fallback


def _calibration_quality(snap: dict) -> "float | None":
    """Return calibration quality 0–100, or **None** when ECE has never been measured.

    Distinguishes two distinct states:
    - Key absent or value None  →  None   (model never evaluated; do NOT display 100%)
    - ECE = 0.05 (measured)    →  95.0
    - ECE = 0.0  (perfect)     →  100.0  (actually measured as zero error)

    Prevents the misleading "100% calibration" badge that appeared after the
    _sf None-safety fix caused calibration_ece=None to fall back to 0.0.
    """
    v = snap.get("calibration_ece")
    if v is None:
        return None
    try:
        return round((1.0 - float(v)) * 100.0, 1)
    except (TypeError, ValueError):
        return None


def _sf(d: dict, key: str, default: float = 0.0) -> float:
    """Return d[key] as a float, substituting *default* when the value is
    absent, None, or non-numeric.  Mirrors layout._sf — prevents
    'NoneType < float' / 'NoneType + float' crashes when a stale scan
    returns a key with a None value rather than omitting the key entirely.
    """
    v = d.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Section 1 — System Health
# ---------------------------------------------------------------------------

def widget_system_health(data: dict) -> dict:
    sys = data.get("system", {})
    sched = _g(sys, "scheduler") or {}
    meta  = _g(sys, "meta")      or {}
    return {
        "application_health": _as_str(_g(meta,  "status",   default="UNKNOWN"), fallback="UNKNOWN"),
        "scheduler_health":   _as_str(_g(sched, "status",   default="UNKNOWN"), fallback="UNKNOWN"),
        "database_status":    _as_str(_g(meta,  "database", default="UNKNOWN"), fallback="UNKNOWN"),
        "api_status":         _as_str(_g(meta,  "api",      default="UNKNOWN"), fallback="UNKNOWN"),
        "feature_flags":      _g(meta, "feature_flags", default=[]),
        "background_jobs":    _g(sched, "active_jobs", default=[]),
    }


# ---------------------------------------------------------------------------
# Section 2 — Portfolio Overview
# ---------------------------------------------------------------------------

def widget_portfolio_overview(data: dict) -> dict:
    pf   = data.get("portfolio", {})
    summ = _g(pf, "summary") or {}
    port = _g(pf, "portfolio") or {}
    return {
        "portfolio_value":    _sf(summ, "total_portfolio_value", 0.0),
        "today_pnl":          _sf(summ, "today_pnl", 0.0),
        "net_pnl":            _sf(summ, "total_net_pnl", 0.0),
        "cash_available":     _sf(summ, "cash_available", 0.0),
        "invested_capital":   _sf(summ, "invested_capital", 0.0),
        "open_positions":     int(_sf(port, "position_count", 0.0)),
        "win_rate":           _sf(summ, "win_rate_pct", 0.0),
        "profit_factor":      _sf(summ, "profit_factor", 0.0),
        "drawdown":           _sf(summ, "max_drawdown_pct", 0.0),
        "current_drawdown":   _sf(summ, "current_drawdown_pct", 0.0),
        "total_return_pct":   _sf(summ, "total_return_pct", 0.0),
        "portfolio_utilisation_pct": _sf(summ, "portfolio_utilisation_pct", 0.0),
        "initial_capital":    _sf(summ, "initial_capital", 500000.0),
    }


# ---------------------------------------------------------------------------
# Section 3 — AI Health
# ---------------------------------------------------------------------------

def widget_ai_health(data: dict) -> dict:
    ai  = data.get("ai", {})
    snap = _g(ai, "snapshot") or {}
    comp = _g(ai, "components") or {}
    learn = _g(ai, "learning") or {}
    return {
        "health_score":         _g(snap, "health_score", default=0.0),
        "health_label":         _as_str(_g(snap, "health_label",     default="N/A"),   fallback="N/A"),
        "prediction_accuracy":  _g(snap, "prediction_accuracy", default=0.0),
        "precision":            _g(snap, "precision", default=0.0),
        "recall":               _g(snap, "recall", default=0.0),
        "avg_confidence":       _g(snap, "avg_confidence", default=0.0),
        "trend_direction":      _as_str(_g(snap, "trend_direction",  default="Stable"), fallback="Stable"),
        "accuracy_delta":       _g(snap, "accuracy_delta", default=0.0),
        "calibration_ece":      _g(snap, "calibration_ece", default=None),
        "calibration_quality":  _calibration_quality(snap),
        "total_signals":        _g(snap, "total_signals", default=0),
        "components":           comp,
        "recent_accuracy":      _g(learn, "recent_accuracy", default=0.0),
    }


# ---------------------------------------------------------------------------
# Section 4 — Strategy Overview
# ---------------------------------------------------------------------------

def widget_strategy_overview(data: dict) -> dict:
    st   = data.get("strategy", {})
    snap = _g(st, "snapshot") or {}
    crit = _g(st, "criterion") or {}
    recs = _g(st, "recs") or []
    best_pf  = _g(crit, "best_profit_factor") or {}
    best_wr  = _g(crit, "best_win_rate") or {}
    best_pnl = _g(crit, "best_net_pnl") or {}
    worst    = _g(crit, "worst_net_pnl") or {}
    return {
        "total_strategies":    int(_sf(snap, "total_strategies", 0.0)),
        "best_strategy":       _as_str(_g(snap,    "best_strategy", default="N/A")),
        "worst_strategy":      _as_str(_g(worst,   "name",          default="N/A")),
        "highest_win_rate":    _as_str(_g(best_wr, "name",          default="N/A")),
        "best_profit_factor":  _as_str(_g(best_pf, "name",          default="N/A")),
        "best_regime":         _as_str(_g(snap,    "best_regime",   default="N/A")),
        "best_sector":         _as_str(_g(snap,    "best_sector",   default="N/A")),
        "total_net_pnl":       _sf(snap, "total_net_pnl", 0.0),
        "overall_win_rate":    _sf(snap, "overall_win_rate", 0.0),
        "recommendation_count": len(recs),
        "strong_buy_count":    sum(1 for r in recs if isinstance(r, dict) and _g(r, "verdict", default="").upper() == "STRONG_BUY"),
        "recommendations":     recs[:5],  # top 5 for executive view
    }


# ---------------------------------------------------------------------------
# Section 5 — Execution Quality
# ---------------------------------------------------------------------------

def widget_execution_quality(data: dict) -> dict:
    eq = data.get("execution_quality", {})
    return {
        "execution_score":   _sf(eq, "avg_execution_score", 0.0),
        "avg_slippage":      _sf(eq, "avg_entry_slippage_pct", 0.0),
        "avg_fill_delay":    _sf(eq, "avg_fill_delay_seconds", 0.0),
        "total_trades":      int(_sf(eq, "total_trades", 0.0)),
        "best_execution":    _sf(eq, "best_execution_score", 0.0),
        "worst_execution":   _sf(eq, "worst_execution_score", 0.0),
        "exit_slippage":     _sf(eq, "avg_exit_slippage_pct", 0.0),
    }


# ---------------------------------------------------------------------------
# Section 6 — Pre-Open Intelligence
# ---------------------------------------------------------------------------

def widget_preopen(data: dict) -> dict:
    po     = data.get("preopen", {})
    status = _g(po, "status") or {}
    ranks  = _g(po, "rankings") or {}
    sects  = _g(po, "sectors") or {}
    top_symbols = _g(ranks, "top_symbols") or []
    top_gapup   = next((s for s in top_symbols if _g(s, "gap_pct", default=0) > 0), {})
    top_gapdown = next((s for s in reversed(top_symbols) if _g(s, "gap_pct", default=0) < 0), {})
    buy_imbals  = [s for s in top_symbols if _g(s, "imbalance_type", default="") == "BUY"]
    sell_imbals = [s for s in top_symbols if _g(s, "imbalance_type", default="") == "SELL"]
    return {
        "top_gap_up":            _as_str(_g(top_gapup,  "symbol", default="N/A")),
        "top_gap_up_pct":        _g(top_gapup,  "gap_pct", default=0.0),
        "top_gap_down":          _as_str(_g(top_gapdown, "symbol", default="N/A")),
        "top_gap_down_pct":      _g(top_gapdown, "gap_pct", default=0.0),
        "buy_imbalance":         _as_str(_g(buy_imbals[0],  "symbol", default="N/A") if buy_imbals else "N/A"),
        "sell_imbalance":        _as_str(_g(sell_imbals[0], "symbol", default="N/A") if sell_imbals else "N/A"),
        "leading_sector":        _as_str(_g(sects,  "leading_sector", default="N/A")),
        "highest_exec_qty":      _g(ranks, "highest_exec_qty", default=0),
        "provider":              _as_str(_g(status, "provider_label", default="N/A")),
        "last_refresh":          _as_str(_g(status, "last_updated",   default="N/A")),
        "symbols_analysed":      _g(status, "symbols_analysed", default=0),
        "trading_date":          _as_str(_g(status, "trading_date",   default="N/A")),
    }


# ---------------------------------------------------------------------------
# Section 7 — Portfolio Risk
# ---------------------------------------------------------------------------

def widget_portfolio_risk(data: dict) -> dict:
    rk     = data.get("risk", {})
    risk   = _g(rk, "risk") or {}
    alerts = _g(rk, "alerts") or {}
    salloc = _g(risk, "sector_allocation") or []
    top_sector = max(salloc, key=lambda x: _g(x, "weight_pct", default=0.0), default={})
    ral = _g(alerts, "alerts") or []
    return {
        "utilisation":           _sf(risk, "utilization_pct", _sf(risk, "portfolio_heat", 0.0)),
        "largest_position":      _sf(risk, "largest_position_pct", 0.0),
        "maximum_risk":          _sf(risk, "daily_risk", 0.0),
        "sector_concentration":  _sf(top_sector, "weight_pct", 0.0),
        "top_sector":            _as_str(_g(top_sector, "sector", default="N/A")),
        "kill_switch_active":    _g(risk, "kill_switch", "active", default=False),
        "risk_alerts":           ral[:5],
        "alert_count":           len(ral),
        "diversification_score": _sf(risk, "diversification_score", 0.0),
        "portfolio_heat":        _sf(risk, "portfolio_heat", 0.0),
    }


# ---------------------------------------------------------------------------
# Section 8 — Live Alerts
# ---------------------------------------------------------------------------

def widget_live_alerts(data: dict) -> dict:
    sys  = data.get("system", {})
    risk = data.get("risk", {})
    meta = _g(sys, "meta") or {}
    sched = _g(sys, "scheduler") or {}
    ral   = _g(risk, "alerts", "alerts") or []
    critical = [a for a in ral if isinstance(a, dict) and _g(a, "level", default="") in ("CRITICAL", "ERROR")]
    warnings = [a for a in ral if isinstance(a, dict) and _g(a, "level", default="") == "WARNING"]
    info     = [a for a in ral if isinstance(a, dict) and _g(a, "level", default="") == "INFO"]
    return {
        "critical":           critical[:3],
        "warnings":           warnings[:5],
        "info":               info[:3],
        "recent_errors":      _g(meta, "recent_errors", default=[])[:3],
        "feature_flag_issues": _g(meta, "feature_flag_issues", default=[])[:3],
        "scheduler_issues":   _g(sched, "issues", default=[])[:3],
        "total_critical":     len(critical),
        "total_warnings":     len(warnings),
    }


# ---------------------------------------------------------------------------
# Section 9 — Market Snapshot
# ---------------------------------------------------------------------------

def widget_market_snapshot(data: dict) -> dict:
    sys  = data.get("system", {})
    meta = _g(sys, "meta") or {}
    return {
        "nifty":         _g(meta, "nifty",      default={"price": None, "change_pct": None}),
        "bank_nifty":    _g(meta, "bank_nifty", default={"price": None, "change_pct": None}),
        "india_vix":     _g(meta, "india_vix",  default={"price": None, "change_pct": None}),
        "market_regime": _as_str(_g(meta, "market_regime", default="UNKNOWN"), fallback="UNKNOWN"),
        "market_breadth": _as_str(_g(meta, "market_breadth", default="N/A")),
        "top_sectors":   _g(meta, "top_sectors", default=[]),
        "market_status": _as_str(_g(meta, "market_status", default="UNKNOWN"), fallback="UNKNOWN"),
        "ist_time":      _as_str(_g(meta, "ist_time", default="N/A")),
    }


# ---------------------------------------------------------------------------
# Section 11 — Live Readiness (Phase 6.5)
# ---------------------------------------------------------------------------

def widget_readiness(data: dict) -> dict:
    """Flat Phase 6.5 snapshot for the Executive Dashboard tile."""
    rd = data.get("readiness", {})
    if not rd.get("available", False):
        return {
            "available":       False,
            "disabled":        True,
            "readiness_score": 0.0,
            "grade":           "N/A",
            "verdict":         "NOT READY",
            "verdict_short":   "DISABLED",
        }
    return {
        "available":       True,
        "disabled":        False,
        "readiness_score": rd.get("readiness_score", 0.0),
        "grade":           _as_str(rd.get("grade",         "N/A"),       fallback="N/A"),
        "verdict":         _as_str(rd.get("verdict",       "NOT READY"), fallback="NOT READY"),
        "verdict_short":   _as_str(rd.get("verdict_short", "NOT READY"), fallback="NOT READY"),
    }


# ---------------------------------------------------------------------------
# Header data
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Section 12 — Paper Analytics (Phase 8.2)
# ---------------------------------------------------------------------------

def widget_paper_analytics(data: dict) -> dict:
    """Flat KPI tile for the Paper Analytics score (Phase 8.2).

    Reads from the ``paper_analytics`` key populated by dashboard_engine
    via ``get_paper_analytics_snapshot()``.  Gracefully degrades when the
    feature flag ``PAPER_ANALYTICS_ENABLED`` is off.
    """
    pa = data.get("paper_analytics", {})
    available = bool(pa.get("available", False))
    if not available:
        return {
            "available":       False,
            "disabled":        True,
            "analytics_score": 0.0,
            "grade":           "N/A",
            "win_rate":        0.0,
            "profit_factor":   0.0,
            "total_trades":    0,
            "total_pnl":       0.0,
            "sharpe_ratio":    0.0,
            "best_strategy":   "N/A",
            "best_sector":     "N/A",
            "advisory_only":   True,
        }
    return {
        "available":       True,
        "disabled":        False,
        "analytics_score": _g(pa, "analytics_score", default=0.0),
        "grade":           _as_str(_g(pa, "grade",           default="N/A")),
        "win_rate":        _g(pa, "win_rate",                default=0.0),
        "profit_factor":   _g(pa, "profit_factor",           default=0.0),
        "total_trades":    int(_g(pa, "total_trades",         default=0) or 0),
        "total_pnl":       _g(pa, "total_pnl",               default=0.0),
        "sharpe_ratio":    _g(pa, "sharpe_ratio",            default=0.0),
        "best_strategy":   _as_str(_g(pa, "best_strategy",   default="N/A")),
        "best_sector":     _as_str(_g(pa, "best_sector",     default="N/A")),
        "advisory_only":   True,
    }


# ---------------------------------------------------------------------------
# Header data
# ---------------------------------------------------------------------------

def widget_header(data: dict) -> dict:
    sys  = data.get("system", {})
    po   = data.get("preopen", {})
    meta = _g(sys, "meta") or {}
    po_status = _g(po, "status") or {}
    return {
        "market_status":     _as_str(_g(meta,      "market_status",  default="UNKNOWN"), fallback="UNKNOWN"),
        "ist_time":          _as_str(_g(meta,      "ist_time",       default="N/A")),
        "market_regime":     _as_str(_g(meta,      "market_regime",  default="UNKNOWN"), fallback="UNKNOWN"),
        "paper_trading":     True,
        "active_provider":   _as_str(_g(po_status, "provider_label", default="N/A")),
        "watchlist_count":   _g(po_status, "symbols_analysed", default=0),
        "trading_date":      _as_str(_g(po_status, "trading_date",   default="N/A")),
    }
