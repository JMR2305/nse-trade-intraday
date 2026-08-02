"""
shared_services.py — Phase 10A
Read-only snapshot functions for the Research Agent.

Stable API consumed by routes.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import (
    RESEARCH_AGENT_ENABLED, is_research_enabled, disabled_response
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── Agent singleton ────────────────────────────────────────────────────────────

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from research_agent.agent import ResearchAgent
        _agent = ResearchAgent()
        _agent.start()
        _agent.beat()
    return _agent


# ── Public API ─────────────────────────────────────────────────────────────────

def get_research_snapshot() -> Dict[str, Any]:
    """Collect, normalise, and return the current ResearchSnapshot."""
    if not is_research_enabled():
        return disabled_response(RESEARCH_AGENT_ENABLED)

    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()

        env = bus.latest("research")
        if env and env.payload:
            payload = dict(env.payload)
            payload["from_cache"] = True
            payload["cache_sequence"] = env.sequence
            return payload

        agent   = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "research")
        return payload

    result = _safe(_f)
    if result is None:
        return {
            "available":     False,
            "advisory_only": True,
            "error":         "Research snapshot unavailable",
        }
    result["available"] = True
    return result


def get_research_metrics() -> Dict[str, Any]:
    """Performance metrics for the Research Agent."""
    if not is_research_enabled():
        return disabled_response(RESEARCH_AGENT_ENABLED)

    def _f():
        from agent_framework.agent_registry import AgentRegistry
        from agent_framework.heartbeat_service import HeartbeatService

        record = AgentRegistry.instance().get("research-agent")
        if record is None:
            return {"available": False, "error": "Research Agent not registered"}

        hb_svc = HeartbeatService()
        hb_status, elapsed = hb_svc.check(
            record.agent_id, record.last_heartbeat, record.heartbeat_interval_s
        )

        return {
            "available":           True,
            "advisory_only":       True,
            "agent_id":            record.agent_id,
            "state":               record.state.value,
            "health_score":        round(record.health_score, 1),
            "queue_depth":         record.queue_depth,
            "processing_time_ms":  round(record.processing_time_ms, 1),
            "snapshots_published": record.snapshots_published,
            "heartbeat_status":    hb_status,
            "heartbeat_elapsed_s": round(elapsed, 1) if elapsed >= 0 else None,
            "last_heartbeat":      record.last_heartbeat,
            "generated_at":        _now_iso(),
        }

    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True}
    return result


def get_research_status() -> Dict[str, Any]:
    """Quick status check for the Research Agent."""
    if not is_research_enabled():
        return disabled_response(RESEARCH_AGENT_ENABLED)

    def _f():
        from agent_framework.agent_registry import AgentRegistry
        record = AgentRegistry.instance().get("research-agent")
        if record is None:
            return {"available": False, "status": "NOT_REGISTERED"}
        return {
            "available":     True,
            "advisory_only": True,
            "agent_id":      record.agent_id,
            "state":         record.state.value,
            "health_score":  round(record.health_score, 1),
            "last_heartbeat":record.last_heartbeat,
        }

    result = _safe(_f)
    return result or {"available": False}
