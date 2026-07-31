"""
paper_analytics/shared_services.py — Phase 8.2
Stable public interface for the Advanced Paper Trading Analytics module.

All downstream phases and super-dashboards import from here — never
from sub-modules directly.

Stable public API:
  get_summary()                → dict
  get_trades()                 → dict
  get_strategies()             → dict
  get_risk()                   → dict
  get_preopen()                → dict
  get_portfolio()              → dict
  get_learning()               → dict
  get_export_json()            → dict
  get_export_csv()             → str
  get_paper_analytics_snapshot() → dict  (flat KPI for Executive Dashboard)

READ-ONLY. ADVISORY-ONLY.
This module NEVER places orders, modifies paper trades, strategies,
portfolio, risk parameters, or AI models.
"""
from __future__ import annotations

from .models import is_enabled, disabled_response, analytics_grade, ADVISORY_LABEL


# ── Safe loader ───────────────────────────────────────────────────────────────

def _safe(fn, default=None):
    """Call fn(); on any exception return default (or {})."""
    try:
        return fn()
    except Exception:
        return default if default is not None else {}


def _load_trades():
    from .trade_analytics import get_trade_analytics
    return _safe(get_trade_analytics, {"available": False, "total_trades": 0, "win_rate": 0.0})


def _load_strategies():
    from .strategy_analytics import get_strategy_analytics
    return _safe(get_strategy_analytics, {"available": False, "strategies": []})


def _load_risk():
    from .risk_analytics import get_risk_analytics
    return _safe(get_risk_analytics, {"available": False, "sharpe_ratio": 0.0, "max_drawdown": 0.0})


def _load_preopen():
    from .preopen_analytics import get_preopen_analytics
    return _safe(get_preopen_analytics, {"available": False})


def _load_portfolio():
    from .portfolio_analytics import get_portfolio_analytics
    return _safe(get_portfolio_analytics, {"available": False})


def _load_learning():
    from .learning_insights import get_learning_insights
    return _safe(get_learning_insights, {"available": False, "has_data": False})


def _load_execution():
    from .execution_analytics import get_execution_analytics
    return _safe(get_execution_analytics, {"available": False})


def _load_time():
    from .time_analytics import get_time_analytics
    return _safe(get_time_analytics, {"available": False})


def _load_sector():
    from .sector_analytics import get_sector_analytics
    return _safe(get_sector_analytics, {"available": False, "sectors": []})


# ── Score formula ─────────────────────────────────────────────────────────────

def _compute_analytics_score(trades: dict, risk: dict, learning: dict) -> float:
    """
    0–100 analytics quality score:
    - Win rate          30 pts
    - Profit factor     20 pts (capped at 3)
    - Sharpe ratio      20 pts (capped at 2)
    - Drawdown penalty  15 pts (inverted max drawdown %)
    - Data quality      15 pts (trade count)
    """
    wr_pts   = float(trades.get("win_rate",     0.0)) / 100 * 30
    pf_raw   = float(trades.get("profit_factor", 0.0))
    pf_pts   = min(pf_raw / 3.0, 1.0) * 20
    sr_raw   = float(risk.get("sharpe_ratio",  0.0))
    sr_pts   = min(max(sr_raw / 2.0, 0.0), 1.0) * 20
    dd_pct   = float(risk.get("max_drawdown_pct", 0.0))
    dd_pts   = max(0.0, 1.0 - dd_pct / 30.0) * 15
    n        = int(trades.get("total_trades", 0))
    data_pts = min(n / 30.0, 1.0) * 15
    return round(min(100.0, wr_pts + pf_pts + sr_pts + dd_pts + data_pts), 1)


# ── Public API ────────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """Unified summary — score, grade, all sub-section highlights."""
    if not is_enabled():
        return disabled_response()
    try:
        from datetime import datetime, timezone

        trades   = _load_trades()
        risk     = _load_risk()
        learning = _load_learning()
        strats   = _load_strategies()
        sector   = _load_sector()

        score = _compute_analytics_score(trades, risk, learning)
        grade = analytics_grade(score)

        n = int(trades.get("total_trades", 0))

        # Rate and ratio fields are undefined — not zero — when there are no
        # closed trades.  Returning None lets the React UI render "—" instead
        # of the misleading "0.00%" or "0.00" that a zero float would produce.
        def _rate(key: str):
            return trades.get(key) if n > 0 else None

        def _risk_ratio(key: str):
            return risk.get(key) if n > 0 else None

        return {
            "status":          "ENABLED",
            "available":       True,
            "advisory_only":   True,
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "analytics_score": score,
            "grade":           grade,
            # Trade highlights
            "total_trades":    n,
            "win_rate":        _rate("win_rate"),
            "profit_factor":   _rate("profit_factor"),
            "expectancy":      _rate("expectancy"),
            "total_pnl":       trades.get("total_pnl", 0.0),
            "realised_pnl":    trades.get("realised_pnl", 0.0),
            # Risk highlights (also undefined without trades)
            "sharpe_ratio":    _risk_ratio("sharpe_ratio"),
            "sortino_ratio":   _risk_ratio("sortino_ratio"),
            "calmar_ratio":    _risk_ratio("calmar_ratio"),
            "max_drawdown_pct": risk.get("max_drawdown_pct", 0.0),
            "volatility_pct":  _risk_ratio("volatility_pct"),
            # Learning highlights
            "best_strategy":   learning.get("best_strategy", "N/A"),
            "worst_strategy":  learning.get("worst_strategy", "N/A"),
            "best_sector":     learning.get("best_sector", "N/A"),
            "best_market_condition": learning.get("best_market_condition", "N/A"),
            # Strategy
            "total_strategies": strats.get("total_strategies", 0),
            # Sector
            "top_sector":      sector.get("best_sector", "N/A"),
        }
    except Exception as exc:
        import traceback
        return {
            "status":    "ERROR",
            "error":     str(exc),
            "trace":     traceback.format_exc(),
            "available": False,
        }


def get_trades() -> dict:
    """Full trade analytics payload."""
    if not is_enabled():
        return disabled_response()
    try:
        data = _load_trades()
        return {"status": "ENABLED", **data}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_strategies() -> dict:
    """Per-strategy performance breakdown."""
    if not is_enabled():
        return disabled_response()
    try:
        data = _load_strategies()
        return {"status": "ENABLED", **data}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_risk() -> dict:
    """Comprehensive risk analytics."""
    if not is_enabled():
        return disabled_response()
    try:
        data = _load_risk()
        return {"status": "ENABLED", **data}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_preopen() -> dict:
    """Pre-open validation analytics."""
    if not is_enabled():
        return disabled_response()
    try:
        data = _load_preopen()
        return {"status": "ENABLED", **data}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_portfolio() -> dict:
    """Portfolio analytics."""
    if not is_enabled():
        return disabled_response()
    try:
        data = _load_portfolio()
        return {"status": "ENABLED", **data}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_learning() -> dict:
    """Learning insights + AI observations."""
    if not is_enabled():
        return disabled_response()
    try:
        learning  = _load_learning()
        time_data = _load_time()
        strats    = _load_strategies()
        preopen   = _load_preopen()
        risk      = _load_risk()

        from .ai_insights import get_ai_insights
        ai_obs = _safe(
            lambda: get_ai_insights(time_data, strats, preopen, learning, risk),
            {"available": False},
        )

        return {
            "status":          "ENABLED",
            **learning,
            "ai_insights":     ai_obs,
            "time_analytics":  time_data,
            "sector_analytics": _load_sector(),
            "execution_analytics": _load_execution(),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


def get_export_json() -> dict:
    """Full JSON export of all sub-sections."""
    if not is_enabled():
        return {"status": "DISABLED"}
    try:
        return {
            "status":    "ENABLED",
            "summary":   get_summary(),
            "trades":    _load_trades(),
            "strategies": _load_strategies(),
            "risk":      _load_risk(),
            "preopen":   _load_preopen(),
            "portfolio": _load_portfolio(),
            "learning":  _load_learning(),
            "time":      _load_time(),
            "sectors":   _load_sector(),
            "execution": _load_execution(),
            "advisory_only": True,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def get_export_csv() -> str:
    """CSV export of summary KPIs."""
    if not is_enabled():
        return ""
    try:
        import csv, io
        summary = get_summary()
        if summary.get("status") != "ENABLED":
            return ""
        fields = [
            "analytics_score", "grade", "total_trades", "win_rate",
            "profit_factor", "expectancy", "total_pnl", "realised_pnl",
            "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "max_drawdown_pct", "volatility_pct",
            "best_strategy", "best_sector",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({k: summary.get(k, "") for k in fields})
        return output.getvalue()
    except Exception:
        return ""


def get_paper_analytics_snapshot() -> dict:
    """
    Flat KPI dict for Executive Dashboard integration and future phases.
    Never raises — returns safe defaults on any error.
    Respects the feature flag: returns disabled payload when flag is false.
    """
    if not is_enabled():
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy": 0.0, "total_pnl": 0.0, "max_drawdown": 0.0,
            "sharpe_ratio": 0.0, "best_strategy": "N/A", "best_sector": "N/A",
            "avg_hold_seconds": 0.0, "analytics_score": 0.0, "grade": "N/A",
            "available": False, "advisory_only": True, "status": "DISABLED",
        }
    try:
        from .models import PaperAnalyticsSnapshot
        trades = _load_trades()
        risk   = _load_risk()
        learn  = _load_learning()
        score  = _compute_analytics_score(trades, risk, learn)

        snap = PaperAnalyticsSnapshot(
            total_trades     = int(trades.get("total_trades", 0)),
            win_rate         = float(trades.get("win_rate", 0.0)),
            profit_factor    = float(trades.get("profit_factor", 0.0)),
            expectancy       = float(trades.get("expectancy", 0.0)),
            total_pnl        = float(trades.get("total_pnl", 0.0)),
            max_drawdown     = float(risk.get("max_drawdown", 0.0)),
            sharpe_ratio     = float(risk.get("sharpe_ratio", 0.0)),
            best_strategy    = str(learn.get("best_strategy", "N/A")),
            best_sector      = str(learn.get("best_sector", "N/A")),
            avg_hold_seconds = float(trades.get("avg_holding_seconds", 0.0)),
            analytics_score  = score,
            grade            = analytics_grade(score),
            available        = True,
        )
        return snap.to_dict()
    except Exception:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy": 0.0, "total_pnl": 0.0, "max_drawdown": 0.0,
            "sharpe_ratio": 0.0, "best_strategy": "N/A", "best_sector": "N/A",
            "avg_hold_seconds": 0.0, "analytics_score": 0.0, "grade": "D",
            "available": False, "advisory_only": True,
        }
