"""
shared_services.py — Phase 10E Collaboration Layer
Aggregates Collaboration Engine + Autonomous Ops into summary / timeline / performance.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn_path: str) -> Optional[Any]:
    try:
        parts = fn_path.rsplit(".", 1)
        mod   = __import__(parts[0], fromlist=[parts[1]])
        fn    = getattr(mod, parts[1])
        return fn()
    except Exception:
        return None


def _get_collab() -> Dict[str, Any]:
    result = _safe("collaboration_engine.shared_services.get_collaboration_snapshot")
    return result or {}


def _get_ops() -> Dict[str, Any]:
    result = _safe("autonomous_operations.shared_services.get_autonomous_ops_snapshot")
    return result or {}


def _get_health() -> Dict[str, Any]:
    result = _safe("autonomous_operations.shared_services.get_system_health")
    return result or {}


def get_collaboration_summary() -> Dict[str, Any]:
    """
    Summary card for Command Centre — Multi-Agent Operations.
    """
    collab  = _get_collab()
    ops     = _get_ops()
    health  = _get_health()

    return {
        "advisory_only":           True,
        "available":               collab.get("available", False) or ops.get("available", False),
        # Agent roster
        "registered_agents":       ops.get("registered_agents", 11),
        "healthy_agents":          ops.get("healthy_agents",    0),
        "warning_agents":          ops.get("warning_agents",    0),
        "failed_agents":           ops.get("failed_agents",     0),
        # Collaboration
        "collaboration_health":    collab.get("collaboration_health", "UNKNOWN"),
        "graph_health_pct":        collab.get("graph_health_pct", 0.0),
        "traceability_pct":        collab.get("traceability_pct", 0.0),
        "alert_count":             collab.get("alert_count", 0),
        "critical_alerts":         collab.get("critical_alerts", 0),
        # System health
        "overall_health":          health.get("overall_health",  "UNKNOWN"),
        "overall_health_score":    health.get("overall_score",   0.0),
        # Operations
        "snapshot_throughput":     ops.get("snapshot_throughput", 0),
        "avg_decision_latency_ms": ops.get("avg_decision_latency_ms", 0.0),
        "data_freshness_s":        ops.get("data_freshness_s",   0),
        "learning_queue":          ops.get("learning_queue",     0),
        "knowledge_queue":         ops.get("knowledge_queue",    0),
        # Top alerts
        "top_alerts":              collab.get("alerts", [])[:3],
        "generated_at":            _now_iso(),
    }


def get_collaboration_timeline() -> List[Dict[str, Any]]:
    """
    Phase-9-compatible timeline events from the Collaboration Engine.
    9 new event types.
    """
    events: List[Dict[str, Any]] = []
    ts = _now_iso()

    collab = _get_collab()
    ops    = _get_ops()
    health = _get_health()

    # 1 — Platform health score event
    score = health.get("overall_score", 0.0)
    events.append({
        "event_id":    "collab_platform_health_001",
        "event_type":  "PLATFORM_HEALTH_UPDATED",
        "title":       f"Platform Health: {score:.0f}%",
        "description": (
            f"System health score is {score:.0f}% "
            f"({health.get('overall_health', 'UNKNOWN')}). "
            "8-component score updated."
        ),
        "source":      "autonomous_ops_agent",
        "severity":    "INFO" if score >= 70 else "WARNING",
        "timestamp":   ts,
    })

    # 2 — Agent registered (one per registered agent slot as INFO)
    total    = ops.get("registered_agents", 11)
    healthy  = ops.get("healthy_agents", 0)
    events.append({
        "event_id":    "collab_agents_registered_001",
        "event_type":  "AGENT_REGISTERED",
        "title":       f"{total} agents registered",
        "description": (
            f"{healthy}/{total} agents healthy. "
            "Full 11-agent platform active."
        ),
        "source":      "collaboration_engine",
        "severity":    "INFO" if healthy >= total * 0.7 else "WARNING",
        "timestamp":   ts,
    })

    # 3 — Snapshot published events (one per available agent)
    graph_health = collab.get("graph_health_pct", 0.0)
    events.append({
        "event_id":    "collab_snapshot_published_001",
        "event_type":  "SNAPSHOT_PUBLISHED",
        "title":       f"Snapshot pipeline: {graph_health:.0f}% healthy",
        "description": (
            f"Collaboration graph health is {graph_health:.0f}%. "
            f"{collab.get('healthy_agents', 0)}/{collab.get('total_agents', 11)} agents publishing."
        ),
        "source":      "snapshot_bus",
        "severity":    "INFO" if graph_health >= 70 else "WARNING",
        "timestamp":   ts,
    })

    # 4 — Missing dependencies / snapshot delayed
    missing = collab.get("missing_dependencies", [])
    if missing:
        events.append({
            "event_id":    "collab_snapshot_delayed_001",
            "event_type":  "SNAPSHOT_DELAYED",
            "title":       f"{len(missing)} snapshot dependency gap(s)",
            "description": "; ".join(missing[:2]),
            "source":      "collaboration_engine",
            "severity":    "WARNING",
            "timestamp":   ts,
        })

    # 5 — Dependency warning
    stale = collab.get("stale_nodes", [])
    if stale:
        events.append({
            "event_id":    "collab_dep_warning_001",
            "event_type":  "DEPENDENCY_WARNING",
            "title":       f"{len(stale)} stale agent(s)",
            "description": f"Stale agents: {', '.join(stale[:4])}",
            "source":      "collaboration_engine",
            "severity":    "WARNING",
            "timestamp":   ts,
        })

    # 6 — Supervisor advisory
    events.append({
        "event_id":    "collab_supervisor_advisory_001",
        "event_type":  "SUPERVISOR_ADVISORY",
        "title":       "Supervisor extended analysis available",
        "description": (
            "Dependency validation, freshness check, capacity score, "
            "restart recommendations all updated."
        ),
        "source":      "supervisor_agent",
        "severity":    "INFO",
        "timestamp":   ts,
    })

    # 7 — Capacity warning if utilisation high
    scal = _safe("autonomous_operations.shared_services.get_scalability_dashboard") or {}
    util = scal.get("utilisation_pct", 0.0)
    if util > 70:
        events.append({
            "event_id":    "collab_capacity_warning_001",
            "event_type":  "CAPACITY_WARNING",
            "title":       f"Capacity utilisation at {util:.0f}%",
            "description": (
                f"Platform is at {util:.0f}% of safe symbol capacity. "
                "Consider reducing watchlist."
            ),
            "source":      "autonomous_ops_agent",
            "severity":    "WARNING",
            "timestamp":   ts,
        })

    # 8 — Learning completed (delegate to learning layer)
    learning_tl = _safe("learning_layer.shared_services.get_learning_timeline")
    if learning_tl and isinstance(learning_tl, list):
        for ev in learning_tl[:2]:
            if ev.get("event_type") in ("LEARNING_COMPLETED", "KNOWLEDGE_INDEXED"):
                events.append({**ev, "event_id": "collab_" + ev.get("event_id", "l001")})

    # 9 — Knowledge updated
    knowledge_snap = _safe("knowledge_agent.shared_services.get_knowledge_snapshot")
    if knowledge_snap and knowledge_snap.get("available"):
        kb_size = knowledge_snap.get("knowledge_base_size", 0)
        events.append({
            "event_id":    "collab_knowledge_updated_001",
            "event_type":  "KNOWLEDGE_UPDATED",
            "title":       f"Knowledge base: {kb_size} records",
            "description": (
                f"Knowledge Agent has indexed {kb_size} entries "
                f"across {knowledge_snap.get('trades_learned', 0)} trades."
            ),
            "source":      "knowledge_agent",
            "severity":    "INFO",
            "timestamp":   ts,
        })

    # Sort newest first (all same ts in stateless build, so keep insertion order)
    events.sort(key=lambda e: e.get("severity", "INFO"), reverse=False)
    return events


def get_collaboration_performance() -> Dict[str, Any]:
    """
    Performance metrics for the full collaboration platform.
    """
    collab = _get_collab()
    ops    = _get_ops()
    health = _get_health()
    scal   = _safe("autonomous_operations.shared_services.get_scalability_dashboard") or {}

    components = health.get("components", {})
    ph = components.get("performance_health", {})

    return {
        "advisory_only":                True,
        "available":                    True,
        "snapshot_latency_ms":          ops.get("avg_snapshot_latency_ms", 0.0),
        "end_to_end_decision_latency_ms": ops.get("avg_decision_latency_ms", 0.0),
        "agent_comm_latency_ms":        collab.get("collaboration_latency_ms", 0.0),
        "heartbeat_latency_ms":         ph.get("avg_latency_ms", 0.0),
        "supervisor_eval_latency_ms":   0.0,  # Stateless — not measurable without persistent state
        "snapshots_per_minute":         scal.get("snapshots_per_minute", 0),
        "recommendations_per_hour":     scal.get("recommendations_per_hour", 0),
        "graph_health_pct":             collab.get("graph_health_pct", 0.0),
        "overall_health_score":         health.get("overall_score", 0.0),
        "scalability": {
            "current_agents":            scal.get("current_agents", 11),
            "current_symbols":           scal.get("current_monitored_symbols", 0),
            "utilisation_pct":           scal.get("utilisation_pct", 0.0),
            "future_agents_supported":   scal.get("future_agents_supported", 0),
            "estimated_cpu_pct":         scal.get("estimated_cpu_pct", 0.0),
            "estimated_memory_mb":       scal.get("estimated_memory_mb", 0.0),
        },
        "generated_at":                 _now_iso(),
    }
