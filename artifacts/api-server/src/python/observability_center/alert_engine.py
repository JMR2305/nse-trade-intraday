"""
alert_engine.py — Phase 8.1
Alert generation from all observability sub-monitors.
Generates, deduplicates and categorises alerts. Never auto-remediates.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .models import (
    ObsAlert, SEV_CRITICAL, SEV_WARNING, SEV_INFO,
    CAT_SYSTEM, CAT_API, CAT_DATABASE, CAT_CACHE,
    CAT_JOB, CAT_ERROR, CAT_PERFORMANCE, CAT_AVAILABILITY,
    STATUS_HEALTHY, STATUS_DOWN,
)

# In-process alert dedup set (alert_id fingerprint → alert)
_active_alerts: dict[str, ObsAlert] = {}


def _fingerprint(category: str, title: str) -> str:
    return hashlib.sha1(f"{category}:{title}".encode()).hexdigest()[:12]


def _emit(severity: str, category: str, title: str, detail: str) -> ObsAlert:
    fp  = _fingerprint(category, title)
    aid = f"{category.lower()}_{fp}"
    alert = ObsAlert(
        alert_id   = aid,
        severity   = severity,
        category   = category,
        title      = title,
        detail     = detail,
    )
    _active_alerts[aid] = alert
    return alert


def _clear_if_healthy(category: str, title: str) -> None:
    fp  = _fingerprint(category, title)
    aid = f"{category.lower()}_{fp}"
    if aid in _active_alerts:
        _active_alerts[aid].resolved = True


def generate_alerts_from_system(system: dict) -> list[ObsAlert]:
    alerts = []
    mem = system.get("memory", {})
    if mem.get("usage_pct", 0) > 90:
        alerts.append(_emit(SEV_CRITICAL, CAT_SYSTEM,
            "Memory critical",
            f"Memory usage at {mem['usage_pct']}% — above 90% threshold."))
    elif mem.get("usage_pct", 0) > 80:
        alerts.append(_emit(SEV_WARNING, CAT_SYSTEM,
            "Memory high",
            f"Memory usage at {mem['usage_pct']}% — above 80% threshold."))
    else:
        _clear_if_healthy(CAT_SYSTEM, "Memory critical")
        _clear_if_healthy(CAT_SYSTEM, "Memory high")

    disk = system.get("disk", {})
    if disk.get("usage_pct", 0) > 90:
        alerts.append(_emit(SEV_CRITICAL, CAT_SYSTEM,
            "Disk critical",
            f"Disk usage at {disk['usage_pct']}% — above 90% threshold."))
    elif disk.get("usage_pct", 0) > 80:
        alerts.append(_emit(SEV_WARNING, CAT_SYSTEM,
            "Disk high",
            f"Disk usage at {disk['usage_pct']}% — above 80% threshold."))

    env = system.get("environment", {})
    if env.get("missing_critical"):
        alerts.append(_emit(SEV_CRITICAL, CAT_SYSTEM,
            "Missing critical environment variables",
            f"These env vars are not set: {env['missing_critical']}"))
    return alerts


def generate_alerts_from_db(db: dict) -> list[ObsAlert]:
    alerts = []
    if db.get("status") == STATUS_DOWN:
        alerts.append(_emit(SEV_CRITICAL, CAT_DATABASE,
            "Database connection failed",
            db.get("connection", {}).get("error", "Unknown error")))
    elif db.get("connection", {}).get("latency_ms", 0) > 500:
        alerts.append(_emit(SEV_WARNING, CAT_DATABASE,
            "Database latency elevated",
            f"Connection probe latency: {db['connection']['latency_ms']} ms"))
    return alerts


def generate_alerts_from_jobs(jobs: dict) -> list[ObsAlert]:
    alerts = []
    last_scan = jobs.get("last_scan", {})
    if last_scan.get("fresh") is False and last_scan.get("age_min") is not None:
        alerts.append(_emit(SEV_WARNING, CAT_JOB,
            "Scan data stale",
            f"Last scan was {last_scan['age_min']} min ago — may need a fresh scan."))
    return alerts


def generate_alerts_from_errors(err: dict) -> list[ObsAlert]:
    alerts = []
    if err.get("error_rate_per_h", 0) > 20:
        alerts.append(_emit(SEV_CRITICAL, CAT_ERROR,
            "High error rate",
            f"Error rate: {err['error_rate_per_h']}/h — investigate immediately."))
    elif err.get("error_rate_per_h", 0) > 5:
        alerts.append(_emit(SEV_WARNING, CAT_ERROR,
            "Elevated error rate",
            f"Error rate: {err['error_rate_per_h']}/h — monitor closely."))
    if err.get("total_errors", 0) > 50:
        alerts.append(_emit(SEV_WARNING, CAT_ERROR,
            "High accumulated error count",
            f"Error buffer contains {err['total_errors']} errors this session."))
    return alerts


def generate_alerts_from_cache(cache: dict) -> list[ObsAlert]:
    alerts = []
    if cache.get("stale_entries", 0) > 3:
        alerts.append(_emit(SEV_WARNING, CAT_CACHE,
            "Multiple stale cache entries",
            f"{cache['stale_entries']} cache entries exceed freshness threshold."))
    return alerts


def generate_alerts_from_performance(perf: dict) -> list[ObsAlert]:
    alerts = []
    score = perf.get("overall_score", 100)
    if score < 40:
        alerts.append(_emit(SEV_CRITICAL, CAT_PERFORMANCE,
            "Performance critically degraded",
            f"Overall performance score: {score}/100"))
    elif score < 65:
        alerts.append(_emit(SEV_WARNING, CAT_PERFORMANCE,
            "Performance below target",
            f"Overall performance score: {score}/100"))
    return alerts


def get_alert_summary(
    system: dict, db: dict, jobs: dict,
    errors: dict, cache: dict, performance: dict,
) -> dict:
    """Collect alerts from all sub-monitors and return the alert center state."""
    new_alerts: list[ObsAlert] = []
    new_alerts += generate_alerts_from_system(system)
    new_alerts += generate_alerts_from_db(db)
    new_alerts += generate_alerts_from_jobs(jobs)
    new_alerts += generate_alerts_from_errors(errors)
    new_alerts += generate_alerts_from_cache(cache)
    new_alerts += generate_alerts_from_performance(performance)

    all_alerts = [a for a in _active_alerts.values() if not a.resolved]
    critical = [a for a in all_alerts if a.severity == SEV_CRITICAL]
    warnings = [a for a in all_alerts if a.severity == SEV_WARNING]
    infos    = [a for a in all_alerts if a.severity == SEV_INFO]
    resolved = [a for a in _active_alerts.values() if a.resolved]

    return {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "total_active":    len(all_alerts),
        "critical_count":  len(critical),
        "warning_count":   len(warnings),
        "info_count":      len(infos),
        "resolved_count":  len(resolved),
        "critical_alerts": [a.to_dict() for a in critical],
        "warnings":        [a.to_dict() for a in warnings],
        "info":            [a.to_dict() for a in infos],
        "resolved":        [a.to_dict() for a in resolved[-10:]],
        "alert_history":   [a.to_dict() for a in list(_active_alerts.values())[-50:]],
        "note": "Alerts are advisory only — no auto-remediation.",
    }
