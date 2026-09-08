"""
test_explainable_ai.py — Phase 7.4 test suite (75+ tests, all mocked)
"""
import sys
import types
import unittest
import pytest
from unittest.mock import MagicMock, patch
from task974_test_isolation import isolated_imports

# ── Stub all upstream modules BEFORE any explainable_ai import ────────────────

_SAMPLE_SIGNAL = {
    "stock": "RELIANCE",
    "symbol": "RELIANCE",
    "signal": "BUY",
    "confidence": 0.75,
    "price": 2450.0,
    "target": 2520.0,
    "stop_loss": 2410.0,
    "risk_level": "MEDIUM",
    "regime": "TRENDING_UP",
    "reasons": ["EMA crossover bullish", "RSI in optimal zone"],
    "explanation": {
        "trend": "Price is in uptrend above EMA20 and EMA50.",
        "momentum": "MACD bullish crossover; RSI at 58.",
        "volume": "Volume 1.8× above 20-period average.",
        "indicator_summary": "Bullish signals from 7/9 indicators.",
        "regime_impact": "Trending-up regime favours momentum entries.",
        "plain_english": "RELIANCE shows a bullish breakout with strong volume confirmation.",
    },
    "timeframe_alignment": True,
}

_SAMPLE_SIGNAL_SELL = {
    "stock": "TCS",
    "symbol": "TCS",
    "signal": "SELL",
    "confidence": 0.62,
    "price": 3800.0,
    "target": 3700.0,
    "stop_loss": 3860.0,
    "risk_level": "HIGH",
    "regime": "TRENDING_DOWN",
    "reasons": ["EMA crossover bearish", "RSI overbought"],
    "explanation": {
        "trend": "Bearish crossover on EMA.",
        "momentum": "RSI overbought at 72.",
        "volume": "Volume spike on sell-off.",
        "indicator_summary": "Bearish signals from 6/9 indicators.",
        "regime_impact": "Trending-down regime.",
        "plain_english": "TCS shows bearish momentum.",
    },
}

_MARKET_SNAP = {
    "available": True,
    "market_health_score": 72.0,
    "grade": "B",
    "trend": "BULLISH",
    "overall_outlook": "BULLISH",
    "top_opportunity": "RELIANCE",
}

_EVENT_SNAP = {
    "available": True,
    "intelligence_score": 65.0,
    "grade": "B",
    "total_events": 4,
    "high_priority_count": 1,
    "bullish_count": 3,
    "bearish_count": 1,
}

_MACRO_SNAP = {
    "available": True,
    "macro_score": 60.0,
    "grade": "B",
    "trend": "NEUTRAL",
    "global_sentiment_score": 55.0,
    "sentiment_label": "NEUTRAL",
    "india_vix": 14.5,
    "vix_regime": "LOW",
    "vix_risk_level": "LOW",
    "fii_posture": "BUYING",
    "upcoming_events": 2,
    "inflation_risk": "LOW",
}

_RISK_SNAP = {
    "available": True,
    "risk_optimisation_score": 68.0,
    "grade": "B",
    "max_drawdown": 0.08,
    "capital_efficiency": 70.0,
    "diversification_score": 65.0,
    "correlation_risk": 55.0,
}


def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    return mod


def _stub_modules():
    """Construct fresh test-local dependencies without modifying module state."""
    stubs = [
        "signals_store", "signals_cache",
        "market_intelligence_hub", "market_intelligence_hub.shared_services",
        "event_intelligence", "event_intelligence.shared_services",
        "macro_intelligence", "macro_intelligence.shared_services",
        "risk_optimisation", "risk_optimisation.shared_services",
        "config",
    ]
    modules = {name: _make_stub(name) for name in stubs}

    # Patch load_signals
    ss = modules["signals_store"]
    ss.load_signals = MagicMock(return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL])
    ss.load_signal_snapshots = MagicMock(return_value=[_SAMPLE_SIGNAL])

    # Patch snapshot functions
    mih_ss = modules["market_intelligence_hub.shared_services"]
    mih_ss.get_market_intelligence_snapshot = MagicMock(return_value=_MARKET_SNAP)

    ei_ss = modules["event_intelligence.shared_services"]
    ei_ss.get_event_intelligence_snapshot = MagicMock(return_value=_EVENT_SNAP)

    mac_ss = modules["macro_intelligence.shared_services"]
    mac_ss.get_macro_intelligence_snapshot = MagicMock(return_value=_MACRO_SNAP)

    ro_ss = modules["risk_optimisation.shared_services"]
    ro_ss.get_risk_optimisation_snapshot = MagicMock(return_value=_RISK_SNAP)

    cfg = modules["config"]
    cfg.DEFAULT_WATCHLIST = ["RELIANCE", "TCS"]

    return modules


@pytest.fixture(autouse=True)
def _isolated_dependencies():
    with isolated_imports(
        _stub_modules(),
        target_packages=("explainable_ai",),
        environment={"EXPLAINABLE_AI_ENABLED": "true"},
    ):
        yield

# ── Now import the module under test ─────────────────────────────────────────
import os

from explainable_ai.models import (
    is_enabled, disabled_response, explainability_grade, confidence_tier,
    ExplainableDecision, ScenarioAnalysis, HistoricalMatch, ConfidenceDecomposition,
    IndicatorContribution, DecisionTreeNode, BUY_SIGNALS, SELL_SIGNALS,
    RISK_LOW, RISK_MEDIUM, RISK_HIGH,
)
from explainable_ai.market_context_explainer import explain_market_context
from explainable_ai.event_context_explainer import explain_event_context
from explainable_ai.macro_context_explainer import explain_macro_context
from explainable_ai.risk_explainer import explain_risk
from explainable_ai.indicator_contributions import compute_contributions
from explainable_ai.confidence_analyzer import compute_confidence
from explainable_ai.scenario_generator import generate_scenarios
from explainable_ai.historical_similarity import find_historical_matches
from explainable_ai.decision_explainer import explain_decision, get_all_explainable_decisions
from explainable_ai.operator_summary import build_operator_summary


# =============================================================================
# 1. models.py
# =============================================================================

class TestModels(unittest.TestCase):

    def test_is_enabled_true(self):
        self.assertTrue(is_enabled())

    def test_is_enabled_false(self):
        with patch.dict(os.environ, {"EXPLAINABLE_AI_ENABLED": "false"}):
            self.assertFalse(is_enabled())

    def test_disabled_response(self):
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertFalse(r["available"])

    def test_disabled_response_with_caller(self):
        r = disabled_response("test_caller")
        self.assertEqual(r["status"], "DISABLED")

    def test_explainability_grade(self):
        self.assertEqual(explainability_grade(95), "A+")
        self.assertEqual(explainability_grade(85), "A")
        self.assertEqual(explainability_grade(75), "B")
        self.assertEqual(explainability_grade(60), "C")
        self.assertEqual(explainability_grade(30), "D")

    def test_confidence_tier(self):
        self.assertEqual(confidence_tier(85), "HIGH")
        self.assertEqual(confidence_tier(70), "MODERATE")
        self.assertEqual(confidence_tier(55), "LOW")
        self.assertEqual(confidence_tier(20), "VERY_LOW")

    def test_buy_sell_constants(self):
        self.assertIn("BUY", BUY_SIGNALS)
        self.assertIn("STRONG_BUY", BUY_SIGNALS)
        self.assertIn("SELL", SELL_SIGNALS)
        self.assertIn("STRONG_SELL", SELL_SIGNALS)

    def test_explainable_decision_primary_reasons_property(self):
        d = ExplainableDecision(
            symbol="TEST", signal_type="BUY",
            primary_reason="Reason A",
            secondary_reasons=["Reason B", "Reason C"],
            supporting_indicators=[], supporting_market_conditions=[],
            supporting_events=[], supporting_macro_conditions=[],
            ai_score=70, strategy_score=65, risk_score=60,
            final_confidence=72, explainability_score=80,
            grade="B", decision_tree={}, plain_english_summary="Test",
        )
        self.assertEqual(d.primary_reasons[0], "Reason A")
        self.assertIn("Reason B", d.primary_reasons)

    def test_explainable_decision_confidence_normalised(self):
        d = ExplainableDecision(
            symbol="TEST", signal_type="BUY",
            primary_reason="R", secondary_reasons=[],
            supporting_indicators=[], supporting_market_conditions=[],
            supporting_events=[], supporting_macro_conditions=[],
            ai_score=70, strategy_score=65, risk_score=60,
            final_confidence=72, explainability_score=80,
            grade="B", decision_tree={}, plain_english_summary="",
        )
        # confidence should be normalised from final_confidence
        self.assertLessEqual(d.confidence, 1.0)
        self.assertGreater(d.confidence, 0.0)

    def test_explainable_decision_to_dict_has_primary_reasons(self):
        d = ExplainableDecision(
            symbol="TEST", signal_type="BUY",
            primary_reason="R1", secondary_reasons=["R2"],
            supporting_indicators=[], supporting_market_conditions=[],
            supporting_events=[], supporting_macro_conditions=[],
            ai_score=70, strategy_score=65, risk_score=60,
            final_confidence=70, explainability_score=80,
            grade="B", decision_tree={}, plain_english_summary="",
        )
        dd = d.to_dict()
        self.assertIn("primary_reasons", dd)
        self.assertIn("R1", dd["primary_reasons"])

    def test_indicator_contribution_alias_fields(self):
        ic = IndicatorContribution(
            name="Trend", indicator_name="", contribution_pct=15.0,
            direction="BULLISH", description="Test", explanation="", weight_basis="test",
        )
        # __post_init__ fills alias
        self.assertEqual(ic.indicator_name, "Trend")
        self.assertEqual(ic.explanation, "Test")

    def test_scenario_analysis_to_dict(self):
        s = ScenarioAnalysis(
            scenario_type="BULLISH", probability=0.55, expected_return=3.2,
            key_conditions=["cond1"], risk_factors=["risk1"],
            narrative="narrative", price_target=2500.0,
        )
        d = s.to_dict()
        self.assertEqual(d["scenario_type"], "BULLISH")
        self.assertAlmostEqual(d["probability"], 0.55)

    def test_historical_match_to_dict(self):
        m = HistoricalMatch(
            symbol="RELIANCE", date="2026-01-15", signal_type="BUY",
            regime="TRENDING_UP", confidence=0.7, outcome="WIN",
            pnl_pct=2.5, similarity_score=0.75,
            match_reasons=["Same regime"], narrative="Matched.",
        )
        d = m.to_dict()
        self.assertEqual(d["symbol"], "RELIANCE")
        self.assertAlmostEqual(d["similarity_score"], 0.75)

    def test_confidence_decomposition_to_dict(self):
        cd = ConfidenceDecomposition(
            symbol="RELIANCE", overall_confidence=72.0, reliability_grade="B",
            technical_score=80.0, fundamental_score=50.0, market_score=72.0,
            event_score=60.0, macro_score=60.0, risk_score=68.0,
            regime_score=85.0, historical_score=75.0, narrative="Test",
        )
        d = cd.to_dict()
        self.assertAlmostEqual(d["overall_confidence"], 72.0)
        self.assertEqual(d["reliability_grade"], "B")


# =============================================================================
# 2. market_context_explainer.py
# =============================================================================

class TestMarketContextExplainer(unittest.TestCase):

    def test_explain_market_context_basic(self):
        r = explain_market_context(_MARKET_SNAP)
        self.assertTrue(r["available"])
        self.assertIn("narrative", r)
        self.assertIsInstance(r["bullet_points"], list)
        self.assertGreater(len(r["bullet_points"]), 0)

    def test_explain_market_context_bullish_narrative(self):
        r = explain_market_context(_MARKET_SNAP)
        self.assertIn("bullish", r["narrative"].lower())

    def test_explain_market_context_unavailable(self):
        r = explain_market_context({"available": False})
        self.assertFalse(r["available"])

    def test_explain_market_context_empty(self):
        r = explain_market_context({})
        self.assertFalse(r["available"])

    def test_explain_market_context_grade(self):
        r = explain_market_context(_MARKET_SNAP)
        self.assertEqual(r["grade"], "B")


# =============================================================================
# 3. event_context_explainer.py
# =============================================================================

class TestEventContextExplainer(unittest.TestCase):

    def test_explain_event_context_basic(self):
        r = explain_event_context(_EVENT_SNAP)
        self.assertTrue(r["available"])
        self.assertIn("narrative", r)
        self.assertEqual(r["total_events"], 4)

    def test_explain_event_context_bullish_net(self):
        r = explain_event_context(_EVENT_SNAP)
        self.assertEqual(r["net_sentiment"], "BULLISH")

    def test_explain_event_context_bearish_net(self):
        snap = {**_EVENT_SNAP, "bullish_count": 1, "bearish_count": 3, "available": True}
        r = explain_event_context(snap)
        self.assertEqual(r["net_sentiment"], "BEARISH")

    def test_explain_event_context_unavailable(self):
        r = explain_event_context({"available": False})
        self.assertFalse(r["available"])

    def test_explain_event_context_zero_events(self):
        snap = {**_EVENT_SNAP, "total_events": 0, "available": True}
        r = explain_event_context(snap)
        self.assertIn("No significant", r["narrative"])


# =============================================================================
# 4. macro_context_explainer.py
# =============================================================================

class TestMacroContextExplainer(unittest.TestCase):

    def test_explain_macro_context_basic(self):
        r = explain_macro_context(_MACRO_SNAP)
        self.assertTrue(r["available"])
        self.assertIn("narrative", r)
        self.assertAlmostEqual(r["macro_score"], 60.0)

    def test_explain_macro_context_vix(self):
        r = explain_macro_context(_MACRO_SNAP)
        self.assertIn("14.5", r["narrative"])

    def test_explain_macro_context_fii(self):
        r = explain_macro_context(_MACRO_SNAP)
        self.assertIn("buyers", r["narrative"].lower())

    def test_explain_macro_context_unavailable(self):
        r = explain_macro_context({"available": False})
        self.assertFalse(r["available"])

    def test_explain_macro_context_upcoming_events(self):
        r = explain_macro_context(_MACRO_SNAP)
        self.assertIn("2", r["narrative"])


# =============================================================================
# 5. risk_explainer.py
# =============================================================================

class TestRiskExplainer(unittest.TestCase):

    def test_explain_risk_basic(self):
        r = explain_risk(_RISK_SNAP)
        self.assertTrue(r["available"])
        self.assertIn("narrative", r)
        self.assertIsInstance(r["dimensions"], list)
        self.assertGreater(len(r["dimensions"]), 0)

    def test_explain_risk_dimensions_count(self):
        r = explain_risk(_RISK_SNAP)
        self.assertGreaterEqual(len(r["dimensions"]), 4)

    def test_explain_risk_overall_level(self):
        r = explain_risk(_RISK_SNAP)
        self.assertIn(r["overall_risk_level"], ("LOW", "MODERATE", "ELEVATED", "HIGH"))

    def test_explain_risk_unavailable(self):
        r = explain_risk({"available": False})
        self.assertFalse(r["available"])

    def test_explain_risk_score(self):
        r = explain_risk(_RISK_SNAP)
        self.assertAlmostEqual(r["overall_score"], 68.0)


# =============================================================================
# 6. indicator_contributions.py
# =============================================================================

class TestIndicatorContributions(unittest.TestCase):

    def test_compute_contributions_count(self):
        contribs = compute_contributions("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP)
        self.assertEqual(len(contribs), 12)

    def test_compute_contributions_sum_100(self):
        contribs = compute_contributions("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP)
        total = sum(c.contribution_pct for c in contribs)
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_compute_contributions_has_direction(self):
        contribs = compute_contributions("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP)
        for c in contribs:
            self.assertIn(c.direction, ("BULLISH", "BEARISH", "NEUTRAL"))

    def test_compute_contributions_no_signal(self):
        contribs = compute_contributions("RELIANCE", {}, _MARKET_SNAP)
        self.assertEqual(len(contribs), 12)
        total = sum(c.contribution_pct for c in contribs)
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_compute_contributions_indicator_names(self):
        contribs = compute_contributions("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP)
        names = {c.name for c in contribs}
        self.assertIn("Trend", names)
        self.assertIn("Momentum", names)
        self.assertIn("Volume", names)

    def test_compute_contributions_alias_fields(self):
        contribs = compute_contributions("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP)
        for c in contribs:
            self.assertEqual(c.indicator_name, c.name)


# =============================================================================
# 7. confidence_analyzer.py
# =============================================================================

class TestConfidenceAnalyzer(unittest.TestCase):

    def test_compute_confidence_returns_decomposition(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertEqual(d.symbol, "RELIANCE")
        self.assertGreater(d.overall_confidence, 0)
        self.assertLessEqual(d.overall_confidence, 100)

    def test_compute_confidence_grade(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertIn(d.reliability_grade, ("A", "B", "C", "D", "F"))

    def test_compute_confidence_8_dimensions(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertEqual(len(d.dimension_details), 8)

    def test_compute_confidence_market_override(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertAlmostEqual(d.market_score, 72.0, places=0)

    def test_compute_confidence_narrative(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertGreater(len(d.narrative), 20)

    def test_compute_confidence_to_dict(self):
        d = compute_confidence("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP, _RISK_SNAP)
        dd = d.to_dict()
        self.assertIn("overall_confidence", dd)
        self.assertIn("dimension_details", dd)


# =============================================================================
# 8. scenario_generator.py
# =============================================================================

class TestScenarioGenerator(unittest.TestCase):

    def test_generate_scenarios_count(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        self.assertEqual(len(scenarios), 3)

    def test_generate_scenarios_types(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        types_ = {s.scenario_type for s in scenarios}
        self.assertEqual(types_, {"BULLISH", "NEUTRAL", "BEARISH"})

    def test_generate_scenarios_probabilities_sum(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        total = sum(s.probability for s in scenarios)
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_generate_scenarios_bullish_has_conditions(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        bullish = next(s for s in scenarios if s.scenario_type == "BULLISH")
        self.assertGreater(len(bullish.key_conditions), 0)

    def test_generate_scenarios_bearish_stop_loss(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        bearish = next(s for s in scenarios if s.scenario_type == "BEARISH")
        self.assertLess(bearish.price_target, _SAMPLE_SIGNAL["price"])

    def test_generate_scenarios_sell_signal(self):
        scenarios = generate_scenarios("TCS", _SAMPLE_SIGNAL_SELL, _MARKET_SNAP, _MACRO_SNAP)
        self.assertEqual(len(scenarios), 3)
        total = sum(s.probability for s in scenarios)
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_generate_scenarios_narrative_present(self):
        scenarios = generate_scenarios("RELIANCE", _SAMPLE_SIGNAL, _MARKET_SNAP, _MACRO_SNAP)
        for s in scenarios:
            self.assertGreater(len(s.narrative), 10)

    def test_generate_scenarios_confidence_scale_0_to_100(self):
        """Live signals use 0–100 scale; probabilities must still vary meaningfully."""
        # Use neutral market/macro/regime so regime/market bonuses don't inflate bull_prob
        neutral_market = {**_MARKET_SNAP, "market_health_score": 50.0}
        neutral_macro  = {**_MACRO_SNAP, "macro_score": 50.0}
        signal_neutral_regime = {
            **_SAMPLE_SIGNAL, "confidence": 75.0, "regime": "NEUTRAL"
        }
        scenarios = generate_scenarios(
            "RELIANCE", signal_neutral_regime, neutral_market, neutral_macro
        )
        total = sum(s.probability for s in scenarios)
        self.assertAlmostEqual(total, 1.0, places=2)
        bullish = next(s for s in scenarios if s.scenario_type == "BULLISH")
        bearish = next(s for s in scenarios if s.scenario_type == "BEARISH")
        # With 75% confidence BUY in neutral conditions, bullish should outweigh bearish
        # but not dominate at 1.0 (the old bug before normalising confidence from 0-100)
        self.assertGreater(bullish.probability, bearish.probability)
        self.assertLess(bullish.probability, 0.90,
            "bullish probability must not clamp near 1.0 when confidence is 75/100 neutral")

    def test_generate_scenarios_low_confidence_scale_0_to_100(self):
        """Low confidence 0–100 signal should produce lower bullish probability."""
        signal_low = {**_SAMPLE_SIGNAL, "confidence": 35.0}   # 35% confidence
        signal_high = {**_SAMPLE_SIGNAL, "confidence": 80.0}  # 80% confidence
        sc_low  = generate_scenarios("RELIANCE", signal_low,  _MARKET_SNAP, _MACRO_SNAP)
        sc_high = generate_scenarios("RELIANCE", signal_high, _MARKET_SNAP, _MACRO_SNAP)
        bull_low  = next(s for s in sc_low  if s.scenario_type == "BULLISH").probability
        bull_high = next(s for s in sc_high if s.scenario_type == "BULLISH").probability
        self.assertLess(bull_low, bull_high,
            "higher confidence must produce higher bullish probability")

    def test_generate_scenarios_both_scales_produce_consistent_probs(self):
        """0.75 and 75.0 confidence should yield the same scenario probabilities."""
        sig_float = {**_SAMPLE_SIGNAL, "confidence": 0.75}
        sig_int   = {**_SAMPLE_SIGNAL, "confidence": 75.0}
        sc_f = generate_scenarios("RELIANCE", sig_float, _MARKET_SNAP, _MACRO_SNAP)
        sc_i = generate_scenarios("RELIANCE", sig_int,   _MARKET_SNAP, _MACRO_SNAP)
        for sf, si in zip(sc_f, sc_i):
            self.assertAlmostEqual(sf.probability, si.probability, places=2,
                msg=f"{sf.scenario_type}: 0.75 and 75.0 confidence must give same probability")


# =============================================================================
# 9. historical_similarity.py
# =============================================================================

class TestHistoricalSimilarity(unittest.TestCase):

    def test_find_matches_same_symbol(self):
        snapshots = [_SAMPLE_SIGNAL]
        matches = find_historical_matches("RELIANCE", _SAMPLE_SIGNAL, snapshots)
        # Same signal shouldn't crash; result may include the snapshot
        self.assertIsInstance(matches, list)

    def test_find_matches_no_snapshots(self):
        matches = find_historical_matches("RELIANCE", _SAMPLE_SIGNAL, [])
        self.assertEqual(len(matches), 0)

    def test_find_matches_dissimilar_signal(self):
        snapshots = [_SAMPLE_SIGNAL_SELL]  # different symbol
        matches = find_historical_matches("RELIANCE", _SAMPLE_SIGNAL, snapshots)
        self.assertIsInstance(matches, list)

    def test_find_matches_max_results(self):
        # Create 10 similar snapshots
        snaps = []
        for i in range(10):
            snaps.append({**_SAMPLE_SIGNAL, "time": f"2026-01-{i+1:02d}"})
        matches = find_historical_matches("RELIANCE", _SAMPLE_SIGNAL, snaps, max_results=5)
        self.assertLessEqual(len(matches), 5)

    def test_find_matches_similarity_score_range(self):
        snapshots = [_SAMPLE_SIGNAL]
        matches = find_historical_matches("RELIANCE", _SAMPLE_SIGNAL, snapshots)
        for m in matches:
            self.assertGreaterEqual(m.similarity_score, 0.0)
            self.assertLessEqual(m.similarity_score, 1.0)


# =============================================================================
# 10. decision_explainer.py
# =============================================================================

class TestDecisionExplainer(unittest.TestCase):

    def setUp(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )

    def test_explain_decision_returns_object(self):
        d = explain_decision("RELIANCE", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertIsNotNone(d)
        self.assertEqual(d.symbol, "RELIANCE")

    def test_explain_decision_signal_type(self):
        d = explain_decision("RELIANCE", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertEqual(d.signal_type, "BUY")

    def test_explain_decision_grade(self):
        d = explain_decision("RELIANCE", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertIn(d.grade, ("A+", "A", "B", "C", "D"))

    def test_explain_decision_has_tree(self):
        d = explain_decision("RELIANCE", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertIsInstance(d.decision_tree, dict)

    def test_explain_decision_no_signal(self):
        sys.modules["signals_store"].load_signals = MagicMock(return_value=[])
        d = explain_decision("UNKNOWN", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertEqual(d.symbol, "UNKNOWN")
        self.assertEqual(d.signal_type, "NO_TRADE")

    def test_explain_decision_extended_fields(self):
        d = explain_decision("RELIANCE", _MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        # Extended fields should be populated
        self.assertEqual(d.risk_level, "MEDIUM")
        self.assertAlmostEqual(d.price, 2450.0)
        self.assertAlmostEqual(d.target, 2520.0)
        self.assertAlmostEqual(d.stop_loss, 2410.0)
        self.assertEqual(d.regime, "TRENDING_UP")

    def test_get_all_explainable_decisions(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )
        results = get_all_explainable_decisions(_MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)

    def test_get_all_returns_dicts(self):
        results = get_all_explainable_decisions(_MARKET_SNAP, _EVENT_SNAP, _MACRO_SNAP, _RISK_SNAP)
        for r in results:
            self.assertIsInstance(r, dict)
            self.assertIn("symbol", r)

    def tearDown(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )


# =============================================================================
# 11. operator_summary.py
# =============================================================================

class TestOperatorSummary(unittest.TestCase):

    def _make_decision(self, sig="BUY", conf=0.75):
        return ExplainableDecision(
            symbol="RELIANCE", signal_type=sig,
            primary_reason="EMA crossover bullish",
            secondary_reasons=["RSI optimal", "Volume spike"],
            supporting_indicators=[], supporting_market_conditions=[],
            supporting_events=[], supporting_macro_conditions=[],
            ai_score=70, strategy_score=65, risk_score=60,
            final_confidence=conf * 100, explainability_score=80,
            grade="B", decision_tree={}, plain_english_summary="Test",
            confidence=conf, risk_level="MEDIUM",
            price=2450.0, target=2520.0, stop_loss=2410.0, regime="TRENDING_UP",
        )

    def test_build_summary_returns_dict(self):
        d = self._make_decision()
        s = build_operator_summary(d)
        self.assertIsInstance(s, dict)

    def test_build_summary_has_why(self):
        s = build_operator_summary(self._make_decision())
        self.assertIn("why", s)
        self.assertGreater(len(s["why"]), 10)

    def test_build_summary_action_items(self):
        s = build_operator_summary(self._make_decision("BUY"))
        self.assertGreater(len(s["action_items"]), 0)
        self.assertIn("long", " ".join(s["action_items"]).lower())

    def test_build_summary_sell_action(self):
        s = build_operator_summary(self._make_decision("SELL", 0.62))
        self.assertTrue(any("exit" in a.lower() or "short" in a.lower() for a in s["action_items"]))

    def test_build_summary_risks(self):
        s = build_operator_summary(self._make_decision())
        self.assertGreater(len(s["risks"]), 0)

    def test_build_summary_top_factors(self):
        s = build_operator_summary(self._make_decision())
        self.assertLessEqual(len(s["top_factors"]), 3)

    def test_build_summary_opportunities_with_target(self):
        s = build_operator_summary(self._make_decision())
        opp_text = " ".join(s["opportunities"]).lower()
        self.assertIn("upside", opp_text)


# =============================================================================
# 12. AST safety test — no write-module imports
# =============================================================================

class TestAstSafety(unittest.TestCase):

    FORBIDDEN = [
        "signals_store",
        "paper_portfolio",
        "paper_trades",
        "auto_paper",
        "portfolio_store",
    ]

    def _scan_file(self, filepath: str) -> list:
        import ast, re
        hits = []
        try:
            with open(filepath) as fh:
                src = fh.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""]
                    )
                    for name in names:
                        for forbidden in self.FORBIDDEN:
                            if forbidden in (name or ""):
                                hits.append((filepath, name))
        except Exception:
            pass
        return hits

    def test_no_write_imports_in_explainable_ai(self):
        import glob
        import os
        pkg_dir = os.path.join(
            os.path.dirname(__file__), "explainable_ai"
        )
        py_files = glob.glob(os.path.join(pkg_dir, "*.py"))
        # signals_store is permitted in decision_explainer & shared_services (read-only)
        write_forbidden = [
            "paper_portfolio", "paper_trades", "auto_paper", "portfolio_store",
        ]
        for fpath in py_files:
            try:
                import ast
                with open(fpath) as fh:
                    src = fh.read()
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = (
                            [a.name for a in node.names]
                            if isinstance(node, ast.Import)
                            else [node.module or ""]
                        )
                        for name in names:
                            for bad in write_forbidden:
                                self.assertNotIn(
                                    bad, (name or ""),
                                    f"{fpath} must not import write module {bad}",
                                )
            except SyntaxError:
                pass


# =============================================================================
# 13. Shared services integration (with mocked internals)
# =============================================================================

class TestSharedServices(unittest.TestCase):

    def setUp(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )

    def test_get_summary_enabled(self):
        from explainable_ai.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("total_decisions", r)
        self.assertIn("decisions", r)

    def test_get_summary_decision_count(self):
        from explainable_ai.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["total_decisions"], 2)

    def test_get_decision_found(self):
        from explainable_ai.shared_services import get_decision
        r = get_decision("RELIANCE")
        self.assertEqual(r["status"], "ENABLED")
        self.assertIsNotNone(r.get("decision"))

    def test_get_decision_summary_present(self):
        from explainable_ai.shared_services import get_decision
        r = get_decision("RELIANCE")
        self.assertIn("summary", r)
        self.assertIn("why", r["summary"])

    def test_get_contributions_found(self):
        from explainable_ai.shared_services import get_contributions
        r = get_contributions("RELIANCE")
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(len(r["contributions"]), 12)

    def test_get_confidence_found(self):
        from explainable_ai.shared_services import get_confidence
        r = get_confidence("RELIANCE")
        self.assertEqual(r["status"], "ENABLED")
        self.assertIsNotNone(r.get("confidence"))

    def test_get_scenarios_found(self):
        from explainable_ai.shared_services import get_scenarios
        r = get_scenarios("RELIANCE")
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(len(r["scenarios"]), 3)

    def test_get_history_no_match(self):
        sys.modules["signals_store"].load_signal_snapshots = MagicMock(return_value=[])
        from importlib import reload
        import explainable_ai.shared_services as ss_mod
        reload(ss_mod)
        r = ss_mod.get_history("RELIANCE")
        self.assertEqual(r.get("status"), "ENABLED")

    def test_get_snapshot_enabled(self):
        from explainable_ai.shared_services import get_explainable_ai_snapshot
        r = get_explainable_ai_snapshot()
        self.assertTrue(r.get("available"))
        self.assertIn("explainable_ai_score", r)
        self.assertIn("grade", r)

    def test_export_csv(self):
        from explainable_ai.shared_services import export_csv
        csv_str = export_csv()
        self.assertIn("symbol", csv_str)
        self.assertIn("RELIANCE", csv_str)

    def test_export_json(self):
        import json as _json
        from explainable_ai.shared_services import export_json
        j = _json.loads(export_json())
        self.assertEqual(j["status"], "ENABLED")
        self.assertIn("decisions", j)

    def test_disabled_returns_disabled_status(self):
        with patch.dict(os.environ, {"EXPLAINABLE_AI_ENABLED": "false"}):
            from importlib import reload
            import explainable_ai.models as models_mod
            reload(models_mod)
            import explainable_ai.shared_services as ss_mod
            reload(ss_mod)
            r = ss_mod.get_summary()
            self.assertEqual(r["status"], "DISABLED")

    def tearDown(self):
        # Restore env and module state
        os.environ["EXPLAINABLE_AI_ENABLED"] = "true"
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )


# =============================================================================
# 14. Context integration — decision endpoint must include context objects
# =============================================================================

class TestDecisionContextFields(unittest.TestCase):
    """Assert that get_decision() always includes the four context objects
    that the dashboard Market/Event/Macro/Risk tabs rely on."""

    def setUp(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL]
        )
        # Reload shared_services so it picks up fresh stubs
        from importlib import reload
        import explainable_ai.shared_services as ss_mod
        reload(ss_mod)
        self._ss = ss_mod

    def test_get_decision_includes_market_context(self):
        r = self._ss.get_decision("RELIANCE")
        d = r.get("decision", {})
        self.assertIn("market_context", d,
            "decision payload must include market_context for the Market tab")

    def test_get_decision_includes_event_context(self):
        r = self._ss.get_decision("RELIANCE")
        d = r.get("decision", {})
        self.assertIn("event_context", d,
            "decision payload must include event_context for the Events tab")

    def test_get_decision_includes_macro_context(self):
        r = self._ss.get_decision("RELIANCE")
        d = r.get("decision", {})
        self.assertIn("macro_context", d,
            "decision payload must include macro_context for the Macro tab")

    def test_get_decision_includes_risk_context(self):
        r = self._ss.get_decision("RELIANCE")
        d = r.get("decision", {})
        self.assertIn("risk_context", d,
            "decision payload must include risk_context for the Risk tab")

    def test_market_context_has_narrative(self):
        r = self._ss.get_decision("RELIANCE")
        mc = r["decision"]["market_context"]
        self.assertIn("narrative", mc)
        self.assertIsInstance(mc["narrative"], str)

    def test_event_context_has_narrative(self):
        r = self._ss.get_decision("RELIANCE")
        ec = r["decision"]["event_context"]
        self.assertIn("narrative", ec)

    def test_macro_context_has_narrative(self):
        r = self._ss.get_decision("RELIANCE")
        mac = r["decision"]["macro_context"]
        self.assertIn("narrative", mac)

    def test_risk_context_has_dimensions(self):
        r = self._ss.get_decision("RELIANCE")
        rc = r["decision"]["risk_context"]
        self.assertIn("dimensions", rc)
        self.assertIsInstance(rc["dimensions"], list)

    def test_market_context_available_flag(self):
        r = self._ss.get_decision("RELIANCE")
        mc = r["decision"]["market_context"]
        # With _MARKET_SNAP injected the context should be available
        self.assertTrue(mc.get("available", False),
            "market_context.available should be True when upstream snapshot is present")

    def test_risk_context_has_overall_risk_level(self):
        r = self._ss.get_decision("RELIANCE")
        rc = r["decision"]["risk_context"]
        self.assertIn("overall_risk_level", rc)
        self.assertIn(rc["overall_risk_level"], ("LOW", "MODERATE", "ELEVATED", "HIGH"))

    def test_context_not_present_when_no_signal(self):
        sys.modules["signals_store"].load_signals = MagicMock(return_value=[])
        from importlib import reload
        import explainable_ai.shared_services as ss_mod
        reload(ss_mod)
        r = ss_mod.get_decision("UNKNOWN")
        # When no signal, decision is None — no crash expected
        self.assertEqual(r.get("status"), "ENABLED")

    def tearDown(self):
        sys.modules["signals_store"].load_signals = MagicMock(
            return_value=[_SAMPLE_SIGNAL, _SAMPLE_SIGNAL_SELL]
        )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.discover(".", pattern="test_explainable_ai.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
