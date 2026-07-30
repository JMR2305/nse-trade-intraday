"""
availability.py — Phase 8.1
Service availability and uptime metrics.
Derives availability from system uptime and module snapshot freshness.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from .models import obs_grade, STATUS_HEALTHY, STATUS_DEGRADED, STATUS_DOWN

# Process start time (imported once)
import time
_process_start = time.time()


def _uptime_seconds() -> float:
    return round(time.time() - _process_start, 1)


def _module_availability() -> list[dict]:
    """Check each Phase 7 module's feature flag and basic reachability."""
    modules = [
        ("Market Intelligence Hub",  "MARKET_INTELLIGENCE_HUB_ENABLED",
         "market_intelligence_hub.shared_services", "get_market_intelligence_snapshot"),
        ("Event Intelligence",        "EVENT_INTELLIGENCE_ENABLED",
         "event_intelligence.shared_services",      "get_event_intelligence_snapshot"),
        ("Macro Intelligence",        "MACRO_INTELLIGENCE_ENABLED",
         "macro_intelligence.shared_services",      "get_macro_intelligence_snapshot"),
        ("Explainable AI",            "EXPLAINABLE_AI_ENABLED",
         "explainable_ai.shared_services",          "get_explainable_ai_snapshot"),
        ("Research Lab",              "RESEARCH_LAB_ENABLED",
         "research_lab.shared_services",            "get_research_lab_snapshot"),
        ("Observability Center",      "OBSERVABILITY_CENTER_ENABLED",
         None,                                       None),
    ]

    result = []
    for label, flag, module_path, fn_name in modules:
        flag_set = os.environ.get(flag, "false").lower() == "true"
        if not flag_set:
            result.append({
                "module":    label,
                "status":    "DISABLED",
                "available": False,
                "flag":      flag,
            })
            continue

        reachable = True
        if module_path and fn_name:
            try:
                import importlib, sys as _sys
                # Check module import + function presence WITHOUT calling the function.
                # Calling snapshot functions triggers yfinance/network I/O which is
                # too slow for an observability probe.  Advisory only.
                mod = _sys.modules.get(module_path)
                if mod is None:
                    mod = importlib.import_module(module_path)
                reachable = callable(getattr(mod, fn_name, None))
            except Exception:
                reachable = False

        result.append({
            "module":    label,
            "status":    STATUS_HEALTHY if reachable else STATUS_DEGRADED,
            "available": reachable,
            "flag":      flag,
        })

    return result


def get_availability() -> dict:
    """Calculate overall platform availability metrics."""
    uptime_s = _uptime_seconds()
    modules  = _module_availability()

    enabled   = [m for m in modules if m["status"] != "DISABLED"]
    available = [m for m in enabled if m["available"]]
    avail_pct = round(len(available) / len(enabled) * 100, 1) if enabled else 0.0

    # Availability score: uptime + module availability
    # Uptime contribution: capped at 50 pts for ≥ 1 hour uptime
    uptime_pts  = min(50.0, uptime_s / 3600 * 50)
    module_pts  = avail_pct / 2  # 0–50 pts
    avail_score = round(uptime_pts + module_pts, 1)

    overall = (STATUS_HEALTHY  if avail_pct >= 80 else
               STATUS_DEGRADED if avail_pct >= 50 else STATUS_DOWN)

    uptime_h = round(uptime_s / 3600, 2)
    uptime_d = round(uptime_s / 86400, 3)

    return {
        "available":         True,
        "advisory_only":     True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "status":            overall,
        "availability_score": avail_score,
        "grade":             obs_grade(avail_score),
        "overall_availability_pct": avail_pct,
        "module_availability": modules,
        "available_modules":  len(available),
        "total_enabled":      len(enabled),
        "uptime": {
            "seconds":  uptime_s,
            "hours":    uptime_h,
            "days":     uptime_d,
            "label":    f"{uptime_h:.1f} hours" if uptime_h < 24 else f"{uptime_d:.1f} days",
        },
        "incident_count":    0,   # no persistent incident log in current architecture
        "recovery_time_avg": None,
        "health_trend":      "STABLE",
    }
