"""
shared_services.py — Phase 10E Autonomous Operations
Public API for the Autonomous Operations Engine.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

_FLAG = "AUTONOMOUS_OPERATIONS_ENABLED"
_TRUE = ("1", "true", "yes")


def _is_enabled() -> bool:
    return os.environ.get(_FLAG, "true").lower() in _TRUE


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available":     False,
        "advisory_only": True,
        "read_only":     True,
        "status":        "UNAVAILABLE",
        "reason":        reason,
        "generated_at":  _now_iso(),
    }


def get_autonomous_ops_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .agent import AutonomousOpsAgent
        return AutonomousOpsAgent().execute()
    except Exception as exc:
        return _unavailable(str(exc))


def get_system_health() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .operations_engine import compute_system_health
        return compute_system_health()
    except Exception as exc:
        return _unavailable(str(exc))


def get_scalability_dashboard() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .operations_engine import compute_scalability_dashboard
        return compute_scalability_dashboard()
    except Exception as exc:
        return _unavailable(str(exc))


def get_supervisor_extended() -> Dict[str, Any]:
    flag = "SUPERVISOR_EXTENDED_ENABLED"
    if not os.environ.get(flag, "true").lower() in _TRUE:
        return disabled_response(flag)
    try:
        from .supervisor_extensions import build_supervisor_extended
        return build_supervisor_extended()
    except Exception as exc:
        return _unavailable(str(exc))


def get_capacity_forecast() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .operations_engine import compute_scalability_dashboard
        scal = compute_scalability_dashboard()
        # Advisory capacity forecast
        current   = scal.get("current_monitored_symbols", 0)
        remaining = scal.get("remaining_capacity", 0)
        est_cpu   = scal.get("estimated_cpu_pct", 0.0)
        est_mem   = scal.get("estimated_memory_mb", 0.0)
        return {
            "advisory_only":           True,
            "available":               True,
            "current_symbols":         current,
            "remaining_capacity":      remaining,
            "estimated_cpu_pct":       est_cpu,
            "estimated_memory_mb":     est_mem,
            "cpu_headroom_pct":        round(max(0, 100 - est_cpu), 1),
            "memory_headroom_mb":      round(max(0, 2048 - est_mem), 1),
            "forecast_30d":            f"At current growth rate, capacity will be ~{min(100, current + 20)} symbols in 30 days.",
            "forecast_90d":            f"Platform estimated at ~{min(200, current + 50)} symbols within 90 days.",
            "scaling_recommendation":  scal.get("scaling_estimate", "No forecast available."),
            "generated_at":            _now_iso(),
        }
    except Exception as exc:
        return _unavailable(str(exc))


def get_autonomous_ops_status() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .agent import AutonomousOpsAgent
        return AutonomousOpsAgent().get_status()
    except Exception as exc:
        return _unavailable(str(exc))
