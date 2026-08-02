"""
shared_services.py — Phase 10B
Read-only snapshot functions for the Stock Monitoring Agent.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

STOCK_MONITORING_AGENT_ENABLED = "STOCK_MONITORING_AGENT_ENABLED"

def _is_enabled() -> bool:
    import os
    return os.environ.get(STOCK_MONITORING_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")

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
        from stock_monitoring_agent.agent import StockMonitoringAgent
        _agent = StockMonitoringAgent()
        _agent.start()
        _agent.beat()
    return _agent

def get_stock_monitoring_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(STOCK_MONITORING_AGENT_ENABLED)
    def _f():
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("stock_monitoring")
        if env and env.payload:
            p = dict(env.payload)
            p["from_cache"] = True
            p["available"] = True
            return p
        agent = _get_agent()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "stock_monitoring")
        payload["available"] = True
        return payload
    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True, "error": "Stock monitoring snapshot unavailable"}
    return result

def get_monitoring_events() -> Dict[str, Any]:
    """Compute events fresh from current scan data.
    Does not rely on rolling in-process history (each request is a new subprocess)."""
    if not _is_enabled():
        return disabled_response(STOCK_MONITORING_AGENT_ENABLED)
    def _f():
        # Compute a fresh snapshot which includes events[] for the current cycle
        snap = get_stock_monitoring_snapshot()
        events = snap.get("events") or []
        return {
            "available":     True,
            "advisory_only": True,
            "events":        events[:100],
            "event_count":   len(events),
            "breakouts":     snap.get("breakouts", []),
            "breakdowns":    snap.get("breakdowns", []),
            "gap_events":    snap.get("gap_events", []),
            "volume_spikes": snap.get("volume_spikes", []),
            "event_breakdown": snap.get("event_breakdown", {}),
            "generated_at":  snap.get("generated_at", _now_iso()),
        }
    return _safe(_f) or {"available": False, "events": [], "event_count": 0}

def get_priority_queue() -> Dict[str, Any]:
    """Compute priority queue fresh from current portfolio + scan state.
    Does not rely on process-level agent singleton (each request is a new subprocess)."""
    if not _is_enabled():
        return disabled_response(STOCK_MONITORING_AGENT_ENABLED)
    def _f():
        snap = get_stock_monitoring_snapshot()
        return {
            "available":       True,
            "advisory_only":   True,
            "priority_queue":  snap.get("priority_queue", []),
            "priority_summary":snap.get("priority_summary", {}),
            "symbols_monitored": snap.get("symbols_monitored", 0),
            "generated_at":    snap.get("generated_at", _now_iso()),
        }
    return _safe(_f) or {"available": False}
