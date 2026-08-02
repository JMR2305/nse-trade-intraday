"""
agent.py — Phase 10C
AI Decision Agent.

Consumes snapshots from Phase 10B analysis agents + research + portfolio.
Produces explainable recommendations for every candidate symbol.
Ranks opportunities by 6 criteria.
Assigns confidence, priority, and expiry.

Decision Types: WATCH | ACCUMULATE | BUY_CANDIDATE | SELL_CANDIDATE |
                REDUCE_EXPOSURE | AVOID | NO_ACTION

READ-ONLY · ADVISORY-ONLY — NEVER places orders.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent
from ai_decision_agent.decision_engine import (
    compute_scores, compute_confidence, assign_decision_type,
    compute_expiry, assign_priority, rank_recommendations, SCORE_WEIGHTS,
)
from ai_decision_agent.explainability import ExplainabilityEngine


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class AIDecisionAgent(BaseAgent):
    """
    Evaluates every candidate symbol across 6 analytical dimensions.
    Produces ranked, explainable recommendations.

    READ-ONLY · ADVISORY-ONLY
    No orders are ever placed by this agent.
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="ai-decision-agent",
            name="AI Decision Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=4,
            dependencies=[
                "market-intelligence-agent", "stock-monitoring-agent",
                "strategy-agent", "risk-agent",
            ],
            capabilities=[
                "decision_generation", "recommendation_ranking",
                "explainable_ai", "conflict_resolution",
                "confidence_estimation", "expiry_management",
            ],
        )
        self._explainer = ExplainabilityEngine()
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "decisions"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        # Load all upstream snapshots (all read-only, all stateless)
        mi         = _safe(self._load_mi)         or {}
        sm         = _safe(self._load_sm)         or {}
        strategy   = _safe(self._load_strategy)   or {}
        risk       = _safe(self._load_risk)       or {}
        research   = _safe(self._load_research)   or {}
        portfolio  = _safe(self._load_portfolio)  or {}

        # Derive candidate symbols from monitoring priority queue
        candidates = self._derive_candidates(sm, portfolio)

        # Evaluate each candidate
        recommendations: List[Dict[str, Any]] = []
        session_info = mi.get("session_info") or {}

        for symbol in candidates[:60]:
            rec = _safe(lambda s=symbol: self._evaluate_symbol(
                s, mi, sm, strategy, risk, research, portfolio, session_info
            ))
            if rec:
                recommendations.append(rec)

        # Rank
        ranked = rank_recommendations(recommendations)

        # Aggregate stats
        decision_counts = _count_decisions(ranked)
        avg_confidence  = (
            sum(r["confidence"] for r in ranked) / len(ranked) if ranked else 0.0
        )
        top_3 = ranked[:3]

        elapsed = round((time.monotonic() * 1000) - start_ms, 1)

        payload = {
            "agent_id":    "ai-decision-agent",
            "agent_name":  "AI Decision Agent",
            "advisory_only": True,
            "read_only":     True,
            "never_places_orders": True,

            # Recommendations
            "recommendations":         ranked[:20],   # top 20 for display
            "total_candidates":        len(candidates),
            "total_recommendations":   len(ranked),
            "top_opportunities":       top_3,

            # Stats
            "decision_counts":         decision_counts,
            "avg_confidence":          round(avg_confidence, 3),
            "pending_recommendations": len([r for r in ranked if r["decision_type"] not in ("NO_ACTION", "AVOID")]),

            # Regime context
            "market_regime":           mi.get("market_regime", "UNKNOWN"),
            "risk_level":              risk.get("risk_level", "UNKNOWN"),
            "session_phase":           session_info.get("phase", "UNKNOWN"),

            # Score weights used
            "score_weights":           SCORE_WEIGHTS,

            "decision_latency_ms":     elapsed,
            "generated_at":            _now_iso(),
        }
        self._last_snapshot = payload
        return payload

    # ── Per-symbol evaluation ─────────────────────────────────────────────────

    def _evaluate_symbol(
        self, symbol: str,
        mi: Dict, sm: Dict, strategy: Dict, risk: Dict,
        research: Dict, portfolio: Dict, session_info: Dict,
    ) -> Dict[str, Any]:

        scores = compute_scores(symbol, mi, strategy, risk, research, portfolio)
        best_strat = scores.pop("_best_strategy", "Unknown")
        conflicts  = self._explainer._detect_conflicts(scores, mi, strategy, risk)
        confidence = compute_confidence(scores, bool(conflicts))
        decision   = assign_decision_type(symbol, scores, risk, portfolio, sm)
        priority   = assign_priority(decision, scores["overall"], confidence)
        expiry, expiry_reason = compute_expiry(decision, session_info)

        # Reward/risk ratio estimate (advisory)
        rr_ratio = _estimate_rr(scores)

        explanation = self._explainer.explain(
            symbol, decision, scores, confidence,
            mi, strategy, risk, research, sm, portfolio
        )
        explanation["expiry_reason"] = expiry_reason

        return {
            "symbol":          symbol,
            "decision_type":   decision,
            "overall_score":   round(scores["overall"], 1),
            "confidence":      confidence,
            "priority":        priority,
            "expiry_at":       expiry,
            "reward_risk_ratio": rr_ratio,
            "best_strategy":   best_strat,
            "scores":          {k: round(v, 1) for k, v in scores.items()},
            "explanation":     explanation,
            "advisory_only":   True,
            "evaluated_at":    _now_iso(),
        }

    # ── Data loaders (all stateless read-only) ────────────────────────────────

    @staticmethod
    def _load_mi() -> Dict[str, Any]:
        from market_intelligence_agent.shared_services import get_market_intelligence_agent_snapshot
        return get_market_intelligence_agent_snapshot()

    @staticmethod
    def _load_sm() -> Dict[str, Any]:
        from stock_monitoring_agent.shared_services import get_stock_monitoring_snapshot
        return get_stock_monitoring_snapshot()

    @staticmethod
    def _load_strategy() -> Dict[str, Any]:
        from strategy_agent.shared_services import get_strategy_snapshot
        return get_strategy_snapshot()

    @staticmethod
    def _load_risk() -> Dict[str, Any]:
        from risk_agent.shared_services import get_risk_snapshot
        return get_risk_snapshot()

    @staticmethod
    def _load_research() -> Dict[str, Any]:
        try:
            from research_agent.shared_services import get_research_snapshot
            return get_research_snapshot()
        except Exception:
            return {}

    @staticmethod
    def _load_portfolio() -> Dict[str, Any]:
        from portfolio_store import load_state
        return load_state() or {}

    # ── Candidate derivation ──────────────────────────────────────────────────

    @staticmethod
    def _derive_candidates(sm: Dict, portfolio: Dict) -> List[str]:
        """Derive candidates from priority queue + open positions."""
        queue = sm.get("priority_queue") or []
        candidates = [item["symbol"] for item in queue if item.get("symbol")]

        # Always include open positions
        positions = portfolio.get("positions") or {}
        if isinstance(positions, dict):
            for sym in positions:
                if sym not in candidates:
                    candidates.insert(0, sym)
        elif isinstance(positions, list):
            for p in positions:
                sym = p.get("symbol")
                if sym and sym not in candidates:
                    candidates.insert(0, sym)

        return list(dict.fromkeys(candidates))  # deduplicate preserving order

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot

    def get_recommendation_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Evaluate a single symbol and return its full recommendation."""
        mi        = _safe(self._load_mi)        or {}
        sm        = _safe(self._load_sm)        or {}
        strategy  = _safe(self._load_strategy)  or {}
        risk      = _safe(self._load_risk)      or {}
        research  = _safe(self._load_research)  or {}
        portfolio = _safe(self._load_portfolio) or {}
        session   = mi.get("session_info") or {}
        return _safe(lambda: self._evaluate_symbol(
            symbol, mi, sm, strategy, risk, research, portfolio, session
        ))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _count_decisions(recs: List[Dict]) -> Dict[str, int]:
    from collections import Counter
    return dict(Counter(r["decision_type"] for r in recs))


def _estimate_rr(scores: Dict) -> float:
    """Advisory reward/risk estimate from strategy + risk scores."""
    reward_proxy = scores.get("strategy", 50.0) / 100.0
    risk_proxy   = max(0.01, (100 - scores.get("risk", 50.0)) / 100.0)
    rr = round(reward_proxy / risk_proxy, 2)
    return min(rr, 10.0)
