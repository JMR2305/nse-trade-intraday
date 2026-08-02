"""
collaboration_graph.py — Phase 10E
Agent dependency graph, snapshot flow, conflict detection.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Canonical agent dependency chain ──────────────────────────────────────────

AGENT_CHAIN: List[Dict[str, Any]] = [
    {
        "agent_id":    "supervisor",
        "label":       "Supervisor Agent",
        "layer":       "ORCHESTRATION",
        "produces":    ["supervisor_snapshot"],
        "consumes":    [],
        "position":    0,
    },
    {
        "agent_id":    "market_data",
        "label":       "Market Data Agent",
        "layer":       "DATA",
        "produces":    ["market_data_snapshot"],
        "consumes":    ["supervisor_snapshot"],
        "position":    1,
    },
    {
        "agent_id":    "research",
        "label":       "Research Agent",
        "layer":       "DATA",
        "produces":    ["research_snapshot"],
        "consumes":    ["market_data_snapshot"],
        "position":    2,
    },
    {
        "agent_id":    "market_intelligence",
        "label":       "Market Intelligence Agent",
        "layer":       "ANALYSIS",
        "produces":    ["market_intelligence_snapshot"],
        "consumes":    ["research_snapshot"],
        "position":    3,
    },
    {
        "agent_id":    "stock_monitoring",
        "label":       "Stock Monitoring Agent",
        "layer":       "ANALYSIS",
        "produces":    ["stock_monitoring_snapshot"],
        "consumes":    ["market_intelligence_snapshot"],
        "position":    4,
    },
    {
        "agent_id":    "strategy",
        "label":       "Strategy Agent",
        "layer":       "ANALYSIS",
        "produces":    ["strategy_snapshot"],
        "consumes":    ["stock_monitoring_snapshot"],
        "position":    5,
    },
    {
        "agent_id":    "risk",
        "label":       "Risk Agent",
        "layer":       "ANALYSIS",
        "produces":    ["risk_snapshot"],
        "consumes":    ["strategy_snapshot"],
        "position":    6,
    },
    {
        "agent_id":    "ai_decision",
        "label":       "AI Decision Agent",
        "layer":       "DECISION",
        "produces":    ["ai_decision_snapshot"],
        "consumes":    ["risk_snapshot"],
        "position":    7,
    },
    {
        "agent_id":    "execution",
        "label":       "Execution Agent",
        "layer":       "DECISION",
        "produces":    ["execution_snapshot"],
        "consumes":    ["ai_decision_snapshot"],
        "position":    8,
    },
    {
        "agent_id":    "learning",
        "label":       "Learning Agent",
        "layer":       "LEARNING",
        "produces":    ["learning_snapshot"],
        "consumes":    ["execution_snapshot"],
        "position":    9,
    },
    {
        "agent_id":    "knowledge",
        "label":       "Knowledge Agent",
        "layer":       "LEARNING",
        "produces":    ["knowledge_snapshot"],
        "consumes":    ["learning_snapshot"],
        "position":    10,
    },
]

_STALE_THRESHOLD_S = 300.0   # 5 min — snapshot older than this is considered stale


def _probe_agent_health(agent_id: str) -> Dict[str, Any]:
    """
    Attempt to fetch live health for the given agent.
    Returns a dict with: health, latency_ms, available, last_snapshot_age_s
    """
    t0 = time.perf_counter()
    health    = "UNKNOWN"
    available = False
    last_age  = None
    try:
        if agent_id == "supervisor":
            from supervisor_agent.shared_services import get_supervisor_snapshot as _f
            snap = _f()
            health    = snap.get("supervisor_health", "UNKNOWN")
            available = snap.get("available", False)
        elif agent_id == "market_data":
            from market_data_agent.shared_services import get_market_data_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "research":
            from research_agent.shared_services import get_research_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "market_intelligence":
            from market_intelligence_agent.shared_services import get_market_intelligence_agent_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "stock_monitoring":
            from stock_monitoring_agent.shared_services import get_stock_monitoring_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "strategy":
            from strategy_agent.shared_services import get_strategy_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "risk":
            from risk_agent.shared_services import get_risk_snapshot as _f
            snap = _f()
            health    = snap.get("agent_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "ai_decision":
            from ai_decision_agent.shared_services import get_ai_decision_snapshot as _f
            snap = _f()
            health    = snap.get("decision_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "execution":
            from execution_agent.shared_services import get_execution_snapshot as _f
            snap = _f()
            health    = snap.get("execution_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "learning":
            from learning_agent.shared_services import get_learning_snapshot as _f
            snap = _f()
            health    = snap.get("learning_health", snap.get("status", "UNKNOWN"))
            available = snap.get("available", False)
        elif agent_id == "knowledge":
            from knowledge_agent.shared_services import get_knowledge_snapshot as _f
            snap = _f()
            health    = "HEALTHY" if snap.get("available") else "UNAVAILABLE"
            available = snap.get("available", False)
    except Exception:
        health    = "UNAVAILABLE"
        available = False

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "health":              health,
        "latency_ms":          latency_ms,
        "available":           available,
        "last_snapshot_age_s": last_age,
    }


def _health_to_score(health: str) -> float:
    mapping = {
        "HEALTHY":     1.0,
        "ACTIVE":      1.0,
        "DEGRADED":    0.6,
        "WARNING":     0.6,
        "NEEDS_REVIEW": 0.4,
        "ERROR":       0.2,
        "UNAVAILABLE": 0.3,
        "DISABLED":    0.5,
        "UNKNOWN":     0.3,
    }
    return mapping.get(health.upper() if health else "UNKNOWN", 0.3)


def build_collaboration_graph() -> Dict[str, Any]:
    """
    Build the full agent collaboration graph with live health data.
    Returns nodes, edges, graph-level health, and dependency analysis.
    """
    t0 = time.perf_counter()

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    missing_deps:  List[str] = []
    stale_nodes:   List[str] = []
    health_scores: List[float] = []

    probe_results: Dict[str, Dict[str, Any]] = {}
    for spec in AGENT_CHAIN:
        probe = _probe_agent_health(spec["agent_id"])
        probe_results[spec["agent_id"]] = probe

    for spec in AGENT_CHAIN:
        aid   = spec["agent_id"]
        probe = probe_results[aid]
        health_scores.append(_health_to_score(probe["health"]))

        node: Dict[str, Any] = {
            "agent_id":    aid,
            "label":       spec["label"],
            "layer":       spec["layer"],
            "position":    spec["position"],
            "produces":    spec["produces"],
            "consumes":    spec["consumes"],
            "health":      probe["health"],
            "latency_ms":  probe["latency_ms"],
            "available":   probe["available"],
        }
        nodes.append(node)

        # Stale detection: agent not available = effectively stale
        if not probe["available"]:
            stale_nodes.append(aid)

        # Build edges: from producer → consumer
        for dep_snap in spec["consumes"]:
            # Find which agent produces this snapshot
            producer = next(
                (s["agent_id"] for s in AGENT_CHAIN if dep_snap in s["produces"]),
                None,
            )
            if producer:
                prod_probe = probe_results[producer]
                edge_health = (
                    "HEALTHY" if prod_probe["available"] and probe["available"]
                    else "DEGRADED" if prod_probe["available"] or probe["available"]
                    else "DOWN"
                )
                edges.append({
                    "from":        producer,
                    "to":          aid,
                    "snapshot":    dep_snap,
                    "health":      edge_health,
                    "latency_ms":  round(prod_probe["latency_ms"] + probe["latency_ms"], 1),
                })
                if not prod_probe["available"]:
                    missing_deps.append(f"{aid} missing dependency: {dep_snap} from {producer}")

    avg_health = round(sum(health_scores) / len(health_scores) * 100, 1) if health_scores else 0.0

    # Detect conflicting outputs: if 2+ consecutive agents have contradictory health
    conflicts: List[str] = []
    for i in range(1, len(nodes)):
        if (nodes[i - 1]["available"] and not nodes[i]["available"]):
            conflicts.append(
                f"Data flow break: {nodes[i-1]['agent_id']} is healthy but "
                f"{nodes[i]['agent_id']} is unavailable."
            )

    build_latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "advisory_only":       True,
        "read_only":           True,
        "nodes":               nodes,
        "edges":               edges,
        "node_count":          len(nodes),
        "edge_count":          len(edges),
        "missing_dependencies": missing_deps,
        "stale_nodes":         stale_nodes,
        "conflicting_outputs": conflicts,
        "graph_health_pct":    avg_health,
        "healthy_agents":      sum(1 for n in nodes if n["available"]),
        "total_agents":        len(nodes),
        "build_latency_ms":    build_latency_ms,
        "generated_at":        _now_iso(),
    }


def build_dependency_report() -> Dict[str, Any]:
    """
    Returns a focused report on dependency health and chain integrity.
    """
    graph = build_collaboration_graph()
    chain_ok = len(graph["missing_dependencies"]) == 0
    return {
        "advisory_only":        True,
        "chain_intact":         chain_ok,
        "missing_dependencies": graph["missing_dependencies"],
        "stale_nodes":          graph["stale_nodes"],
        "conflicting_outputs":  graph["conflicting_outputs"],
        "dependency_health_pct": graph["graph_health_pct"],
        "total_agents":         graph["total_agents"],
        "healthy_agents":       graph["healthy_agents"],
        "generated_at":         _now_iso(),
    }
