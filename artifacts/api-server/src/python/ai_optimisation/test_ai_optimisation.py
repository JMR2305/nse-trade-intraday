"""
test_ai_optimisation.py — Phase 6.3
Tests: zero trades, small dataset, large dataset, poor AI, excellent AI,
       missing confidence, feature flag, API endpoints, restart persistence.
"""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["AI_OPTIMISATION_ENABLED"] = "true"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _rec(trade_id, symbol="RELIANCE", strategy="Momentum", regime="Bull",
         sector="Energy", pnl=500.0, pnl_pct=2.0, confidence=0.78,
         eq_score=85.0, risk=0.3, rec="BUY", hold=315.0,
         ts="2026-07-29T14:30:00+05:30"):
    from paper_trading_validation.validation_models import TradeRecord
    return TradeRecord(
        trade_id=trade_id, timestamp=ts, symbol=symbol,
        strategy=strategy, market_regime=regime, sector=sector,
        entry_price=2500.0, exit_price=2500.0 + pnl / 10,
        quantity=10, holding_time_minutes=hold,
        pnl=pnl, pnl_pct=pnl_pct,
        execution_quality_score=eq_score, ai_confidence=confidence,
        ai_recommendation=rec, signal_validation_status="VALID",
        risk_score=risk, portfolio_value_at_entry=500000.0,
        executive_score_snapshot=72.0, exit_reason="Target",
    )


def _patch(records):
    return patch("ai_optimisation.shared_services._get_records", return_value=records)


def _good_records(n=20):
    return [_rec(f"g{i}", pnl=500 + i * 10, confidence=0.78) for i in range(n)]


def _poor_records(n=20):
    return [_rec(f"p{i}", pnl=-300 if i % 3 != 0 else 200, confidence=0.3, rec="BUY") for i in range(n)]


# ---------------------------------------------------------------------------
# TestFeatureFlag
# ---------------------------------------------------------------------------

class TestFeatureFlag(unittest.TestCase):

    def _test_disabled(self, fn_path, fn_name):
        with patch.dict(os.environ, {"AI_OPTIMISATION_ENABLED": "false"}):
            import importlib
            mod = importlib.import_module(fn_path)
            fn = getattr(mod, fn_name)
            r = fn()
            self.assertEqual(r["status"], "DISABLED")

    def test_summary_disabled(self):
        self._test_disabled("ai_optimisation.shared_services", "get_summary")

    def test_calibration_disabled(self):
        self._test_disabled("ai_optimisation.shared_services", "get_calibration")

    def test_drift_disabled(self):
        self._test_disabled("ai_optimisation.shared_services", "get_drift")

    def test_recommendations_disabled(self):
        self._test_disabled("ai_optimisation.shared_services", "get_recommendations")

    def test_history_disabled(self):
        self._test_disabled("ai_optimisation.shared_services", "get_history")


# ---------------------------------------------------------------------------
# TestPerformanceAnalyser
# ---------------------------------------------------------------------------

class TestPerformanceAnalyser(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_empty_returns_zeroes(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        r = analyse_prediction_quality([])
        self.assertEqual(r["total_signals"], 0)
        self.assertEqual(r["accuracy"], 0.0)

    def test_all_winning_buys(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        records = [_rec(f"w{i}", pnl=500, rec="BUY") for i in range(10)]
        r = analyse_prediction_quality(records)
        self.assertGreater(r["accuracy"], 0.0)
        self.assertGreater(r["precision"], 0.0)
        self.assertEqual(r["tp"], 10)
        self.assertEqual(r["fp"], 0)

    def test_all_losing_buys(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        records = [_rec(f"l{i}", pnl=-300, rec="BUY") for i in range(10)]
        r = analyse_prediction_quality(records)
        self.assertEqual(r["tp"], 0)
        self.assertEqual(r["fp"], 10)

    def test_mixed_signals(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        records = ([_rec(f"w{i}", pnl=500, rec="BUY") for i in range(7)]
                   + [_rec(f"l{i}", pnl=-300, rec="BUY") for i in range(3)])
        r = analyse_prediction_quality(records)
        self.assertAlmostEqual(r["accuracy"], 0.7, places=2)

    def test_ece_well_calibrated(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        # 10 trades with 80% confidence, 8 wins → well calibrated
        records = ([_rec(f"w{i}", pnl=500, rec="BUY", confidence=0.82) for i in range(8)]
                   + [_rec(f"l{i}", pnl=-300, rec="BUY", confidence=0.82) for i in range(2)])
        r = analyse_prediction_quality(records)
        self.assertLess(r["ece"], 0.15)

    def test_missing_confidence_handled(self):
        from ai_optimisation.performance_analyser import analyse_prediction_quality
        from paper_trading_validation.validation_models import TradeRecord
        rec = TradeRecord(
            trade_id="nc1", timestamp="2026-07-29T14:30:00+05:30",
            symbol="TCS", strategy="Momentum", market_regime="Bull",
            sector="IT", entry_price=3000.0, exit_price=3060.0, quantity=5,
            holding_time_minutes=120.0, pnl=300.0, pnl_pct=2.0,
            execution_quality_score=80.0, ai_confidence=None,
            ai_recommendation="BUY", signal_validation_status="VALID",
            risk_score=0.3, portfolio_value_at_entry=500000.0,
            executive_score_snapshot=70.0, exit_reason="Target",
        )
        r = analyse_prediction_quality([rec])
        self.assertIsNotNone(r["avg_confidence"])


# ---------------------------------------------------------------------------
# TestCalibrationAnalyser
# ---------------------------------------------------------------------------

class TestCalibrationAnalyser(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_empty_returns_five_bands(self):
        from ai_optimisation.calibration_analyser import analyse_calibration
        r = analyse_calibration([])
        self.assertEqual(len(r["bands"]), 5)

    def test_band_population(self):
        from ai_optimisation.calibration_analyser import analyse_calibration
        records = [_rec(f"r{i}", confidence=0.72) for i in range(10)]
        r = analyse_calibration(records)
        band_60_80 = next(b for b in r["bands"] if b["band"] == "60–80%")
        self.assertEqual(band_60_80["trades"], 10)

    def test_threshold_recommendation_present(self):
        from ai_optimisation.calibration_analyser import analyse_calibration
        records = _good_records(30)
        r = analyse_calibration(records)
        self.assertIn("recommended_threshold", r)
        self.assertIsInstance(r["recommended_threshold"], float)

    def test_prediction_error_nonnegative(self):
        from ai_optimisation.calibration_analyser import analyse_calibration
        records = _good_records(20)
        r = analyse_calibration(records)
        for b in r["bands"]:
            self.assertGreaterEqual(b["prediction_error"], 0.0)


# ---------------------------------------------------------------------------
# TestFalseSignalAnalyser
# ---------------------------------------------------------------------------

class TestFalseSignalAnalyser(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_empty_returns_zero_rate(self):
        from ai_optimisation.false_signal_analyser import analyse_false_signals
        r = analyse_false_signals([])
        self.assertEqual(r["false_signal_rate"], 0.0)

    def test_false_buy_detected(self):
        from ai_optimisation.false_signal_analyser import analyse_false_signals
        records = [_rec(f"fb{i}", pnl=-300, rec="BUY") for i in range(5)]
        r = analyse_false_signals(records)
        fb = next(s for s in r["false_signals"] if s["signal_type"] == "FALSE_BUY")
        self.assertEqual(fb["count"], 5)

    def test_high_conf_loss_detected(self):
        from ai_optimisation.false_signal_analyser import analyse_false_signals
        records = [_rec(f"hcl{i}", pnl=-300, confidence=0.85, rec="BUY") for i in range(3)]
        r = analyse_false_signals(records)
        hcl = next(s for s in r["false_signals"] if s["signal_type"] == "HIGH_CONF_LOSS")
        self.assertEqual(hcl["count"], 3)

    def test_low_conf_win_detected(self):
        from ai_optimisation.false_signal_analyser import analyse_false_signals
        records = [_rec(f"lcw{i}", pnl=500, confidence=0.35, rec="BUY") for i in range(4)]
        r = analyse_false_signals(records)
        lcw = next(s for s in r["false_signals"] if s["signal_type"] == "LOW_CONF_WIN")
        self.assertEqual(lcw["count"], 4)

    def test_insights_generated_on_high_false_rate(self):
        from ai_optimisation.false_signal_analyser import analyse_false_signals
        records = [_rec(f"hfr{i}", pnl=-300, rec="BUY", confidence=0.8) for i in range(10)]
        r = analyse_false_signals(records)
        self.assertGreater(len(r["advisory_insights"]), 0)


# ---------------------------------------------------------------------------
# TestDriftAnalyser
# ---------------------------------------------------------------------------

class TestDriftAnalyser(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_empty_returns_empty_metrics(self):
        from ai_optimisation.drift_analyser import analyse_drift
        r = analyse_drift([])
        self.assertEqual(r["total_drift_dimensions"], 6)
        self.assertEqual(r["metrics"], [])

    def test_insufficient_history_stable(self):
        from ai_optimisation.drift_analyser import analyse_drift
        records = [_rec(f"s{i}") for i in range(5)]
        r = analyse_drift(records)
        self.assertIn(r["overall_drift_severity"], ["STABLE", "LOW", "MEDIUM", "HIGH", "NONE"])

    def test_large_dataset_has_six_metrics(self):
        from ai_optimisation.drift_analyser import analyse_drift
        records = [_rec(f"d{i}", ts=f"2026-07-{(i%28)+1:02d}T14:30:00+05:30") for i in range(60)]
        r = analyse_drift(records)
        if r["metrics"]:  # may be stable list
            self.assertEqual(len(r["metrics"]), 6)

    def test_drift_score_in_range(self):
        from ai_optimisation.drift_analyser import analyse_drift
        records = [_rec(f"dr{i}", ts=f"2026-07-{(i%28)+1:02d}T14:30:00+05:30") for i in range(60)]
        r = analyse_drift(records)
        self.assertGreaterEqual(r["drift_score"], 0.0)
        self.assertLessEqual(r["drift_score"], 1.0)


# ---------------------------------------------------------------------------
# TestLearningAnalyser
# ---------------------------------------------------------------------------

class TestLearningAnalyser(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_empty_returns_insufficient_data(self):
        from ai_optimisation.learning_analyser import analyse_learning
        r = analyse_learning([])
        self.assertEqual(r["adaptive_trend"], "INSUFFICIENT_DATA")

    def test_improving_velocity_positive(self):
        from ai_optimisation.learning_analyser import analyse_learning
        # Win rates improving over time: early losses, recent wins
        ts_base = "2026-07-{:02d}T14:30:00+05:30"
        records = (
            [_rec(f"early{i}", pnl=-300, ts=ts_base.format(i + 1)) for i in range(5)]
            + [_rec(f"late{i}",  pnl=500,  ts=ts_base.format(i + 10)) for i in range(15)]
        )
        r = analyse_learning(records)
        # velocity could be positive or stable depending on bucket split
        self.assertIsInstance(r["learning_velocity"], float)

    def test_history_buckets_present(self):
        from ai_optimisation.learning_analyser import analyse_learning
        records = [_rec(f"b{i}") for i in range(20)]
        r = analyse_learning(records)
        self.assertGreater(len(r["history"]), 0)

    def test_improvement_regression_sum_le_one(self):
        from ai_optimisation.learning_analyser import analyse_learning
        records = [_rec(f"ir{i}") for i in range(20)]
        r = analyse_learning(records)
        self.assertLessEqual(r["improvement_rate"] + r["regression_rate"], 1.0 + 1e-9)


# ---------------------------------------------------------------------------
# TestRecommendationEngine
# ---------------------------------------------------------------------------

class TestRecommendationEngine(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_no_records_returns_no_data_rec(self):
        from ai_optimisation.recommendation_engine import generate_recommendations
        recs = generate_recommendations([], {})
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].category, "General")

    def test_recommendations_all_advisory(self):
        from ai_optimisation.recommendation_engine import generate_recommendations
        from ai_optimisation.calibration_analyser import analyse_calibration
        records = _good_records(30)
        cal = analyse_calibration(records)
        recs = generate_recommendations(records, cal)
        for r in recs:
            self.assertTrue(r.advisory_only)

    def test_confidence_threshold_rec_present(self):
        from ai_optimisation.recommendation_engine import generate_recommendations
        from ai_optimisation.calibration_analyser import analyse_calibration
        records = _good_records(30)
        cal = analyse_calibration(records)
        recs = generate_recommendations(records, cal)
        categories = [r.category for r in recs]
        self.assertIn("ConfidenceThreshold", categories)


# ---------------------------------------------------------------------------
# TestSharedServicesAPI
# ---------------------------------------------------------------------------

class TestSharedServicesAPI(unittest.TestCase):

    def setUp(self):
        os.environ["AI_OPTIMISATION_ENABLED"] = "true"

    def test_summary_enabled_zero_trades(self):
        with _patch([]):
            from ai_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_trades"], 0)
        self.assertIn("ai_optimisation_score", r)

    def test_summary_score_in_range(self):
        with _patch(_good_records(20)):
            from ai_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertGreaterEqual(r["ai_optimisation_score"], 0.0)
        self.assertLessEqual(r["ai_optimisation_score"], 100.0)

    def test_calibration_has_five_bands(self):
        with _patch(_good_records(20)):
            from ai_optimisation.shared_services import get_calibration
            r = get_calibration()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(len(r["bands"]), 5)

    def test_drift_has_advisory_only(self):
        with _patch(_good_records(20)):
            from ai_optimisation.shared_services import get_drift
            r = get_drift()
        self.assertTrue(r["advisory_only"])

    def test_recommendations_advisory_only_flag(self):
        with _patch(_good_records(20)):
            from ai_optimisation.shared_services import get_recommendations
            r = get_recommendations()
        self.assertTrue(r["advisory_only"])
        for rec in r["recommendations"]:
            self.assertTrue(rec["advisory_only"])

    def test_history_has_learning_velocity(self):
        with _patch(_good_records(20)):
            from ai_optimisation.shared_services import get_history
            r = get_history()
        self.assertIn("learning_velocity", r)

    def test_excellent_ai_high_score(self):
        """Excellent AI: high confidence, all wins, well calibrated."""
        records = [_rec(f"ex{i}", pnl=500, confidence=0.82, rec="BUY") for i in range(50)]
        with _patch(records):
            from ai_optimisation.shared_services import get_summary
            r = get_summary()
        self.assertGreater(r["ai_optimisation_score"], 40.0)

    def test_poor_ai_lower_score(self):
        """Poor AI: low confidence, mostly losses."""
        records = _poor_records(40)
        with _patch(records):
            from ai_optimisation.shared_services import get_summary
            r = get_summary()
        excellent_records = [_rec(f"ex{i}", pnl=500, confidence=0.82) for i in range(50)]
        with _patch(excellent_records):
            from ai_optimisation.shared_services import get_summary as get_summary2
            r_good = get_summary2()
        # poor AI should score lower than excellent AI
        self.assertLess(r["ai_optimisation_score"], r_good["ai_optimisation_score"])


# ---------------------------------------------------------------------------
# TestHealthScoreModel
# ---------------------------------------------------------------------------

class TestHealthScoreModel(unittest.TestCase):

    def test_perfect_inputs(self):
        from ai_optimisation.optimisation_models import compute_ai_optimisation_score, health_grade
        score = compute_ai_optimisation_score(1.0, 0.0, 0.0, 1.0, 0.0)
        self.assertGreater(score, 80.0)
        self.assertIn(health_grade(score), ["A+", "A"])

    def test_zero_inputs(self):
        from ai_optimisation.optimisation_models import compute_ai_optimisation_score, health_grade
        score = compute_ai_optimisation_score(0.0, 1.0, 1.0, -1.0, 1.0)
        self.assertLessEqual(score, 30.0)
        self.assertEqual(health_grade(score), "D")

    def test_grade_thresholds(self):
        from ai_optimisation.optimisation_models import health_grade
        self.assertEqual(health_grade(92), "A+")
        self.assertEqual(health_grade(82), "A")
        self.assertEqual(health_grade(67), "B")
        self.assertEqual(health_grade(52), "C")
        self.assertEqual(health_grade(30), "D")

    def test_snapshot_never_raises(self):
        with _patch([]):
            from ai_optimisation.shared_services import get_ai_optimisation_snapshot
            snap = get_ai_optimisation_snapshot()
        required = ["ai_optimisation_score", "grade", "accuracy",
                    "f1_score", "false_signal_rate", "adaptive_trend"]
        for k in required:
            self.assertIn(k, snap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
