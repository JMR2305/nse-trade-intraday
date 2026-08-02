"""
shared_services.py — Phase 10B
Read-only snapshot functions for the Risk Agent.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

RISK_AGENT_ENABLED = "RISK_AGENT_ENABLED"

def _is_enabled() -> bool:
    import os
    return os.environ.get(RISK_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default

_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        from risk_agent.agent import RiskAgent
        _agent = RiskAgent()
        _agent.start()
        _agent.beat()
    return _agent

def get_risk_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(RISK_AGENT_ENABLED)
    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("risk")
        if env and env.payload:
            p = dict(env.payload)
            p["from_cache"] = True
            p["available"] = True
            return p
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "risk")
        payload["available"] = True
        return payload
    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True, "error": "Risk snapshot unavailable"}
    return result

def get_risk_detail() -> Dict[str, Any]:
    """Same as get_risk_snapshot — returns the full computed breakdown.
    Computes fresh because each HTTP request is a new subprocess."""
    if not _is_enabled():
        return disabled_response(RISK_AGENT_ENABLED)
    return get_risk_snapshot()
