"""
agent.py — Phase 10D Knowledge Agent
Creates a searchable long-term knowledge base for ApexQuant AI.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
All outputs require operator review before adoption.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone

from .knowledge_engine import (
    build_knowledge_index,
    search_knowledge,
    build_trade_memory,
    generate_lessons_library,
)
from learning_agent.learning_engine import discover_patterns


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class KnowledgeAgent:
    """
    Phase 10D Knowledge Agent.

    READ-ONLY · ADVISORY-ONLY.
    Stateless: instantiated per-request.
    Consumes: Research, Timeline, Reports, Learning Snapshot,
              Decision Snapshot, Annotations.
    Produces: Knowledge Snapshot.
    """

    AGENT_ID   = "knowledge_agent"
    AGENT_NAME = "Knowledge Agent"
    VERSION    = "10D.1"

    def __init__(self) -> None:
        self._started_at = _now_iso()
        self._heartbeat  = _now_iso()

    def beat(self) -> None:
        self._heartbeat = _now_iso()

    # ── upstream data loaders ─────────────────────────────────────────────────

    def _load_trades(self) -> list[dict]:
        try:
            from portfolio_store import load_portfolio
            return load_portfolio().get("trades", [])
        except Exception:
            return []

    def _load_recommendations(self) -> list[dict]:
        try:
            from ai_decision_agent.shared_services import get_ai_decision_recommendations
            return get_ai_decision_recommendations().get("recommendations", [])
        except Exception:
            return []

    def _load_research_snapshot(self) -> dict:
        try:
            from research_agent.shared_services import get_research_snapshot
            return get_research_snapshot()
        except Exception:
            return {}

    def _load_timeline_events(self) -> list[dict]:
        try:
            from decision_layer.shared_services import get_decision_timeline
            return get_decision_timeline().get("events", [])
        except Exception:
            return []

    def _load_decision_snapshot(self) -> dict:
        try:
            from ai_decision_agent.shared_services import get_ai_decision_snapshot
            return get_ai_decision_snapshot()
        except Exception:
            return {}

    def _load_learning_snapshot(self) -> dict:
        try:
            from learning_agent.shared_services import get_learning_snapshot
            return get_learning_snapshot()
        except Exception:
            return {}

    def _load_annotations(self) -> list[dict]:
        # Annotations are operator notes stored in localStorage on the frontend;
        # backend has no persistent store — return empty list gracefully.
        return []

    # ── core execution ────────────────────────────────────────────────────────

    def execute(self, query: str | None = None) -> dict:
        """
        Build or search the knowledge base.
        Returns the Knowledge Snapshot (with optional search results).
        """
        t0 = time.monotonic()
        self.beat()

        trades           = self._load_trades()
        recommendations  = self._load_recommendations()
        research_snap    = self._load_research_snapshot()
        timeline_events  = self._load_timeline_events()
        decision_snap    = self._load_decision_snapshot()
        learning_snap    = self._load_learning_snapshot()
        annotations      = self._load_annotations()

        entries      = build_knowledge_index(
            trades, recommendations, research_snap,
            timeline_events, decision_snap, annotations,
        )
        trade_memory = build_trade_memory(trades, recommendations, decision_snap)

        metrics_raw  = learning_snap.get("metrics", {})
        insights_raw = learning_snap.get("insights", {})
        lessons      = generate_lessons_library(trade_memory, metrics_raw, insights_raw)

        patterns     = discover_patterns(trades)

        search_results: list[dict] = []
        if query:
            search_results = search_knowledge(query, entries)

        indexing_ms = round((time.monotonic() - t0) * 1000, 1)

        return {
            "agent_id":   self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "version":    self.VERSION,
            "status":     "ACTIVE",
            "advisory_only": True,
            "read_only":     True,
            # Knowledge base stats
            "knowledge_base_size":        len(entries),
            "trades_learned":             len(trade_memory),
            "recommendations_analysed":   len([e for e in entries if e["type"] == "RECOMMENDATION"]),
            "patterns_identified":        len([p for p in patterns if p.get("pattern_id") != "BASELINE_OBSERVATION"]),
            "search_activity":            1 if query else 0,
            "learning_health":            learning_snap.get("learning_health", "UNKNOWN"),
            # Content
            "entries_sample":   entries[:10],   # first 10 for dashboard preview
            "trade_memory":     trade_memory,
            "lessons_library":  lessons,
            "patterns":         patterns,
            "search_results":   search_results,
            "search_query":     query,
            # Performance
            "indexing_latency_ms": indexing_ms,
            "generated_at":        _now_iso(),
            "started_at":          self._started_at,
            "last_heartbeat":      self._heartbeat,
        }

    def search(self, query: str) -> dict:
        t0 = time.monotonic()
        self.beat()

        trades           = self._load_trades()
        recommendations  = self._load_recommendations()
        research_snap    = self._load_research_snapshot()
        timeline_events  = self._load_timeline_events()
        decision_snap    = self._load_decision_snapshot()
        annotations      = self._load_annotations()

        entries       = build_knowledge_index(
            trades, recommendations, research_snap,
            timeline_events, decision_snap, annotations,
        )
        results       = search_knowledge(query, entries)
        search_ms     = round((time.monotonic() - t0) * 1000, 1)

        return {
            "query":         query,
            "results":       results,
            "result_count":  len(results),
            "search_latency_ms": search_ms,
            "generated_at":  _now_iso(),
            "advisory_only": True,
        }

    def get_status(self) -> dict:
        return {
            "agent_id":   self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "version":    self.VERSION,
            "status":     "ACTIVE",
            "advisory_only": True,
            "read_only":     True,
            "started_at":     self._started_at,
            "last_heartbeat": self._heartbeat,
        }
