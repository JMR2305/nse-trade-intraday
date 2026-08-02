"""
shared_services.py — Phase 10C
Read-only snapshot functions for the AI Decision Agent.
Each function computes fresh (stateless subprocess model).
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent_framework.config import disabled_response

AI_DECISION_AGENT_ENABLED = "AI_DECISION_AGENT_ENABLED"


def _is_enabled() -> bool:
    import os
    return os.environ.get(AI_DECISION_AGENT_ENABLED, "true").lower() in ("1", "true", "yes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def get_ai_decision_snapshot() -> Dict[str, Any]:
    """Full decision snapshot with all ranked recommendations."""
    if not _is_enabled():
        return disabled_response(AI_DECISION_AGENT_ENABLED)

    def _f():
        from ai_decision_agent.agent import AIDecisionAgent
        agent = AIDecisionAgent()
        agent.start()
        agent.beat()
        payload = agent.execute_task() or {}
        if payload:
            agent.publish(payload, "decisions")
        payload["available"] = True
        return payload

    result = _safe(_f)
    if result is None:
        return {"available": False, "advisory_only": True,
                "error": "AI Decision snapshot unavailable"}
    return result


def get_ai_decision_recommendations() -> Dict[str, Any]:
    """Ranked recommendations list — lightweight subset of snapshot."""
    if not _is_enabled():
        return disabled_response(AI_DECISION_AGENT_ENABLED)

    snap = get_ai_decision_snapshot()
    if not snap.get("available"):
        return snap

    recs = snap.get("recommendations") or []
    return {
        "available":           True,
        "advisory_only":       True,
        "recommendations":     recs,
        "total_recommendations": snap.get("total_recommendations", 0),
        "pending_recommendations": snap.get("pending_recommendations", 0),
        "top_opportunities":   snap.get("top_opportunities", []),
        "decision_counts":     snap.get("decision_counts", {}),
        "avg_confidence":      snap.get("avg_confidence", 0.0),
        "market_regime":       snap.get("market_regime", "UNKNOWN"),
        "generated_at":        snap.get("generated_at", _now_iso()),
    }


def get_ai_decision_for_symbol(symbol: str) -> Dict[str, Any]:
    """Full explainable recommendation for a single symbol."""
    if not _is_enabled():
        return disabled_response(AI_DECISION_AGENT_ENABLED)

    def _f():
        from ai_decision_agent.agent import AIDecisionAgent
        agent = AIDecisionAgent()
        agent.start()
        agent.beat()
        result = agent.get_recommendation_for_symbol(symbol)
        if result is None:
            return {"available": False, "error": f"No data for symbol: {symbol}"}
        result["available"] = True
        return result

    return _safe(_f) or {"available": False, "error": "Decision unavailable"}


def get_ai_decision_status() -> Dict[str, Any]:
    """Agent status — computed from snapshot metadata."""
    if not _is_enabled():
        return disabled_response(AI_DECISION_AGENT_ENABLED)

    snap = _safe(get_ai_decision_snapshot) or {}
    available = bool(snap.get("available"))
    return {
        "available":           available,
        "advisory_only":       True,
        "agent_id":            "ai-decision-agent",
        "state":               "ACTIVE" if available else "UNKNOWN",
        "total_candidates":    snap.get("total_candidates", 0),
        "total_recommendations": snap.get("total_recommendations", 0),
        "avg_confidence":      snap.get("avg_confidence", 0.0),
        "decision_latency_ms": snap.get("decision_latency_ms", 0.0),
        "generated_at":        snap.get("generated_at", _now_iso()),
    }
