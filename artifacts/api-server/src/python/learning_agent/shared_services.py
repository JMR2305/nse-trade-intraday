"""
shared_services.py — Phase 10D Learning Agent
Read-only stateless snapshot functions consumed by main.py dispatch.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

LEARNING_AGENT_ENABLED = "LEARNING_AGENT_ENABLED"
_TRUE = ("1", "true", "yes")


def _is_enabled() -> bool:
    return os.environ.get(LEARNING_AGENT_ENABLED, "true").lower() in _TRUE


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _disabled() -> dict:
    return {
        "status": "DISABLED",
        "available": False,
        "advisory_only": True,
        "read_only": True,
        "auto_model_updates": False,
        "auto_strategy_tuning": False,
        "message": f"Set {LEARNING_AGENT_ENABLED}=true to enable the Learning Agent.",
    }


def get_learning_snapshot() -> dict:
    """Full learning snapshot including metrics, insights, and patterns."""
    if not _is_enabled():
        return _disabled()
    try:
        from .agent import LearningAgent
        agent = LearningAgent()
        agent.beat()
        result = agent.execute()
        result["available"] = True
        return result
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "advisory_only": True,
            "read_only": True,
            "auto_model_updates": False,
            "auto_strategy_tuning": False,
            "error": str(exc),
            "generated_at": _now_iso(),
        }


def get_learning_metrics() -> dict:
    """Lightweight learning metrics only (no full snapshot overhead)."""
    if not _is_enabled():
        return _disabled()
    snap = _safe(get_learning_snapshot, {})
    return {
        "available":    snap.get("available", False),
        "metrics":      snap.get("metrics", {}),
        "learning_health": snap.get("learning_health", "UNKNOWN"),
        "generated_at": snap.get("generated_at", _now_iso()),
        "advisory_only": True,
        "auto_model_updates":   False,
        "auto_strategy_tuning": False,
    }


def get_learning_insights() -> dict:
    """Learning insights and pattern observations only."""
    if not _is_enabled():
        return _disabled()
    snap = _safe(get_learning_snapshot, {})
    return {
        "available":  snap.get("available", False),
        "insights":   snap.get("insights", {}),
        "patterns":   snap.get("patterns", []),
        "generated_at": snap.get("generated_at", _now_iso()),
        "advisory_only": True,
        "auto_model_updates":   False,
        "auto_strategy_tuning": False,
    }


def get_learning_status() -> dict:
    """Quick status check for the Learning Agent."""
    if not _is_enabled():
        return _disabled()
    try:
        from .agent import LearningAgent
        agent = LearningAgent()
        return agent.get_status()
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "error": str(exc),
            "generated_at": _now_iso(),
        }
