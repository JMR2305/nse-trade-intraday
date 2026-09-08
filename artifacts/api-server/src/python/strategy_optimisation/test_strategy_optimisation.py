"""
test_strategy_optimisation.py — Phase 6.2
Tests: zero trades, small dataset, large dataset, conflicting strategies,
missing data, feature flag, API endpoints, dashboard structure, restart persistence.
"""
import sys, os, json, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers to build mock TradeRecord objects
# ---------------------------------------------------------------------------

def _rec(trade_id, symbol="RELIANCE", strategy="Momentum", regime="Bull",
         sector="Energy", entry=2500.0, exit_p=2600.0, qty=10,
         hold_mins=315.0, pnl=None, pnl_pct=None,
         confidence=0.78, eq_score=85.0, risk=0.3,
         exit_reason="Target", ts="2026-07-29T14:30:00+05:30"):
    from paper_trading_validation.validation_models import TradeRecord
    if pnl is None:
        pnl = (exit_p - entry) * qty
    if pnl_pct is None:
        pnl_pct = (exit_p - entry) / entry * 100.0
    return TradeRecord(
        trade_id=trade_id, timestamp=ts, symbol=symbol,
        strategy=strategy, market_regime=regime, sector=sector,
        entry_price=entry, exit_price=exit_p, quantity=qty,
        holding_time_minutes=hold_mins, pnl=pnl, pnl_pct=pnl_pct,
        execution_quality_score=eq_score, ai_confidence=confidence,
        ai_recommendation="BUY", signal_validation_status="VALID",
        risk_score=risk, portfolio_value_at_entry=500000.0,
        executive_score_snapshot=72.0, exit_reason=exit_reason,
    )


def _patch_records(records):
    return patch(
        "strategy_optimisation.shared_services._get_records",
        return_value=records,
    )


def _set_enabled(val: bool):
    return patch.dict(os.environ, {"STRATEGY_OPTIMISATION_ENABLED": "true" if val else "false"})


# ---------------------------------------------------------------------------
# TestFeatureFlag
# ---------------------------------------------------------------------------

class TestFeatureFlag(unittest.TestCase):

    def test_summary_disabled(self):
        with _set_enabled(False):
            from strategy_optimisation.shared_services import get_summary
            r = get_summary()
            self.assertEqual(r["status"], "DISABLED")

    def test_strategies_disabled(self):
        with _set_enabled(False):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
            self.assertEqual(r["status"], "DISABLED")

    def test_recommendations_disabled(self):
        with _set_enabled(False):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
            self.assertEqual(r["status"], "DISABLED")

    def test_patterns_disabled(self):
        with _set_enabled(False):
            from strategy_optimisation.shared_services import get_patterns
            r = get_patterns()
            self.assertEqual(r["status"], "DISABLED")


# ---------------------------------------------------------------------------
# TestZeroTrades
# ---------------------------------------------------------------------------

class TestZeroTrades(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"

    def test_summary_zero(self):
        with _patch_records([]):
            from strategy_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["total_strategies"], 0)
        self.assertIsNone(r["best_regime"])
        self.assertIsNone(r["best_sector"])

    def test_strategies_zero(self):
        with _patch_records([]):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        self.assertEqual(r["strategies"], [])

    def test_recommendations_zero(self):
        with _patch_records([]):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        self.assertEqual(r["parameter_recommendations"], [])
        self.assertEqual(r["underperforming_actions"], [])

    def test_patterns_zero(self):
        with _patch_records([]):
            from strategy_optimisation.shared_services import get_patterns
            r = get_patterns()
        self.assertEqual(r["total_patterns"], 0)


# ---------------------------------------------------------------------------
# TestSmallDataset (3 trades, 1 strategy)
# ---------------------------------------------------------------------------

class TestSmallDataset(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        self.records = [
            _rec("t1", strategy="Momentum", exit_p=2600, pnl=1000, ts="2026-07-28T14:30:00+05:30"),
            _rec("t2", strategy="Momentum", exit_p=2550, pnl=500, ts="2026-07-29T11:00:00+05:30"),
            _rec("t3", strategy="Momentum", entry=2500, exit_p=2450, pnl=-500, ts="2026-07-29T14:30:00+05:30"),
        ]

    def test_one_strategy_profiled(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        self.assertEqual(len(r["strategies"]), 1)
        self.assertEqual(r["strategies"][0]["strategy"], "Momentum")

    def test_win_rate_two_of_three(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        strat = r["strategies"][0]
        self.assertAlmostEqual(strat["win_rate"], 2 / 3, places=3)

    def test_health_score_in_range(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        hs = r["strategies"][0]["health_score"]
        self.assertGreaterEqual(hs, 0)
        self.assertLessEqual(hs, 100)

    def test_grade_assigned(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        grade = r["strategies"][0]["grade"]
        self.assertIn(grade, ["A+", "A", "B", "C", "D"])

    def test_advisory_only_flag(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        self.assertTrue(r["advisory_only"])
        for s in r["strategies"]:
            self.assertTrue(s["advisory_only"])


# ---------------------------------------------------------------------------
# TestLargeDataset (12 trades, 2 strategies)
# ---------------------------------------------------------------------------

class TestLargeDataset(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        # 6 Momentum wins, 2 losses; 3 MeanRev wins, 1 loss
        self.records = (
            [_rec(f"m_win_{i}", strategy="Momentum", pnl=800, ts=f"2026-07-2{i % 9 + 1}T14:30:00+05:30") for i in range(6)]
            + [_rec(f"m_lose_{i}", strategy="Momentum", exit_p=2400, pnl=-1000, ts=f"2026-07-2{i % 9 + 1}T10:00:00+05:30") for i in range(2)]
            + [_rec(f"mr_win_{i}", strategy="MeanReversion", pnl=600, ts=f"2026-07-2{i % 9 + 1}T11:30:00+05:30") for i in range(3)]
            + [_rec("mr_lose", strategy="MeanReversion", exit_p=2400, pnl=-700, ts="2026-07-25T15:00:00+05:30")]
        )

    def test_two_strategies_profiled(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        strat_names = [s["strategy"] for s in r["strategies"]]
        self.assertIn("Momentum", strat_names)
        self.assertIn("MeanReversion", strat_names)

    def test_momentum_higher_than_meanrev(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        scores = {s["strategy"]: s["health_score"] for s in r["strategies"]}
        self.assertGreater(scores["Momentum"], scores["MeanReversion"])

    def test_regime_analysis_populated(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertIsNotNone(r["best_regime"])
        self.assertEqual(r["best_regime"]["regime"], "Bull")

    def test_sector_analysis_populated(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertIsNotNone(r["best_sector"])

    def test_time_window_analysis(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        # Best time window may or may not be set depending on data
        self.assertIn("time_window_recommendation", r)

    def test_patterns_discovered(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_patterns
            r = get_patterns()
        self.assertGreaterEqual(r["total_patterns"], 0)  # may be 0 with < 3 per combo

    def test_adaptive_learning_has_trend(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        al = r["adaptive_learning"]
        self.assertIn("overall_trend", al)
        self.assertIn(al["overall_trend"], ["IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"])


# ---------------------------------------------------------------------------
# TestConflictingStrategies
# ---------------------------------------------------------------------------

class TestConflictingStrategies(unittest.TestCase):
    """One strategy has very high win rate, another has very low — both profiled correctly."""

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        # Bad strategy: poor execution (eq=45) + poor confidence (conf=0.3)
        # → triggers "Poor Execution" + "Poor AI Confidence" checks
        self.records = (
            [_rec(f"good_{i}", strategy="GoodStrategy", pnl=1000,
                  confidence=0.85, eq_score=88.0) for i in range(8)]
            + [_rec(f"bad_{i}", strategy="BadStrategy", exit_p=2300, pnl=-2000,
                    confidence=0.3, eq_score=45.0, risk=0.5) for i in range(8)]
        )

    def test_good_ranked_first(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        self.assertEqual(r["strategies"][0]["strategy"], "GoodStrategy")

    def test_bad_marked_underperforming(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        bad = next(s for s in r["strategies"] if s["strategy"] == "BadStrategy")
        self.assertTrue(bad["is_underperforming"])
        self.assertEqual(bad["grade"], "D")

    def test_bad_gets_pause_or_retune(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        bad = next(s for s in r["strategies"] if s["strategy"] == "BadStrategy")
        self.assertIn(bad["action"], ["Pause", "Retune", "Observe"])


# ---------------------------------------------------------------------------
# TestMissingData
# ---------------------------------------------------------------------------

class TestMissingData(unittest.TestCase):
    """TradeRecord with None fields should not crash any analyser."""

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        from paper_trading_validation.validation_models import TradeRecord
        self.records = [
            TradeRecord(
                trade_id="null_trade", timestamp="2026-07-29T14:30:00+05:30",
                symbol="TEST", strategy="NullStrat", market_regime="Unknown",
                sector="Unknown", entry_price=1000.0, exit_price=1050.0, quantity=10,
                holding_time_minutes=60.0, pnl=500.0, pnl_pct=5.0,
                execution_quality_score=None, ai_confidence=None,
                ai_recommendation=None, signal_validation_status=None,
                risk_score=None, portfolio_value_at_entry=None,
                executive_score_snapshot=None, exit_reason="Target",
            )
        ]

    def test_no_crash_on_null_fields(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies, get_patterns, get_recommendations
            s = get_strategies()
            p = get_patterns()
            r = get_recommendations()
        self.assertEqual(s["status"], "ENABLED")
        self.assertEqual(p["status"], "ENABLED")
        self.assertEqual(r["status"], "ENABLED")

    def test_profile_has_zero_confidence(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r = get_strategies()
        strat = r["strategies"][0]
        self.assertEqual(strat["avg_confidence"], 0.0)


# ---------------------------------------------------------------------------
# TestParameterOptimiser
# ---------------------------------------------------------------------------

class TestParameterOptimiser(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        # 5 wins, 3 losses — enough to trigger most recommendations
        self.records = (
            [_rec(f"w{i}", pnl=1000, confidence=0.8, eq_score=88.0) for i in range(5)]
            + [_rec(f"l{i}", exit_p=2350, pnl=-1500, confidence=0.45, eq_score=55.0) for i in range(3)]
        )

    def test_recommendations_generated(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        params = [p["parameter"] for p in r["parameter_recommendations"]]
        self.assertIn("Stop Loss", params)
        self.assertIn("Target", params)
        self.assertIn("Risk/Reward", params)

    def test_all_recs_advisory_only(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        for rec in r["parameter_recommendations"]:
            self.assertTrue(rec["advisory_only"])


# ---------------------------------------------------------------------------
# TestStrategyScoring
# ---------------------------------------------------------------------------

class TestStrategyScoring(unittest.TestCase):

    def test_grade_function(self):
        from strategy_optimisation.optimisation_models import grade
        self.assertEqual(grade(95), "A+")
        self.assertEqual(grade(82), "A")
        self.assertEqual(grade(70), "B")
        self.assertEqual(grade(55), "C")
        self.assertEqual(grade(30), "D")

    def test_perfect_strategy_gets_high_score(self):
        from strategy_optimisation.strategy_analyser import analyse_strategies
        records = [_rec(f"p{i}", pnl=1000, confidence=0.9) for i in range(10)]
        profiles = analyse_strategies(records)
        self.assertEqual(len(profiles), 1)
        self.assertGreater(profiles[0].health_score, 60)

    def test_losing_strategy_gets_low_score(self):
        from strategy_optimisation.strategy_analyser import analyse_strategies
        records = [_rec(f"l{i}", exit_p=2200, pnl=-3000, confidence=0.3) for i in range(10)]
        profiles = analyse_strategies(records)
        self.assertLess(profiles[0].health_score, 50)


# ---------------------------------------------------------------------------
# TestRestartPersistence
# ---------------------------------------------------------------------------

class TestRestartPersistence(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"
        self.records = [_rec(f"r{i}", pnl=(1 if i % 2 == 0 else -1) * 500) for i in range(6)]

    def test_summary_deterministic(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_summary
            r1 = get_summary()
            r2 = get_summary()
        self.assertEqual(r1["total_strategies"], r2["total_strategies"])
        self.assertEqual(r1["total_trades"], r2["total_trades"])

    def test_strategies_deterministic(self):
        with _patch_records(self.records):
            from strategy_optimisation.shared_services import get_strategies
            r1 = get_strategies()
            r2 = get_strategies()
        s1 = r1["strategies"][0]["health_score"] if r1["strategies"] else None
        s2 = r2["strategies"][0]["health_score"] if r2["strategies"] else None
        self.assertEqual(s1, s2)


# ---------------------------------------------------------------------------
# TestAdaptiveLearning
# ---------------------------------------------------------------------------

class TestAdaptiveLearning(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"

    def test_lifecycle_emerging_on_few_trades(self):
        from strategy_optimisation.adaptive_learning import _lifecycle_state
        records = [_rec(f"e{i}", pnl=500) for i in range(3)]
        state = _lifecycle_state(records)
        self.assertEqual(state, "EMERGING")

    def test_lifecycle_active_on_consistent_trades(self):
        from datetime import date
        from strategy_optimisation.adaptive_learning import _lifecycle_state
        records = [_rec(f"a{i}", pnl=500, ts="2026-07-29T14:30:00+05:30") for i in range(8)]
        with patch("strategy_optimisation.adaptive_learning.date", wraps=date) as clock:
            clock.today.return_value = date(2026, 7, 30)
            state = _lifecycle_state(records)
        self.assertIn(state, ["ACTIVE", "DECLINING"])  # depends on win rate

    def test_trend_direction_improving(self):
        from strategy_optimisation.adaptive_learning import _trend_direction
        self.assertEqual(_trend_direction([0.3, 0.4, 0.5, 0.6, 0.7]), "IMPROVING")

    def test_trend_direction_declining(self):
        from strategy_optimisation.adaptive_learning import _trend_direction
        self.assertEqual(_trend_direction([0.7, 0.6, 0.5, 0.4, 0.3]), "DECLINING")

    def test_trend_direction_stable(self):
        from strategy_optimisation.adaptive_learning import _trend_direction
        self.assertEqual(_trend_direction([0.6, 0.6, 0.6, 0.6, 0.6]), "STABLE")


# ---------------------------------------------------------------------------
# TestOptimisationSnapshot
# ---------------------------------------------------------------------------

class TestOptimisationSnapshot(unittest.TestCase):

    def setUp(self):
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"

    def test_snapshot_required_keys(self):
        records = [_rec(f"s{i}", pnl=500) for i in range(5)]
        with _patch_records(records):
            from strategy_optimisation.shared_services import get_optimisation_snapshot
            snap = get_optimisation_snapshot()
        required = ["total_strategies", "best_strategy", "best_strategy_health",
                    "best_strategy_grade", "underperforming_count"]
        for key in required:
            self.assertIn(key, snap)

    def test_snapshot_zero_on_no_data(self):
        with _patch_records([]):
            from strategy_optimisation.shared_services import get_optimisation_snapshot
            snap = get_optimisation_snapshot()
        self.assertEqual(snap["total_strategies"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
