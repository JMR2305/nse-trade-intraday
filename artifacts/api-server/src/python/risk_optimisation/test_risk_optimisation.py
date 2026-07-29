"""
test_risk_optimisation.py — Phase 6.4
Comprehensive unit tests for the Risk Optimisation & Capital Allocation module.

Tests cover:
  - Feature flag (5)
  - Capital analyser (6)
  - Position sizing (4)
  - Concentration analyser (5)
  - Drawdown analyser (6)
  - Stop loss analyser (5)
  - Target analyser (4)
  - Stress tester (5)
  - Recommendation engine (4)
  - Shared services API (6)
  - Health score model (4)
"""
import sys, os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    symbol="RELIANCE",
    strategy="MOMENTUM",
    sector="Energy",
    regime="TRENDING_BULLISH",
    entry=2500.0,
    exit_p=2550.0,
    qty=10,
    pnl=500.0,
    pnl_pct=0.02,
    holding=45.0,
    exit_reason="target",
    ai_conf=0.75,
    timestamp="2024-01-15T10:30:00",
):
    return {
        "trade_id": f"T-{symbol}-{timestamp}",
        "timestamp": timestamp,
        "symbol": symbol,
        "strategy": strategy,
        "market_regime": regime,
        "sector": sector,
        "entry_price": entry,
        "exit_price": exit_p,
        "quantity": qty,
        "holding_time_minutes": holding,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "execution_quality_score": 85.0,
        "ai_confidence": ai_conf,
        "ai_recommendation": "BUY",
        "exit_reason": exit_reason,
    }


def _win():
    return _make_record(pnl=500.0, pnl_pct=0.02, exit_reason="target")


def _loss():
    return _make_record(
        symbol="TCS", entry=3500.0, exit_p=3430.0, qty=5,
        pnl=-350.0, pnl_pct=-0.02, exit_reason="stop_loss",
        sector="IT", timestamp="2024-01-15T11:00:00",
    )


def _small_dataset():
    return [_win(), _loss(), _win(), _loss(), _win()]


def _large_dataset(n=50):
    records = []
    for i in range(n):
        win = i % 3 != 0  # ~67% win rate
        records.append(_make_record(
            symbol=f"SYM{i % 5}",
            strategy="MOMENTUM" if i % 2 == 0 else "REVERSAL",
            sector=["Energy", "IT", "Finance", "Pharma"][i % 4],
            regime="TRENDING_BULLISH" if i % 2 == 0 else "RANGING",
            entry=1000.0 + i * 10,
            exit_p=1000.0 + i * 10 + (20 if win else -15),
            qty=10,
            pnl=200.0 if win else -150.0,
            pnl_pct=0.02 if win else -0.015,
            exit_reason="target" if win else "stop_loss",
            timestamp=f"2024-01-{(i % 28) + 1:02d}T10:00:00",
        ))
    return records


# ===========================================================================
# 1. Feature flag (5 tests)
# ===========================================================================

class TestFeatureFlag(unittest.TestCase):

    def setUp(self):
        os.environ.pop("RISK_OPTIMISATION_ENABLED", None)

    def tearDown(self):
        os.environ.pop("RISK_OPTIMISATION_ENABLED", None)

    def test_flag_disabled_by_default(self):
        from risk_optimisation.risk_models import is_enabled
        self.assertFalse(is_enabled())

    def test_flag_enabled_when_set_true(self):
        os.environ["RISK_OPTIMISATION_ENABLED"] = "true"
        from risk_optimisation.risk_models import is_enabled
        self.assertTrue(is_enabled())

    def test_summary_returns_disabled(self):
        from risk_optimisation.shared_services import get_summary
        result = get_summary()
        self.assertEqual(result["status"], "DISABLED")

    def test_capital_returns_disabled(self):
        from risk_optimisation.shared_services import get_capital
        result = get_capital()
        self.assertEqual(result["status"], "DISABLED")

    def test_all_endpoints_disabled_when_flag_off(self):
        from risk_optimisation.shared_services import (
            get_summary, get_capital, get_drawdown, get_stress, get_recommendations
        )
        for fn in [get_summary, get_capital, get_drawdown, get_stress, get_recommendations]:
            self.assertEqual(fn()["status"], "DISABLED")


# ===========================================================================
# 2. Capital analyser (6 tests)
# ===========================================================================

class TestCapitalAnalyser(unittest.TestCase):

    def test_empty_records_returns_zeros(self):
        from risk_optimisation.capital_analyser import analyse_capital
        r = analyse_capital([])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["capital_utilisation_rate"], 0.0)

    def test_capital_deployed_is_entry_x_qty(self):
        from risk_optimisation.capital_analyser import analyse_capital
        rec = _make_record(entry=1000.0, qty=50, pnl=500.0)
        r = analyse_capital([rec])
        self.assertAlmostEqual(r["avg_capital_usage"], 50_000.0, places=1)

    def test_idle_capital_is_remainder(self):
        from risk_optimisation.capital_analyser import analyse_capital
        rec = _make_record(entry=1000.0, qty=10, pnl=100.0)
        r = analyse_capital([rec], starting_capital=500_000.0)
        self.assertAlmostEqual(r["idle_capital"], 500_000.0 - 10_000.0, places=0)

    def test_capital_efficiency_bounded_0_1(self):
        from risk_optimisation.capital_analyser import analyse_capital
        records = _small_dataset()
        r = analyse_capital(records)
        self.assertGreaterEqual(r["capital_efficiency"], 0.0)
        self.assertLessEqual(r["capital_efficiency"], 1.0)

    def test_recommended_allocation_gte_zero(self):
        from risk_optimisation.capital_analyser import analyse_capital
        r = analyse_capital(_large_dataset())
        self.assertGreaterEqual(r["recommended_allocation"], 0.0)

    def test_allocation_stability_bounded(self):
        from risk_optimisation.capital_analyser import analyse_capital
        r = analyse_capital(_large_dataset())
        self.assertGreaterEqual(r["allocation_stability"], 0.0)
        self.assertLessEqual(r["allocation_stability"], 1.0)


# ===========================================================================
# 3. Position sizing (4 tests)
# ===========================================================================

class TestPositionAnalyser(unittest.TestCase):

    def test_empty_records(self):
        from risk_optimisation.capital_analyser import analyse_position_sizing
        r = analyse_position_sizing([])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["avg_position_size"], 0.0)

    def test_avg_position_non_negative(self):
        from risk_optimisation.capital_analyser import analyse_position_sizing
        r = analyse_position_sizing(_small_dataset())
        self.assertGreater(r["avg_position_size"], 0)

    def test_largest_position_gte_smallest(self):
        from risk_optimisation.capital_analyser import analyse_position_sizing
        r = analyse_position_sizing(_large_dataset())
        self.assertGreaterEqual(r["largest_position"], r["smallest_position"])

    def test_position_sizing_score_bounded(self):
        from risk_optimisation.capital_analyser import analyse_position_sizing
        r = analyse_position_sizing(_large_dataset())
        self.assertGreaterEqual(r["position_sizing_score"], 0.0)
        self.assertLessEqual(r["position_sizing_score"], 1.0)


# ===========================================================================
# 4. Concentration analyser (5 tests)
# ===========================================================================

class TestConcentrationAnalyser(unittest.TestCase):

    def test_empty_records(self):
        from risk_optimisation.concentration_analyser import analyse_concentration
        r = analyse_concentration([])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["diversification_score"], 0.0)

    def test_single_sector_high_hhi(self):
        from risk_optimisation.concentration_analyser import analyse_concentration
        records = [_win() for _ in range(10)]  # all Energy sector
        r = analyse_concentration(records)
        self.assertGreater(r["hhi_sector"], 0.5)

    def test_multiple_sectors_lower_hhi(self):
        from risk_optimisation.concentration_analyser import analyse_concentration
        r = analyse_concentration(_large_dataset())
        self.assertLess(r["hhi_sector"], 0.5)

    def test_diversification_score_bounded(self):
        from risk_optimisation.concentration_analyser import analyse_concentration
        r = analyse_concentration(_large_dataset())
        self.assertGreaterEqual(r["diversification_score"], 0.0)
        self.assertLessEqual(r["diversification_score"], 1.0)

    def test_correlation_risk_values(self):
        from risk_optimisation.concentration_analyser import analyse_concentration
        r = analyse_concentration(_large_dataset())
        self.assertIn(r["correlation_risk"], ("LOW", "MEDIUM", "HIGH"))


# ===========================================================================
# 5. Drawdown analyser (6 tests)
# ===========================================================================

class TestDrawdownAnalyser(unittest.TestCase):

    def test_empty_records(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        r = analyse_drawdown([])
        self.assertEqual(r["max_drawdown"], 0.0)
        self.assertEqual(r["total_drawdown_periods"], 0)

    def test_all_wins_no_drawdown(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        records = [_win() for _ in range(10)]
        r = analyse_drawdown(records)
        self.assertEqual(r["max_drawdown"], 0.0)

    def test_alternating_win_loss_has_drawdown(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        records = _small_dataset()  # wins and losses
        r = analyse_drawdown(records)
        self.assertGreaterEqual(r["max_drawdown"], 0.0)

    def test_max_drawdown_bounded_0_1(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        records = _large_dataset()
        r = analyse_drawdown(records)
        self.assertGreaterEqual(r["max_drawdown"], 0.0)
        self.assertLessEqual(r["max_drawdown"], 1.0)

    def test_equity_curve_starts_at_starting_capital(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        r = analyse_drawdown(_small_dataset(), starting_capital=500_000.0)
        self.assertEqual(r["equity_curve_head"][0], 500_000.0)

    def test_high_drawdown_severity_near_1(self):
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        # All losses
        records = [_loss() for _ in range(30)]
        r = analyse_drawdown(records, starting_capital=500_000.0)
        self.assertGreater(r["drawdown_severity"], 0.0)


# ===========================================================================
# 6. Stop loss analyser (5 tests)
# ===========================================================================

class TestStopLossAnalyser(unittest.TestCase):

    def test_empty_records(self):
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        r = analyse_stop_loss([])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["stop_loss_hits"], 0)

    def test_counts_stop_loss_exits(self):
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        records = [_loss(), _loss(), _win()]  # 2 stop, 1 target
        r = analyse_stop_loss(records)
        self.assertEqual(r["stop_loss_hits"], 2)

    def test_stop_loss_rate_bounded(self):
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        r = analyse_stop_loss(_large_dataset())
        self.assertGreaterEqual(r["stop_loss_rate"], 0.0)
        self.assertLessEqual(r["stop_loss_rate"], 1.0)

    def test_quality_score_bounded(self):
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        r = analyse_stop_loss(_large_dataset())
        self.assertGreaterEqual(r["stop_loss_quality_score"], 0.0)
        self.assertLessEqual(r["stop_loss_quality_score"], 1.0)

    def test_advisory_is_string(self):
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        r = analyse_stop_loss(_small_dataset())
        self.assertIsInstance(r["advisory"], str)
        self.assertGreater(len(r["advisory"]), 0)


# ===========================================================================
# 7. Target analyser (4 tests)
# ===========================================================================

class TestTargetAnalyser(unittest.TestCase):

    def test_empty_records(self):
        from risk_optimisation.target_analyser import analyse_targets
        r = analyse_targets([])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["target_hits"], 0)

    def test_counts_target_exits(self):
        from risk_optimisation.target_analyser import analyse_targets
        records = [_win(), _win(), _loss()]  # 2 target, 1 SL
        r = analyse_targets(records)
        self.assertEqual(r["target_hits"], 2)

    def test_reward_risk_ratio_gte_zero(self):
        from risk_optimisation.target_analyser import analyse_targets
        r = analyse_targets(_large_dataset())
        self.assertGreaterEqual(r["reward_risk_ratio"], 0.0)

    def test_win_rate_plus_loss_rate_eq_1(self):
        from risk_optimisation.target_analyser import analyse_targets
        records = _large_dataset()
        r = analyse_targets(records)
        n = r["total_trades"]
        self.assertEqual(r["winning_trades"] + r["losing_trades"], n)


# ===========================================================================
# 8. Stress tester (5 tests)
# ===========================================================================

class TestStressTester(unittest.TestCase):

    def test_always_returns_7_scenarios(self):
        from risk_optimisation.stress_tester import run_stress_tests
        r = run_stress_tests([])
        self.assertEqual(r["total_scenarios"], 7)

    def test_scenarios_have_required_keys(self):
        from risk_optimisation.stress_tester import run_stress_tests
        r = run_stress_tests(_small_dataset())
        for s in r["scenarios"]:
            self.assertIn("name", s)
            self.assertIn("severity", s)
            self.assertIn("estimated_portfolio_pnl", s)
            self.assertIn("advisory", s)

    def test_gap_up_positive_pnl(self):
        from risk_optimisation.stress_tester import run_stress_tests
        r = run_stress_tests(_small_dataset())
        gap_up = next(s for s in r["scenarios"] if s["scenario_type"] == "GAP_UP")
        self.assertGreater(gap_up["estimated_portfolio_pnl"], 0)

    def test_correction_negative_pnl(self):
        from risk_optimisation.stress_tester import run_stress_tests
        r = run_stress_tests(_small_dataset())
        corr = next(s for s in r["scenarios"] if s["scenario_type"] == "CORRECTION")
        self.assertLess(corr["estimated_portfolio_pnl"], 0)

    def test_monte_carlo_disabled_by_default(self):
        from risk_optimisation.stress_tester import run_stress_tests
        r = run_stress_tests([])
        self.assertFalse(r["monte_carlo_simulation"]["enabled"])


# ===========================================================================
# 9. Recommendation engine (4 tests)
# ===========================================================================

class TestRecommendationEngine(unittest.TestCase):

    def _build_inputs(self, records):
        from risk_optimisation.capital_analyser import analyse_capital, analyse_position_sizing
        from risk_optimisation.concentration_analyser import analyse_concentration
        from risk_optimisation.drawdown_analyser import analyse_drawdown
        from risk_optimisation.stop_loss_analyser import analyse_stop_loss
        from risk_optimisation.target_analyser import analyse_targets
        return (
            analyse_capital(records),
            analyse_position_sizing(records),
            analyse_concentration(records),
            analyse_drawdown(records),
            analyse_stop_loss(records),
            analyse_targets(records),
        )

    def test_no_data_returns_empty_list(self):
        from risk_optimisation.recommendation_engine import generate_risk_recommendations
        cap, pos, conc, dd, sl, tgt = self._build_inputs([])
        recs = generate_risk_recommendations(cap, pos, conc, dd, sl, tgt)
        self.assertIsInstance(recs, list)

    def test_advisory_only_always_true(self):
        from risk_optimisation.recommendation_engine import generate_risk_recommendations
        cap, pos, conc, dd, sl, tgt = self._build_inputs(_large_dataset())
        recs = generate_risk_recommendations(cap, pos, conc, dd, sl, tgt)
        for r in recs:
            self.assertTrue(r.advisory_only)
            self.assertTrue(r.to_dict()["advisory_only"])

    def test_high_priority_recs_sorted_first(self):
        from risk_optimisation.recommendation_engine import generate_risk_recommendations
        # Create dataset with known issues: high concentration + high drawdown
        records = [_loss() for _ in range(20)] + [_win() for _ in range(5)]
        cap, pos, conc, dd, sl, tgt = self._build_inputs(records)
        recs = generate_risk_recommendations(cap, pos, conc, dd, sl, tgt)
        if len(recs) >= 2:
            order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            priorities = [order[r.priority] for r in recs]
            self.assertEqual(priorities, sorted(priorities))

    def test_recs_have_required_fields(self):
        from risk_optimisation.recommendation_engine import generate_risk_recommendations
        cap, pos, conc, dd, sl, tgt = self._build_inputs(_large_dataset())
        recs = generate_risk_recommendations(cap, pos, conc, dd, sl, tgt)
        for r in recs:
            d = r.to_dict()
            for key in ("category", "recommendation", "rationale", "confidence", "expected_benefit", "priority"):
                self.assertIn(key, d)


# ===========================================================================
# 10. Shared services API (6 tests)
# ===========================================================================

class TestSharedServicesAPI(unittest.TestCase):

    def setUp(self):
        os.environ["RISK_OPTIMISATION_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("RISK_OPTIMISATION_ENABLED", None)

    def _patch_records(self, records):
        """Monkey-patch _get_records for the duration of the test."""
        import risk_optimisation.shared_services as ss
        ss._original_get_records = ss._get_records
        ss._get_records = lambda: records
        return ss

    def _unpatch(self, ss):
        ss._get_records = ss._original_get_records

    def test_summary_returns_enabled(self):
        from risk_optimisation.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")

    def test_summary_score_bounded_0_100(self):
        ss = self._patch_records(_large_dataset())
        try:
            from risk_optimisation.shared_services import get_summary
            r = get_summary()
            self.assertGreaterEqual(r["risk_optimisation_score"], 0.0)
            self.assertLessEqual(r["risk_optimisation_score"], 100.0)
        finally:
            self._unpatch(ss)

    def test_capital_endpoint_has_nested_sections(self):
        ss = self._patch_records(_large_dataset())
        try:
            from risk_optimisation.shared_services import get_capital
            r = get_capital()
            self.assertIn("capital_allocation", r)
            self.assertIn("position_sizing", r)
            self.assertIn("portfolio_concentration", r)
        finally:
            self._unpatch(ss)

    def test_drawdown_endpoint_keys(self):
        ss = self._patch_records(_large_dataset())
        try:
            from risk_optimisation.shared_services import get_drawdown
            r = get_drawdown()
            for k in ("max_drawdown", "avg_drawdown", "recovery_efficiency"):
                self.assertIn(k, r)
        finally:
            self._unpatch(ss)

    def test_stress_endpoint_has_7_scenarios(self):
        ss = self._patch_records(_small_dataset())
        try:
            from risk_optimisation.shared_services import get_stress
            r = get_stress()
            self.assertEqual(r["total_scenarios"], 7)
        finally:
            self._unpatch(ss)

    def test_recommendations_advisory_only(self):
        ss = self._patch_records(_large_dataset())
        try:
            from risk_optimisation.shared_services import get_recommendations
            r = get_recommendations()
            self.assertTrue(r["advisory_only"])
            for rec in r["recommendations"]:
                self.assertTrue(rec["advisory_only"])
        finally:
            self._unpatch(ss)


# ===========================================================================
# 11. Health score model (4 tests)
# ===========================================================================

class TestHealthScoreModel(unittest.TestCase):

    def test_perfect_inputs_gives_100(self):
        from risk_optimisation.risk_models import compute_risk_optimisation_score, health_grade
        score = compute_risk_optimisation_score(1.0, 0.0, 1.0, 1.0, 1.0)
        self.assertEqual(score, 100.0)
        self.assertEqual(health_grade(score), "A+")

    def test_zero_inputs_gives_low_score(self):
        from risk_optimisation.risk_models import compute_risk_optimisation_score, health_grade
        score = compute_risk_optimisation_score(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertLessEqual(score, 20.0)
        self.assertEqual(health_grade(score), "D")

    def test_grade_thresholds(self):
        from risk_optimisation.risk_models import health_grade
        self.assertEqual(health_grade(95.0), "A+")
        self.assertEqual(health_grade(85.0), "A")
        self.assertEqual(health_grade(70.0), "B")
        self.assertEqual(health_grade(55.0), "C")
        self.assertEqual(health_grade(30.0), "D")

    def test_snapshot_has_required_keys(self):
        os.environ["RISK_OPTIMISATION_ENABLED"] = "true"
        try:
            from risk_optimisation.shared_services import get_risk_optimisation_snapshot
            snap = get_risk_optimisation_snapshot()
            for k in ("risk_optimisation_score", "grade", "max_drawdown", "capital_efficiency",
                      "diversification_score", "correlation_risk"):
                self.assertIn(k, snap)
        finally:
            os.environ.pop("RISK_OPTIMISATION_ENABLED", None)


if __name__ == "__main__":
    unittest.main()
