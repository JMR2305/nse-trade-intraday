"""
shared_services.py — Phase 9.1
Unified Command Centre — pure aggregation layer.

READ-ONLY. ADVISORY-ONLY.
Performs ZERO calculations. Aggregates snapshot data from existing modules only.
Never modifies trading state, orders, portfolio, configuration, or infrastructure.

Downstream stable interface:
  get_command_center_snapshot() -> dict   ← safe for future consumers
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from command_center.models import (
    is_enabled, disabled_response,
    platform_grade, platform_status, _now_iso, _now_display,
    SEV_CRITICAL, SEV_WARNING, SEV_INFO,
    QUICK_ACTIONS, SYSTEM_MODULES,
)


# ── Safe upstream loader ───────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── Upstream snapshot loaders — zero recalculation ────────────────────────────

def _load_market_snapshot() -> dict:
    def _f():
        from market_intelligence_hub.shared_services import get_market_intelligence_snapshot
        return get_market_intelligence_snapshot()
    return _safe(_f) or {"available": False, "market_health_score": 0.0, "grade": "D"}


def _load_market_overview() -> dict:
    def _f():
        from market_intelligence_hub.shared_services import get_overview
        return get_overview()
    return _safe(_f) or {"available": False}


def _load_paper_analytics() -> dict:
    def _f():
        from paper_analytics.shared_services import get_paper_analytics_snapshot
        return get_paper_analytics_snapshot()
    return _safe(_f) or {"available": False, "analytics_score": 0.0, "total_trades": 0}


def _load_executive() -> dict:
    def _f():
        from executive_dashboard.shared_services import get_executive_snapshot
        return get_executive_snapshot()
    return _safe(_f) or {"available": False, "portfolio_value": 0.0}


def _load_ai_snapshot() -> dict:
    def _f():
        from ai_performance.shared_services import get_ai_snapshot
        return get_ai_snapshot()
    return _safe(_f) or {"available": False, "health_score": 0.0}


def _load_risk_snapshot() -> dict:
    def _f():
        from risk_validation.shared_services import get_risk_validation_snapshot
        return get_risk_validation_snapshot()
    return _safe(_f) or {"advisory_only": True, "risk_score": 0.0}


def _load_data_quality() -> dict:
    def _f():
        from data_quality.shared_services import get_data_quality_snapshot
        return get_data_quality_snapshot()
    return _safe(_f) or {"available": False, "quality_score": 0.0}


def _load_observability() -> dict:
    def _f():
        from observability_center.shared_services import get_observability_snapshot
        return get_observability_snapshot()
    return _safe(_f) or {"available": False, "observability_score": 0.0}


def _load_operations() -> dict:
    def _f():
        from operations_center.shared_services import get_operations_snapshot
        return get_operations_snapshot()
    return _safe(_f) or {"available": False, "operations_score": 0.0}


def _load_security() -> dict:
    def _f():
        from security_center.shared_services import get_security_snapshot
        return get_security_snapshot()
    return _safe(_f) or {"available": False, "security_score": 0.0}


def _load_performance() -> dict:
    def _f():
        from performance_center.shared_services import get_performance_snapshot
        return get_performance_snapshot()
    return _safe(_f) or {"available": False, "performance_score": 0.0}


def _load_deployment() -> dict:
    def _f():
        from deployment_center.shared_services import get_deployment_snapshot
        return get_deployment_snapshot()
    return _safe(_f) or {"available": False, "dr_score": 0.0}


def _load_scheduler_health() -> dict:
    def _f():
        from phase20_store import get_scheduler_health
        return get_scheduler_health()
    return _safe(_f) or {"status": "UNKNOWN"}


def _load_notifications(limit: int = 50) -> list:
    def _f():
        from phase20_store import list_notifications
        return list_notifications(limit=limit)
    return _safe(_f) or []


def _load_scan_runs(limit: int = 20) -> list:
    def _f():
        from phase20_store import list_scan_runs
        return list_scan_runs(limit=limit)
    return _safe(_f) or []


# ── Platform health score (aggregated from existing scores) ───────────────────

def _compute_platform_score(
    obs: dict, ops: dict, dq: dict, sec: dict, perf: dict, deploy: dict
) -> float:
    """
    Aggregate platform health from Phase 8 module scores.
    Weights: obs 20% · ops 20% · dq 20% · sec 15% · perf 15% · deploy 10%.
    All inputs are existing snapshot scores — zero new computation.
    """
    weights = [
        (float(obs.get("observability_score",  0.0)), 0.20),
        (float(ops.get("operations_score",     0.0)), 0.20),
        (float(dq.get("quality_score",         0.0)), 0.20),
        (float(sec.get("security_score",       0.0)), 0.15),
        (float(perf.get("performance_score",   0.0)), 0.15),
        (float(deploy.get("dr_score",          0.0)), 0.10),
    ]
    total_w = sum(w for _, w in weights)
    score   = sum(s * w for s, w in weights) / total_w if total_w > 0 else 0.0
    return round(min(100.0, max(0.0, score)), 1)


# ── Section builders ───────────────────────────────────────────────────────────

def _build_market_section(overview: dict) -> dict:
    """Section 1 — Market Overview. Pure extraction from existing snapshots."""
    regime  = overview.get("regime", {}) or {}
    breadth = overview.get("breadth", {}) or {}
    sectors = overview.get("sectors", {}) or {}
    indices = overview.get("indices", {}) or {}

    return {
        "nifty50": {
            "price":      indices.get("nifty50_price")  or regime.get("nifty_price", 0.0),
            "change_pct": indices.get("nifty50_change") or regime.get("nifty_change_pct", 0.0),
            "trend":      regime.get("nifty_trend", "SIDEWAYS"),
        },
        "bank_nifty": {
            "price":      indices.get("banknifty_price")  or regime.get("banknifty_price", 0.0),
            "change_pct": indices.get("banknifty_change") or regime.get("banknifty_change_pct", 0.0),
            "trend":      regime.get("banknifty_trend", "SIDEWAYS"),
        },
        "india_vix": {
            "value":  regime.get("vix_value", 0.0),
            "status": regime.get("vix_status", "UNKNOWN"),
        },
        "advance":         breadth.get("advancing", 0),
        "decline":         breadth.get("declining", 0),
        "neutral":         breadth.get("neutral",   0),
        "bullish_stocks":  breadth.get("bullish",   0),
        "bearish_stocks":  breadth.get("bearish",   0),
        "top_gainers":     overview.get("top_gainers", [])[:5],
        "top_losers":      overview.get("top_losers",  [])[:5],
        "top_volume":      overview.get("top_volume",  [])[:5],
        "strongest_sector":sectors.get("strongest_sector", "N/A"),
        "weakest_sector":  sectors.get("weakest_sector",   "N/A"),
        "sector_list":     sectors.get("sectors", [])[:10],
        "regime":          regime.get("regime", "UNKNOWN"),
        "sub_regime":      regime.get("sub_regime", "NORMAL"),
        "trend_strength":  regime.get("trend_strength", 0.0),
        "high_volatility": regime.get("high_volatility", False),
    }


def _build_portfolio_section(executive: dict, paper: dict) -> dict:
    """Section 2 — Portfolio Snapshot. Derived from executive + paper analytics snapshots."""
    return {
        "portfolio_value":      executive.get("portfolio_value",    0.0),
        "net_pnl":              executive.get("net_pnl",            0.0),
        "win_rate":             executive.get("win_rate",           0.0),
        "open_positions":       executive.get("open_positions",     0),
        "total_trades":         paper.get("total_trades",           0),
        "total_pnl":            paper.get("total_pnl",              0.0),
        "realised_pnl":         paper.get("total_pnl",              0.0),
        "max_drawdown":         paper.get("max_drawdown",           0.0),
        "sharpe_ratio":         paper.get("sharpe_ratio",           0.0),
        "best_strategy":        paper.get("best_strategy",          "N/A"),
        "best_sector":          paper.get("best_sector",            "N/A"),
        "analytics_grade":      paper.get("grade",                  "N/A"),
        "analytics_score":      paper.get("analytics_score",        0.0),
        "execution_score":      executive.get("execution_score",    0.0),
        "executive_score":      executive.get("executive_score",    0.0),
        "executive_label":      executive.get("executive_label",    "N/A"),
    }


def _build_trading_section(paper: dict) -> dict:
    """Section 3 — Today's Trading. Extracted from paper analytics snapshot."""
    return {
        "total_trades":   paper.get("total_trades",       0),
        "win_rate":       paper.get("win_rate",           0.0),
        "profit_factor":  paper.get("profit_factor",      0.0),
        "expectancy":     paper.get("expectancy",         0.0),
        "avg_hold_secs":  paper.get("avg_hold_seconds",   0.0),
        "total_pnl":      paper.get("total_pnl",          0.0),
        "max_drawdown":   paper.get("max_drawdown",       0.0),
        "best_strategy":  paper.get("best_strategy",      "N/A"),
        "grade":          paper.get("grade",              "N/A"),
        "execution_mode": "PAPER_TRADING",
        "advisory_only":  True,
    }


def _build_ai_section(ai: dict) -> dict:
    """Section 4 — AI Summary. Extracted from ai_performance snapshot."""
    return {
        "health_score":         ai.get("health_score",           0.0),
        "health_label":         ai.get("health_label",           "N/A"),
        "prediction_accuracy":  ai.get("prediction_accuracy",    0.0),
        "avg_confidence":       ai.get("avg_confidence",         0.0),
        "calibration_quality":  ai.get("calibration_quality_label", "N/A"),
        "trend_direction":      ai.get("trend_direction",        "Stable"),
        "accuracy_delta":       ai.get("accuracy_delta",         0.0),
        "total_signals":        ai.get("total_signals",          0),
        "f1_score":             ai.get("f1_score",               0.0),
        "precision":            ai.get("precision",              0.0),
        "recall":               ai.get("recall",                 0.0),
        "advisory_only":        True,
    }


def _build_risk_section(risk: dict) -> dict:
    """Section 5 — Risk Summary. Extracted from risk_validation snapshot."""
    domains = risk.get("domains", {}) or {}

    def _domain_score(key: str) -> float:
        d = domains.get(key, {})
        return float(d.get("score", 0.0)) if isinstance(d, dict) else 0.0

    return {
        "risk_score":    float(risk.get("risk_score", 0.0)),
        "grade":         risk.get("grade", "D"),
        "portfolio_heat":_domain_score("portfolio"),
        "tail_risk":     _domain_score("tail_risk"),
        "exposure":      _domain_score("sector"),
        "correlation":   _domain_score("correlation"),
        "concentration": _domain_score("portfolio"),
        "status":        risk.get("status", "UNKNOWN"),
        "advisory_only": True,
    }


def _build_system_health_section(
    obs: dict, ops: dict, dq: dict, sec: dict, perf: dict, deploy: dict
) -> dict:
    """Section 7 — System Health. Pure extraction from Phase 8 snapshots."""
    platform_score = _compute_platform_score(obs, ops, dq, sec, perf, deploy)

    modules = [
        {
            "id":     "observability",
            "label":  "Observability",
            "score":  float(obs.get("observability_score", 0.0)),
            "grade":  obs.get("grade", "D"),
            "available": obs.get("available", False),
        },
        {
            "id":     "operations",
            "label":  "Operations",
            "score":  float(ops.get("operations_score", 0.0)),
            "grade":  ops.get("grade", "D"),
            "available": ops.get("available", False),
        },
        {
            "id":     "data_quality",
            "label":  "Data Quality",
            "score":  float(dq.get("quality_score", 0.0)),
            "grade":  dq.get("grade", "D"),
            "available": dq.get("available", False),
        },
        {
            "id":     "security",
            "label":  "Security",
            "score":  float(sec.get("security_score", 0.0)),
            "grade":  sec.get("grade", "D"),
            "available": sec.get("available", False),
        },
        {
            "id":     "performance",
            "label":  "Performance",
            "score":  float(perf.get("performance_score", 0.0)),
            "grade":  perf.get("grade", "D"),
            "available": perf.get("available", False),
        },
        {
            "id":     "deployment",
            "label":  "Deployment & DR",
            "score":  float(deploy.get("dr_score", 0.0)),
            "grade":  deploy.get("grade", "D"),
            "available": deploy.get("available", False),
        },
    ]

    return {
        "platform_score":  platform_score,
        "platform_grade":  platform_grade(platform_score),
        "platform_status": platform_status(platform_score),
        "modules":         modules,
        "advisory_only":   True,
    }


def _build_watchlist_section(overview: dict) -> dict:
    """Section 8 — Watchlist. Extracted from market intelligence overview."""
    watchlist_data = overview.get("watchlist", {}) or {}
    items = watchlist_data.get("watchlist", []) if isinstance(watchlist_data, dict) else []
    top_opps = watchlist_data.get("top_opportunities", []) if isinstance(watchlist_data, dict) else []

    # Classify by regime-adjusted opportunity score
    high_conviction = [i for i in items if float(i.get("opportunity_score", 0)) >= 70][:5]
    breakouts       = [i for i in items if i.get("signal", "").upper() in ("BUY", "STRONG_BUY")][:5]
    momentum        = sorted(items, key=lambda x: float(x.get("composite_score", 0)), reverse=True)[:5]

    return {
        "top_ai_picks":     top_opps[:5],
        "high_conviction":  high_conviction,
        "breakouts":        breakouts,
        "momentum":         momentum,
        "total_symbols":    watchlist_data.get("total_symbols", 0) if isinstance(watchlist_data, dict) else 0,
        "advisory_only":    True,
    }


# ── Alerts aggregation ─────────────────────────────────────────────────────────

def get_alerts() -> dict:
    """Section 9 — Alert Centre. Aggregates from all notification sources."""
    if not is_enabled():
        return disabled_response()

    notifications = _load_notifications(50)
    risk_data     = _load_risk_snapshot()
    sec_data      = _load_security()
    ops_data      = _load_operations()

    alerts: list[dict] = []

    # Platform notifications
    for n in notifications:
        kind    = str(n.get("kind", "info")).upper()
        severity = SEV_CRITICAL if kind in ("CRITICAL", "ERROR", "KILL_SWITCH") else \
                   SEV_WARNING  if kind in ("WARNING", "WARN") else SEV_INFO
        alerts.append({
            "id":         str(n.get("id", "")),
            "severity":   severity,
            "category":   "Platform",
            "title":      str(n.get("title", "")),
            "body":       str(n.get("body", "")),
            "timestamp":  str(n.get("created_at", "")),
            "read":       bool(n.get("read", False)),
        })

    # Risk alerts — critical risk score
    risk_score = float(risk_data.get("risk_score", 0.0))
    if risk_score < 40:
        alerts.append({
            "id":        "risk_critical",
            "severity":  SEV_CRITICAL,
            "category":  "Risk",
            "title":     f"Risk score critical: {risk_score:.1f}/100",
            "body":      "Risk score is below 40. Review risk validation immediately.",
            "timestamp": _now_iso(),
            "read":      False,
        })
    elif risk_score < 60:
        alerts.append({
            "id":        "risk_warning",
            "severity":  SEV_WARNING,
            "category":  "Risk",
            "title":     f"Risk score degraded: {risk_score:.1f}/100",
            "body":      "Risk score is below 60. Review risk domains.",
            "timestamp": _now_iso(),
            "read":      False,
        })

    # Security alerts — missing critical secrets
    missing = int(sec_data.get("missing_secrets", 0))
    if missing > 0:
        alerts.append({
            "id":        "sec_missing_secrets",
            "severity":  SEV_CRITICAL,
            "category":  "Security",
            "title":     f"{missing} critical secret(s) missing",
            "body":      "Required secrets are not set. Platform security is at risk.",
            "timestamp": _now_iso(),
            "read":      False,
        })

    # Ops alerts — critical_alerts from operations snapshot
    ops_critical = int(ops_data.get("critical_alerts", 0))
    if ops_critical > 0:
        alerts.append({
            "id":        "ops_critical",
            "severity":  SEV_CRITICAL,
            "category":  "Operations",
            "title":     f"{ops_critical} critical operations alert(s)",
            "body":      "Visit Operations Centre for details.",
            "timestamp": _now_iso(),
            "read":      False,
        })

    # Sort: critical first, then warning, then info
    order = {SEV_CRITICAL: 0, SEV_WARNING: 1, SEV_INFO: 2}
    alerts.sort(key=lambda a: order.get(a["severity"], 9))

    return {
        "available":      True,
        "advisory_only":  True,
        "read_only":      True,
        "alert_count":    len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == SEV_CRITICAL),
        "warning_count":  sum(1 for a in alerts if a["severity"] == SEV_WARNING),
        "info_count":     sum(1 for a in alerts if a["severity"] == SEV_INFO),
        "alerts":         alerts,
        "generated_at":   _now_iso(),
    }


# ── Session Timeline ───────────────────────────────────────────────────────────

def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def get_timeline() -> dict:
    """Section 12 — Session Timeline. Derived from scan runs + notifications."""
    if not is_enabled():
        return disabled_response()

    scan_runs     = _load_scan_runs(20)
    notifications = _load_notifications(30)
    sched         = _load_scheduler_health()

    events: list[dict] = []

    # Scan run events
    for run in scan_runs:
        ts = _parse_ts(run.get("snapshot_ts") or run.get("started_at"))
        if ts:
            status  = run.get("status", "unknown")
            label   = "Market Scan Complete" if status == "completed" else f"Market Scan ({status})"
            events.append({
                "time":     ts.strftime("%H:%M"),
                "ts_iso":   ts.isoformat(),
                "event":    label,
                "category": "Scan",
                "status":   "success" if status == "completed" else "warning",
            })

    # Notification events
    for n in notifications:
        ts = _parse_ts(n.get("created_at"))
        if ts:
            kind   = str(n.get("kind", "info")).upper()
            status = "critical" if kind in ("CRITICAL", "ERROR") else \
                     "warning"  if kind in ("WARNING", "WARN") else "info"
            events.append({
                "time":     ts.strftime("%H:%M"),
                "ts_iso":   ts.isoformat(),
                "event":    str(n.get("title", "Platform event")),
                "category": "Platform",
                "status":   status,
            })

    # Scheduler state
    sched_status = sched.get("status", "UNKNOWN")
    events.append({
        "time":     _now_display()[:5],
        "ts_iso":   _now_iso(),
        "event":    f"Scheduler: {sched_status}",
        "category": "System",
        "status":   "success" if sched_status == "RUNNING" else "warning",
    })

    # Sort by timestamp descending (most recent first)
    def _sort_key(e: dict) -> str:
        return e.get("ts_iso", "")

    events.sort(key=_sort_key, reverse=True)

    return {
        "available":    True,
        "advisory_only": True,
        "read_only":    True,
        "event_count":  len(events),
        "events":       events[:30],
        "generated_at": _now_iso(),
    }


# ── AI Daily Briefing ──────────────────────────────────────────────────────────

def get_briefing() -> dict:
    """Section 10 — AI Daily Briefing. Natural language summary from aggregated snapshots."""
    if not is_enabled():
        return disabled_response()

    market   = _load_market_snapshot()
    paper    = _load_paper_analytics()
    ai       = _load_ai_snapshot()
    risk     = _load_risk_snapshot()
    obs      = _load_observability()
    overview = _load_market_overview()

    regime         = overview.get("regime", {}) or {}
    breadth        = overview.get("breadth", {}) or {}
    market_regime  = regime.get("regime",    "UNKNOWN")
    nifty_trend    = regime.get("nifty_trend", "SIDEWAYS")
    vix_status     = regime.get("vix_status", "UNKNOWN")
    advancing      = int(breadth.get("advancing", 0))
    declining      = int(breadth.get("declining", 0))
    sectors        = (overview.get("sectors", {}) or {})
    strongest      = sectors.get("strongest_sector", "N/A")
    weakest        = sectors.get("weakest_sector",   "N/A")

    win_rate       = float(paper.get("win_rate", 0.0))
    total_trades   = int(paper.get("total_trades", 0))
    total_pnl      = float(paper.get("total_pnl", 0.0))
    ai_health      = float(ai.get("health_score", 0.0))
    ai_confidence  = float(ai.get("avg_confidence", 0.0))
    risk_score     = float(risk.get("risk_score", 0.0))
    risk_grade     = risk.get("grade", "D")
    total_signals  = int(ai.get("total_signals", 0))
    platform_ok    = obs.get("available", False)

    # Market sentiment
    if market_regime in ("BULLISH", "STRONG_BULL"):
        sentiment = "strongly bullish"
    elif market_regime in ("MODERATELY_BULLISH", "TRENDING_BULL"):
        sentiment = "moderately bullish"
    elif market_regime in ("BEARISH", "STRONG_BEAR", "TRENDING_BEAR"):
        sentiment = "bearish"
    elif market_regime == "HIGH_VOLATILITY":
        sentiment = "highly volatile"
    else:
        sentiment = "sideways"

    # Construct briefing paragraphs
    market_para = (
        f"Market is {sentiment}. "
        + (f"{advancing} stocks advancing, {declining} declining. " if advancing + declining > 0 else "")
        + (f"{strongest} is the strongest sector. " if strongest != "N/A" else "")
        + (f"India VIX is {vix_status.lower()}. " if vix_status != "UNKNOWN" else "")
    ).strip()

    portfolio_para = (
        f"Portfolio has {total_trades} paper trade(s) recorded. "
        + (f"Win rate is {win_rate:.1f}%. " if win_rate > 0 else "")
        + (f"Total P&L: ₹{total_pnl:,.2f}. " if total_pnl != 0 else "")
    ).strip()

    ai_para = (
        f"AI health score is {ai_health:.1f}/100. "
        + (f"Average signal confidence is {ai_confidence:.1f}%. " if ai_confidence > 0 else "")
        + (f"{total_signals} signal(s) analysed this session. " if total_signals > 0 else "")
    ).strip()

    risk_para = (
        f"Risk level is {risk_grade}. "
        + (f"Risk score: {risk_score:.1f}/100. " if risk_score > 0 else "")
        + ("Risk is within acceptable bounds. " if risk_score >= 60 else "Risk requires attention. ")
    ).strip()

    platform_para = (
        "Platform is operational. " if platform_ok else "Platform observability is unavailable. "
    )

    lines = [l for l in [market_para, portfolio_para, ai_para, risk_para, platform_para] if l]

    return {
        "available":      True,
        "advisory_only":  True,
        "read_only":      True,
        "title":          "Today's Summary",
        "generated_at":   _now_iso(),
        "briefing_lines": lines,
        "briefing_text":  " ".join(lines),
        "market_regime":  market_regime,
        "market_sentiment": sentiment,
        "risk_grade":     risk_grade,
        "ai_health":      ai_health,
        "total_trades":   total_trades,
        "total_signals":  total_signals,
    }


# ── Main summary endpoint ──────────────────────────────────────────────────────

def get_summary() -> dict:
    """
    GET /api/command-center/summary
    Aggregates ALL module snapshots into one response.
    ZERO recalculation — snapshot data only.
    """
    if not is_enabled():
        return disabled_response()

    # Load all snapshots
    market_snap = _load_market_snapshot()
    overview    = _load_market_overview()
    paper       = _load_paper_analytics()
    executive   = _load_executive()
    ai          = _load_ai_snapshot()
    risk        = _load_risk_snapshot()
    dq          = _load_data_quality()
    obs         = _load_observability()
    ops         = _load_operations()
    sec         = _load_security()
    perf        = _load_performance()
    deploy      = _load_deployment()
    sched       = _load_scheduler_health()

    platform_score = _compute_platform_score(obs, ops, dq, sec, perf, deploy)

    return {
        "available":      True,
        "advisory_only":  True,
        "read_only":      True,
        "generated_at":   _now_iso(),
        "current_time":   _now_display(),
        "execution_mode": "PAPER_TRADING",
        "trading_session": "NSE_EQUITY",
        "platform_score": platform_score,
        "platform_grade": platform_grade(platform_score),
        "platform_status":platform_status(platform_score),
        "scheduler_status":sched.get("status", "UNKNOWN"),

        # Section 1 — Market Overview
        "market": _build_market_section(overview),

        # Section 2 — Portfolio Snapshot
        "portfolio": _build_portfolio_section(executive, paper),

        # Section 3 — Today's Trading
        "trading": _build_trading_section(paper),

        # Section 4 — AI Summary
        "ai": _build_ai_section(ai),

        # Section 5 — Risk Summary
        "risk": _build_risk_section(risk),

        # Section 6 — Market Intelligence top-level
        "market_intelligence": {
            "market_health_score": float(market_snap.get("market_health_score", 0.0)),
            "grade":               market_snap.get("grade", "D"),
            "trend":               market_snap.get("trend", "STABLE"),
            "overall_outlook":     market_snap.get("overall_outlook", ""),
            "top_opportunity":     market_snap.get("top_opportunity"),
        },

        # Section 7 — System Health
        "system_health": _build_system_health_section(obs, ops, dq, sec, perf, deploy),

        # Section 8 — Watchlist
        "watchlist": _build_watchlist_section(overview),

        # Section 11 — Quick Actions
        "quick_actions": QUICK_ACTIONS,
    }


# ── Snapshot (lightweight downstream interface) ────────────────────────────────

def get_command_center_snapshot() -> dict:
    """Stable downstream interface for future Phase 9.x consumers."""
    if not is_enabled():
        return {"available": False, "advisory_only": True, "read_only": True}

    obs    = _load_observability()
    ops    = _load_operations()
    dq     = _load_data_quality()
    sec    = _load_security()
    perf   = _load_performance()
    deploy = _load_deployment()

    platform_score = _compute_platform_score(obs, ops, dq, sec, perf, deploy)

    return {
        "available":       True,
        "advisory_only":   True,
        "read_only":       True,
        "platform_score":  platform_score,
        "platform_grade":  platform_grade(platform_score),
        "platform_status": platform_status(platform_score),
        "generated_at":    _now_iso(),
    }


# ── Export ─────────────────────────────────────────────────────────────────────

def export_json() -> dict:
    if not is_enabled():
        return disabled_response()
    summary  = get_summary()
    briefing = get_briefing()
    alerts   = get_alerts()
    timeline = get_timeline()
    return {
        "available":     True,
        "advisory_only": True,
        "read_only":     True,
        "export_format": "json",
        "generated_at":  _now_iso(),
        "summary":       summary,
        "briefing":      briefing,
        "alerts":        alerts,
        "timeline":      timeline,
    }


def export_csv() -> dict:
    if not is_enabled():
        return disabled_response()

    summary = get_summary()
    port    = summary.get("portfolio", {})
    trading = summary.get("trading",   {})
    ai      = summary.get("ai",        {})
    risk    = summary.get("risk",      {})
    sys     = summary.get("system_health", {})

    rows = [
        ["section", "metric", "value"],
        ["platform",   "platform_score",     summary.get("platform_score")],
        ["platform",   "platform_grade",     summary.get("platform_grade")],
        ["platform",   "platform_status",    summary.get("platform_status")],
        ["platform",   "execution_mode",     summary.get("execution_mode")],
        ["portfolio",  "portfolio_value",    port.get("portfolio_value")],
        ["portfolio",  "net_pnl",            port.get("net_pnl")],
        ["portfolio",  "win_rate",           port.get("win_rate")],
        ["portfolio",  "open_positions",     port.get("open_positions")],
        ["portfolio",  "total_trades",       port.get("total_trades")],
        ["portfolio",  "sharpe_ratio",       port.get("sharpe_ratio")],
        ["trading",    "win_rate",           trading.get("win_rate")],
        ["trading",    "profit_factor",      trading.get("profit_factor")],
        ["trading",    "expectancy",         trading.get("expectancy")],
        ["ai",         "health_score",       ai.get("health_score")],
        ["ai",         "prediction_accuracy",ai.get("prediction_accuracy")],
        ["ai",         "avg_confidence",     ai.get("avg_confidence")],
        ["ai",         "total_signals",      ai.get("total_signals")],
        ["risk",       "risk_score",         risk.get("risk_score")],
        ["risk",       "grade",              risk.get("grade")],
        ["system",     "platform_score",     sys.get("platform_score")],
    ]

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerows(rows)

    return {
        "available":     True,
        "advisory_only": True,
        "read_only":     True,
        "export_format": "csv",
        "generated_at":  _now_iso(),
        "csv":           buf.getvalue(),
        "row_count":     len(rows) - 1,
    }
