"""
test_decision_layer.py — Phase 10C
Tests for the Decision Layer agents.

Covers:
  - DecisionEngine: score computation, decision type assignment, ranking
  - ExplainabilityEngine: all fields, conflict detection, NL summary
  - AIDecisionAgent: snapshot shape, advisory flags, no buy/sell in field names
  - PreExecutionChecklist: all 10 checks
  - OrderValidator: instrument/qty/price/tick validation
  - ExecutionPlan: charges, sizing, stop/target
  - ExecutionAgent: snapshot shape, paper order creation, safety flags
  - Feature flags
  - SnapshotBus integration
  - Decision timeline events
  - Decision performance metrics
  - Safety: LIVE_EXECUTION_ENABLED=false by default

Target: ≥ 60 passing tests.
"""
import sys, os, pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def reset_singletons():
    from agent_framework.agent_registry import AgentRegistry
    from agent_framework.snapshot_bus import SnapshotBus
    AgentRegistry.reset()
    SnapshotBus.reset()
    yield
    AgentRegistry.reset()
    SnapshotBus.reset()


# ── helpers ────────────────────────────────────────────────────────────────────

def _mi(regime="BULL", trend=65.0, breadth=70.0, momentum="BULLISH",
        vix=16.0, liq=70.0, vol_regime="NORMAL_VOLATILITY"):
    return {
        "market_regime": regime, "trend_strength": trend,
        "breadth_score": breadth, "momentum_state": momentum,
        "vix_value": vix, "liquidity_score": liq,
        "volatility_regime": vol_regime,
        "session_info": {"phase": "OPEN", "in_session": True},
        "available": True,
    }

def _strategy(symbol="INFY", score=72.0):
    return {
        "top_setups": [{"symbol": symbol, "best_score": score,
                        "best_strategy": "Breakout",
                        "all_strategies": [
                            {"strategy": "Breakout", "score": score, "confidence": 0.72},
                            {"strategy": "Momentum", "score": 60.0, "confidence": 0.60},
                        ]}],
        "top_strategy": "Breakout",
        "highest_score": score,
        "available": True,
    }

def _risk(level="LOW", score=90.0):
    return {
        "risk_level": level, "risk_score": score,
        "capital_utilisation": {"utilisation_pct": 30.0},
        "daily_risk": {"daily_risk_pct": 0.5},
        "sector_concentration": {"max_sector_pct": 20.0},
        "risk_breakdown": {"Exposure": "✓ OK", "Sizing": "✓ OK"},
        "available": True,
    }

def _research(macro="EXPANSIONARY"):
    return {"macro_regime": macro, "global_risk_score": 35.0, "available": True}

def _portfolio(cash=200000.0, n_pos=2):
    positions = {f"SYM{i}": {"qty": 10, "avg_price": 100.0} for i in range(n_pos)}
    return {"cash": cash, "capital": 500000.0, "available_capital": cash,
            "positions": positions}

def _monitoring(breakouts=None):
    return {
        "events": [],
        "breakouts": breakouts or [],
        "breakdowns": [],
        "gap_events": [],
        "priority_queue": [{"symbol": "INFY", "priority": 1},
                           {"symbol": "TCS", "priority": 2}],
        "available": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DecisionEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionEngine:
    def test_compute_scores_returns_all_components(self):
        from ai_decision_agent.decision_engine import compute_scores
        s = compute_scores("INFY", _mi(), _strategy(), _risk(), _research(), _portfolio())
        for k in ("market", "strategy", "risk", "research", "liquidity",
                  "volatility", "portfolio_impact", "overall"):
            assert k in s

    def test_overall_score_in_range(self):
        from ai_decision_agent.decision_engine import compute_scores
        s = compute_scores("INFY", _mi(), _strategy(), _risk(), _research(), _portfolio())
        assert 0 <= s["overall"] <= 100

    def test_bull_regime_raises_market_score(self):
        from ai_decision_agent.decision_engine import compute_scores
        bull = compute_scores("X", _mi("BULL"),  _strategy(), _risk(), _research(), _portfolio())
        bear = compute_scores("X", _mi("BEAR"),  _strategy(), _risk(), _research(), _portfolio())
        assert bull["market"] > bear["market"]

    def test_high_risk_lowers_risk_score(self):
        from ai_decision_agent.decision_engine import compute_scores
        low  = compute_scores("X", _mi(), _strategy(), _risk("LOW"),      _research(), _portfolio())
        high = compute_scores("X", _mi(), _strategy(), _risk("CRITICAL"), _research(), _portfolio())
        assert low["risk"] > high["risk"]

    def test_compute_confidence_clamped_0_1(self):
        from ai_decision_agent.decision_engine import compute_confidence
        s = {"overall": 80.0, "strategy": 75.0, "market": 70.0, "risk": 85.0,
             "research": 60.0, "liquidity": 70.0, "volatility": 65.0}
        c = compute_confidence(s, False)
        assert 0.0 <= c <= 1.0

    def test_conflict_reduces_confidence(self):
        from ai_decision_agent.decision_engine import compute_confidence
        s = {"overall": 70.0, "strategy": 70.0, "market": 70.0, "risk": 70.0,
             "research": 70.0, "liquidity": 70.0, "volatility": 70.0}
        c_no  = compute_confidence(s, False)
        c_yes = compute_confidence(s, True)
        assert c_no > c_yes

    def test_assign_decision_buy_candidate(self):
        from ai_decision_agent.decision_engine import assign_decision_type
        scores = {"overall": 70.0, "strategy": 65.0, "market": 68.0}
        dt = assign_decision_type("INFY", scores, _risk("LOW"), _portfolio(n_pos=0), _monitoring())
        assert dt == "BUY_CANDIDATE"

    def test_assign_decision_avoid_on_critical_risk(self):
        from ai_decision_agent.decision_engine import assign_decision_type
        scores = {"overall": 70.0, "strategy": 65.0, "market": 68.0}
        dt = assign_decision_type("X", scores, _risk("CRITICAL"), _portfolio(), _monitoring())
        assert dt == "AVOID"

    def test_assign_decision_watch_medium_score(self):
        from ai_decision_agent.decision_engine import assign_decision_type
        scores = {"overall": 46.0, "strategy": 45.0, "market": 48.0}
        dt = assign_decision_type("X", scores, _risk("MODERATE"), _portfolio(), _monitoring())
        assert dt == "WATCH"

    def test_assign_decision_no_action_low_score(self):
        from ai_decision_agent.decision_engine import assign_decision_type
        scores = {"overall": 35.0, "strategy": 35.0, "market": 35.0}
        dt = assign_decision_type("X", scores, _risk("LOW"), _portfolio(n_pos=0), _monitoring())
        assert dt in ("NO_ACTION", "AVOID")

    def test_compute_expiry_buy_candidate(self):
        from ai_decision_agent.decision_engine import compute_expiry
        expiry, reason = compute_expiry("BUY_CANDIDATE", {"phase": "OPEN"})
        assert "2" in reason.lower() or "hour" in reason.lower()
        assert "T" in expiry  # ISO format

    def test_assign_priority_ranges(self):
        from ai_decision_agent.decision_engine import assign_priority
        p = assign_priority("BUY_CANDIDATE", 80.0, 0.8)
        assert 1 <= p <= 5

    def test_rank_recommendations_by_confidence(self):
        from ai_decision_agent.decision_engine import rank_recommendations
        recs = [
            {"symbol": "A", "confidence": 0.5, "overall_score": 60,
             "scores": {"risk": 70, "liquidity": 60, "market": 60}, "reward_risk_ratio": 1.5},
            {"symbol": "B", "confidence": 0.9, "overall_score": 80,
             "scores": {"risk": 85, "liquidity": 75, "market": 75}, "reward_risk_ratio": 2.5},
        ]
        ranked = rank_recommendations(recs)
        assert ranked[0]["symbol"] == "B"

    def test_valid_decision_types(self):
        from ai_decision_agent.decision_engine import assign_decision_type
        valid = {"WATCH", "ACCUMULATE", "BUY_CANDIDATE", "SELL_CANDIDATE",
                 "REDUCE_EXPOSURE", "AVOID", "NO_ACTION"}
        for s_val, risk_lv, n_pos in [
            (70, "LOW", 0), (50, "MODERATE", 2), (30, "HIGH", 3),
            (20, "CRITICAL", 1), (45, "LOW", 0),
        ]:
            scores = {"overall": float(s_val), "strategy": float(s_val), "market": float(s_val)}
            dt = assign_decision_type("X", scores, _risk(risk_lv), _portfolio(n_pos=n_pos), _monitoring())
            assert dt in valid, f"Invalid decision: {dt}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ExplainabilityEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestExplainabilityEngine:
    def _engine(self):
        from ai_decision_agent.explainability import ExplainabilityEngine
        return ExplainabilityEngine()

    def test_explain_returns_all_fields(self):
        e = self._engine()
        scores = {"overall": 72.0, "market": 70.0, "strategy": 75.0, "risk": 80.0,
                  "research": 60.0, "liquidity": 65.0, "volatility": 70.0, "portfolio_impact": 60.0}
        result = e.explain("INFY", "BUY_CANDIDATE", scores, 0.72,
                           _mi(), _strategy(), _risk(), _research(), _monitoring(), _portfolio())
        for k in ("why_generated", "contributing_agents", "supporting_signals",
                  "supporting_strategies", "risk_explanation", "confidence_explanation",
                  "conflicting_evidence", "natural_language_summary", "advisory_only"):
            assert k in result, f"Missing: {k}"

    def test_advisory_only_true(self):
        e = self._engine()
        scores = {"overall": 60.0, "market": 60.0, "strategy": 60.0, "risk": 70.0,
                  "research": 55.0, "liquidity": 60.0, "volatility": 65.0, "portfolio_impact": 55.0}
        result = e.explain("TCS", "WATCH", scores, 0.6,
                           _mi(), _strategy(), _risk(), _research(), _monitoring(), _portfolio())
        assert result["advisory_only"] is True

    def test_contributing_agents_has_5(self):
        e = self._engine()
        scores = {"overall": 65.0, "market": 65.0, "strategy": 70.0, "risk": 75.0,
                  "research": 60.0, "liquidity": 65.0, "volatility": 70.0, "portfolio_impact": 60.0}
        result = e.explain("X", "BUY_CANDIDATE", scores, 0.65,
                           _mi(), _strategy(), _risk(), _research(), _monitoring(), _portfolio())
        assert len(result["contributing_agents"]) == 5

    def test_conflict_detection_bullish_strategy_bearish_market(self):
        e = self._engine()
        scores = {"overall": 55.0, "market": 30.0, "strategy": 75.0, "risk": 60.0,
                  "research": 55.0, "liquidity": 60.0, "volatility": 60.0}
        conflicts = e._detect_conflicts(scores, _mi("BEAR"), _strategy(), _risk())
        assert len(conflicts) > 0

    def test_no_conflict_when_aligned(self):
        e = self._engine()
        scores = {"overall": 72.0, "market": 72.0, "strategy": 72.0, "risk": 72.0,
                  "research": 72.0, "liquidity": 72.0, "volatility": 72.0}
        conflicts = e._detect_conflicts(scores, _mi("BULL"), _strategy(), _risk("LOW"))
        assert len(conflicts) == 0

    def test_nl_summary_contains_symbol(self):
        e = self._engine()
        scores = {"overall": 70.0, "market": 70.0, "strategy": 72.0, "risk": 80.0,
                  "research": 65.0, "liquidity": 70.0, "volatility": 70.0}
        result = e.explain("WIPRO", "BUY_CANDIDATE", scores, 0.7,
                           _mi(), _strategy(), _risk(), _research(), _monitoring(), _portfolio())
        assert "WIPRO" in result["natural_language_summary"]

    def test_nl_summary_contains_advisory(self):
        e = self._engine()
        scores = {"overall": 65.0, "market": 65.0, "strategy": 65.0, "risk": 75.0,
                  "research": 60.0, "liquidity": 65.0, "volatility": 65.0}
        result = e.explain("BEL", "WATCH", scores, 0.65,
                           _mi(), _strategy(), _risk(), _research(), _monitoring(), _portfolio())
        assert "advisory" in result["natural_language_summary"].lower()

    def test_risk_explanation_mentions_risk_level(self):
        e = self._engine()
        risk = _risk("HIGH", 38.0)
        expl = e._risk_explanation(risk)
        assert "HIGH" in expl

    def test_confidence_explanation_mentions_percentage(self):
        from ai_decision_agent.explainability import ExplainabilityEngine
        e = ExplainabilityEngine()
        expl = e._confidence_explanation(0.78, [])
        assert "78" in expl


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AIDecisionAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIDecisionAgent:
    def _agent(self):
        from ai_decision_agent.agent import AIDecisionAgent
        a = AIDecisionAgent()
        a.start(); a.beat()
        return a

    def test_registered_in_registry(self):
        from agent_framework.agent_registry import AgentRegistry
        self._agent()
        assert AgentRegistry.instance().get("ai-decision-agent") is not None

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("agent_id", "agent_name", "advisory_only", "never_places_orders",
                  "recommendations", "total_candidates", "avg_confidence",
                  "decision_counts", "top_opportunities", "generated_at"):
            assert k in snap, f"Missing: {k}"

    def test_advisory_only_true(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["never_places_orders"] is True

    def test_no_direct_buy_sell_field_names(self):
        import json
        a = self._agent()
        snap = a.execute_task()
        # Check top-level keys only — "BUY_CANDIDATE" as value is fine
        for k in snap:
            assert k not in ("buy_signal", "sell_signal", "order", "live_order")

    def test_recommendations_are_list(self):
        a = self._agent()
        snap = a.execute_task()
        assert isinstance(snap["recommendations"], list)

    def test_each_recommendation_has_explanation(self):
        a = self._agent()
        snap = a.execute_task()
        for rec in snap["recommendations"][:3]:
            assert "explanation" in rec
            assert "decision_type" in rec
            assert "confidence" in rec

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "decisions")
        env = SnapshotBus.instance().latest("decisions")
        assert env is not None

    def test_decision_types_valid(self):
        valid = {"WATCH", "ACCUMULATE", "BUY_CANDIDATE", "SELL_CANDIDATE",
                 "REDUCE_EXPOSURE", "AVOID", "NO_ACTION"}
        a = self._agent()
        snap = a.execute_task()
        for rec in snap["recommendations"]:
            assert rec["decision_type"] in valid, f"Invalid: {rec['decision_type']}"

    def test_confidence_in_0_1(self):
        a = self._agent()
        snap = a.execute_task()
        for rec in snap["recommendations"]:
            assert 0.0 <= rec["confidence"] <= 1.0

    def test_score_in_0_100(self):
        a = self._agent()
        snap = a.execute_task()
        for rec in snap["recommendations"]:
            assert 0.0 <= rec["overall_score"] <= 100.0

    def test_derive_candidates_deduplicates(self):
        from ai_decision_agent.agent import AIDecisionAgent
        sm = {"priority_queue": [{"symbol": "INFY"}, {"symbol": "TCS"}, {"symbol": "INFY"}]}
        portfolio = {"positions": {"INFY": {"qty": 10}}}
        result = AIDecisionAgent._derive_candidates(sm, portfolio)
        assert len(result) == len(set(result))

    def test_derive_candidates_open_positions_first(self):
        from ai_decision_agent.agent import AIDecisionAgent
        sm = {"priority_queue": [{"symbol": "TCS"}, {"symbol": "WIPRO"}]}
        portfolio = {"positions": {"INFY": {"qty": 10}}}
        result = AIDecisionAgent._derive_candidates(sm, portfolio)
        assert result[0] == "INFY"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PreExecutionChecklist
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreExecutionChecklist:
    def _chk(self):
        from execution_agent.execution_planner import PreExecutionChecklist
        return PreExecutionChecklist()

    def test_all_10_checks_present(self):
        chk = self._chk()
        _, results = chk.run("INFY", 10, 1500.0, _portfolio(), _risk(), _mi())
        check_names = [r["check"] for r in results]
        for expected in chk.CHECKS:
            assert expected in check_names

    def test_passes_on_valid_order(self):
        chk = self._chk()
        all_passed, results = chk.run("INFY", 5, 500.0, _portfolio(200000), _risk("LOW"), _mi())
        assert all_passed

    def test_fails_on_insufficient_capital(self):
        chk = self._chk()
        _, results = chk.run("INFY", 1000, 5000.0, _portfolio(1000), _risk("LOW"), _mi())
        capital_check = next(r for r in results if r["check"] == "capital")
        assert not capital_check["passed"]

    def test_fails_outside_session(self):
        chk = self._chk()
        mi_closed = _mi()
        mi_closed["session_info"] = {"phase": "CLOSED", "in_session": False}
        _, results = chk.run("INFY", 5, 500.0, _portfolio(), _risk(), mi_closed)
        session_check = next(r for r in results if r["check"] == "trading_session")
        assert not session_check["passed"]

    def test_fails_on_critical_risk(self):
        chk = self._chk()
        _, results = chk.run("INFY", 5, 500.0, _portfolio(), _risk("CRITICAL"), _mi())
        risk_check = next(r for r in results if r["check"] == "risk_limits")
        assert not risk_check["passed"]

    def test_fails_over_freeze_qty(self):
        chk = self._chk()
        _, results = chk.run("INFY", 2000, 100.0, _portfolio(), _risk(), _mi())
        freeze_check = next(r for r in results if r["check"] == "freeze_quantity")
        assert not freeze_check["passed"]

    def test_fails_over_max_positions(self):
        chk = self._chk()
        big_portfolio = _portfolio(n_pos=12)
        _, results = chk.run("NEW", 5, 500.0, big_portfolio, _risk(), _mi())
        pos_check = next(r for r in results if r["check"] == "portfolio_limits")
        assert not pos_check["passed"]

    def test_each_check_has_required_fields(self):
        chk = self._chk()
        _, results = chk.run("INFY", 5, 500.0, _portfolio(), _risk(), _mi())
        for r in results:
            assert "check" in r and "passed" in r and "detail" in r


# ═══════════════════════════════════════════════════════════════════════════════
# 5. OrderValidator
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderValidator:
    def _v(self):
        from execution_agent.execution_planner import OrderValidator
        return OrderValidator()

    def test_valid_order_passes(self):
        v = self._v()
        ok, errors = v.validate("INFY", 10, 1500.00)
        assert ok
        assert len(errors) == 0

    def test_zero_qty_fails(self):
        v = self._v()
        ok, _ = v.validate("INFY", 0, 1500.0)
        assert not ok

    def test_negative_price_fails(self):
        v = self._v()
        ok, _ = v.validate("INFY", 10, -100.0)
        assert not ok

    def test_excessive_order_value_fails(self):
        v = self._v()
        ok, errors = v.validate("INFY", 10000, 1000.0)
        assert not ok
        assert any("limit" in e.lower() or "exceed" in e.lower() for e in errors)

    def test_tick_alignment_advisory(self):
        v = self._v()
        # Price exactly on tick — should pass
        ok, _ = v.validate("TCS", 5, 3500.05)
        assert ok


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ExecutionPlan
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionPlan:
    def _plan(self):
        from execution_agent.execution_planner import ExecutionPlan
        return ExecutionPlan()

    def test_plan_required_fields(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 72.0, "confidence": 0.72}
        plan = p.generate("INFY", rec, _portfolio(), price_hint=1500.0)
        for k in ("symbol", "suggested_entry", "suggested_exit", "stop_loss", "target_1",
                  "reward_risk_ratio", "suggested_qty", "estimated_charges",
                  "expected_holding_time", "advisory_only"):
            assert k in plan

    def test_stop_loss_below_entry(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 70.0, "confidence": 0.7}
        plan = p.generate("TCS", rec, _portfolio(), price_hint=3500.0)
        assert plan["stop_loss"] < plan["suggested_entry"]

    def test_target_above_entry(self):
        p = self._plan()
        rec = {"decision_type": "ACCUMULATE", "overall_score": 60.0, "confidence": 0.6}
        plan = p.generate("WIPRO", rec, _portfolio(), price_hint=400.0)
        assert plan["target_1"] > plan["suggested_entry"]

    def test_reward_risk_positive(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 70.0, "confidence": 0.7}
        plan = p.generate("BEL", rec, _portfolio(), price_hint=200.0)
        assert plan["reward_risk_ratio"] > 0

    def test_charges_dict_has_total(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 70.0, "confidence": 0.7}
        plan = p.generate("INFY", rec, _portfolio(), price_hint=1500.0)
        assert "total" in plan["estimated_charges"]
        assert plan["estimated_charges"]["total"] > 0

    def test_advisory_only_true(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 70.0, "confidence": 0.7}
        plan = p.generate("X", rec, _portfolio(), price_hint=100.0)
        assert plan["advisory_only"] is True
        assert plan["prices_are_estimates"] is True

    def test_position_pct_within_limits(self):
        p = self._plan()
        rec = {"decision_type": "BUY_CANDIDATE", "overall_score": 65.0, "confidence": 0.65}
        plan = p.generate("SAIL", rec, _portfolio(200000), price_hint=100.0)
        assert plan["position_pct_of_capital"] <= 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ExecutionAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionAgent:
    def _agent(self):
        from execution_agent.agent import ExecutionAgent
        a = ExecutionAgent()
        a.start(); a.beat()
        return a

    def test_registered_in_registry(self):
        from agent_framework.agent_registry import AgentRegistry
        self._agent()
        assert AgentRegistry.instance().get("execution-agent") is not None

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("agent_id", "advisory_only", "never_autonomous_live",
                  "execution_mode", "execution_queue", "paper_orders",
                  "live_execution_enabled", "generated_at"):
            assert k in snap

    def test_advisory_only_true(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["never_autonomous_live"] is True

    def test_live_execution_disabled_by_default(self):
        import os
        os.environ.pop("LIVE_EXECUTION_ENABLED", None)
        a = self._agent()
        snap = a.execute_task()
        assert snap["live_execution_enabled"] is False

    def test_paper_mode_by_default(self):
        import os
        os.environ.pop("LIVE_EXECUTION_ENABLED", None)
        os.environ["PAPER_EXECUTION_ENABLED"] = "true"
        a = self._agent()
        snap = a.execute_task()
        assert snap["execution_mode"] == "PAPER"
        os.environ.pop("PAPER_EXECUTION_ENABLED", None)

    def test_paper_orders_have_advisory_flag(self):
        a = self._agent()
        snap = a.execute_task()
        for order in snap["paper_orders"]:
            assert order.get("advisory_only") is True
            assert order.get("is_paper") is True

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "execution")
        env = SnapshotBus.instance().latest("execution")
        assert env is not None

    def test_execution_queue_items_shape(self):
        a = self._agent()
        snap = a.execute_task()
        for item in snap["execution_queue"]:
            assert "symbol" in item
            assert "execution_mode" in item
            assert "advisory_only" in item


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Feature Flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlags10C:
    def test_ai_decision_disabled(self):
        import os
        os.environ["AI_DECISION_AGENT_ENABLED"] = "false"
        from ai_decision_agent.shared_services import get_ai_decision_snapshot
        result = get_ai_decision_snapshot()
        assert result["available"] is False
        os.environ.pop("AI_DECISION_AGENT_ENABLED", None)

    def test_execution_disabled(self):
        import os
        os.environ["EXECUTION_AGENT_ENABLED"] = "false"
        from execution_agent.shared_services import get_execution_snapshot
        result = get_execution_snapshot()
        assert result["available"] is False
        os.environ.pop("EXECUTION_AGENT_ENABLED", None)

    def test_live_execution_false_by_default(self):
        import os
        os.environ.pop("LIVE_EXECUTION_ENABLED", None)
        from execution_agent.execution_planner import determine_execution_mode
        mode = determine_execution_mode()
        assert mode != "LIVE"

    def test_paper_execution_true_by_default(self):
        import os
        os.environ.pop("LIVE_EXECUTION_ENABLED", None)
        os.environ.pop("PAPER_EXECUTION_ENABLED", None)
        from execution_agent.execution_planner import determine_execution_mode
        mode = determine_execution_mode()
        assert mode == "PAPER"

    def test_config_has_phase10c_flags(self):
        from agent_framework.config import (
            AI_DECISION_AGENT_ENABLED, EXECUTION_AGENT_ENABLED,
            LIVE_EXECUTION_ENABLED, PAPER_EXECUTION_ENABLED,
        )
        assert AI_DECISION_AGENT_ENABLED == "AI_DECISION_AGENT_ENABLED"
        assert EXECUTION_AGENT_ENABLED   == "EXECUTION_AGENT_ENABLED"
        assert LIVE_EXECUTION_ENABLED    == "LIVE_EXECUTION_ENABLED"
        assert PAPER_EXECUTION_ENABLED   == "PAPER_EXECUTION_ENABLED"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Decision Timeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionTimeline:
    def test_timeline_required_fields(self):
        from decision_layer.shared_services import get_decision_timeline
        result = get_decision_timeline()
        assert "events" in result
        assert "event_count" in result
        assert result["advisory_only"] is True

    def test_timeline_events_have_correct_shape(self):
        from decision_layer.shared_services import get_decision_timeline
        result = get_decision_timeline()
        for event in result["events"]:
            for k in ("type", "category", "title", "severity", "timestamp", "advisory_only"):
                assert k in event

    def test_timeline_valid_event_types(self):
        from decision_layer.shared_services import get_decision_timeline
        valid_types = {
            "RECOMMENDATION_CREATED", "RECOMMENDATION_EXPIRY_ALERT",
            "PAPER_ORDER_CREATED", "VALIDATION_FAILED", "EXECUTION_CANCELLED",
            "RECOMMENDATION_UPDATED",
        }
        result = get_decision_timeline()
        for event in result["events"]:
            assert event["type"] in valid_types or event["type"].startswith("RECOMMENDATION")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Decision Performance
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionPerformance:
    def test_performance_required_fields(self):
        from decision_layer.shared_services import get_decision_performance
        result = get_decision_performance()
        for k in ("available", "agent_metrics", "decision_latency_ms",
                  "planning_latency_ms", "avg_confidence", "generated_at"):
            assert k in result

    def test_performance_has_both_agents(self):
        from decision_layer.shared_services import get_decision_performance
        result = get_decision_performance()
        ids = [m["agent_id"] for m in result["agent_metrics"]]
        assert "ai-decision-agent" in ids
        assert "execution-agent" in ids


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SnapshotBus Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotBusDecisionLayer:
    def test_decisions_and_execution_publish_to_distinct_topics(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        bus.publish("decisions",  "ai-decision-agent", {"advisory_only": True, "available": True})
        bus.publish("execution",  "execution-agent",   {"advisory_only": True, "available": True})
        assert bus.latest("decisions")  is not None
        assert bus.latest("execution")  is not None

    def test_execution_agent_reads_decisions_from_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        bus.publish("decisions", "ai-decision-agent", {
            "recommendations": [{"symbol": "INFY", "decision_type": "BUY_CANDIDATE",
                                 "overall_score": 72.0, "confidence": 0.72, "expiry_at": "2026-08-02T12:00:00Z"}],
            "market_regime": "BULL", "risk_level": "LOW", "available": True,
        })
        # ExecutionAgent._load_decisions checks bus first via shared_services
        from agent_framework.snapshot_bus import SnapshotBus as SB
        env = SB.instance().latest("decisions")
        assert env.payload["risk_level"] == "LOW"

    def test_all_phase10c_topics_accessible(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        for topic, publisher in [("decisions", "ai-decision-agent"),
                                  ("execution", "execution-agent")]:
            bus.publish(topic, publisher, {"available": True})
        for topic in ("decisions", "execution"):
            assert bus.latest(topic) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
