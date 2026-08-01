"""
shared_services.py — Phase 8.5
Operational Control Centre — aggregation layer.

READ-ONLY. ADVISORY-ONLY.
Reuses cached snapshots from upstream phases.
Never duplicates calculations.
Never modifies orders, portfolio, strategies, AI models, or configuration.

Downstream stable interface:
  get_operations_snapshot() -> dict   ← safe for any downstream phase
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Any

from operations_center.models import (
    is_enabled, disabled_response,
    ops_grade, trend_label,
    STATUS_OPERATIONAL, STATUS_DEGRADED, STATUS_DOWN, STATUS_UNKNOWN,
    SEV_CRITICAL, SEV_WARNING, SEV_INFO,
    OpsAlert, TimelineEvent, ChecklistItem,
    KNOWN_FLAGS, checklist_phase, _now_iso, _now_ist,
    CHECKLIST_MORNING, CHECKLIST_PREOPEN, CHECKLIST_MARKET_OPEN,
    CHECKLIST_MID_SESSION, CHECKLIST_CLOSING, CHECKLIST_EOD,
)

# ── Safe loader helper ─────────────────────────────────────────────────────────

def _safe(fn, default=None):
    """Call fn(); return default on any exception."""
    try:
        return fn()
    except Exception:
        return default


# ── Upstream snapshot loaders (lazy, safe) ─────────────────────────────────────

def _load_observability() -> dict:
    def _f():
        from observability_center.shared_services import get_observability_snapshot
        return get_observability_snapshot()
    return _safe(_f) or {"available": False, "observability_score": 0, "grade": "D", "system_status": "UNKNOWN"}


def _load_data_quality() -> dict:
    def _f():
        from data_quality.shared_services import get_data_quality_snapshot
        return get_data_quality_snapshot()
    return _safe(_f) or {"available": False, "quality_score": 0, "grade": "D", "critical_count": 0, "warning_count": 0}


def _load_risk_validation() -> dict:
    def _f():
        from risk_validation.shared_services import get_risk_validation_snapshot
        return get_risk_validation_snapshot()
    return _safe(_f) or {"available": False, "validation_score": 0, "grade": "D"}


def _load_market_intelligence() -> dict:
    def _f():
        from market_intelligence_hub.shared_services import get_market_intelligence_snapshot
        return get_market_intelligence_snapshot()
    return _safe(_f) or {"available": False, "regime": "UNKNOWN", "vix": None}


def _load_paper_analytics() -> dict:
    def _f():
        from paper_analytics.shared_services import get_paper_analytics_snapshot
        return get_paper_analytics_snapshot()
    return _safe(_f) or {"available": False}


def _load_portfolio() -> dict:
    def _f():
        from paper_trader import get_portfolio
        return get_portfolio()
    return _safe(_f) or {}


def _load_scheduler_health() -> dict:
    def _f():
        from phase20_store import get_scheduler_health
        return get_scheduler_health()
    return _safe(_f) or {"status": "UNKNOWN", "available": False}


def _load_recent_scan_runs(limit: int = 20) -> list:
    def _f():
        from phase20_store import list_scan_runs
        return list_scan_runs(limit=limit)
    return _safe(_f) or []


def _load_notifications(limit: int = 50) -> list:
    def _f():
        from phase20_store import list_notifications
        return list_notifications(limit=limit, unread_only=False)
    return _safe(_f) or []


def _load_observability_alerts() -> list:
    def _f():
        from observability_center.shared_services import get_alerts
        result = get_alerts()
        return result.get("alerts", []) if isinstance(result, dict) else []
    return _safe(_f) or []


def _load_data_quality_issues() -> list:
    def _f():
        from data_quality.shared_services import get_data_quality_snapshot
        snap = get_data_quality_snapshot()
        return snap.get("issues", []) if isinstance(snap, dict) else []
    return _safe(_f) or []


def _load_risk_alerts() -> list:
    def _f():
        from risk_validation.shared_services import get_risk_validation_snapshot
        snap = get_risk_validation_snapshot()
        return snap.get("alerts", []) if isinstance(snap, dict) else []
    return _safe(_f) or []


# ── Operations score ───────────────────────────────────────────────────────────

def _ops_score(obs: dict, dq: dict, rv: dict, sched: dict) -> float:
    """Weighted composite 0–100."""
    obs_score = float(obs.get("observability_score", 0) if obs.get("available") else 0)
    dq_score  = float(dq.get("quality_score", 0)       if dq.get("available")  else 0)
    rv_score  = float(rv.get("validation_score", 0)    if rv.get("available")  else 0)
    sched_ok  = sched.get("status") in ("HEALTHY", "OK", "RUNNING") if sched else False
    sched_score = 100.0 if sched_ok else 50.0

    score = (
        obs_score * 0.25 +
        dq_score  * 0.30 +
        rv_score  * 0.30 +
        sched_score * 0.15
    )
    return round(min(100.0, max(0.0, score)), 1)


# ── Overall platform status ────────────────────────────────────────────────────

def _platform_status(score: float, obs: dict, dq: dict) -> str:
    critical_dq = int(dq.get("critical_count", 0))
    obs_status = obs.get("system_status", "UNKNOWN")
    if score >= 80 and critical_dq == 0 and obs_status not in ("DOWN", "DEGRADED"):
        return STATUS_OPERATIONAL
    if score >= 50 or critical_dq <= 2:
        return STATUS_DEGRADED
    return STATUS_DOWN


# ── Market status ──────────────────────────────────────────────────────────────

def _market_status() -> dict:
    ist = _now_ist()
    h, m = ist.hour, ist.minute
    total_min = h * 60 + m
    weekday = ist.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        session = "WEEKEND_CLOSED"
        is_open = False
    elif total_min < 9 * 60:
        session = "PRE_MARKET"
        is_open = False
    elif total_min < 9 * 60 + 15:
        session = "PRE_OPEN_CALL_AUCTION"
        is_open = False
    elif total_min < 9 * 60 + 30:
        session = "PRICE_DISCOVERY"
        is_open = False
    elif total_min < 15 * 60 + 30:
        session = "NORMAL_SESSION"
        is_open = True
    elif total_min < 16 * 60:
        session = "CLOSING_SESSION"
        is_open = True
    else:
        session = "AFTER_HOURS"
        is_open = False

    mi = _load_market_intelligence()
    regime = mi.get("regime", "UNKNOWN") if mi.get("available") else "UNKNOWN"
    vix = mi.get("vix") or mi.get("india_vix")
    data_provider = mi.get("data_provider", "UNKNOWN") if mi.get("available") else "UNKNOWN"

    return {
        "market_open": is_open,
        "session":     session,
        "regime":      regime,
        "india_vix":   vix,
        "data_provider": data_provider,
        "ist_time":    ist.strftime("%H:%M:%S"),
        "weekday":     ist.strftime("%A"),
        "available":   True,
        "advisory_only": True,
    }


# ── Paper trading status ───────────────────────────────────────────────────────

def _paper_status() -> dict:
    portfolio = _load_portfolio()
    pa = _load_paper_analytics()

    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []
    open_positions = [p for p in positions if isinstance(p, dict) and float(p.get("quantity", 0)) > 0]
    cash = float(portfolio.get("cash", portfolio.get("available_cash", 0))) if isinstance(portfolio, dict) else 0.0
    capital = float(portfolio.get("total_value", portfolio.get("capital", 0))) if isinstance(portfolio, dict) else 0.0
    pnl = float(portfolio.get("total_pnl", portfolio.get("pnl", 0))) if isinstance(portfolio, dict) else 0.0

    # Today's trades from paper analytics snapshot
    todays_trades = 0
    if isinstance(pa, dict) and pa.get("available"):
        todays_trades = int(pa.get("trades_today", pa.get("today_trades", 0)))

    exposure = capital - cash if capital > 0 else 0.0

    return {
        "open_positions": len(open_positions),
        "todays_trades":  todays_trades,
        "cash":           round(cash, 2),
        "capital":        round(capital, 2),
        "exposure":       round(exposure, 2),
        "current_pnl":    round(pnl, 2),
        "available":      True,
        "advisory_only":  True,
    }


# ── Feature flags ──────────────────────────────────────────────────────────────

def _get_feature_flags() -> list[dict]:
    result = []
    for flag in KNOWN_FLAGS:
        val = os.environ.get(flag["name"], "").lower()
        enabled = val in ("1", "true", "yes")
        experimental = flag["category"] == "experimental"
        future = flag.get("future", False)
        result.append({
            "name":        flag["name"],
            "category":    flag["category"],
            "description": flag["description"],
            "enabled":     enabled,
            "experimental": experimental,
            "future":      future,
            "raw_value":   os.environ.get(flag["name"], "<not set>"),
        })
    return result


# ── Jobs status ────────────────────────────────────────────────────────────────

def _get_jobs() -> dict:
    sched = _load_scheduler_health()
    runs = _load_recent_scan_runs(limit=20)

    current_jobs = []
    failed_jobs = []
    recent_jobs = []

    for run in runs:
        if not isinstance(run, dict):
            continue
        status = run.get("status", "UNKNOWN")
        entry = {
            "job_id":     run.get("run_id", run.get("id", "?")),
            "type":       run.get("run_type", "SCAN"),
            "status":     status,
            "started_at": run.get("started_at", ""),
            "duration_s": run.get("duration_seconds", run.get("elapsed_s")),
        }
        if status in ("RUNNING", "IN_PROGRESS"):
            current_jobs.append(entry)
        elif status in ("FAILED", "ERROR"):
            failed_jobs.append(entry)
        else:
            recent_jobs.append(entry)

    ist = _now_ist()
    # Next scheduled scan: top of the next minute
    next_minute = ist.replace(second=0, microsecond=0) + timedelta(minutes=1)
    upcoming = [{"type": "MARKET_SCAN", "scheduled_at": next_minute.isoformat()}]

    return {
        "scheduler_status": sched.get("status", "UNKNOWN"),
        "scheduler_available": sched.get("available", False),
        "current_jobs":     current_jobs,
        "upcoming_jobs":    upcoming,
        "failed_jobs":      failed_jobs[-5:],
        "recent_jobs":      recent_jobs[:10],
        "available":        True,
        "advisory_only":    True,
    }


# ── Alert aggregation ──────────────────────────────────────────────────────────

def _aggregate_alerts() -> dict:
    all_alerts: list[dict] = []

    # From observability center
    for a in _load_observability_alerts():
        if isinstance(a, dict):
            all_alerts.append({**a, "source": "OBSERVABILITY"})

    # From data quality
    for issue in _load_data_quality_issues():
        if isinstance(issue, dict):
            severity = SEV_CRITICAL if issue.get("severity") == "CRITICAL" else SEV_WARNING
            all_alerts.append({
                "alert_id":    f"dq_{issue.get('check_id', issue.get('id', 'unknown'))}",
                "severity":    severity,
                "source":      "DATA_QUALITY",
                "title":       issue.get("title", issue.get("check_name", "Data Quality Issue")),
                "detail":      issue.get("detail", issue.get("message", "")),
                "generated_at": _now_iso(),
                "acknowledged": False,
                "resolved":    False,
            })

    # From risk validation
    for a in _load_risk_alerts():
        if isinstance(a, dict):
            all_alerts.append({**a, "source": a.get("source", "RISK_VALIDATION")})

    # Notifications from phase20 scheduler as INFO alerts
    notifs = _load_notifications(limit=10)
    for n in notifs:
        if isinstance(n, dict) and not n.get("read"):
            all_alerts.append({
                "alert_id":    f"notif_{n.get('id', 'unknown')}",
                "severity":    SEV_INFO,
                "source":      "SCHEDULER",
                "title":       n.get("title", n.get("kind", "Notification")),
                "detail":      n.get("message", n.get("body", "")),
                "generated_at": n.get("created_at", _now_iso()),
                "acknowledged": n.get("read", False),
                "resolved":    False,
            })

    critical = [a for a in all_alerts if a.get("severity") == SEV_CRITICAL and not a.get("resolved")]
    warnings  = [a for a in all_alerts if a.get("severity") == SEV_WARNING  and not a.get("resolved")]
    info      = [a for a in all_alerts if a.get("severity") == SEV_INFO     and not a.get("resolved")]
    resolved  = [a for a in all_alerts if a.get("resolved")]

    return {
        "total":      len(all_alerts),
        "critical":   critical,
        "warnings":   warnings,
        "info":       info,
        "resolved":   resolved[:10],
        "critical_count": len(critical),
        "warning_count":  len(warnings),
        "info_count":     len(info),
        "available":      True,
        "advisory_only":  True,
    }


# ── Daily checklist ────────────────────────────────────────────────────────────

_CHECKLISTS: dict[str, list[dict]] = {
    CHECKLIST_MORNING: [
        {"item_id": "m01", "title": "Platform health check",     "description": "Verify all services are operational before market open."},
        {"item_id": "m02", "title": "Database connectivity",     "description": "Confirm database connections are healthy."},
        {"item_id": "m03", "title": "Data provider availability","description": "Check live data feed and fallback providers are reachable."},
        {"item_id": "m04", "title": "Kite session status",       "description": "Verify Zerodha Kite session token is valid (if live mode)."},
        {"item_id": "m05", "title": "Scheduler running",         "description": "Confirm market scheduler is active and last run succeeded."},
        {"item_id": "m06", "title": "Paper portfolio state",     "description": "Review overnight paper positions and P&L."},
        {"item_id": "m07", "title": "Risk limits review",        "description": "Confirm risk parameters are within acceptable bounds."},
        {"item_id": "m08", "title": "Feature flags review",      "description": "Verify correct flags are enabled for today's session."},
    ],
    CHECKLIST_PREOPEN: [
        {"item_id": "p01", "title": "Pre-open data available",   "description": "IEP/IEQ data from NSE pre-open session is being collected."},
        {"item_id": "p02", "title": "AI signals ready",          "description": "Signal generation pipeline has completed the morning scan."},
        {"item_id": "p03", "title": "Risk validation score",     "description": "Risk validation score is above threshold before entering trades."},
        {"item_id": "p04", "title": "Data quality check",        "description": "No critical data quality issues are active."},
        {"item_id": "p05", "title": "Macro context loaded",      "description": "Macro intelligence snapshot is fresh (< 2 hours old)."},
        {"item_id": "p06", "title": "Regime determination",      "description": "Market regime has been determined for today's session."},
    ],
    CHECKLIST_MARKET_OPEN: [
        {"item_id": "mo01", "title": "Market open confirmed",    "description": "NSE normal session has commenced (09:15 IST)."},
        {"item_id": "mo02", "title": "Live signals flowing",     "description": "Signal pipeline is running and generating live signals."},
        {"item_id": "mo03", "title": "Auto-paper entries armed", "description": "Auto paper trading is in the expected state (ON/OFF per policy)."},
        {"item_id": "mo04", "title": "Observability monitoring", "description": "Observability center is capturing performance metrics."},
        {"item_id": "mo05", "title": "First scan completed",     "description": "First market scan run post-open has succeeded."},
    ],
    CHECKLIST_MID_SESSION: [
        {"item_id": "ms01", "title": "Position exposure check",  "description": "Review open position exposure vs. risk limits."},
        {"item_id": "ms02", "title": "P&L monitoring",           "description": "Current paper P&L within expected range."},
        {"item_id": "ms03", "title": "Data freshness",           "description": "Data quality score remains above warning threshold."},
        {"item_id": "ms04", "title": "Scheduler heartbeat",      "description": "Scheduler has run successfully in the last 5 minutes."},
        {"item_id": "ms05", "title": "Alert review",             "description": "No unacknowledged critical alerts in the system."},
        {"item_id": "ms06", "title": "Correlation risk",         "description": "Portfolio correlation metrics reviewed and acceptable."},
    ],
    CHECKLIST_CLOSING: [
        {"item_id": "c01", "title": "Closing session active",    "description": "NSE closing session is in progress (15:00–15:30 IST)."},
        {"item_id": "c02", "title": "Position review",           "description": "Review all open positions — decide whether to hold overnight."},
        {"item_id": "c03", "title": "EOD signal generation",     "description": "End-of-day signal pipeline has been triggered."},
        {"item_id": "c04", "title": "Risk score final check",    "description": "Risk validation score reviewed before session close."},
        {"item_id": "c05", "title": "Reconciliation triggered",  "description": "09:20 reconciliation run confirmed (or scheduled)."},
    ],
    CHECKLIST_EOD: [
        {"item_id": "e01", "title": "Session report generated",  "description": "Daily session report has been produced by the scheduler."},
        {"item_id": "e02", "title": "Trade history reviewed",    "description": "All today's paper trades have been reconciled and logged."},
        {"item_id": "e03", "title": "P&L recorded",             "description": "End-of-day P&L snapshot saved for performance tracking."},
        {"item_id": "e04", "title": "Data quality EOD check",   "description": "Final data quality assessment for the session."},
        {"item_id": "e05", "title": "Alerts cleared",           "description": "All critical alerts acknowledged or resolved."},
        {"item_id": "e06", "title": "Next-day preparation",     "description": "Any configuration changes needed for tomorrow flagged."},
        {"item_id": "e07", "title": "Observability summary",    "description": "Platform uptime and error-rate reviewed for the session."},
    ],
}


def _build_checklist(obs: dict, dq: dict, sched: dict) -> dict:
    phase = checklist_phase()
    raw_items = _CHECKLISTS.get(phase, [])
    items = []

    for raw in raw_items:
        item_id = raw["item_id"]
        # Determine status from live platform state
        status = "UNKNOWN"
        detail = ""

        if item_id in ("m01", "mo04") and obs.get("available"):
            sys_status = obs.get("system_status", "UNKNOWN")
            status = "OK" if sys_status in ("HEALTHY", "OK") else "WARNING"
            detail = f"System: {sys_status}"
        elif item_id == "m05" and sched.get("available"):
            sched_status = sched.get("status", "UNKNOWN")
            status = "OK" if sched_status in ("HEALTHY", "RUNNING", "OK") else "WARNING"
            detail = f"Scheduler: {sched_status}"
        elif item_id in ("p04", "ms03") and dq.get("available"):
            critical = int(dq.get("critical_count", 0))
            status = "OK" if critical == 0 else "WARNING"
            detail = f"{critical} critical issue(s)" if critical > 0 else "No critical issues"
        elif item_id == "ms04" and sched.get("available"):
            status = "OK" if sched.get("status") in ("HEALTHY", "RUNNING", "OK") else "WARNING"
        else:
            status = "UNKNOWN"
            detail = "Manual verification required"

        items.append({
            "item_id":     item_id,
            "title":       raw["title"],
            "description": raw["description"],
            "status":      status,
            "detail":      detail,
        })

    ok_count      = sum(1 for i in items if i["status"] == "OK")
    warning_count = sum(1 for i in items if i["status"] == "WARNING")
    unknown_count = sum(1 for i in items if i["status"] == "UNKNOWN")

    return {
        "phase":         phase,
        "items":         items,
        "ok_count":      ok_count,
        "warning_count": warning_count,
        "unknown_count": unknown_count,
        "total":         len(items),
        "completion_pct": round(ok_count / len(items) * 100) if items else 0,
        "available":     True,
        "advisory_only": True,
    }


# ── Operational timeline ───────────────────────────────────────────────────────

def _build_timeline() -> dict:
    events: list[dict] = []

    # From scheduler scan runs
    runs = _load_recent_scan_runs(limit=30)
    for run in runs:
        if not isinstance(run, dict):
            continue
        status = run.get("status", "UNKNOWN")
        severity = SEV_INFO if status in ("SUCCESS", "COMPLETED") else SEV_WARNING
        events.append({
            "event_id":  f"scan_{run.get('run_id', run.get('id', 'unknown'))}",
            "category":  "SCHEDULER",
            "title":     f"Market Scan — {status}",
            "detail":    f"Duration: {run.get('duration_seconds', '?')}s | Symbols: {run.get('symbols_scanned', '?')}",
            "timestamp": run.get("started_at", run.get("created_at", _now_iso())),
            "severity":  severity,
        })

    # From scheduler notifications
    notifs = _load_notifications(limit=20)
    for n in notifs:
        if not isinstance(n, dict):
            continue
        kind = n.get("kind", n.get("type", "NOTIFICATION"))
        events.append({
            "event_id":  f"notif_{n.get('id', 'unknown')}",
            "category":  "NOTIFICATION",
            "title":     n.get("title", kind),
            "detail":    n.get("message", n.get("body", "")),
            "timestamp": n.get("created_at", _now_iso()),
            "severity":  SEV_INFO,
        })

    # Platform startup marker (approximate — service start time)
    events.append({
        "event_id":  "startup",
        "category":  "PLATFORM",
        "title":     "Platform Operational Control Centre Loaded",
        "detail":    "Phase 8.5 Operational Control Centre aggregation active",
        "timestamp": _now_iso(),
        "severity":  SEV_INFO,
    })

    # Sort chronologically descending
    def _ts(e):
        try:
            return e.get("timestamp", "") or ""
        except Exception:
            return ""
    events.sort(key=_ts, reverse=True)

    return {
        "events":      events[:50],
        "total":       len(events),
        "available":   True,
        "advisory_only": True,
    }


# ── Primary public API ─────────────────────────────────────────────────────────

def get_summary() -> dict:
    """Operations overview — platform score, status, active modules."""
    if not is_enabled():
        return disabled_response()

    obs   = _load_observability()
    dq    = _load_data_quality()
    rv    = _load_risk_validation()
    sched = _load_scheduler_health()
    market = _market_status()

    score = _ops_score(obs, dq, rv, sched)
    grade = ops_grade(score)
    status = _platform_status(score, obs, dq)

    alerts = _aggregate_alerts()
    outstanding_alerts = alerts["critical_count"] + alerts["warning_count"]

    active_modules = []
    if obs.get("available"):  active_modules.append("OBSERVABILITY")
    if dq.get("available"):   active_modules.append("DATA_QUALITY")
    if rv.get("available"):   active_modules.append("RISK_VALIDATION")

    return {
        "operations_score":    score,
        "grade":               grade,
        "trend":               "STABLE",
        "platform_status":     status,
        "market_open":         market.get("market_open", False),
        "trading_session":     market.get("session", "UNKNOWN"),
        "system_health":       obs.get("system_status", "UNKNOWN"),
        "risk_level":          rv.get("grade", "UNKNOWN"),
        "data_quality_grade":  dq.get("grade", "UNKNOWN"),
        "outstanding_alerts":  outstanding_alerts,
        "active_modules":      active_modules,
        "observability_score": obs.get("observability_score", 0),
        "quality_score":       dq.get("quality_score", 0),
        "validation_score":    rv.get("validation_score", 0),
        "generated_at":        _now_iso(),
        "available":           True,
        "advisory_only":       True,
    }


def get_market() -> dict:
    if not is_enabled():
        return disabled_response()
    return _market_status()


def get_risk() -> dict:
    if not is_enabled():
        return disabled_response()
    rv = _load_risk_validation()
    if not rv.get("available"):
        return {"available": False, "advisory_only": True, "message": "Risk Validation module unavailable"}
    return {**rv, "advisory_only": True}


def get_paper_trading() -> dict:
    if not is_enabled():
        return disabled_response()
    return _paper_status()


def get_data_quality() -> dict:
    if not is_enabled():
        return disabled_response()
    dq = _load_data_quality()
    if not dq.get("available"):
        return {"available": False, "advisory_only": True, "message": "Data Quality module unavailable"}
    return {**dq, "advisory_only": True}


def get_observability() -> dict:
    if not is_enabled():
        return disabled_response()
    obs = _load_observability()
    if not obs.get("available"):
        return {"available": False, "advisory_only": True, "message": "Observability Center unavailable"}
    return {**obs, "advisory_only": True}


def get_feature_flags() -> dict:
    if not is_enabled():
        return disabled_response()
    flags = _get_feature_flags()
    enabled    = [f for f in flags if f["enabled"] and not f["experimental"]]
    disabled   = [f for f in flags if not f["enabled"] and not f["experimental"]]
    experimental = [f for f in flags if f["experimental"]]
    return {
        "flags":        flags,
        "enabled":      enabled,
        "disabled":     disabled,
        "experimental": experimental,
        "total":        len(flags),
        "available":    True,
        "advisory_only": True,
        "read_only":    True,
    }


def get_jobs() -> dict:
    if not is_enabled():
        return disabled_response()
    return _get_jobs()


def get_alerts() -> dict:
    if not is_enabled():
        return disabled_response()
    return _aggregate_alerts()


def get_checklist() -> dict:
    if not is_enabled():
        return disabled_response()
    obs   = _load_observability()
    dq    = _load_data_quality()
    sched = _load_scheduler_health()
    return _build_checklist(obs, dq, sched)


def get_timeline() -> dict:
    if not is_enabled():
        return disabled_response()
    return _build_timeline()


def get_operations_snapshot() -> dict:
    """
    Stable downstream interface for Phase 8.6, 8.7, 8.8, etc.
    Returns a lightweight aggregate safe for any downstream consumer.
    """
    if not is_enabled():
        return {"available": False, "advisory_only": True}

    obs   = _load_observability()
    dq    = _load_data_quality()
    rv    = _load_risk_validation()
    sched = _load_scheduler_health()

    score = _ops_score(obs, dq, rv, sched)
    return {
        "available":           True,
        "advisory_only":       True,
        "operations_score":    score,
        "grade":               ops_grade(score),
        "platform_status":     _platform_status(score, obs, dq),
        "observability_score": obs.get("observability_score", 0),
        "quality_score":       dq.get("quality_score", 0),
        "validation_score":    rv.get("validation_score", 0),
        "scheduler_status":    sched.get("status", "UNKNOWN"),
        "generated_at":        _now_iso(),
    }


def export_json() -> dict:
    return {
        "summary":       get_summary(),
        "market":        get_market(),
        "paper_trading": get_paper_trading(),
        "risk":          get_risk(),
        "data_quality":  get_data_quality(),
        "observability": get_observability(),
        "feature_flags": get_feature_flags(),
        "jobs":          get_jobs(),
        "alerts":        get_alerts(),
        "checklist":     get_checklist(),
        "timeline":      get_timeline(),
        "exported_at":   _now_iso(),
        "advisory_only": True,
    }


def export_csv() -> dict:
    """CSV of the operations summary scores."""
    summary = get_summary()
    rows = [
        "metric,value",
        f"operations_score,{summary.get('operations_score', 0)}",
        f"grade,{summary.get('grade', 'N/A')}",
        f"platform_status,{summary.get('platform_status', 'UNKNOWN')}",
        f"observability_score,{summary.get('observability_score', 0)}",
        f"quality_score,{summary.get('quality_score', 0)}",
        f"validation_score,{summary.get('validation_score', 0)}",
        f"outstanding_alerts,{summary.get('outstanding_alerts', 0)}",
        f"market_open,{summary.get('market_open', False)}",
        f"trading_session,{summary.get('trading_session', 'UNKNOWN')}",
        f"generated_at,{summary.get('generated_at', '')}",
    ]
    return {"csv": "\n".join(rows), "advisory_only": True}
