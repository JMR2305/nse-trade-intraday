"""
shared_services.py — Phase 10D Knowledge Agent
Read-only stateless snapshot functions consumed by main.py dispatch.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

KNOWLEDGE_AGENT_ENABLED = "KNOWLEDGE_AGENT_ENABLED"
_TRUE = ("1", "true", "yes")


def _is_enabled() -> bool:
    return os.environ.get(KNOWLEDGE_AGENT_ENABLED, "true").lower() in _TRUE


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
        "message": f"Set {KNOWLEDGE_AGENT_ENABLED}=true to enable the Knowledge Agent.",
    }


def get_knowledge_snapshot() -> dict:
    """Full knowledge snapshot: index stats, trade memory, lessons, patterns."""
    if not _is_enabled():
        return _disabled()
    try:
        from .agent import KnowledgeAgent
        agent = KnowledgeAgent()
        agent.beat()
        result = agent.execute()
        result["available"] = True
        return result
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "advisory_only": True,
            "error": str(exc),
            "generated_at": _now_iso(),
        }


def get_knowledge_search(query: str) -> dict:
    """Natural-language search over the knowledge base."""
    if not _is_enabled():
        return _disabled()
    if not query or not query.strip():
        return {
            "available": True,
            "query": query,
            "results": [],
            "result_count": 0,
            "advisory_only": True,
            "message": "Provide a non-empty search query.",
            "generated_at": _now_iso(),
        }
    try:
        from .agent import KnowledgeAgent
        agent = KnowledgeAgent()
        agent.beat()
        return agent.search(query)
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "advisory_only": True,
            "error": str(exc),
            "generated_at": _now_iso(),
        }


def get_knowledge_patterns() -> dict:
    """Pattern discovery results only."""
    if not _is_enabled():
        return _disabled()
    snap = _safe(get_knowledge_snapshot, {})
    return {
        "available": snap.get("available", False),
        "patterns":  snap.get("patterns", []),
        "patterns_identified": snap.get("patterns_identified", 0),
        "generated_at": snap.get("generated_at", _now_iso()),
        "advisory_only": True,
    }


def get_knowledge_lessons() -> dict:
    """Lessons library: what worked, failed, to review, to monitor, open questions."""
    if not _is_enabled():
        return _disabled()
    snap = _safe(get_knowledge_snapshot, {})
    return {
        "available":       snap.get("available", False),
        "lessons_library": snap.get("lessons_library", {}),
        "trades_analysed": snap.get("trades_learned", 0),
        "generated_at":    snap.get("generated_at", _now_iso()),
        "advisory_only":   True,
    }


def get_trade_memory() -> dict:
    """Full trade memory records for completed paper trades."""
    if not _is_enabled():
        return _disabled()
    snap = _safe(get_knowledge_snapshot, {})
    return {
        "available":     snap.get("available", False),
        "trade_memory":  snap.get("trade_memory", []),
        "trades_learned": snap.get("trades_learned", 0),
        "generated_at":  snap.get("generated_at", _now_iso()),
        "advisory_only": True,
    }


def get_knowledge_status() -> dict:
    """Quick status check for the Knowledge Agent."""
    if not _is_enabled():
        return _disabled()
    try:
        from .agent import KnowledgeAgent
        agent = KnowledgeAgent()
        return agent.get_status()
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "error": str(exc),
            "generated_at": _now_iso(),
        }
