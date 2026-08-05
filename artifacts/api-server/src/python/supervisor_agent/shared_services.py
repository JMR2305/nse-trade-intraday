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


def get_framework_diagnostics() -> Dict[str, Any]:
    """
    Backend diagnostics for the Agent Framework.

    Explains the subprocess-per-request model (why AgentRegistry is always 0
    in a diagnostics call), reports active agent count from snapshot data,
    SnapshotBus stats, last snapshot timestamp, and feature-flag summary.

    Always returns available=True — the framework IS enabled; the registry
    being empty is expected behaviour, not a configuration error.
    """
    # ── In-process AgentRegistry (expected = 0 in subprocess model) ──────────
    registry_count = 0
    registry_error: Optional[str] = None
    try:
        from agent_framework.agent_registry import AgentRegistry
        registry_count = AgentRegistry.instance().count()
    except Exception as exc:
        registry_error = f"{type(exc).__name__}: {exc}"

    # ── SnapshotBus stats (also empty in subprocess model) ────────────────────
    bus_stats: Dict[str, Any] = {"topic_count": 0, "subscriber_count": 0, "topics": []}
    bus_error: Optional[str] = None
    try:
        from agent_framework.snapshot_bus import SnapshotBus
        bus_stats = SnapshotBus.instance().stats()
    except Exception as exc:
        bus_error = f"{type(exc).__name__}: {exc}"

    # ── Last snapshot + active-agent count from KV cache ─────────────────────
    last_snapshot_ts: Optional[str] = None
    last_health_pct: Optional[str] = None
    active_agents = 0
    scan_id: Optional[str] = None
    try:
        from phase20_store import kv_get as _kv_get
        last_snapshot_ts = _kv_get("ops_last_snapshot_ts") or _kv_get("ops_agents_ts")
        last_health_pct  = _kv_get("ops_last_health_pct")
        scan_id          = _kv_get("live_scan_id") or _kv_get("scan_id")
        active_str       = _kv_get("ops_active_agents")
        active_agents    = int(active_str) if active_str and str(active_str).isdigit() else 0
    except Exception:
        pass

    # ── Feature flags ─────────────────────────────────────────────────────────
    # Each flag maps 1:1 to the collector in get_ops_centre_agents() that it gates:
    #   AGENT_FRAMEWORK_ENABLED     — top-level gate (all collectors check this)
    #   SUPERVISOR_AGENT_ENABLED    — _collect_supervisor
    #   MARKET_DATA_AGENT_ENABLED   — _collect_market_data
    #   RESEARCH_AGENT_ENABLED      — _collect_research
    #   MARKET_INTELLIGENCE_AGENT_ENABLED — _collect_market_intelligence
    #   STOCK_MONITORING_AGENT_ENABLED    — _collect_monitoring
    #   STRATEGY_AGENT_ENABLED      — _collect_strategy
    #   RISK_AGENT_ENABLED          — _collect_risk
    #   AI_DECISION_AGENT_ENABLED   — _collect_ai_decision
    #   EXECUTION_AGENT_ENABLED     — _collect_execution
    #   LEARNING_AGENT_ENABLED      — _collect_learning
    #   KNOWLEDGE_AGENT_ENABLED     — _collect_knowledge
    #   AUTONOMOUS_OPS_ENABLED      — _collect_operations
    flag_names = [
        "AGENT_FRAMEWORK_ENABLED", "SUPERVISOR_AGENT_ENABLED",
        "MARKET_DATA_AGENT_ENABLED", "RESEARCH_AGENT_ENABLED",
        "MARKET_INTELLIGENCE_AGENT_ENABLED", "STOCK_MONITORING_AGENT_ENABLED",
        "STRATEGY_AGENT_ENABLED", "RISK_AGENT_ENABLED",
        "AI_DECISION_AGENT_ENABLED", "EXECUTION_AGENT_ENABLED",
        "LEARNING_AGENT_ENABLED", "KNOWLEDGE_AGENT_ENABLED",
        "AUTONOMOUS_OPS_ENABLED",
    ]
    import os as _os

    def _flag_on(name: str) -> bool:
        return _os.environ.get(name, "true").lower() in ("1", "true", "yes")

    framework_enabled = _flag_on("AGENT_FRAMEWORK_ENABLED")
    flags_enabled = sum(1 for fn in flag_names if _flag_on(fn))

    return {
        "available":         framework_enabled,
        "advisory_only":     True,
        "registry_model":    "subprocess-per-request",
        "registry_model_note": (
            "Each API call spawns a fresh Python subprocess. "
            "AgentRegistry is an in-process singleton that starts empty on every call. "
            "A count of 0 is expected — it is NOT a configuration error. "
            "Active agent count is derived from live snapshot data, not the registry."
        ),
        "registry_connected":    registry_error is None,
        "registry_count":        registry_count,   # always 0 in subprocess model
        "registry_error":        registry_error,
        "bus_connected":         bus_error is None,
        "bus_topics":            bus_stats.get("topics", []),
        "bus_topic_count":       bus_stats.get("topic_count", 0),
        "bus_subscriber_count":  bus_stats.get("subscriber_count", 0),
        "active_agents_from_snapshot": active_agents,
        "last_snapshot_ts":      last_snapshot_ts,
        "last_health_pct":       last_health_pct,
        "scan_id":               scan_id,
        "flags_enabled":         flags_enabled,
        "flags_total":           len(flag_names),
        "connected_pages": [
            "AI Paper Trader", "AI Operations Centre",
            "Agent Operations", "Command Centre",
        ],
    }


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
