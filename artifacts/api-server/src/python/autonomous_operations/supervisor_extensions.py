"""
supervisor_extensions.py — Phase 10E
Extended Supervisor capabilities: dependency validation, freshness validation,
collaboration health, capacity score, restart/recovery/maintenance recommendations.

READ-ONLY · ADVISORY-ONLY
No automatic recovery. Recommendations only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn_path: str) -> Optional[Dict[str, Any]]:
    try:
        parts = fn_path.rsplit(".", 1)
        mod   = __import__(parts[0], fromlist=[parts[1]])
        fn    = getattr(mod, parts[1])
        return fn()
    except Exception:
        return None


def _validate_dependencies(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Check all agent dependency chains are intact."""
    missing = graph.get("missing_dependencies", [])
    stale   = graph.get("stale_nodes", [])
    chain_ok = len(missing) == 0

    return {
        "chain_intact":         chain_ok,
        "missing_dependencies": missing,
        "stale_nodes":          stale,
        "dependency_score":     round(max(0, 1.0 - len(missing) * 0.15) * 100, 1),
        "recommendation": (
            "All dependencies are satisfied — pipeline healthy."
            if chain_ok
            else f"Fix missing dependencies: {', '.join(missing[:3])}. "
                 "Ensure upstream agents complete before downstream polling."
        ),
    }


def _validate_snapshot_freshness(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that all agent snapshots are fresh."""
    nodes      = graph.get("nodes", [])
    stale      = [n["agent_id"] for n in nodes if not n.get("available")]
    fresh_cnt  = len(nodes) - len(stale)
    freshness_pct = round(fresh_cnt / len(nodes) * 100, 1) if nodes else 0.0

    return {
        "fresh_agents":    fresh_cnt,
        "stale_agents":    len(stale),
        "total_agents":    len(nodes),
        "freshness_pct":   freshness_pct,
        "stale_ids":       stale,
        "recommendation": (
            "All snapshots are fresh."
            if not stale
            else f"Snapshots stale for: {', '.join(stale[:3])}. "
                 "Run a fresh scan cycle or restart affected agents."
        ),
    }


def _collaboration_health_summary(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise collaboration health from graph metrics."""
    health_pct  = graph.get("graph_health_pct", 0.0)
    conflicts   = graph.get("conflicting_outputs", [])
    health_str  = (
        "HEALTHY"  if health_pct >= 80 else
        "DEGRADED" if health_pct >= 55 else
        "CRITICAL"
    )
    return {
        "collaboration_health":    health_str,
        "graph_health_pct":        health_pct,
        "conflicting_outputs":     conflicts,
        "conflict_count":          len(conflicts),
        "recommendation": (
            "Collaboration pipeline is healthy."
            if not conflicts
            else f"{len(conflicts)} data flow conflict(s) detected. "
                 "Review agents at break points."
        ),
    }


def _capacity_score(scalability: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate system capacity score."""
    util_pct   = scalability.get("utilisation_pct", 0.0)
    cap_score  = round(max(0, 100 - util_pct), 1)
    cap_health = (
        "HEALTHY"  if util_pct < 60 else
        "WARNING"  if util_pct < 80 else
        "CRITICAL"
    )
    return {
        "capacity_score":       cap_score,
        "utilisation_pct":      util_pct,
        "capacity_health":      cap_health,
        "safe_capacity":        scalability.get("safe_capacity_symbols", 0),
        "current_symbols":      scalability.get("current_monitored_symbols", 0),
        "remaining_capacity":   scalability.get("remaining_capacity", 0),
        "recommendation": (
            "System capacity is comfortable."
            if util_pct < 60
            else "System approaching capacity. "
                 "Consider reducing watchlist size or adding agent replicas."
        ),
    }


def _restart_recommendations(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate advisory agent restart recommendations. No automatic action."""
    recs: List[Dict[str, Any]] = []
    nodes = graph.get("nodes", [])
    for node in nodes:
        if not node.get("available"):
            recs.append({
                "agent_id":   node["agent_id"],
                "label":      node["label"],
                "reason":     f"Agent not responding (health: {node.get('health', 'UNKNOWN')})",
                "action":     "ADVISORY_RESTART",
                "priority":   "HIGH" if node["layer"] in ("DATA", "DECISION") else "MEDIUM",
                "note":       "Operator must manually restart. No automatic recovery.",
                "advisory_only": True,
            })
        elif node.get("health") in ("DEGRADED", "WARNING", "NEEDS_REVIEW"):
            recs.append({
                "agent_id":   node["agent_id"],
                "label":      node["label"],
                "reason":     f"Degraded health: {node.get('health')}",
                "action":     "ADVISORY_REVIEW",
                "priority":   "LOW",
                "note":       "Monitor closely. Restart only if health continues to degrade.",
                "advisory_only": True,
            })
    return recs


def _recovery_suggestions(graph: Dict[str, Any]) -> List[str]:
    """Advisory recovery suggestions for degraded state."""
    suggestions: List[str] = []
    health_pct  = graph.get("graph_health_pct", 100.0)
    stale       = graph.get("stale_nodes", [])

    if health_pct < 40:
        suggestions.append(
            "Platform health critical. Run a full scan cycle to refresh all snapshots."
        )
    if "market_data" in stale:
        suggestions.append(
            "Market Data Agent offline. Verify NSE/yfinance connectivity and API keys."
        )
    if "research" in stale:
        suggestions.append(
            "Research Agent offline. Check watchlist configuration and scan scheduler."
        )
    if "ai_decision" in stale:
        suggestions.append(
            "AI Decision Agent offline. Ensure upstream risk and strategy agents are healthy."
        )
    if not suggestions:
        suggestions.append("System is healthy. No recovery actions needed at this time.")
    return suggestions


def _maintenance_recommendations() -> List[str]:
    """Periodic maintenance recommendations. Advisory-only."""
    return [
        "Schedule a watchlist review every 30 days to remove delisted or illiquid symbols.",
        "Review AI Decision confidence calibration monthly using the Learning Agent analytics.",
        "Archive old paper trades quarterly to keep the portfolio store performant.",
        "Verify Kite OAuth token refresh schedule is active before each trading session.",
        "Review scan interval configuration if monitored symbols exceed 200.",
    ]


def build_supervisor_extended() -> Dict[str, Any]:
    """
    Full extended Supervisor snapshot with all recommendations.
    """
    graph_snap   = _safe("collaboration_engine.shared_services.get_collaboration_graph")
    scal_snap    = _safe("autonomous_operations.operations_engine.compute_scalability_dashboard")

    graph = graph_snap or {
        "nodes": [], "edges": [], "missing_dependencies": [],
        "stale_nodes": [], "conflicting_outputs": [], "graph_health_pct": 0.0,
        "healthy_agents": 0, "total_agents": 0,
    }
    scalability = scal_snap or {}

    dep_validation  = _validate_dependencies(graph)
    freshness_val   = _validate_snapshot_freshness(graph)
    collab_health   = _collaboration_health_summary(graph)
    capacity        = _capacity_score(scalability)
    restart_recs    = _restart_recommendations(graph)
    recovery_sugg   = _recovery_suggestions(graph)
    maintenance     = _maintenance_recommendations()

    return {
        "advisory_only":              True,
        "read_only":                  True,
        "auto_recovery":              False,
        "available":                  True,
        "dependency_validation":      dep_validation,
        "snapshot_freshness":         freshness_val,
        "collaboration_health":       collab_health,
        "capacity_score":             capacity,
        "restart_recommendations":    restart_recs,
        "recovery_suggestions":       recovery_sugg,
        "maintenance_recommendations": maintenance,
        "overall_status": (
            "HEALTHY"  if dep_validation["chain_intact"] and capacity["utilisation_pct"] < 80
            else "DEGRADED"
        ),
        "generated_at":               _now_iso(),
    }
