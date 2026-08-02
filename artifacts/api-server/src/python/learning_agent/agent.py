"""
agent.py — Phase 10D Learning Agent
Analyses completed trading sessions and recommendation outcomes.

READ-ONLY · ADVISORY-ONLY
No model retraining. No parameter tuning. No automatic optimisation.
All outputs require operator review before adoption.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any

from .learning_engine import (
    compute_learning_metrics,
    compute_learning_insights,
    discover_patterns,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class LearningAgent:
    """
    Phase 10D Learning Agent.

    READ-ONLY · ADVISORY-ONLY.
    Stateless: instantiated per-request, no persistent singleton state.
    Consumes: Decision Snapshot, Execution Snapshot, Paper Trading Results,
              Trading Timeline, Executive Reports, Risk Snapshot, Strategy Snapshot.
    Produces:  Learning Snapshot.

    Safety guarantees:
    - AUTO_MODEL_UPDATES = false (hardcoded)
    - AUTO_STRATEGY_TUNING = false (hardcoded)
    - No order placement, no trade execution, no parameter changes.
    """

    AGENT_ID   = "learning_agent"
    AGENT_NAME = "Learning Agent"
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
            portfolio = load_portfolio()
            return portfolio.get("trades", [])
        except Exception:
            return []

    def _load_recommendations(self) -> list[dict]:
        try:
            from ai_decision_agent.shared_services import get_ai_decision_recommendations
            data = get_ai_decision_recommendations()
            return data.get("recommendations", [])
        except Exception:
            return []

    def _load_risk_snapshot(self) -> dict:
        try:
            from risk_agent.shared_services import get_risk_snapshot
            return get_risk_snapshot()
        except Exception:
            return {}

    def _load_strategy_snapshot(self) -> dict:
        try:
            from strategy_agent.shared_services import get_strategy_snapshot
            return get_strategy_snapshot()
        except Exception:
            return {}

    def _load_decision_snapshot(self) -> dict:
        try:
            from ai_decision_agent.shared_services import get_ai_decision_snapshot
            return get_ai_decision_snapshot()
        except Exception:
            return {}

    def _load_timeline_events(self) -> list[dict]:
        try:
            from decision_layer.shared_services import get_decision_timeline
            data = get_decision_timeline()
            return data.get("events", [])
        except Exception:
            return []

    # ── core execution ────────────────────────────────────────────────────────

    def execute(self) -> dict:
        """
        Run the full learning analysis cycle.
        Returns the Learning Snapshot.
        """
        t0 = time.monotonic()
        self.beat()

        trades           = self._load_trades()
        recommendations  = self._load_recommendations()
        risk_snapshot    = self._load_risk_snapshot()
        strategy_snapshot = self._load_strategy_snapshot()
        timeline_events  = self._load_timeline_events()

        metrics  = compute_learning_metrics(trades, recommendations, risk_snapshot, strategy_snapshot)
        insights = compute_learning_insights(metrics, trades, recommendations, risk_snapshot)
        patterns = discover_patterns(trades)

        latency_ms = round((time.monotonic() - t0) * 1000, 1)

        return {
            "agent_id":   self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "version":    self.VERSION,
            "status":     "ACTIVE",
            "advisory_only": True,
            "read_only":     True,
            # Safety flags — hardcoded false, never overridden
            "auto_model_updates":   False,
            "auto_strategy_tuning": False,
            # Metrics
            "metrics":  metrics,
            "insights": insights,
            "patterns": patterns,
            # Summary KPIs
            "trades_analysed":            metrics.get("trades_analysed", 0),
            "recommendations_analysed":   metrics.get("recommendations_analysed", 0),
            "patterns_identified":        len([p for p in patterns if p.get("pattern_id") != "BASELINE_OBSERVATION"]),
            "top_insight":                insights.get("best_strategy_today", "N/A"),
            "learning_health":            self._compute_health(metrics),
            # Performance
            "learning_latency_ms": latency_ms,
            "generated_at":        _now_iso(),
            "started_at":          self._started_at,
            "last_heartbeat":      self._heartbeat,
        }

    def _compute_health(self, metrics: dict) -> str:
        wr  = metrics.get("strategy_win_rate", 50)
        acc = metrics.get("recommendation_accuracy", 50)
        cal = metrics.get("confidence_calibration", 0.5)
        if wr >= 50 and acc >= 50 and cal >= 0.6:
            return "HEALTHY"
        if wr >= 35 or acc >= 35:
            return "DEGRADED"
        return "NEEDS_REVIEW"

    def get_status(self) -> dict:
        return {
            "agent_id":   self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "version":    self.VERSION,
            "status":     "ACTIVE",
            "advisory_only": True,
            "read_only":     True,
            "auto_model_updates":   False,
            "auto_strategy_tuning": False,
            "started_at":     self._started_at,
            "last_heartbeat": self._heartbeat,
        }
