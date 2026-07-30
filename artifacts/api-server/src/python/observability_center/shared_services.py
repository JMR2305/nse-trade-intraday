"""
shared_services.py — Phase 8.1
Stable public interface for the Production Monitoring & Observability Center.

All downstream phases should import from here — never from sub-modules.

READ-ONLY. ADVISORY-ONLY.
This module NEVER enables live trading, places orders, or modifies any
trading engine, portfolio, strategies, signals, AI models, or risk parameters.
"""
from __future__ import annotations
import os
from .models import is_enabled, disabled_response, obs_grade, trend_label


# ---------------------------------------------------------------------------
# Internal safe-loaders
# ---------------------------------------------------------------------------

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default if default is not None else {}


def _load_system():
    from .system_health import get_system_health
    return _safe(get_system_health, {"available": False, "health_score": 0.0,
                                     "overall_status": "UNKNOWN"})


def _load_api_metrics():
    from .api_metrics import get_api_metrics
    return _safe(get_api_metrics, {"available": False, "status": "UNKNOWN",
                                   "stats": {}})


def _load_db():
    from .db_metrics import get_db_metrics
    return _safe(get_db_metrics, {"available": False, "status": "UNKNOWN",
                                  "health_score": 0.0})


def _load_cache():
    from .cache_metrics import get_cache_metrics
    return _safe(get_cache_metrics, {"available": False, "status": "UNKNOWN",
                                     "total_entries": 0})


def _load_jobs():
    from .job_monitor import get_job_monitor
    return _safe(get_job_monitor, {"available": False,
                                   "scheduler_status": "UNKNOWN"})


def _load_errors():
    from .error_monitor import get_error_monitor
    return _safe(get_error_monitor, {"available": False, "total_errors": 0,
                                     "error_rate_per_h": 0.0})


def _load_performance():
    from .performance_dashboard import get_performance_dashboard
    return _safe(get_performance_dashboard, {"available": False,
                                             "overall_score": 50.0})


def _load_availability():
    from .availability import get_availability
    return _safe(get_availability, {"available": False,
                                    "overall_availability_pct": 0.0})


def _compute_obs_score(system, db, api, jobs, errors, performance, availability) -> float:
    """
    0–100 observability score:
    - System health      25 pts
    - DB health          20 pts
    - API health         20 pts
    - Job scheduler      15 pts
    - Error rate         10 pts
    - Availability       10 pts
    """
    sys_pts  = float(system.get("health_score",           50.0)) / 100 * 25
    db_pts   = float(db.get("health_score",               50.0)) / 100 * 20
    api_sc   = 100.0 if api.get("status") == "HEALTHY"    else 50.0
    api_pts  = api_sc / 100 * 20
    job_sc   = 100.0 if jobs.get("scheduler_status") == "HEALTHY" else (
               50.0  if jobs.get("scheduler_status") == "DEGRADED" else 25.0)
    job_pts  = job_sc / 100 * 15
    err_rate = float(errors.get("error_rate_per_h",        0.0))
    err_pts  = max(0.0, 10.0 - err_rate * 0.5)
    avail_pct = float(availability.get("overall_availability_pct", 50.0))
    avail_pts = avail_pct / 100 * 10
    return round(min(100.0, sys_pts + db_pts + api_pts + job_pts + err_pts + avail_pts), 1)


# ---------------------------------------------------------------------------
# GET /api/observability/summary
# ---------------------------------------------------------------------------

def get_summary() -> dict:
    """Unified Observability Center summary — score, grade, trend, highlights."""
    if not is_enabled():
        return disabled_response()
    try:
        from datetime import datetime, timezone
        system      = _load_system()
        api         = _load_api_metrics()
        db          = _load_db()
        cache       = _load_cache()
        jobs        = _load_jobs()
        errors      = _load_errors()
        performance = _load_performance()
        availability= _load_availability()

        score = _compute_obs_score(system, db, api, jobs, errors,
                                   performance, availability)
        grade = obs_grade(score)

        return {
            "status":             "ENABLED",
            "available":          True,
            "advisory_only":      True,
            "generated_at":       datetime.now(timezone.utc).isoformat(),
            "observability_score": score,
            "grade":              grade,
            "trend":              "STABLE",
            "system_status":      system.get("overall_status", "UNKNOWN"),
            "db_status":          db.get("status", "UNKNOWN"),
            "api_status":         api.get("status", "UNKNOWN"),
            "scheduler_status":   jobs.get("scheduler_status", "UNKNOWN"),
            "error_count_session": errors.get("total_errors", 0),
            "error_rate_per_h":   errors.get("error_rate_per_h", 0.0),
            "availability_pct":   availability.get("overall_availability_pct", 0.0),
            "performance_score":  performance.get("overall_score", 0.0),
            "cache_entries":      cache.get("total_entries", 0),
            "uptime_hours":       system.get("uptime_hours", 0.0),
        }
    except Exception as exc:
        import traceback
        return {"status": "ERROR", "error": str(exc),
                "trace":  traceback.format_exc(), "available": False}


# ---------------------------------------------------------------------------
# GET /api/observability/system
# ---------------------------------------------------------------------------

def get_system() -> dict:
    """Full system health — memory, CPU, disk, process, flags, environment."""
    if not is_enabled():
        return disabled_response()
    try:
        system = _load_system()
        db     = _load_db()
        cache  = _load_cache()
        jobs   = _load_jobs()
        return {
            **system,
            "status":   "ENABLED",
            "db":       db,
            "cache":    cache,
            "jobs":     jobs,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/observability/performance
# ---------------------------------------------------------------------------

def get_performance() -> dict:
    """Performance dashboard — module response times, score, slow endpoints."""
    if not is_enabled():
        return disabled_response()
    try:
        perf = _load_performance()
        api  = _load_api_metrics()
        return {
            **perf,
            "status":      "ENABLED",
            "api_metrics": api,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/observability/errors
# ---------------------------------------------------------------------------

def get_errors() -> dict:
    """Error monitoring — application errors, API errors, validation errors."""
    if not is_enabled():
        return disabled_response()
    try:
        errors = _load_errors()
        return {**errors, "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/observability/alerts
# ---------------------------------------------------------------------------

def get_alerts() -> dict:
    """Alert center — critical alerts, warnings, info, resolved, history."""
    if not is_enabled():
        return disabled_response()
    try:
        system  = _load_system()
        db      = _load_db()
        jobs    = _load_jobs()
        errors  = _load_errors()
        cache   = _load_cache()
        perf    = _load_performance()
        from .alert_engine import get_alert_summary
        alerts  = get_alert_summary(system, db, jobs, errors, cache, perf)
        return {**alerts, "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# GET /api/observability/audit
# ---------------------------------------------------------------------------

def get_audit() -> dict:
    """Audit dashboard — user actions, config changes, feature flags, timeline."""
    if not is_enabled():
        return disabled_response()
    try:
        from .audit_tracker import get_audit_timeline
        audit = get_audit_timeline()
        return {**audit, "status": "ENABLED"}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "available": False}


# ---------------------------------------------------------------------------
# Flat snapshot for Executive Dashboard / future phases
# ---------------------------------------------------------------------------

def get_observability_snapshot() -> dict:
    """
    Flat KPI dict for Executive Dashboard and Phase 8.2+ integration.
    Never raises — returns safe defaults on any error.
    """
    try:
        system      = _load_system()
        db          = _load_db()
        api         = _load_api_metrics()
        jobs        = _load_jobs()
        errors      = _load_errors()
        performance = _load_performance()
        availability= _load_availability()
        score = _compute_obs_score(system, db, api, jobs, errors,
                                   performance, availability)
        return {
            "observability_score":      score,
            "grade":                    obs_grade(score),
            "trend":                    "STABLE",
            "system_status":            system.get("overall_status", "UNKNOWN"),
            "db_status":                db.get("status", "UNKNOWN"),
            "scheduler_status":         jobs.get("scheduler_status", "UNKNOWN"),
            "error_rate_per_h":         errors.get("error_rate_per_h", 0.0),
            "availability_pct":         availability.get("overall_availability_pct", 0.0),
            "performance_score":        performance.get("overall_score", 50.0),
            "uptime_hours":             system.get("uptime_hours", 0.0),
            "available":                True,
        }
    except Exception:
        return {
            "observability_score": 0.0, "grade": "D", "trend": "STABLE",
            "system_status": "UNKNOWN", "db_status": "UNKNOWN",
            "scheduler_status": "UNKNOWN", "error_rate_per_h": 0.0,
            "availability_pct": 0.0, "performance_score": 50.0,
            "uptime_hours": 0.0, "available": False,
        }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_csv() -> str:
    if not is_enabled():
        return ""
    try:
        import csv, io
        summary = get_summary()
        output  = io.StringIO()
        fields  = ["observability_score", "grade", "trend", "system_status",
                   "db_status", "api_status", "scheduler_status",
                   "error_count_session", "error_rate_per_h",
                   "availability_pct", "performance_score", "uptime_hours"]
        writer  = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({k: summary.get(k, "") for k in fields})
        return output.getvalue()
    except Exception:
        return ""


def export_json() -> dict:
    if not is_enabled():
        return {"status": "DISABLED"}
    try:
        return {
            "summary":      get_summary(),
            "system":       _load_system(),
            "db":           _load_db(),
            "cache":        _load_cache(),
            "jobs":         _load_jobs(),
            "errors":       _load_errors(),
            "performance":  _load_performance(),
            "availability": _load_availability(),
            "advisory_only": True,
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}
