"""
agent.py — Phase 10E Collaboration Engine
Coordinates all agents through the Snapshot Bus and provides collaboration intelligence.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
All outputs require operator review before adoption.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from .collaboration_graph import build_collaboration_graph, build_dependency_report
from .decision_lineage import build_decision_lineage
from .collaboration_alerts import generate_collaboration_alerts as _gen_alerts

AGENT_ID   = "collaboration_engine"
AGENT_NAME = "Collaboration Engine"
VERSION    = "10E.1"

# Safety constants — hardcoded, never changed by environment
AUTONOMOUS_EXECUTION = False
AUTO_RECOVERY        = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_alerts(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate advisory collaboration alerts from graph analysis."""
    return _gen_alerts(graph)


def _compute_collab_health(graph: Dict[str, Any], alerts: List[Dict[str, Any]]) -> str:
    health_pct   = graph.get("graph_health_pct", 0.0)
    critical_cnt = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
    if critical_cnt > 2 or health_pct < 40:
        return "CRITICAL"
    if critical_cnt > 0 or health_pct < 70:
        return "DEGRADED"
    if health_pct >= 90:
        return "HEALTHY"
    return "WARNING"


class CollaborationEngine:
    """
    Stateless collaboration engine — instantiated per API call.
    Coordinates all agents through the Snapshot Bus.
    """

    def __init__(self) -> None:
        self._started_at = _now_iso()

    @property
    def agent_id(self) -> str:
        return AGENT_ID

    @property
    def version(self) -> str:
        return VERSION

    def execute(self) -> Dict[str, Any]:
        """
        Build a full collaboration snapshot.
        """
        t0 = time.perf_counter()

        graph   = build_collaboration_graph()
        lineage = build_decision_lineage()
        deps    = build_dependency_report()
        alerts  = _generate_alerts(graph)
        health  = _compute_collab_health(graph, alerts)

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        return {
            "agent_id":               AGENT_ID,
            "agent_name":             AGENT_NAME,
            "version":                VERSION,
            "advisory_only":          True,
            "read_only":              True,
            "autonomous_execution":   AUTONOMOUS_EXECUTION,
            "auto_recovery":          AUTO_RECOVERY,
            "available":              True,
            "collaboration_health":   health,
            "graph_health_pct":       graph.get("graph_health_pct", 0.0),
            "healthy_agents":         graph.get("healthy_agents", 0),
            "total_agents":           graph.get("total_agents", 0),
            "missing_dependencies":   deps.get("missing_dependencies", []),
            "stale_nodes":            deps.get("stale_nodes", []),
            "conflicting_outputs":    graph.get("conflicting_outputs", []),
            "alerts":                 alerts,
            "alert_count":            len(alerts),
            "critical_alerts":        sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
            "traceability_pct":       lineage.get("traceability_pct", 0.0),
            "snapshot_throughput":    self._estimate_throughput(graph),
            "collaboration_latency_ms": latency_ms,
            "started_at":             self._started_at,
            "generated_at":           _now_iso(),
        }

    def _estimate_throughput(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        healthy = graph.get("healthy_agents", 0)
        return {
            "snapshots_per_minute":   healthy * 2,
            "active_pipelines":       1 if healthy >= 5 else 0,
            "throughput_health":      "HEALTHY" if healthy >= 8 else "DEGRADED" if healthy >= 4 else "LOW",
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id":              AGENT_ID,
            "agent_name":            AGENT_NAME,
            "version":               VERSION,
            "advisory_only":         True,
            "read_only":             True,
            "autonomous_execution":  AUTONOMOUS_EXECUTION,
            "auto_recovery":         AUTO_RECOVERY,
            "available":             True,
            "started_at":            self._started_at,
            "generated_at":          _now_iso(),
        }
