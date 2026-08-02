"""
operations_engine.py — Phase 10E
System health score (8 components), ops snapshot, scalability dashboard.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn_path: str, *args: Any) -> Optional[Dict[str, Any]]:
    try:
        parts = fn_path.rsplit(".", 1)
        mod   = __import__(parts[0], fromlist=[parts[1]])
        fn    = getattr(mod, parts[1])
        return fn(*args) if args else fn()
    except Exception:
        return None


# ── System Health Score (8 components) ────────────────────────────────────────

_WEIGHTS = {
    "agent_health":         0.30,
    "snapshot_health":      0.15,
    "heartbeat_health":     0.10,
    "timeline_health":      0.10,
    "knowledge_health":     0.10,
    "learning_health":      0.05,
    "performance_health":   0.10,
    "collaboration_health": 0.10,
}

_HISTORY: List[Dict[str, Any]] = []   # In-process ring buffer (last 20 scores)
_MAX_HISTORY = 20


def _health_str_to_float(health: str) -> float:
    mapping = {
        "HEALTHY":      1.0,
        "ACTIVE":       1.0,
        "DEGRADED":     0.6,
        "WARNING":      0.6,
        "NEEDS_REVIEW": 0.4,
        "CRITICAL":     0.2,
        "ERROR":        0.2,
        "UNAVAILABLE":  0.3,
        "DISABLED":     0.5,
        "UNKNOWN":      0.3,
    }
    return mapping.get((health or "UNKNOWN").upper(), 0.3)


def compute_system_health() -> Dict[str, Any]:
    """
    Compute the 8-component System Health Score.
    All inputs come from existing agent snapshots — no new computation.
    """
    t0 = time.perf_counter()
    components: Dict[str, Any] = {}

    # 1 — Agent Health
    supervisor_snap = _safe("supervisor_agent.shared_services.get_supervisor_snapshot")
    if supervisor_snap and supervisor_snap.get("available"):
        fm = supervisor_snap.get("framework_metrics", {})
        total   = fm.get("agent_count",   0)
        healthy = fm.get("healthy_agents", 0)
        agent_score = (healthy / total) if total > 0 else 0.5
        agent_health_str = "HEALTHY" if agent_score >= 0.8 else "DEGRADED" if agent_score >= 0.5 else "CRITICAL"
    else:
        agent_score      = 0.3
        agent_health_str = "UNAVAILABLE"
    components["agent_health"] = {
        "score":       round(agent_score * 100, 1),
        "health":      agent_health_str,
        "weight":      _WEIGHTS["agent_health"],
        "contribution": round(agent_score * _WEIGHTS["agent_health"] * 100, 1),
    }

    # 2 — Snapshot Health (from collaboration graph)
    collab_snap = _safe("collaboration_engine.shared_services.get_collaboration_health")
    if collab_snap and collab_snap.get("available"):
        snap_score_val   = collab_snap.get("graph_health_pct", 0.0) / 100.0
        snap_health_str  = "HEALTHY" if snap_score_val >= 0.8 else "DEGRADED" if snap_score_val >= 0.5 else "CRITICAL"
    else:
        snap_score_val  = 0.3
        snap_health_str = "UNAVAILABLE"
    components["snapshot_health"] = {
        "score":        round(snap_score_val * 100, 1),
        "health":       snap_health_str,
        "weight":       _WEIGHTS["snapshot_health"],
        "contribution": round(snap_score_val * _WEIGHTS["snapshot_health"] * 100, 1),
    }

    # 3 — Heartbeat Health (supervisor alerts — low alert count = healthy)
    alerts_snap = _safe("supervisor_agent.shared_services.get_supervisor_alerts")
    if alerts_snap and isinstance(alerts_snap, list):
        alert_count     = len(alerts_snap)
        hb_score        = max(0.0, 1.0 - alert_count * 0.1)
        hb_health_str   = "HEALTHY" if hb_score >= 0.8 else "DEGRADED"
    elif alerts_snap and isinstance(alerts_snap, dict):
        alert_count     = alerts_snap.get("alert_count", 0)
        hb_score        = max(0.0, 1.0 - alert_count * 0.1)
        hb_health_str   = "HEALTHY" if hb_score >= 0.8 else "DEGRADED"
    else:
        hb_score        = 0.5
        hb_health_str   = "UNKNOWN"
    components["heartbeat_health"] = {
        "score":        round(hb_score * 100, 1),
        "health":       hb_health_str,
        "weight":       _WEIGHTS["heartbeat_health"],
        "contribution": round(hb_score * _WEIGHTS["heartbeat_health"] * 100, 1),
    }

    # 4 — Timeline Health (recent events present = healthy)
    timeline_snap = _safe("learning_layer.shared_services.get_learning_timeline")
    if timeline_snap and isinstance(timeline_snap, list) and len(timeline_snap) > 0:
        tl_score      = min(1.0, len(timeline_snap) / 5)
        tl_health_str = "HEALTHY"
    elif timeline_snap is not None:
        tl_score      = 0.4
        tl_health_str = "DEGRADED"
    else:
        tl_score      = 0.3
        tl_health_str = "UNAVAILABLE"
    components["timeline_health"] = {
        "score":        round(tl_score * 100, 1),
        "health":       tl_health_str,
        "weight":       _WEIGHTS["timeline_health"],
        "contribution": round(tl_score * _WEIGHTS["timeline_health"] * 100, 1),
    }

    # 5 — Knowledge Health
    knowledge_snap = _safe("knowledge_agent.shared_services.get_knowledge_snapshot")
    if knowledge_snap and knowledge_snap.get("available"):
        kb_size   = knowledge_snap.get("knowledge_base_size", 0)
        kh_score  = min(1.0, kb_size / 20) if kb_size > 0 else 0.4
        kh_health = "HEALTHY" if kh_score >= 0.5 else "DEGRADED"
    else:
        kh_score  = 0.3
        kh_health = "UNAVAILABLE"
    components["knowledge_health"] = {
        "score":        round(kh_score * 100, 1),
        "health":       kh_health,
        "weight":       _WEIGHTS["knowledge_health"],
        "contribution": round(kh_score * _WEIGHTS["knowledge_health"] * 100, 1),
    }

    # 6 — Learning Health
    learning_snap = _safe("learning_agent.shared_services.get_learning_snapshot")
    if learning_snap and learning_snap.get("available"):
        lh_str   = learning_snap.get("learning_health", "UNKNOWN")
        lh_score = _health_str_to_float(lh_str)
        lh_health = lh_str
    else:
        lh_score  = 0.3
        lh_health = "UNAVAILABLE"
    components["learning_health"] = {
        "score":        round(lh_score * 100, 1),
        "health":       lh_health,
        "weight":       _WEIGHTS["learning_health"],
        "contribution": round(lh_score * _WEIGHTS["learning_health"] * 100, 1),
    }

    # 7 — Performance Health (based on avg API latency from recent agents)
    perf_latencies = []
    for ai in ["market_data", "research", "strategy", "risk", "ai_decision"]:
        if ai == "market_data":
            snap = _safe("market_data_agent.shared_services.get_market_data_metrics")
        elif ai == "research":
            snap = _safe("research_agent.shared_services.get_research_metrics")
        else:
            snap = None
        if snap:
            lat = snap.get("avg_processing_time_ms") or snap.get("snapshot_latency_ms")
            if lat is not None:
                perf_latencies.append(float(lat))
    if perf_latencies:
        avg_lat    = sum(perf_latencies) / len(perf_latencies)
        ph_score   = max(0.0, 1.0 - avg_lat / 5000)
        ph_health  = "HEALTHY" if ph_score >= 0.8 else "DEGRADED"
    else:
        ph_score   = 0.5
        ph_health  = "UNKNOWN"
    components["performance_health"] = {
        "score":        round(ph_score * 100, 1),
        "health":       ph_health,
        "weight":       _WEIGHTS["performance_health"],
        "contribution": round(ph_score * _WEIGHTS["performance_health"] * 100, 1),
        "avg_latency_ms": round(sum(perf_latencies) / len(perf_latencies), 1) if perf_latencies else 0.0,
    }

    # 8 — Collaboration Health
    ch_snap = _safe("collaboration_engine.shared_services.get_collaboration_health")
    if ch_snap and ch_snap.get("available"):
        ch_str   = ch_snap.get("collaboration_health", "UNKNOWN")
        ch_score = _health_str_to_float(ch_str)
        ch_health = ch_str
    else:
        ch_score  = 0.3
        ch_health = "UNAVAILABLE"
    components["collaboration_health"] = {
        "score":        round(ch_score * 100, 1),
        "health":       ch_health,
        "weight":       _WEIGHTS["collaboration_health"],
        "contribution": round(ch_score * _WEIGHTS["collaboration_health"] * 100, 1),
    }

    # Overall score = weighted sum
    overall = sum(c["contribution"] for c in components.values())
    overall = round(min(100.0, overall), 1)
    overall_health = (
        "HEALTHY"  if overall >= 80 else
        "DEGRADED" if overall >= 55 else
        "CRITICAL" if overall >= 30 else
        "DOWN"
    )

    # Append to history ring buffer
    history_entry = {
        "score":      overall,
        "health":     overall_health,
        "timestamp":  _now_iso(),
    }
    _HISTORY.append(history_entry)
    if len(_HISTORY) > _MAX_HISTORY:
        _HISTORY.pop(0)

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "advisory_only":       True,
        "read_only":           True,
        "available":           True,
        "overall_score":       overall,
        "overall_health":      overall_health,
        "components":          components,
        "history":             list(_HISTORY[-10:]),  # last 10 samples
        "computation_latency_ms": latency_ms,
        "generated_at":        _now_iso(),
    }


def compute_scalability_dashboard() -> Dict[str, Any]:
    """
    Scalability and capacity planning metrics. Advisory-only.
    """
    supervisor_snap = _safe("supervisor_agent.shared_services.get_supervisor_snapshot")
    scalability     = _safe("supervisor_agent.shared_services.get_scalability_estimate")
    learning_snap   = _safe("learning_layer.shared_services.get_learning_performance")
    knowledge_snap  = _safe("knowledge_agent.shared_services.get_knowledge_snapshot")

    # Current metrics
    agent_count  = 11
    symbols      = 0
    snap_per_min = 0
    if supervisor_snap and supervisor_snap.get("available"):
        fm          = supervisor_snap.get("framework_metrics", {})
        agent_count = fm.get("agent_count", 11)
        symbols     = supervisor_snap.get("monitored_symbols", 0) or 0
        snap_per_min = fm.get("total_snapshots_published", 0)

    # Learning throughput
    learning_throughput = "—"
    if learning_snap and isinstance(learning_snap, dict):
        sc = learning_snap.get("scalability", {})
        learning_throughput = sc.get("learning_throughput", "—")

    # Knowledge growth
    kb_size    = 0
    kb_growth  = "—"
    if knowledge_snap and knowledge_snap.get("available"):
        kb_size   = knowledge_snap.get("knowledge_base_size", 0)
        kb_growth = f"~{kb_size} records"

    # Capacity estimates
    safe_cap    = agent_count * 100
    max_cap     = agent_count * 200
    util_pct    = round(symbols / safe_cap * 100, 1) if safe_cap > 0 else 0.0
    remaining   = max(0, safe_cap - symbols)

    # CPU/memory estimates (advisory)
    est_cpu_pct  = min(95, round(5.0 + agent_count * 2.5 + symbols * 0.05, 1))
    est_mem_mb   = round(150.0 + agent_count * 20 + symbols * 0.5, 1)

    # Future scaling
    future_agents    = max(0, 20 - agent_count)
    future_symbols   = future_agents * 100
    scaling_estimate = (
        f"Platform can support up to {20} agents and {future_symbols + symbols} symbols "
        "without architectural redesign."
    )

    recs_per_hour = max(0, symbols * 2) if symbols > 0 else 0

    return {
        "advisory_only":             True,
        "available":                 True,
        "current_agents":            agent_count,
        "current_monitored_symbols": symbols,
        "snapshots_per_minute":      snap_per_min,
        "recommendations_per_hour":  recs_per_hour,
        "learning_throughput":       learning_throughput,
        "knowledge_growth":          kb_growth,
        "knowledge_base_size":       kb_size,
        "safe_capacity_symbols":     safe_cap,
        "max_capacity_symbols":      max_cap,
        "utilisation_pct":           util_pct,
        "remaining_capacity":        remaining,
        "estimated_cpu_pct":         est_cpu_pct,
        "estimated_memory_mb":       est_mem_mb,
        "future_agents_supported":   future_agents,
        "future_symbols_supported":  future_symbols,
        "scaling_estimate":          scaling_estimate,
        "scalability_advisory":      scalability or {},
        "generated_at":              _now_iso(),
    }


def compute_ops_snapshot() -> Dict[str, Any]:
    """
    Full autonomous operations snapshot.
    """
    t0 = time.perf_counter()

    health     = compute_system_health()
    scalability = compute_scalability_dashboard()

    # Agent roster from supervisor
    supervisor_snap = _safe("supervisor_agent.shared_services.get_supervisor_snapshot")
    fm = {}
    if supervisor_snap and supervisor_snap.get("available"):
        fm = supervisor_snap.get("framework_metrics", {})

    registered  = fm.get("agent_count",   11)
    healthy_cnt = fm.get("healthy_agents", 0)
    warning_cnt = fm.get("warning_agents", 0)
    error_cnt   = fm.get("error_agents",  0)
    busy_cnt    = fm.get("active_agents",  0)
    failed_cnt  = error_cnt

    # Data freshness
    data_freshness = _safe("market_data_agent.shared_services.get_market_data_snapshot")
    freshness_s    = 0
    if data_freshness and data_freshness.get("available"):
        freshness_s = data_freshness.get("data_freshness_s", 0) or 0

    # Decision latency
    decision_snap = _safe("ai_decision_agent.shared_services.get_ai_decision_snapshot")
    avg_decision_lat = 0.0
    if decision_snap and decision_snap.get("available"):
        avg_decision_lat = decision_snap.get("decision_latency_ms", 0.0) or 0.0

    # Snapshot latency
    avg_snap_lat = 0.0
    ch = health.get("components", {}).get("performance_health", {})
    avg_snap_lat = ch.get("avg_latency_ms", 0.0)

    # Learning and knowledge queues
    learning_snap = _safe("learning_agent.shared_services.get_learning_snapshot")
    knowledge_snap = _safe("knowledge_agent.shared_services.get_knowledge_snapshot")
    learning_queue = 0
    knowledge_queue = 0
    if learning_snap and learning_snap.get("available"):
        metrics = learning_snap.get("metrics") or {}
        learning_queue = metrics.get("trades_analysed", 0)
    if knowledge_snap and knowledge_snap.get("available"):
        knowledge_queue = knowledge_snap.get("knowledge_base_size", 0)

    # Collaboration alerts
    collab_alerts = _safe("collaboration_engine.shared_services.get_collaboration_alerts")
    alert_list = []
    if collab_alerts and collab_alerts.get("available"):
        alert_list = collab_alerts.get("alerts", [])

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "advisory_only":            True,
        "read_only":                True,
        "available":                True,
        "registered_agents":        registered,
        "healthy_agents":           healthy_cnt,
        "busy_agents":              busy_cnt,
        "warning_agents":           warning_cnt,
        "failed_agents":            failed_cnt,
        "snapshot_throughput":      fm.get("total_snapshots_published", 0),
        "queue_depth":              fm.get("total_queue_depth", 0),
        "heartbeat_status":         "HEALTHY" if warning_cnt == 0 else "DEGRADED",
        "data_freshness_s":         freshness_s,
        "avg_decision_latency_ms":  avg_decision_lat,
        "avg_snapshot_latency_ms":  avg_snap_lat,
        "learning_queue":           learning_queue,
        "knowledge_queue":          knowledge_queue,
        "overall_health":           health.get("overall_health", "UNKNOWN"),
        "overall_health_score":     health.get("overall_score", 0.0),
        "collaboration_alerts":     alert_list[:5],
        "ops_latency_ms":           latency_ms,
        "generated_at":             _now_iso(),
    }
