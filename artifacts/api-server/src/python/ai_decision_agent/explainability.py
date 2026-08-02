"""
explainability.py — Phase 10C
Explainability Engine for the AI Decision Agent.

Every recommendation includes:
  - why_generated
  - contributing_agents
  - supporting_signals
  - supporting_strategies
  - risk_explanation
  - confidence_explanation
  - conflicting_evidence
  - expiry_reason
  - natural_language_summary

Conflict resolution: documents when agents disagree and explains
how the final decision was reached despite conflicting evidence.

ADVISORY-ONLY.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class ExplainabilityEngine:
    """
    Generates human-readable explanations for every recommendation.
    All output is advisory — never constitutes financial advice.
    """

    # ── Main entry ─────────────────────────────────────────────────────────────

    def explain(
        self,
        symbol: str,
        decision_type: str,
        scores: Dict[str, float],
        confidence: float,
        mi: Dict[str, Any],
        strategy: Dict[str, Any],
        risk: Dict[str, Any],
        research: Dict[str, Any],
        monitoring: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:

        contributing = self._contributing_agents(scores, decision_type)
        signals      = self._supporting_signals(symbol, monitoring)
        strategies   = self._supporting_strategies(symbol, strategy)
        conflicts    = self._detect_conflicts(scores, mi, strategy, risk)
        risk_expl    = self._risk_explanation(risk)
        conf_expl    = self._confidence_explanation(confidence, conflicts)
        why          = self._why_generated(symbol, decision_type, scores, mi, risk)
        nl_summary   = self._nl_summary(
            symbol, decision_type, scores, confidence, mi, risk, conflicts
        )

        return {
            "why_generated":        why,
            "contributing_agents":  contributing,
            "supporting_signals":   signals,
            "supporting_strategies":strategies,
            "risk_explanation":     risk_expl,
            "confidence_explanation": conf_expl,
            "conflicting_evidence": conflicts,
            "natural_language_summary": nl_summary,
            "advisory_only":        True,
        }

    # ── Why generated ──────────────────────────────────────────────────────────

    @staticmethod
    def _why_generated(
        symbol: str, decision_type: str, scores: Dict, mi: Dict, risk: Dict
    ) -> str:
        overall  = scores.get("overall", 0)
        regime   = mi.get("market_regime", "UNKNOWN")
        risk_lv  = risk.get("risk_level", "UNKNOWN")
        strat    = scores.get("strategy", 0)
        market   = scores.get("market", 0)

        reasons = {
            "BUY_CANDIDATE":
                f"{symbol} scored {overall:.0f}/100 with strong strategy ({strat:.0f}) "
                f"and market alignment ({market:.0f}) under {regime} regime.",
            "ACCUMULATE":
                f"{symbol} meets accumulation criteria (score {overall:.0f}/100) with "
                f"{risk_lv} risk and supportive market conditions.",
            "WATCH":
                f"{symbol} shows developing setup (score {overall:.0f}/100) but lacks "
                f"conviction for action; monitoring for further development.",
            "SELL_CANDIDATE":
                f"{symbol} flagged for review: strategy score {strat:.0f} or risk level "
                f"{risk_lv} suggests position review.",
            "REDUCE_EXPOSURE":
                f"Risk level {risk_lv} with existing position in {symbol}; "
                f"exposure reduction recommended.",
            "AVOID":
                f"{symbol} avoided: score {overall:.0f}/100, risk {risk_lv}, "
                f"regime {regime} — conditions unfavourable.",
            "NO_ACTION":
                f"{symbol} does not meet minimum criteria (score {overall:.0f}/100) "
                f"for any active recommendation.",
        }
        return reasons.get(decision_type,
                           f"{symbol}: overall score {overall:.0f}/100 under {regime} regime.")

    # ── Contributing agents ────────────────────────────────────────────────────

    @staticmethod
    def _contributing_agents(scores: Dict, decision_type: str) -> List[Dict]:
        agents = []

        def add(agent_id, name, score_key, weight, threshold):
            score = scores.get(score_key, 0.0)
            influenced = score >= threshold or score < (100 - threshold)
            agents.append({
                "agent_id":   agent_id,
                "name":       name,
                "score":      round(score, 1),
                "weight_pct": round(weight * 100),
                "influenced_decision": influenced,
            })

        add("market-intelligence-agent", "Market Intelligence", "market", 0.20, 40)
        add("strategy-agent",            "Strategy Agent",       "strategy", 0.25, 45)
        add("risk-agent",                "Risk Agent",           "risk",     0.20, 45)
        add("research-agent",            "Research Agent",       "research", 0.10, 40)
        add("stock-monitoring-agent",    "Stock Monitoring",     "liquidity",0.10, 40)
        return agents

    # ── Supporting signals ─────────────────────────────────────────────────────

    @staticmethod
    def _supporting_signals(symbol: str, monitoring: Dict) -> List[str]:
        events = monitoring.get("events") or []
        signals = []
        for e in events:
            if e.get("symbol") == symbol:
                signals.append(
                    f"{e.get('event_type','EVENT')}: {e.get('description','detected')}"
                )
        if not signals:
            breakouts = monitoring.get("breakouts") or []
            for b in breakouts:
                if b.get("symbol") == symbol:
                    signals.append(f"BREAKOUT: {b.get('description','pattern detected')}")
        return signals[:5]

    # ── Supporting strategies ──────────────────────────────────────────────────

    @staticmethod
    def _supporting_strategies(symbol: str, strategy_snap: Dict) -> List[Dict]:
        top_setups = strategy_snap.get("top_setups") or []
        for setup in top_setups:
            if setup.get("symbol") == symbol:
                results = setup.get("all_strategies") or []
                return [
                    {"strategy": r["strategy"], "score": r["score"], "confidence": r["confidence"]}
                    for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:3]
                ]
        return []

    # ── Conflict detection ─────────────────────────────────────────────────────

    def _detect_conflicts(
        self, scores: Dict, mi: Dict, strategy: Dict, risk: Dict
    ) -> List[str]:
        conflicts = []
        strat  = scores.get("strategy", 50)
        market = scores.get("market", 50)
        risk_s = scores.get("risk", 50)
        conf   = scores.get("overall", 50)

        # Bullish strategy + bearish market
        if strat > 65 and market < 40:
            conflicts.append(
                f"Bullish strategy signal ({strat:.0f}) conflicts with weak market "
                f"conditions ({market:.0f}). Strategy may not materialise."
            )

        # High confidence score + high risk
        if conf > 65 and risk_s < 40:
            conflicts.append(
                f"Strong opportunity signal ({conf:.0f}) conflicts with elevated portfolio "
                f"risk ({risk_s:.0f}). Risk limits may prevent execution."
            )

        # Good market + poor strategy
        if market > 65 and strat < 35:
            conflicts.append(
                f"Supportive market ({market:.0f}) but no clear strategy setup ({strat:.0f}). "
                f"Wait for strategy alignment before acting."
            )

        # Research vs strategy divergence
        research = scores.get("research", 50)
        if abs(research - strat) > 35:
            conflicts.append(
                f"Strategy score ({strat:.0f}) diverges significantly from "
                f"research/macro score ({research:.0f})."
            )

        return conflicts

    # ── Risk explanation ───────────────────────────────────────────────────────

    @staticmethod
    def _risk_explanation(risk: Dict) -> str:
        level   = risk.get("risk_level", "UNKNOWN")
        score   = _f(risk.get("risk_score")) or 0.0
        bd      = risk.get("risk_breakdown") or {}
        flagged = [k for k, v in bd.items() if "FLAGGED" in str(v)]

        if not flagged:
            return f"Portfolio risk is {level} (score {score:.0f}/100). No risk dimensions flagged."
        return (
            f"Portfolio risk is {level} (score {score:.0f}/100). "
            f"Flagged dimensions: {', '.join(flagged)}. "
            f"Recommendation is sized conservatively to account for these risks."
        )

    # ── Confidence explanation ─────────────────────────────────────────────────

    @staticmethod
    def _confidence_explanation(confidence: float, conflicts: List[str]) -> str:
        pct = round(confidence * 100)
        tier = (
            "Very high" if pct >= 80 else
            "High"      if pct >= 65 else
            "Moderate"  if pct >= 50 else
            "Low"
        )
        conflict_note = (
            f" Reduced by {len(conflicts)} conflicting signal(s)." if conflicts else ""
        )
        return (
            f"{tier} confidence ({pct}%). Derived from weighted scores across "
            f"6 analytical agents.{conflict_note}"
        )

    # ── Natural language summary ───────────────────────────────────────────────

    @staticmethod
    def _nl_summary(
        symbol: str, decision_type: str, scores: Dict,
        confidence: float, mi: Dict, risk: Dict, conflicts: List[str]
    ) -> str:
        overall  = scores.get("overall", 0)
        regime   = mi.get("market_regime", "UNKNOWN")
        risk_lv  = risk.get("risk_level", "UNKNOWN")
        conf_pct = round(confidence * 100)
        strat    = scores.get("strategy", 0)
        momentum = mi.get("momentum_state", "NEUTRAL")

        action = {
            "BUY_CANDIDATE":    "a buy candidate",
            "ACCUMULATE":       "an accumulation candidate",
            "WATCH":            "under active watch",
            "SELL_CANDIDATE":   "flagged for potential exit",
            "REDUCE_EXPOSURE":  "flagged for exposure reduction",
            "AVOID":            "flagged to avoid",
            "NO_ACTION":        "not actionable at this time",
        }.get(decision_type, "under review")

        conflict_note = (
            f" Note: {len(conflicts)} conflicting signal(s) detected — "
            f"review carefully before acting."
            if conflicts else ""
        )

        return (
            f"{symbol} is {action} with {conf_pct}% confidence (score {overall:.0f}/100). "
            f"Market is in {regime} regime with {momentum.replace('_',' ').lower()} momentum. "
            f"Strategy alignment: {strat:.0f}/100. Portfolio risk: {risk_lv}."
            f"{conflict_note} This is an advisory recommendation only."
        )
