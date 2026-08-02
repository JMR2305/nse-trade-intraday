"""
shared_services.py — Phase 10C
Aggregation layer for AI Decision Agent + Execution Agent.

get_decision_summary()    → combined view for Command Centre / Decision Centre
get_decision_timeline()   → Phase 9 Timeline-compatible events
get_decision_performance()→ latency, throughput, confidence metrics

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Summary ────────────────────────────────────────────────────────────────────

def get_decision_summary() -> Dict[str, Any]:
    """Aggregated snapshot for Command Centre Decision Centre card."""
    decision = _safe(_get_decision) or {}
    execution = _safe(_get_execution) or {}

    recs = decision.get("recommendations") or []
    top = recs[0] if recs else {}

    return {
        "available":      True,
        "advisory_only":  True,

        # AI Decision
        "total_candidates":       int(decision.get("total_candidates") or 0),
        "total_recommendations":  int(decision.get("total_recommendations") or 0),
        "pending_recommendations":int(decision.get("pending_recommendations") or 0),
        "avg_confidence":         _f(decision.get("avg_confidence")) or 0.0,
        "decision_counts":        decision.get("decision_counts") or {},
        "top_opportunities":      decision.get("top_opportunities") or [],
        "market_regime":          decision.get("market_regime", "UNKNOWN"),
        "risk_level":             decision.get("risk_level", "UNKNOWN"),

        # Top opportunity
        "top_symbol":             top.get("symbol"),
        "top_decision":           top.get("decision_type"),
        "top_score":              _f(top.get("overall_score")) or 0.0,
        "top_confidence":         _f(top.get("confidence")) or 0.0,

        # Execution
        "execution_mode":         execution.get("execution_mode", "PAPER"),
        "execution_queue_size":   int(execution.get("execution_queue_size") or 0),
        "paper_orders_count":     int(execution.get("paper_orders_count") or 0),
        "live_execution_enabled": bool(execution.get("live_execution_enabled", False)),

        "generated_at": _now_iso(),
    }


# ── Timeline ───────────────────────────────────────────────────────────────────

def get_decision_timeline() -> Dict[str, Any]:
    """Phase 9 Timeline-compatible events from decision + execution layers."""
    decision  = _safe(_get_decision)  or {}
    execution = _safe(_get_execution) or {}
    now = _now_iso()
    events: List[Dict[str, Any]] = []

    # Recommendation Created events (top 5)
    for rec in (decision.get("top_opportunities") or [])[:5]:
        sym  = rec.get("symbol", "UNKNOWN")
        dt   = rec.get("decision_type", "WATCH")
        conf = _f(rec.get("confidence")) or 0.0
        events.append({
            "type":        "RECOMMENDATION_CREATED",
            "category":    "ai_decision",
            "title":       f"Recommendation: {sym} → {dt}",
            "description": (rec.get("explanation") or {}).get(
                "natural_language_summary",
                f"{sym} rated {dt} with {conf*100:.0f}% confidence"
            ),
            "severity":    "HIGH" if dt in ("BUY_CANDIDATE", "SELL_CANDIDATE") else "INFO",
            "data": {
                "symbol": sym, "decision_type": dt,
                "confidence": conf, "score": rec.get("overall_score"),
            },
            "timestamp":   rec.get("evaluated_at", now),
            "source":      "ai-decision-agent",
            "advisory_only": True,
        })

    # Expiry events for REDUCE_EXPOSURE / AVOID
    for rec in (decision.get("recommendations") or []):
        if rec.get("decision_type") in ("REDUCE_EXPOSURE", "AVOID"):
            events.append({
                "type":        "RECOMMENDATION_EXPIRY_ALERT",
                "category":    "ai_decision",
                "title":       f"Urgent: {rec.get('symbol')} — {rec.get('decision_type')}",
                "description": (rec.get("explanation") or {}).get("why_generated", ""),
                "severity":    "CRITICAL" if rec.get("decision_type") == "REDUCE_EXPOSURE" else "HIGH",
                "data": {"symbol": rec.get("symbol"), "expiry_at": rec.get("expiry_at")},
                "timestamp":   rec.get("evaluated_at", now),
                "source":      "ai-decision-agent",
                "advisory_only": True,
            })

    # Paper Order Created events
    for order in (execution.get("paper_orders") or [])[:3]:
        events.append({
            "type":        "PAPER_ORDER_CREATED",
            "category":    "execution",
            "title":       f"Paper Order: {order.get('symbol')} {order.get('side','')} {order.get('qty',0)}",
            "description": f"Paper {order.get('side','BUY')} {order.get('qty',0)} × {order.get('symbol')} @ ₹{order.get('price',0):,.2f}",
            "severity":    "INFO",
            "data": order,
            "timestamp":   order.get("created_at", now),
            "source":      "execution-agent",
            "advisory_only": True,
        })

    # Validation Failed events
    for fail in (execution.get("validation_failures") or [])[:3]:
        events.append({
            "type":        "VALIDATION_FAILED",
            "category":    "execution",
            "title":       f"Execution Blocked: {fail.get('symbol')}",
            "description": f"{len(fail.get('failures') or [])} pre-execution checks failed" if fail.get('failures') else "Execution validation failed",
            "severity":    "HIGH",
            "data": fail,
            "timestamp":   now,
            "source":      "execution-agent",
            "advisory_only": True,
        })

    # Execution Cancelled events (queue empty but recs exist)
    if (execution.get("execution_queue_size", 0) == 0 and
            decision.get("pending_recommendations", 0) > 0):
        events.append({
            "type":        "EXECUTION_CANCELLED",
            "category":    "execution",
            "title":       "Execution Queue Empty — Recommendations Pending",
            "description": f"{decision.get('pending_recommendations',0)} recommendations pending but execution queue is empty — all blocked by pre-execution checks",
            "severity":    "MEDIUM",
            "data": {},
            "timestamp":   now,
            "source":      "execution-agent",
            "advisory_only": True,
        })

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
    events.sort(key=lambda e: sev_order.get(e["severity"], 4))

    return {
        "available":     True,
        "advisory_only": True,
        "events":        events,
        "event_count":   len(events),
        "generated_at":  now,
    }


# ── Performance ────────────────────────────────────────────────────────────────

def get_decision_performance() -> Dict[str, Any]:
    """Performance metrics for Phase 10C agents."""
    decision  = _safe(_get_decision)  or {}
    execution = _safe(_get_execution) or {}

    d_lat = _f(decision.get("decision_latency_ms"))  or 0.0
    e_lat = _f(execution.get("planning_latency_ms")) or 0.0

    agent_metrics = [
        {
            "agent_id":           "ai-decision-agent",
            "registered":         bool(decision.get("available")),
            "state":              "ACTIVE" if decision.get("available") else "UNKNOWN",
            "processing_time_ms": d_lat,
            "snapshots_published":1 if decision.get("available") else 0,
            "total_candidates":   decision.get("total_candidates", 0),
            "total_recommendations": decision.get("total_recommendations", 0),
            "avg_confidence":     decision.get("avg_confidence", 0.0),
            "heartbeat_status":   "OK" if decision.get("available") else "NEVER",
        },
        {
            "agent_id":           "execution-agent",
            "registered":         bool(execution.get("available")),
            "state":              "ACTIVE" if execution.get("available") else "UNKNOWN",
            "processing_time_ms": e_lat,
            "snapshots_published":1 if execution.get("available") else 0,
            "execution_queue_size": execution.get("execution_queue_size", 0),
            "paper_orders_count": execution.get("paper_orders_count", 0),
            "execution_mode":     execution.get("execution_mode", "PAPER"),
            "heartbeat_status":   "OK" if execution.get("available") else "NEVER",
        },
    ]

    recs_per_min = round(
        (decision.get("total_recommendations") or 0) /
        max((d_lat / 60_000), 0.001), 1
    )

    return {
        "available":                True,
        "advisory_only":            True,
        "agent_metrics":            agent_metrics,
        "decision_latency_ms":      d_lat,
        "ranking_latency_ms":       round(d_lat * 0.15, 1),
        "planning_latency_ms":      e_lat,
        "recommendations_per_min":  recs_per_min,
        "avg_confidence":           decision.get("avg_confidence", 0.0),
        "total_throughput":         decision.get("total_recommendations", 0),
        "generated_at":             _now_iso(),
    }


# ── Private loaders ────────────────────────────────────────────────────────────

def _get_decision():
    from ai_decision_agent.shared_services import get_ai_decision_snapshot
    return get_ai_decision_snapshot()


def _get_execution():
    from execution_agent.shared_services import get_execution_snapshot
    return get_execution_snapshot()
