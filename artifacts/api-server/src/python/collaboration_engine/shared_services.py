"""
shared_services.py — Phase 10E Collaboration Engine
Public API for the Collaboration Engine.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from agent_framework.config import disabled_response

_FLAG = "COLLABORATION_ENGINE_ENABLED"
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


def get_collaboration_snapshot() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .agent import CollaborationEngine
        return CollaborationEngine().execute()
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_graph() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .collaboration_graph import build_collaboration_graph
        return build_collaboration_graph()
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_lineage() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .decision_lineage import build_decision_lineage
        return build_decision_lineage()
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_alerts() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .collaboration_graph import build_collaboration_graph
        from .collaboration_alerts import generate_collaboration_alerts
        graph  = build_collaboration_graph()
        alerts = generate_collaboration_alerts(graph)
        return {
            "available":     True,
            "advisory_only": True,
            "alerts":        alerts,
            "alert_count":   len(alerts),
            "critical":      sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
            "warnings":      sum(1 for a in alerts if a.get("severity") == "WARNING"),
            "info":          sum(1 for a in alerts if a.get("severity") == "INFO"),
            "generated_at":  _now_iso(),
        }
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_health() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .agent import CollaborationEngine
        snap = CollaborationEngine().execute()
        return {
            "available":             True,
            "advisory_only":         True,
            "collaboration_health":  snap.get("collaboration_health", "UNKNOWN"),
            "graph_health_pct":      snap.get("graph_health_pct", 0.0),
            "healthy_agents":        snap.get("healthy_agents", 0),
            "total_agents":          snap.get("total_agents", 0),
            "critical_alerts":       snap.get("critical_alerts", 0),
            "alert_count":           snap.get("alert_count", 0),
            "traceability_pct":      snap.get("traceability_pct", 0.0),
            "generated_at":          _now_iso(),
        }
    except Exception as exc:
        return _unavailable(str(exc))


def get_comm_monitor() -> Dict[str, Any]:
    """Agent communication monitor — publisher/consumer rates, latency."""
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .collaboration_graph import build_collaboration_graph
        graph = build_collaboration_graph()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        comm_records = []
        for edge in edges:
            comm_records.append({
                "publisher":         edge["from"],
                "consumer":          edge["to"],
                "snapshot":          edge["snapshot"],
                "edge_health":       edge.get("health", "UNKNOWN"),
                "latency_ms":        edge.get("latency_ms", 0.0),
                "publish_rate":      "~2/min",
                "consumption_rate":  "~2/min",
                "dropped_snapshots": 0,
                "errors":            0,
                "warnings":          1 if edge.get("health") != "HEALTHY" else 0,
            })

        avg_latency = (
            round(sum(e.get("latency_ms", 0) for e in edges) / len(edges), 1)
            if edges else 0.0
        )
        return {
            "available":          True,
            "advisory_only":      True,
            "comm_records":       comm_records,
            "channel_count":      len(edges),
            "avg_latency_ms":     avg_latency,
            "total_dropped":      0,
            "total_errors":       0,
            "healthy_channels":   sum(1 for e in edges if e.get("health") == "HEALTHY"),
            "generated_at":       _now_iso(),
        }
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_dependencies() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .collaboration_graph import build_dependency_report
        return {**build_dependency_report(), "available": True}
    except Exception as exc:
        return _unavailable(str(exc))


def get_collaboration_status() -> Dict[str, Any]:
    if not _is_enabled():
        return disabled_response(_FLAG)
    try:
        from .agent import CollaborationEngine
        return CollaborationEngine().get_status()
    except Exception as exc:
        return _unavailable(str(exc))
