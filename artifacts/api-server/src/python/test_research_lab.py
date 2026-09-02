"""
test_research_lab.py — Phase 7.5
Tests for the Research, Simulation & Innovation Lab.

READ-ONLY · ADVISORY-ONLY · 100% unit-level with mocked upstreams.
"""
from __future__ import annotations
import os, sys, unittest
import pytest
from unittest.mock import MagicMock, patch

# ── Enable feature flag ────────────────────────────────────────────────────────

# ── Stub all upstream dependencies ────────────────────────────────────────────
_SIGNALS = [
    {
        "stock": "RELIANCE", "symbol": "RELIANCE", "signal": "BUY",
        "confidence": 0.75, "price": 2850.0, "regime": "TRENDING_UP",
        "risk_level": "MEDIUM", "reasons": ["Strong trend"],
    },
    {
        "stock": "TCS", "symbol": "TCS", "signal": "SELL",
        "confidence": 0.60, "price": 3900.0, "regime": "MEAN_REVERSION",
        "risk_level": "LOW", "reasons": ["Overbought"],
    },
    {
        "stock": "INFY", "symbol": "INFY", "signal": "BUY",
        "confidence": 55.0, "price": 1750.0, "regime": "TRENDING_UP",
        "risk_level": "MEDIUM", "reasons": ["Breakout"],
    },
    {
        "stock": "HDFCBANK", "symbol": "HDFCBANK", "signal": "HOLD",
        "confidence": 0.45, "price": 1600.0, "regime": "RANGE",
        "risk_level": "LOW", "reasons": [],
    },
    {
        "stock": "ITC", "symbol": "ITC", "signal": "STRONG_BUY",
        "confidence": 0.82, "price": 450.0, "regime": "MOMENTUM",
        "risk_level": "LOW", "reasons": ["Momentum surge"],
    },
]

_SNAPSHOTS = [
    {
        "stock": "RELIANCE", "time": "2026-07-28 10:30", "signal": "BUY",
        "confidence": 0.72, "price": 2820.0, "regime": "TRENDING_UP",
    },
    {
        "stock": "TCS", "time": "2026-07-27 11:00", "signal": "SELL",
        "confidence": 0.65, "price": 3850.0, "regime": "RANGE",
    },
]

_MARKET_SNAP = {
    "status": "ENABLED", "available": True,
    "market_health_score": 72.0, "overall_outlook": "BULLISH",
    "win_rate": 0.58, "max_drawdown": 0.07,
}

_MACRO_SNAP = {
    "status": "ENABLED", "available": True,
    "india_vix": 15.8, "fii_posture": "BUYING",
    "trend": "IMPROVING", "macro_score": 65.0,
    "inflation_risk": "LOW",
}

_RISK_SNAP = {
    "status": "ENABLED", "available": True,
    "risk_optimisation_score": 68.0, "grade": "B",
    "max_drawdown": 0.09, "capital_efficiency": 65.0,
    "diversification_score": 70.0, "correlation_risk": 30.0,
}

_XAI_SNAP = {
    "status": "ENABLED",
    "explainable_ai_score": 72.0, "grade": "B",
    "total_decisions": 5, "avg_confidence": 0.65,
    "buy_count": 3, "sell_count": 1, "hold_count": 1,
}

def _stub_modules():
    modules = {}
    # Stub signals_store
    modules["signals_store"] = MagicMock()
    modules["signals_store"].load_signals = MagicMock(return_value=_SIGNALS)
    modules["signals_store"].load_signal_snapshots = MagicMock(return_value=_SNAPSHOTS)

    # Stub upstream shared_services
    _mss = MagicMock(); _mss.get_market_intelligence_snapshot = MagicMock(return_value=_MARKET_SNAP)
    _mess = MagicMock(); _mess.get_event_intelligence_snapshot = MagicMock(return_value={})
    _macss = MagicMock(); _macss.get_macro_intelligence_snapshot = MagicMock(return_value=_MACRO_SNAP)
    _xaiss = MagicMock(); _xaiss.get_explainable_ai_snapshot = MagicMock(return_value=_XAI_SNAP)
    _ross = MagicMock(); _ross.get_risk_optimisation_snapshot = MagicMock(return_value=_RISK_SNAP)
    _ppss = MagicMock(); _ppss.get_portfolio_performance_snapshot = MagicMock(return_value=_MARKET_SNAP)

    modules["market_intelligence"] = MagicMock()
    modules["market_intelligence.shared_services"] = _mss
    modules["event_intelligence"] = MagicMock()
    modules["event_intelligence.shared_services"] = _mess
    modules["macro_intelligence"] = MagicMock()
    modules["macro_intelligence.shared_services"] = _macss
    modules["explainable_ai"] = MagicMock()
    modules["explainable_ai.shared_services"] = _xaiss
    modules["risk_optimisation"] = MagicMock()
    modules["risk_optimisation.shared_services"] = _ross
    modules["portfolio_performance"] = MagicMock()
    modules["portfolio_performance.shared_services"] = _ppss

    return modules


@pytest.fixture(autouse=True)
def _isolated_dependencies():
    with patch.dict(sys.modules, _stub_modules()), patch.dict(os.environ, {"RESEARCH_LAB_ENABLED": "true"}):
        yield


# =============================================================================
# 1. Models
# =============================================================================

class TestModels(unittest.TestCase):

    def test_is_enabled_true(self):
        from research_lab.models import is_enabled
        self.assertTrue(is_enabled())

    def test_is_enabled_false_when_unset(self):
        import os
        from research_lab.models import is_enabled
        orig = os.environ.pop("RESEARCH_LAB_ENABLED", None)
        try:
            self.assertFalse(is_enabled())
        finally:
            if orig: os.environ["RESEARCH_LAB_ENABLED"] = orig

    def test_disabled_response(self):
        from research_lab.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertTrue(r["advisory_only"])

    def test_research_grade(self):
        from research_lab.models import research_grade
        self.assertEqual(research_grade(92), "A+")
        self.assertEqual(research_grade(82), "A")
        self.assertEqual(research_grade(72), "B")
        self.assertEqual(research_grade(57), "C")
        self.assertEqual(research_grade(40), "D")

    def test_trend_label_improving(self):
        from research_lab.models import trend_label
        self.assertEqual(trend_label(75, 70), "IMPROVING")

    def test_trend_label_weakening(self):
        from research_lab.models import trend_label
        self.assertEqual(trend_label(60, 67), "WEAKENING")

    def test_trend_label_stable(self):
        from research_lab.models import trend_label
        self.assertEqual(trend_label(65, 64), "STABLE")

    def test_all_strategies_count(self):
        from research_lab.models import ALL_STRATEGIES
        self.assertEqual(len(ALL_STRATEGIES), 7)

    def test_all_scenarios_count(self):
        from research_lab.models import ALL_SCENARIOS
        self.assertEqual(len(ALL_SCENARIOS), 8)

    def test_all_regimes_count(self):
        from research_lab.models import ALL_REGIMES
        self.assertEqual(len(ALL_REGIMES), 6)

    def test_strategy_profile_to_dict(self):
        from research_lab.models import StrategyProfile
        sp = StrategyProfile(
            strategy_type="TREND_FOLLOWING", label="Trend", description="desc",
            signal_count=5, win_rate=0.6, avg_confidence=70.0, avg_drawdown=5.0,
            consistency=60.0, risk_score=65.0, performance_score=68.0, grade="B",
            best_regime="TRENDING_UP", worst_regime="RANGE", recommendation="ok",
        )
        d = sp.to_dict()
        self.assertIn("strategy_type", d)
        self.assertTrue(d["advisory_only"])

    def test_scenario_result_to_dict(self):
        from research_lab.models import ScenarioResult
        s = ScenarioResult(
            scenario_type="BULL_MARKET", label="Bull", description="d",
            market_impact="POSITIVE", expected_signals=10, signal_shift="More BUY",
            risk_level="LOW", opportunity_score=80.0, threat_score=20.0,
            affected_sectors=[], key_risks=[], key_opportunities=[],
            recommended_actions=[],
        )
        d = s.to_dict()
        self.assertTrue(d["advisory_only"])


# =============================================================================
# 2. Strategy Research
# =============================================================================

class TestStrategyResearch(unittest.TestCase):

    def test_returns_7_profiles(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        self.assertEqual(len(profiles), 7)

    def test_profiles_sorted_by_performance(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        scores = [p.performance_score for p in profiles]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_all_have_grade(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        for p in profiles:
            self.assertIn(p.grade, ("A+", "A", "B", "C", "D"))

    def test_win_rate_range(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        for p in profiles:
            self.assertGreaterEqual(p.win_rate, 0.0)
            self.assertLessEqual(p.win_rate, 1.0)

    def test_advisory_only_flag(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        for p in profiles:
            self.assertTrue(p.advisory_only)

    def test_empty_signals(self):
        from research_lab.strategy_research import build_strategy_profiles
        profiles = build_strategy_profiles([], _RISK_SNAP)
        self.assertEqual(len(profiles), 7)


# =============================================================================
# 3. Scenario Simulation
# =============================================================================

class TestScenarioSimulation(unittest.TestCase):

    def _scenarios(self):
        from research_lab.scenario_simulation import simulate_all_scenarios
        return simulate_all_scenarios(_SIGNALS, _MACRO_SNAP, _MARKET_SNAP)

    def test_returns_8_scenarios(self):
        self.assertEqual(len(self._scenarios()), 8)

    def test_all_advisory_only(self):
        for s in self._scenarios():
            self.assertTrue(s.advisory_only)

    def test_opportunity_score_range(self):
        for s in self._scenarios():
            self.assertGreaterEqual(s.opportunity_score, 0.0)
            self.assertLessEqual(s.opportunity_score, 100.0)

    def test_threat_score_range(self):
        for s in self._scenarios():
            self.assertGreaterEqual(s.threat_score, 0.0)
            self.assertLessEqual(s.threat_score, 100.0)

    def test_expected_signals_positive(self):
        for s in self._scenarios():
            self.assertGreater(s.expected_signals, 0)

    def test_bull_has_positive_impact(self):
        scenarios = self._scenarios()
        bull = next(s for s in scenarios if s.scenario_type == "BULL_MARKET")
        self.assertEqual(bull.market_impact, "POSITIVE")

    def test_bear_has_negative_impact(self):
        scenarios = self._scenarios()
        bear = next(s for s in scenarios if s.scenario_type == "BEAR_MARKET")
        self.assertEqual(bear.market_impact, "NEGATIVE")

    def test_macro_shock_highest_threat(self):
        scenarios = self._scenarios()
        macro = next(s for s in scenarios if s.scenario_type == "MACRO_SHOCK")
        others = [s for s in scenarios if s.scenario_type != "MACRO_SHOCK"]
        self.assertGreater(macro.threat_score, min(s.threat_score for s in others))

    def test_to_dict_works(self):
        for s in self._scenarios():
            d = s.to_dict()
            self.assertIn("scenario_type", d)


# =============================================================================
# 4. Historical Replay
# =============================================================================

class TestHistoricalReplay(unittest.TestCase):

    def test_build_frames_returns_list(self):
        from research_lab.historical_replay import build_replay_frames
        frames = build_replay_frames(_SNAPSHOTS)
        self.assertIsInstance(frames, list)

    def test_frames_respect_limit(self):
        from research_lab.historical_replay import build_replay_frames
        frames = build_replay_frames(_SNAPSHOTS * 50, limit=10)
        self.assertLessEqual(len(frames), 10)

    def test_frame_has_required_fields(self):
        from research_lab.historical_replay import build_replay_frames
        frames = build_replay_frames(_SNAPSHOTS)
        for f in frames:
            self.assertIsNotNone(f.frame_id)
            self.assertIn(f.outcome, ("WIN", "LOSS", "UNKNOWN"))

    def test_replay_summary_empty(self):
        from research_lab.historical_replay import replay_summary
        s = replay_summary([])
        self.assertEqual(s["total_frames"], 0)
        self.assertEqual(s["win_rate"], 0.0)

    def test_replay_summary_with_data(self):
        from research_lab.historical_replay import build_replay_frames, replay_summary
        frames = build_replay_frames(_SNAPSHOTS)
        s = replay_summary(frames)
        self.assertIn("total_frames", s)
        self.assertIn("symbols_covered", s)
        self.assertIn("regimes_seen", s)


# =============================================================================
# 5. Parameter Experiments
# =============================================================================

class TestParameterExperiments(unittest.TestCase):

    def test_returns_experiments(self):
        from research_lab.parameter_experiments import run_parameter_experiments
        exps = run_parameter_experiments(_SIGNALS)
        self.assertGreater(len(exps), 0)

    def test_impact_label_valid(self):
        from research_lab.parameter_experiments import run_parameter_experiments
        for e in run_parameter_experiments(_SIGNALS):
            self.assertIn(e.impact_label, ("IMPROVED", "NEUTRAL", "DEGRADED"))

    def test_advisory_only(self):
        from research_lab.parameter_experiments import run_parameter_experiments
        for e in run_parameter_experiments(_SIGNALS):
            self.assertTrue(e.advisory_only)

    def test_has_narrative(self):
        from research_lab.parameter_experiments import run_parameter_experiments
        for e in run_parameter_experiments(_SIGNALS):
            self.assertGreater(len(e.narrative), 20)

    def test_to_dict_works(self):
        from research_lab.parameter_experiments import run_parameter_experiments
        for e in run_parameter_experiments(_SIGNALS):
            d = e.to_dict()
            self.assertIn("parameter_name", d)
            self.assertIn("impact_label", d)


# =============================================================================
# 6. Regime Comparison
# =============================================================================

class TestRegimeComparison(unittest.TestCase):

    def test_returns_6_regimes(self):
        from research_lab.regime_comparison import build_regime_profiles
        profiles = build_regime_profiles(_SIGNALS, _RISK_SNAP)
        self.assertEqual(len(profiles), 6)

    def test_all_advisory_only(self):
        from research_lab.regime_comparison import build_regime_profiles
        for p in build_regime_profiles(_SIGNALS, _RISK_SNAP):
            self.assertTrue(p.advisory_only)

    def test_win_rate_range(self):
        from research_lab.regime_comparison import build_regime_profiles
        for p in build_regime_profiles(_SIGNALS, _RISK_SNAP):
            self.assertGreaterEqual(p.win_rate, 0.0)
            self.assertLessEqual(p.win_rate, 1.0)

    def test_all_have_vix_range(self):
        from research_lab.regime_comparison import build_regime_profiles
        for p in build_regime_profiles(_SIGNALS, _RISK_SNAP):
            self.assertIsNotNone(p.vix_range)

    def test_all_have_best_strategy(self):
        from research_lab.regime_comparison import build_regime_profiles
        for p in build_regime_profiles(_SIGNALS, _RISK_SNAP):
            self.assertIsNotNone(p.best_strategy)

    def test_empty_signals(self):
        from research_lab.regime_comparison import build_regime_profiles
        profiles = build_regime_profiles([], _RISK_SNAP)
        self.assertEqual(len(profiles), 6)


# =============================================================================
# 7. Risk Simulation
# =============================================================================

class TestRiskSimulation(unittest.TestCase):

    def _sim(self, signals=None):
        from research_lab.risk_simulation import simulate_risk
        return simulate_risk(signals or _SIGNALS, _RISK_SNAP, _MACRO_SNAP)

    def test_returns_risk_simulation(self):
        from research_lab.models import RiskSimulation
        sim = self._sim()
        self.assertIsInstance(sim, RiskSimulation)

    def test_expected_drawdown_positive(self):
        self.assertGreater(self._sim().expected_drawdown, 0)

    def test_max_dd_gt_expected(self):
        sim = self._sim()
        self.assertGreater(sim.max_drawdown_estimate, sim.expected_drawdown)

    def test_risk_distribution_sums_to_1(self):
        sim = self._sim()
        total = sum(sim.risk_distribution.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_reward_distribution_sums_to_1(self):
        sim = self._sim()
        total = sum(sim.reward_distribution.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_stress_scenarios_not_empty(self):
        self.assertGreater(len(self._sim().stress_scenarios), 0)

    def test_volatility_exposure_range(self):
        sim = self._sim()
        self.assertGreaterEqual(sim.volatility_exposure, 0)
        self.assertLessEqual(sim.volatility_exposure, 100)

    def test_monte_carlo_note_present(self):
        self.assertIn("advisory", self._sim().monte_carlo_note.lower())

    def test_advisory_only(self):
        self.assertTrue(self._sim().advisory_only)

    def test_capital_usage_range(self):
        sim = self._sim()
        self.assertGreaterEqual(sim.capital_usage_pct, 0)
        self.assertLessEqual(sim.capital_usage_pct, 100)


# =============================================================================
# 8. Performance Benchmark
# =============================================================================

class TestPerformanceBenchmark(unittest.TestCase):

    def _bm(self):
        from research_lab.performance_benchmark import compute_benchmark
        return compute_benchmark(_SIGNALS, _RISK_SNAP, _MARKET_SNAP, _XAI_SNAP)

    def test_returns_benchmark_comparison(self):
        from research_lab.models import BenchmarkComparison
        self.assertIsInstance(self._bm(), BenchmarkComparison)

    def test_all_scores_in_range(self):
        bm = self._bm()
        for score in [bm.research_score, bm.baseline_score, bm.market_score, bm.paper_score]:
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_has_winner(self):
        bm = self._bm()
        self.assertIn(bm.winner, ["Research", "Baseline (NIFTY)", "Market", "Paper Trading"])

    def test_narrative_non_empty(self):
        self.assertGreater(len(self._bm().narrative), 20)

    def test_advisory_only(self):
        self.assertTrue(self._bm().advisory_only)

    def test_to_dict_works(self):
        d = self._bm().to_dict()
        self.assertIn("research_score", d)
        self.assertIn("winner", d)


# =============================================================================
# 9. Innovation Workspace
# =============================================================================

class TestInnovationWorkspace(unittest.TestCase):

    def test_get_all_experiments_returns_list(self):
        from research_lab.innovation_workspace import get_all_experiments
        exps = get_all_experiments()
        self.assertGreater(len(exps), 0)

    def test_all_have_required_fields(self):
        from research_lab.innovation_workspace import get_all_experiments
        for e in get_all_experiments():
            self.assertIsNotNone(e.title)
            self.assertIsNotNone(e.status)
            self.assertIsInstance(e.tags, list)
            self.assertGreater(e.version, 0)

    def test_advisory_only(self):
        from research_lab.innovation_workspace import get_all_experiments
        for e in get_all_experiments():
            self.assertTrue(e.advisory_only)

    def test_workspace_summary_counts(self):
        from research_lab.innovation_workspace import get_all_experiments, get_workspace_summary
        exps = get_all_experiments()
        s = get_workspace_summary(exps)
        self.assertEqual(s["total"], len(exps))
        self.assertEqual(s["complete"] + s["running"] + s["draft"], len(exps))

    def test_workspace_summary_has_top_tags(self):
        from research_lab.innovation_workspace import get_all_experiments, get_workspace_summary
        s = get_workspace_summary(get_all_experiments())
        self.assertIsInstance(s["top_tags"], list)


# =============================================================================
# 10. Research Reports
# =============================================================================

class TestResearchReports(unittest.TestCase):

    def _report(self):
        from research_lab.strategy_research  import build_strategy_profiles
        from research_lab.scenario_simulation import simulate_all_scenarios
        from research_lab.risk_simulation     import simulate_risk
        from research_lab.performance_benchmark import compute_benchmark
        from research_lab.innovation_workspace import get_all_experiments
        from research_lab.research_reports    import generate_research_report

        strategies  = build_strategy_profiles(_SIGNALS, _RISK_SNAP)
        scenarios   = simulate_all_scenarios(_SIGNALS, _MACRO_SNAP, _MARKET_SNAP)
        risk_sim    = simulate_risk(_SIGNALS, _RISK_SNAP, _MACRO_SNAP)
        benchmark   = compute_benchmark(_SIGNALS, _RISK_SNAP, _MARKET_SNAP, _XAI_SNAP)
        experiments = get_all_experiments()
        return generate_research_report(
            strategies, scenarios, risk_sim, benchmark,
            experiments, _MARKET_SNAP, _MACRO_SNAP, _XAI_SNAP
        )

    def test_returns_research_report(self):
        from research_lab.models import ResearchReport
        self.assertIsInstance(self._report(), ResearchReport)

    def test_score_in_range(self):
        r = self._report()
        self.assertGreaterEqual(r.research_score, 0)
        self.assertLessEqual(r.research_score, 100)

    def test_grade_valid(self):
        self.assertIn(self._report().grade, ("A+", "A", "B", "C", "D"))

    def test_trend_valid(self):
        self.assertIn(self._report().trend, ("IMPROVING", "STABLE", "WEAKENING"))

    def test_executive_summary_non_empty(self):
        self.assertGreater(len(self._report().executive_summary), 30)

    def test_has_findings(self):
        self.assertGreater(len(self._report().key_findings), 0)

    def test_has_recommendations(self):
        self.assertGreater(len(self._report().recommendations), 0)

    def test_has_limitations(self):
        self.assertGreater(len(self._report().limitations), 0)

    def test_advisory_only(self):
        self.assertTrue(self._report().advisory_only)

    def test_to_dict_works(self):
        d = self._report().to_dict()
        self.assertIn("executive_summary", d)
        self.assertIn("recommendations", d)


# =============================================================================
# 11. Shared Services
# =============================================================================

class TestSharedServices(unittest.TestCase):

    def test_get_summary_enabled(self):
        from research_lab.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")

    def test_get_summary_has_score(self):
        from research_lab.shared_services import get_summary
        r = get_summary()
        self.assertIn("research_score", r)
        self.assertGreaterEqual(r["research_score"], 0)

    def test_get_strategies_enabled(self):
        from research_lab.shared_services import get_strategies
        r = get_strategies()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(len(r["strategies"]), 7)

    def test_get_simulations_enabled(self):
        from research_lab.shared_services import get_simulations
        r = get_simulations()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(len(r["scenarios"]), 8)

    def test_get_replay_enabled(self):
        from research_lab.shared_services import get_replay
        r = get_replay()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("frames", r)
        self.assertIn("summary", r)

    def test_get_benchmark_enabled(self):
        from research_lab.shared_services import get_benchmark
        r = get_benchmark()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("benchmark", r)
        self.assertIn("regimes", r)

    def test_get_reports_enabled(self):
        from research_lab.shared_services import get_reports
        r = get_reports()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("report", r)
        self.assertIn("innovations", r)

    def test_get_snapshot_enabled(self):
        from research_lab.shared_services import get_research_lab_snapshot
        r = get_research_lab_snapshot()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("research_score", r)
        self.assertTrue(r["advisory_only"])

    def test_export_csv_returns_string(self):
        from research_lab.shared_services import export_csv
        csv_str = export_csv()
        self.assertIn("strategy_type", csv_str)

    def test_export_json_returns_string(self):
        import json
        from research_lab.shared_services import export_json
        data = json.loads(export_json())
        self.assertEqual(data["status"], "ENABLED")

    def test_disabled_returns_disabled(self):
        import os
        orig = os.environ.pop("RESEARCH_LAB_ENABLED", None)
        try:
            from importlib import reload
            import research_lab.shared_services as ss
            reload(ss)
            r = ss.get_summary()
            self.assertEqual(r["status"], "DISABLED")
        finally:
            os.environ["RESEARCH_LAB_ENABLED"] = orig or "true"

    def test_advisory_only_in_all_responses(self):
        from research_lab.shared_services import (
            get_summary, get_strategies, get_simulations,
            get_replay, get_benchmark, get_reports, get_research_lab_snapshot,
        )
        for fn in [get_summary, get_strategies, get_simulations,
                   get_replay, get_benchmark, get_reports, get_research_lab_snapshot]:
            r = fn()
            self.assertTrue(r.get("advisory_only"), f"{fn.__name__} must set advisory_only=True")


# =============================================================================
# 12. API dispatch
# =============================================================================

class TestApiDispatch(unittest.TestCase):

    def test_cmd_summary_returns_dict(self):
        from research_lab.api import cmd_summary
        r = cmd_summary()
        self.assertIsInstance(r, dict)
        self.assertEqual(r.get("status"), "ENABLED")

    def test_cmd_strategies_returns_dict(self):
        from research_lab.api import cmd_strategies
        r = cmd_strategies()
        self.assertIsInstance(r, dict)

    def test_cmd_simulations_returns_dict(self):
        from research_lab.api import cmd_simulations
        r = cmd_simulations()
        self.assertIsInstance(r, dict)

    def test_cmd_replay_returns_dict(self):
        from research_lab.api import cmd_replay
        r = cmd_replay()
        self.assertIsInstance(r, dict)

    def test_cmd_benchmark_returns_dict(self):
        from research_lab.api import cmd_benchmark
        r = cmd_benchmark()
        self.assertIsInstance(r, dict)

    def test_cmd_reports_returns_dict(self):
        from research_lab.api import cmd_reports
        r = cmd_reports()
        self.assertIsInstance(r, dict)

    def test_cmd_snapshot_returns_dict(self):
        from research_lab.api import cmd_snapshot
        r = cmd_snapshot()
        self.assertIsInstance(r, dict)

    def test_cmd_export_json_returns_dict(self):
        from research_lab.api import cmd_export
        import sys
        sys.argv = ["main.py", "research_lab_export", "json"]
        r = cmd_export()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["format"], "json")

    def test_cmd_export_csv_returns_dict(self):
        from research_lab.api import cmd_export
        import sys
        sys.argv = ["main.py", "research_lab_export", "csv"]
        r = cmd_export()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["format"], "csv")
        self.assertIn("strategy_type", r["content"])


# =============================================================================
# 13. Safety: AST guard — no write-module imports
# =============================================================================

class TestAstSafety(unittest.TestCase):

    def test_no_write_imports_in_research_lab(self):
        import ast, pathlib
        forbidden = {
            "paper_portfolio", "paper_trades", "auto_paper",
            "portfolio_store", "signal_store_writer", "order_manager",
        }
        pkg = pathlib.Path(__file__).parent / "research_lab"
        for py_file in pkg.glob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = ""
                    if isinstance(node, ast.ImportFrom) and node.module:
                        module = node.module
                    elif isinstance(node, ast.Import):
                        module = ",".join(a.name for a in node.names)
                    for fb in forbidden:
                        self.assertNotIn(
                            fb, module,
                            f"{py_file.name} must not import write module '{fb}'"
                        )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.discover(".", pattern="test_research_lab.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
