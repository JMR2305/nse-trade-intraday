"""
shared_services.py — Phase 10A
Read-only snapshot functions for the Supervisor Agent.

All functions are advisory-only; none modify any state.
Stable API consumed by routes and Command Centre integration.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from agent_framework.config import (
    SUPERVISOR_AGENT_ENABLED, is_supervisor_enabled, disabled_response
)
from agent_framework.metrics import ScalabilityEstimator


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── Public API ─────────────────────────────────────────────────────────────────

def get_supervisor_snapshot() -> Dict[str, Any]:
    """Full supervisor snapshot — overall health, agent list, alerts, bus stats."""
    if not is_supervisor_enabled():
        return disabled_response(SUPERVISOR_AGENT_ENABLED)

    def _f():
        from supervisor_agent.supervisor import get_supervisor
        return get_supervisor().snapshot()

    result = _safe(_f)
    if result is None:
        return {
            "available":     False,
            "advisory_only": True,
            "error":         "Supervisor snapshot unavailable",
        }
    return result


def get_agent_list() -> Dict[str, Any]:
    """List of all registered agents with health and heartbeat status."""
    if not is_supervisor_enabled():
        return disabled_response(SUPERVISOR_AGENT_ENABLED)

    def _f():
        from supervisor_agent.supervisor import get_supervisor
        agents = get_supervisor().agent_list()
        return {
            "available":     True,
            "advisory_only": True,
            "agents":        agents,
            "count":         len(agents),
        }

    result = _safe(_f)
    if result is None:
        return {"available": False, "agents": [], "count": 0}
    return result


def get_agent_detail(agent_id: str) -> Dict[str, Any]:
    """Detailed record for a single agent."""
    if not is_supervisor_enabled():
        return disabled_response(SUPERVISOR_AGENT_ENABLED)

    def _f():
        from supervisor_agent.supervisor import get_supervisor
        detail = get_supervisor().agent_detail(agent_id)
        if detail is None:
            return {"available": False, "error": f"Agent '{agent_id}' not found"}
        detail["available"] = True
        detail["advisory_only"] = True
        return detail

    result = _safe(_f)
    if result is None:
        return {"available": False, "error": "Agent detail unavailable"}
    return result


def get_supervisor_alerts() -> Dict[str, Any]:
    """Advisory alerts from the supervisor — no auto-restart actions."""
    if not is_supervisor_enabled():
        return disabled_response(SUPERVISOR_AGENT_ENABLED)

    def _f():
        from supervisor_agent.supervisor import get_supervisor
        return get_supervisor().alerts()

    result = _safe(_f)
    if result is None:
        return {"available": False, "alerts": [], "alert_count": 0}
    return result


def get_scalability_estimate() -> Dict[str, Any]:
    """Advisory scalability and capacity estimate."""
    if not is_supervisor_enabled():
        return disabled_response(SUPERVISOR_AGENT_ENABLED)

    def _f():
        from agent_framework.agent_registry import AgentRegistry
        from agent_framework.metrics import ScalabilityEstimator
        from agent_framework.snapshot_bus import SnapshotBus

        records = AgentRegistry.instance().all()
        bus     = SnapshotBus.instance()
        md_env  = bus.latest("market_data")
        symbols = md_env.payload.get("symbols_count", 0) if md_env else 0
        return ScalabilityEstimator.estimate(records, current_symbols=symbols)

    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True}
    result["available"] = True
    result["advisory_only"] = True
    return result
