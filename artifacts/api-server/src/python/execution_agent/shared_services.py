"""
shared_services.py — Phase 10C
Read-only snapshot functions for the Execution Agent.
All functions compute fresh (stateless subprocess model).

Paper execution by default.
Live execution requires LIVE_EXECUTION_ENABLED=true (default false).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

EXECUTION_AGENT_ENABLED = "EXECUTION_AGENT_ENABLED"


def _is_enabled() -> bool:
    import os
    return os.environ.get(EXECUTION_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def get_execution_snapshot() -> Dict[str, Any]:
    """Full execution snapshot with queue, paper orders, and validation results."""
    if not _is_enabled():
        return disabled_response(EXECUTION_AGENT_ENABLED)

    def _f():
        from execution_agent.agent import ExecutionAgent
        agent = ExecutionAgent()
        agent.start()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "execution")
        payload["available"] = True
        return payload

    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True,
                "error": "Execution snapshot unavailable"}
    return result


def get_execution_queue() -> Dict[str, Any]:
    """Execution queue — plans ready for operator review."""
    if not _is_enabled():
        return disabled_response(EXECUTION_AGENT_ENABLED)

    snap = get_execution_snapshot()
    if not snap.get("available"):
        return snap
    return {
        "available":          True,
        "advisory_only":      True,
        "execution_mode":     snap.get("execution_mode", "PAPER"),
        "execution_queue":    snap.get("execution_queue", []),
        "execution_queue_size": snap.get("execution_queue_size", 0),
        "paper_orders":       snap.get("paper_orders", []),
        "paper_orders_count": snap.get("paper_orders_count", 0),
        "validation_failures":snap.get("validation_failures", []),
        "generated_at":       snap.get("generated_at", _now_iso()),
    }


def get_execution_plan_for_symbol(symbol: str) -> Dict[str, Any]:
    """Full execution plan for a specific symbol with checklist results."""
    if not _is_enabled():
        return disabled_response(EXECUTION_AGENT_ENABLED)

    def _f():
        from execution_agent.agent import ExecutionAgent
        agent = ExecutionAgent()
        agent.start()
        agent.beat()
        result = agent.get_plan_for_symbol(symbol)
        if result is None:
            return {"available": False, "error": f"No execution plan for: {symbol}"}
        return result

    return _safe(_f) or {"available": False, "error": "Plan unavailable"}


def get_execution_status() -> Dict[str, Any]:
    """Execution agent operational status."""
    if not _is_enabled():
        return disabled_response(EXECUTION_AGENT_ENABLED)

    snap = _safe(get_execution_snapshot) or {}
    available = bool(snap.get("available"))
    return {
        "available":             available,
        "advisory_only":         True,
        "agent_id":              "execution-agent",
        "state":                 "ACTIVE" if available else "UNKNOWN",
        "execution_mode":        snap.get("execution_mode", "PAPER"),
        "live_execution_enabled":snap.get("live_execution_enabled", False),
        "execution_queue_size":  snap.get("execution_queue_size", 0),
        "paper_orders_count":    snap.get("paper_orders_count", 0),
        "planning_latency_ms":   snap.get("planning_latency_ms", 0.0),
        "never_autonomous_live": True,
        "generated_at":          snap.get("generated_at", _now_iso()),
    }
