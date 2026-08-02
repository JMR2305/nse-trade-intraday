"""
shared_services.py — Phase 10B
Read-only snapshot functions for the Strategy Agent.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent_framework.config import disabled_response

STRATEGY_AGENT_ENABLED = "STRATEGY_AGENT_ENABLED"

def _is_enabled() -> bool:
    import os
    return os.environ.get(STRATEGY_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")

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
        from strategy_agent.agent import StrategyAgent
        _agent = StrategyAgent()
        _agent.start()
        _agent.beat()
    return _agent

def get_strategy_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(STRATEGY_AGENT_ENABLED)
    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("strategy")
        if env and env.payload:
            p = dict(env.payload)
            p["from_cache"] = True
            p["available"] = True
            return p
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "strategy")
        payload["available"] = True
        return payload
    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True, "error": "Strategy snapshot unavailable"}
    return result

def get_strategy_for_symbol(symbol: str) -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(STRATEGY_AGENT_ENABLED)
    def _f():
        agent = _get_agent()
        result = agent.evaluate_symbol(symbol)
        if result is None:
            return {"available": False, "error": f"No data for symbol: {symbol}"}
        result["available"] = True
        return result
    return _safe(_f) or {"available": False, "error": "Strategy evaluation unavailable"}
