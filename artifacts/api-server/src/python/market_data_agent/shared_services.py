"""
shared_services.py — Phase 10A
Read-only snapshot functions for the Market Data Agent.

Stable API consumed by routes and Command Centre.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import (
    MARKET_DATA_AGENT_ENABLED, is_market_data_enabled, disabled_response
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
        from market_data_agent.agent import MarketDataAgent
        _agent = MarketDataAgent()
        _agent.start()
        _agent.beat()
    return _agent


# ── Public API ─────────────────────────────────────────────────────────────────

def get_market_data_snapshot() -> Dict[str, Any]:
    """Collect, normalise, and return the current MarketSnapshot."""
    if not is_market_data_enabled():
        return disabled_response(MARKET_DATA_AGENT_ENABLED)

    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()

        # Try cached snapshot from bus first
        env = bus.latest("market_data")
        if env and env.payload:
            payload = dict(env.payload)
            payload["from_cache"] = True
            payload["cache_sequence"] = env.sequence
            return payload

        # Execute fresh
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "market_data")
        return payload

    result = _safe(_f)
    if result is None:
        return {
            "available":     False,
            "advisory_only": True,
            "error":         "Market data snapshot unavailable",
        }
    result["available"] = True
    return result


def get_market_data_metrics() -> Dict[str, Any]:
    """Performance metrics for the Market Data Agent."""
    if not is_market_data_enabled():
        return disabled_response(MARKET_DATA_AGENT_ENABLED)

    def _f():
        from agent_framework.agent_registry import AgentRegistry
        from agent_framework.heartbeat_service import HeartbeatService
        from agent_framework.metrics import AgentMetrics

        registry = AgentRegistry.instance()
        record   = registry.get("market-data-agent")

        if record is None:
            return {"available": False, "error": "Market Data Agent not registered"}

        hb_svc  = HeartbeatService()
        hb_status, elapsed = hb_svc.check(
            record.agent_id, record.last_heartbeat, record.heartbeat_interval_s
        )

        return {
            "available":              True,
            "advisory_only":          True,
            "agent_id":               record.agent_id,
            "state":                  record.state.value,
            "health_score":           round(record.health_score, 1),
            "queue_depth":            record.queue_depth,
            "processing_time_ms":     round(record.processing_time_ms, 1),
            "snapshots_published":    record.snapshots_published,
            "heartbeat_status":       hb_status,
            "heartbeat_elapsed_s":    round(elapsed, 1) if elapsed >= 0 else None,
            "last_heartbeat":         record.last_heartbeat,
            "generated_at":           _now_iso(),
        }

    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True}
    return result


def get_market_data_status() -> Dict[str, Any]:
    """Quick status check for the Market Data Agent."""
    if not is_market_data_enabled():
        return disabled_response(MARKET_DATA_AGENT_ENABLED)

    def _f():
        from agent_framework.agent_registry import AgentRegistry
        record = AgentRegistry.instance().get("market-data-agent")
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
