"""
collaboration_alerts.py — Phase 10E
Advisory alert generation for agent collaboration issues.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ALERT_ID_COUNTER = 0


def _make_alert(
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    source: str,
    recommendation: str,
) -> Dict[str, Any]:
    global _ALERT_ID_COUNTER
    _ALERT_ID_COUNTER += 1
    return {
        "alert_id":       f"collab_{alert_type.lower()}_{_ALERT_ID_COUNTER:04d}",
        "alert_type":     alert_type,
        "severity":       severity,   # CRITICAL / WARNING / INFO
        "title":          title,
        "description":    description,
        "source":         source,
        "recommendation": recommendation,
        "advisory_only":  True,
        "generated_at":   _now_iso(),
    }


def generate_collaboration_alerts(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate advisory alerts from graph analysis.
    Returns a list of alert dicts, ordered by severity.
    """
    alerts: List[Dict[str, Any]] = []
    nodes  = graph.get("nodes", [])
    edges  = graph.get("edges", [])

    # 1 — MISSING SNAPSHOT: agent not available
    for node in nodes:
        if not node.get("available") and node["agent_id"] != "supervisor":
            alerts.append(_make_alert(
                alert_type     = "MISSING_SNAPSHOT",
                severity       = "CRITICAL",
                title          = f"Missing snapshot: {node['label']}",
                description    = (
                    f"Agent '{node['agent_id']}' has not produced a snapshot. "
                    "Downstream agents may receive stale or missing data."
                ),
                source         = node["agent_id"],
                recommendation = (
                    f"Verify {node['label']} is running. "
                    "Check upstream dependencies and API server logs."
                ),
            ))

    # 2 — AGENT OFFLINE: marked unavailable
    offline = [n for n in nodes if not n.get("available")]
    if len(offline) > 3:
        alerts.append(_make_alert(
            alert_type     = "AGENT_OFFLINE",
            severity       = "CRITICAL",
            title          = f"{len(offline)} agents offline",
            description    = (
                f"Multiple agents are unavailable: "
                f"{', '.join(n['agent_id'] for n in offline[:5])}. "
                "Platform collaboration is severely degraded."
            ),
            source         = "collaboration_engine",
            recommendation = (
                "Review API server and Python backend logs. "
                "Ensure all agent shared_services modules are importable."
            ),
        ))

    # 3 — HEARTBEAT MISSED: agent health is ERROR or UNAVAILABLE
    for node in nodes:
        if node.get("health") in ("ERROR", "UNAVAILABLE") and node.get("available"):
            alerts.append(_make_alert(
                alert_type     = "HEARTBEAT_MISSED",
                severity       = "WARNING",
                title          = f"Heartbeat anomaly: {node['label']}",
                description    = (
                    f"Agent '{node['agent_id']}' health is {node['health']} despite responding. "
                    "Heartbeat may be degraded."
                ),
                source         = node["agent_id"],
                recommendation = (
                    "Review agent internal diagnostics. "
                    "Consider supervisor advisory restart."
                ),
            ))

    # 4 — QUEUE OVERLOAD: estimate from total agents with latency > 500ms
    slow_agents = [n for n in nodes if n.get("latency_ms", 0) > 500]
    if slow_agents:
        alerts.append(_make_alert(
            alert_type     = "QUEUE_OVERLOAD",
            severity       = "WARNING",
            title          = f"High latency on {len(slow_agents)} agent(s)",
            description    = (
                f"Agents with latency > 500ms: "
                f"{', '.join(n['agent_id'] for n in slow_agents[:3])}. "
                "Queue may be backing up."
            ),
            source         = "collaboration_engine",
            recommendation = (
                "Review snapshot publish/consume latencies. "
                "Consider staggering agent polling intervals."
            ),
        ))

    # 5 — SLOW CONSUMER: edges with latency > 1000ms
    slow_edges = [e for e in edges if e.get("latency_ms", 0) > 1000]
    for edge in slow_edges[:2]:
        alerts.append(_make_alert(
            alert_type     = "SLOW_CONSUMER",
            severity       = "WARNING",
            title          = f"Slow snapshot flow: {edge['from']} → {edge['to']}",
            description    = (
                f"Snapshot '{edge['snapshot']}' delivery latency is "
                f"{edge['latency_ms']:.0f}ms — above 1000ms threshold."
            ),
            source         = f"{edge['from']}→{edge['to']}",
            recommendation = "Investigate network latency or processing backlog.",
        ))

    # 6 — STALE RESEARCH: research agent unavailable
    research_node = next((n for n in nodes if n["agent_id"] == "research"), None)
    if research_node and not research_node.get("available"):
        alerts.append(_make_alert(
            alert_type     = "STALE_RESEARCH",
            severity       = "WARNING",
            title          = "Research snapshot stale",
            description    = (
                "Research Agent is not providing fresh data. "
                "Market Intelligence and downstream agents may use outdated research."
            ),
            source         = "research",
            recommendation = (
                "Verify Research Agent data sources are accessible. "
                "Check watchlist and scan configuration."
            ),
        ))

    # 7 — DATA FRESHNESS: overall graph health < 60%
    if graph.get("graph_health_pct", 100) < 60:
        alerts.append(_make_alert(
            alert_type     = "DATA_FRESHNESS",
            severity       = "WARNING",
            title          = "Overall data freshness below threshold",
            description    = (
                f"Platform graph health is {graph.get('graph_health_pct', 0):.0f}%. "
                "Multiple agents may be serving stale data."
            ),
            source         = "collaboration_engine",
            recommendation = (
                "Run a fresh scan cycle. Verify all data source connections. "
                "Review scan schedule configuration."
            ),
        ))

    # 8 — CONFLICTING RECOMMENDATIONS: data flow breaks
    for conflict in graph.get("conflicting_outputs", [])[:3]:
        alerts.append(_make_alert(
            alert_type     = "CONFLICTING_RECOMMENDATIONS",
            severity       = "INFO",
            title          = "Data flow inconsistency detected",
            description    = conflict,
            source         = "collaboration_engine",
            recommendation = (
                "Review the agents involved. "
                "Ensure upstream agents complete before downstream ones are queried."
            ),
        ))

    # Sort: CRITICAL first, then WARNING, then INFO
    _severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: _severity_order.get(a["severity"], 3))

    return alerts
