"""
shared_services.py — Phase 10B
Read-only snapshot functions for the Market Intelligence Agent.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

MARKET_INTELLIGENCE_AGENT_ENABLED = "MARKET_INTELLIGENCE_AGENT_ENABLED"

def _is_enabled() -> bool:
    import os
    return os.environ.get(MARKET_INTELLIGENCE_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")

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
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        _agent = MarketIntelligenceAgent()
        _agent.start()
        _agent.beat()
    return _agent

def get_market_intelligence_agent_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(MARKET_INTELLIGENCE_AGENT_ENABLED)
    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("market_intelligence")
        if env and env.payload:
            p = dict(env.payload)
            p["from_cache"] = True
            p["available"] = True
            return p
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "market_intelligence")
        payload["available"] = True
        return payload
    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True, "error": "Market intelligence snapshot unavailable"}
    return result

def get_market_intelligence_agent_status() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(MARKET_INTELLIGENCE_AGENT_ENABLED)
    def _f():
        from agent_framework.agent_registry import AgentRegistry
        from agent_framework.heartbeat_service import HeartbeatService
        reg = AgentRegistry.instance()
        rec = reg.get("market-intelligence-agent")
        if rec is None:
            return {"available": False, "status": "NOT_REGISTERED"}
        hb_svc = HeartbeatService()
        hb_status, elapsed = hb_svc.check(rec.agent_id, rec.last_heartbeat, rec.heartbeat_interval_s)
        return {
            "available":           True,
            "advisory_only":       True,
            "agent_id":            rec.agent_id,
            "state":               rec.state.value,
            "health_score":        round(rec.health_score, 1),
            "queue_depth":         rec.queue_depth,
            "processing_time_ms":  round(rec.processing_time_ms, 1),
            "snapshots_published": rec.snapshots_published,
            "heartbeat_status":    hb_status,
            "heartbeat_elapsed_s": round(elapsed, 1) if elapsed >= 0 else None,
            "generated_at":        _now_iso(),
        }
    return _safe(_f) or {"available": False}
