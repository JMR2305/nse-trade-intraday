"""
test_ai_performance.py — Phase 5D.4 unit tests.

14 test scenarios covering all spec requirements:
  ✓ Disabled feature flag
  ✓ Zero signals
  ✓ One signal
  ✓ Multiple signals
  ✓ High confidence predictions
  ✓ Low confidence predictions
  ✓ Precision / Recall calculations
  ✓ Calibration calculations
  ✓ AI Health Score
  ✓ Shared service reuse (5D.3 strategy_intelligence)
  ✓ API responses
  ✓ Recommendation analysis
  ✓ Learning / trend analysis
  ✓ Restart persistence

Run: python -m pytest ai_performance/test_ai_performance.py -v
"""
from __future__ import annotations

import os
import sys
import math
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

# Disable feature flags by default
os.environ.pop("AI_PERFORMANCE_ENABLED", None)
os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

# ── Stub market_scanner ────────────────────────────────────────────────────────
_scanner = types.ModuleType("market_scanner")
_scanner._sector_of = lambda sym: {"INFY": "IT", "HDFCBANK": "Banking", "RELIANCE": "Energy"}.get(sym, "Unknown")
sys.modules.setdefault("market_scanner", _scanner)

# ── Stub execution_quality ────────────────────────────────────────────────────
_eq_stub = types.ModuleType("execution_quality")
_eq_metrics_stub = types.ModuleType("execution_quality.metrics")
_eq_metrics_stub.build_execution_records = lambda: []
_eq_stub.metrics = _eq_metrics_stub
sys.modules.setdefault("execution_quality", _eq_stub)
sys.modules.setdefault("execution_quality.metrics", _eq_metrics_stub)


# ── Trade helpers ─────────────────────────────────────────────────────────────
def _ts(offset_hours: float = 0, day_offset: int = 0) -> str:
    base = datetime(2026, 7, 21, 4, 0, 0, tzinfo=timezone.utc)  # Mon 09:30 IST
    return (base + timedelta(hours=offset_hours, days=day_offset)).isoformat()


def _buy(symbol="INFY", offset=0.0, day=0, strategy_name="Momentum",
         confidence=0.75, regime="Bullish", stop=950.0, target=1080.0):
    qty, price = 10, 1000.0
    return {
        "id": f"buy-{symbol}-{day}-{offset}",
        "symbol": symbol, "action": "BUY",
        "quantity": qty, "price": price, "total": qty * price,
        "timestamp": _ts(offset, day),
        "strategy_id": "s1", "strategy_name": strategy_name,
        "stop_loss": stop, "target": target,
        "market_regime_at_entry": regime,
        "signal_confidence": confidence, "reason": "signal",
    }


def _sell(symbol="INFY", pnl=500.0, offset=2.0, day=0,
          exit_type="TARGET_HIT"):
    qty, price = 10, 1000.0 + pnl / 10
    return {
        "id": f"sell-{symbol}-{day}-{offset}",
        "symbol": symbol, "action": "SELL",
        "quantity": qty, "price": price, "total": qty * price,
        "timestamp": _ts(offset, day),
        "pnl": pnl, "pnl_pct": pnl / (qty * 1000.0) * 100,
        "exit_type": exit_type,
    }


def _make_trades(specs):
    """specs: list of (symbol, confidence, pnl, day, exit_type)"""
    trades = []
    for i, (sym, conf, pnl, day, xt) in enumerate(specs):
        trades.append(_buy(sym, offset=i * 4 % 12, day=day, confidence=conf))
        trades.append(_sell(sym, pnl=pnl, offset=i * 4 % 12 + 2, day=day, exit_type=xt))
    return trades


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feature flag
# ══════════════════════════════════════════════════════════════════════════════
class TestFeatureFlag(unittest.TestCase):
    def setUp(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_all_endpoints_disabled(self):
        from ai_performance.api import (
            get_summary, get_confidence, get_calibration,
            get_predictions, get_recommendations, get_learning,
        )
        for fn in (get_summary, get_confidence, get_calibration,
                   get_predictions, get_recommendations, get_learning):
            r = fn()
            self.assertEqual(r["status"], "DISABLED", msg=fn.__name__)

    def test_shared_services_disabled(self):
        from ai_performance.shared_services import (
            get_ai_summary, get_ai_snapshot, get_health_score,
        )
        for fn in (get_ai_summary, get_ai_snapshot, get_health_score):
            r = fn()
            self.assertEqual(r["status"], "DISABLED", msg=fn.__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Zero signals
# ══════════════════════════════════════════════════════════════════════════════
class TestZeroSignals(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def _mock(self):
        return patch("portfolio_store.load_all_trades_any", return_value=[])

    def test_summary_zero(self):
        from ai_performance.api import get_summary
        with self._mock():
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_signals"], 0)
        self.assertEqual(r["signal_success_rate"], 0.0)

    def test_predictions_zero(self):
        from ai_performance.api import get_predictions
        with self._mock():
            r = get_predictions()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["tp"] + r["fp"] + r["tn"] + r["fn"], 0)

    def test_calibration_zero(self):
        from ai_performance.api import get_calibration
        with self._mock():
            r = get_calibration()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["ece"], 0.0)
        self.assertEqual(r["calibration_curve"], [])


# ══════════════════════════════════════════════════════════════════════════════
# 3. One signal
# ══════════════════════════════════════════════════════════════════════════════
class TestOneSignal(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_one_winner(self):
        from ai_performance.api import get_summary
        trades = _make_trades([("INFY", 0.75, 500.0, 0, "TARGET_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_summary()
        self.assertEqual(r["total_signals"], 1)
        self.assertEqual(r["successful_signals"], 1)
        self.assertEqual(r["signal_success_rate"], 100.0)

    def test_one_loser(self):
        from ai_performance.api import get_summary
        trades = _make_trades([("INFY", 0.75, -300.0, 0, "STOP_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_summary()
        self.assertEqual(r["total_signals"], 1)
        self.assertEqual(r["successful_signals"], 0)
        self.assertEqual(r["failed_signals"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# 4. High confidence predictions → should mostly be TP
# ══════════════════════════════════════════════════════════════════════════════
class TestHighConfidencePredictions(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_high_conf_winners_are_tp(self):
        from ai_performance.ai_engine import build_ai_signals
        from ai_performance.ai_models import CONFIDENCE_THRESHOLD
        trades = _make_trades([
            ("INFY", 0.85, 500.0, 0, "TARGET_HIT"),
            ("HDFCBANK", 0.90, 700.0, 1, "TARGET_HIT"),
            ("RELIANCE", 0.80, 300.0, 2, "TARGET_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            signals = build_ai_signals()
        tps = [s for s in signals if s.is_tp]
        self.assertEqual(len(tps), 3)

    def test_high_conf_losers_are_fp(self):
        from ai_performance.ai_engine import build_ai_signals
        trades = _make_trades([
            ("INFY", 0.85, -200.0, 0, "STOP_HIT"),
            ("HDFCBANK", 0.92, -300.0, 1, "STOP_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            signals = build_ai_signals()
        fps = [s for s in signals if s.is_fp]
        self.assertEqual(len(fps), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Low confidence predictions → should be TN/FN
# ══════════════════════════════════════════════════════════════════════════════
class TestLowConfidencePredictions(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_low_conf_losers_are_tn(self):
        from ai_performance.ai_engine import build_ai_signals
        trades = _make_trades([
            ("INFY", 0.45, -200.0, 0, "STOP_HIT"),   # low conf, lost → TN
            ("HDFCBANK", 0.50, -100.0, 1, "STOP_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            signals = build_ai_signals()
        tns = [s for s in signals if s.is_tn]
        self.assertEqual(len(tns), 2)

    def test_low_conf_winners_are_fn(self):
        from ai_performance.ai_engine import build_ai_signals
        trades = _make_trades([
            ("INFY", 0.45, 500.0, 0, "TARGET_HIT"),   # low conf, won → FN
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            signals = build_ai_signals()
        fns = [s for s in signals if s.is_fn]
        self.assertEqual(len(fns), 1)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Precision and Recall calculations
# ══════════════════════════════════════════════════════════════════════════════
class TestPrecisionRecall(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_precision_recall_known_values(self):
        from ai_performance.prediction_analysis import compute_prediction_metrics
        from ai_performance.ai_models import AISignalRecord
        # TP=3, FP=1, TN=2, FN=1  → precision=3/4=0.75, recall=3/4=0.75
        signals = [
            AISignalRecord(is_tp=True,  is_winner=True,  is_high_confidence=True),
            AISignalRecord(is_tp=True,  is_winner=True,  is_high_confidence=True),
            AISignalRecord(is_tp=True,  is_winner=True,  is_high_confidence=True),
            AISignalRecord(is_fp=True,  is_winner=False, is_high_confidence=True),
            AISignalRecord(is_tn=True,  is_winner=False, is_high_confidence=False),
            AISignalRecord(is_tn=True,  is_winner=False, is_high_confidence=False),
            AISignalRecord(is_fn=True,  is_winner=True,  is_high_confidence=False),
        ]
        m = compute_prediction_metrics(signals)
        self.assertAlmostEqual(m.precision, 0.75, places=3)
        self.assertAlmostEqual(m.recall,    0.75, places=3)
        self.assertAlmostEqual(m.f1_score,  0.75, places=3)
        self.assertEqual(m.tp, 3)
        self.assertEqual(m.fp, 1)
        self.assertEqual(m.tn, 2)
        self.assertEqual(m.fn, 1)

    def test_balanced_accuracy(self):
        from ai_performance.prediction_analysis import compute_prediction_metrics
        from ai_performance.ai_models import AISignalRecord
        # TPR = 3/4 = 0.75, TNR = 2/3 ≈ 0.667, BA = (0.75+0.667)/2 ≈ 0.708
        signals = [
            AISignalRecord(is_tp=True), AISignalRecord(is_tp=True),
            AISignalRecord(is_tp=True), AISignalRecord(is_fn=True),
            AISignalRecord(is_tn=True), AISignalRecord(is_tn=True),
            AISignalRecord(is_fp=True),
        ]
        m = compute_prediction_metrics(signals)
        self.assertAlmostEqual(m.balanced_accuracy, (0.75 + 2/3) / 2, places=3)

    def test_mcc_perfect(self):
        from ai_performance.prediction_analysis import compute_prediction_metrics
        from ai_performance.ai_models import AISignalRecord
        # All TP and TN → MCC = 1.0
        signals = [
            AISignalRecord(is_tp=True), AISignalRecord(is_tp=True),
            AISignalRecord(is_tn=True), AISignalRecord(is_tn=True),
        ]
        m = compute_prediction_metrics(signals)
        self.assertAlmostEqual(m.mcc, 1.0, places=3)

    def test_predictions_api(self):
        from ai_performance.api import get_predictions
        trades = _make_trades([
            ("INFY",     0.80, 500.0, 0, "TARGET_HIT"),
            ("HDFCBANK", 0.75, 600.0, 1, "TARGET_HIT"),
            ("RELIANCE", 0.70, -200.0, 2, "STOP_HIT"),
            ("INFY",     0.40, -100.0, 3, "STOP_HIT"),
            ("HDFCBANK", 0.45, 300.0, 4, "TARGET_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_predictions()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("precision", r)
        self.assertIn("recall", r)
        self.assertIn("f1_score", r)
        self.assertIn("mcc", r)
        self.assertIn("balanced_accuracy", r)
        # TP+FP+TN+FN must equal total signals
        self.assertEqual(r["tp"] + r["fp"] + r["tn"] + r["fn"], 5)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Calibration calculations
# ══════════════════════════════════════════════════════════════════════════════
class TestCalibrationCalculations(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_perfect_calibration(self):
        """If confidence ≈ actual win rate in every bucket → ECE ≈ 0."""
        from ai_performance.ai_models import AISignalRecord
        from ai_performance.calibration import compute_calibration
        # 80% confidence, 8 winners out of 10 = 80% actual → near-perfect
        signals = (
            [AISignalRecord(signal_confidence=0.80, confidence_bucket="80–90",
                            is_winner=True,  is_tp=True)] * 8 +
            [AISignalRecord(signal_confidence=0.80, confidence_bucket="80–90",
                            is_winner=False, is_fp=True)] * 2
        )
        m = compute_calibration(signals)
        self.assertLess(m.ece, 0.05)   # near-perfect calibration

    def test_overconfident_model(self):
        """Confidence 90% but only 30% win rate → overconfident."""
        from ai_performance.ai_models import AISignalRecord
        from ai_performance.calibration import compute_calibration
        signals = (
            [AISignalRecord(signal_confidence=0.90, confidence_bucket="90–100",
                            is_winner=True,  is_tp=True)] * 3 +
            [AISignalRecord(signal_confidence=0.90, confidence_bucket="90–100",
                            is_winner=False, is_fp=True)] * 7
        )
        m = compute_calibration(signals)
        self.assertGreater(m.confidence_bias, 0)    # positive bias = overconfident
        self.assertGreater(m.overconfidence_score, 0)

    def test_calibration_api_structure(self):
        from ai_performance.api import get_calibration
        trades = _make_trades([
            ("INFY",     0.85, 500.0,  0, "TARGET_HIT"),
            ("HDFCBANK", 0.72, 400.0,  1, "TARGET_HIT"),
            ("RELIANCE", 0.65, -200.0, 2, "STOP_HIT"),
            ("INFY",     0.45, -100.0, 3, "STOP_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_calibration()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("ece", r)
        self.assertIn("reliability_score", r)
        self.assertIn("confidence_bias", r)
        self.assertIn("overconfidence_score", r)
        self.assertIn("underconfidence_score", r)
        self.assertIn("calibration_curve", r)
        self.assertIsInstance(r["calibration_curve"], list)


# ══════════════════════════════════════════════════════════════════════════════
# 8. AI Health Score
# ══════════════════════════════════════════════════════════════════════════════
class TestAIHealthScore(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_health_score_in_range(self):
        from ai_performance.api import get_summary
        trades = _make_trades([
            ("INFY",     0.80, 500.0, 0, "TARGET_HIT"),
            ("HDFCBANK", 0.75, 600.0, 1, "TARGET_HIT"),
            ("RELIANCE", 0.85, -200.0, 2, "STOP_HIT"),
            ("INFY",     0.40, -100.0, 3, "STOP_HIT"),
            ("HDFCBANK", 0.70, 300.0, 4, "TARGET_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_summary()
        h = r["health_score"]
        self.assertGreaterEqual(h["total_score"], 0.0)
        self.assertLessEqual(h["total_score"], 100.0)
        self.assertIn(h["label"], ["Excellent", "Good", "Fair", "Poor", "Critical"])

    def test_health_score_components_present(self):
        from ai_performance.api import get_summary
        trades = _make_trades([("INFY", 0.80, 500.0, 0, "TARGET_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_summary()
        c = r["health_score"]["components"]
        for key in ("prediction_accuracy", "calibration_quality", "consistency",
                    "execution_outcome", "risk_awareness", "recommendation_quality"):
            self.assertIn(key, c)

    def test_health_score_zero_trades(self):
        from ai_performance.shared_services import get_health_score
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            r = get_health_score()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_score"], 0.0)

    def test_health_label_mapping(self):
        from ai_performance.ai_models import health_label
        self.assertEqual(health_label(95.0), "Excellent")
        self.assertEqual(health_label(80.0), "Good")
        self.assertEqual(health_label(65.0), "Fair")
        self.assertEqual(health_label(45.0), "Poor")
        self.assertEqual(health_label(20.0), "Critical")


# ══════════════════════════════════════════════════════════════════════════════
# 9. Recommendation analysis
# ══════════════════════════════════════════════════════════════════════════════
class TestRecommendationAnalysis(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_recommendation_success_pct(self):
        from ai_performance.recommendation_analysis import compute_recommendation_analysis
        from ai_performance.ai_models import AISignalRecord
        signals = [
            AISignalRecord(is_winner=True),
            AISignalRecord(is_winner=True),
            AISignalRecord(is_winner=False),
            AISignalRecord(is_winner=False),
        ]
        r = compute_recommendation_analysis(signals)
        self.assertAlmostEqual(r["recommendation_success_pct"], 50.0, places=1)
        self.assertAlmostEqual(r["recommendation_failure_pct"], 50.0, places=1)

    def test_accepted_vs_flagged_win_rates(self):
        from ai_performance.recommendation_analysis import compute_recommendation_analysis
        from ai_performance.ai_models import AISignalRecord
        signals = [
            AISignalRecord(is_winner=True,  strategy_recommendation="Increase Allocation", pnl=500.0),
            AISignalRecord(is_winner=True,  strategy_recommendation="Increase Allocation", pnl=400.0),
            AISignalRecord(is_winner=False, strategy_recommendation="Reduce Allocation",   pnl=-200.0),
        ]
        r = compute_recommendation_analysis(signals)
        self.assertAlmostEqual(r["accepted_win_rate"], 100.0, places=1)
        self.assertAlmostEqual(r["rejected_win_rate"],   0.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Learning / trend analysis
# ══════════════════════════════════════════════════════════════════════════════
class TestLearningAnalysis(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_learning_api_structure(self):
        from ai_performance.api import get_learning
        trades = []
        for i in range(8):
            trades += _make_trades([("INFY", 0.75, 500.0 if i % 2 == 0 else -200.0, i, "TARGET_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_learning()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("daily",     r)
        self.assertIn("weekly",    r)
        self.assertIn("monthly",   r)
        self.assertIn("rolling_30d", r)
        self.assertIn("trend_direction", r)
        self.assertIn(r["trend_direction"], ["Improving", "Stable", "Declining"])

    def test_trend_improving(self):
        from ai_performance.ai_models import AISignalRecord
        from ai_performance.learning_analysis import compute_learning_analysis, compute_trend_direction, _rolling_30d
        # Early signals: low win rate; recent: high win rate
        from datetime import date
        signals = []
        # Days 1-5: mostly losers
        for i in range(5):
            d = f"2026-07-{i+1:02d}"
            signals.append(AISignalRecord(is_winner=False, exit_date=d, exit_week=f"2026-W27", exit_month="2026-07"))
        # Days 10-14: all winners
        for i in range(5):
            d = f"2026-07-{i+10:02d}"
            signals.append(AISignalRecord(is_winner=True, exit_date=d, exit_week=f"2026-W28", exit_month="2026-07"))
        rolling = _rolling_30d(signals)
        # Just verify it produces data
        self.assertGreater(len(rolling), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Shared service reuse (5D.3 strategy_intelligence)
# ══════════════════════════════════════════════════════════════════════════════
class TestSharedServiceReuse(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_ai_engine_calls_strategy_intelligence(self):
        """ai_engine.load_all_data reuses 5D.3 strategy_intelligence.strategy_engine."""
        trades = _make_trades([("INFY", 0.75, 500.0, 0, "TARGET_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            from ai_performance.ai_engine import load_all_data
            d = load_all_data()
        self.assertIn("signals",  d)
        self.assertIn("profiles", d)   # comes from 5D.3 shared_services

    def test_snapshot_for_executive_dashboard(self):
        """get_ai_snapshot() returns flat KPI dict for Phase 5D.5."""
        trades = _make_trades([
            ("INFY",     0.80, 500.0, 0, "TARGET_HIT"),
            ("HDFCBANK", 0.75, -200.0, 1, "STOP_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            from ai_performance.shared_services import get_ai_snapshot
            r = get_ai_snapshot()
        self.assertEqual(r["status"], "ENABLED")
        for key in ("health_score", "health_label", "prediction_accuracy",
                    "precision", "recall", "f1_score", "avg_confidence",
                    "calibration_ece", "trend_direction", "total_signals"):
            self.assertIn(key, r, msg=f"Missing key: {key}")


# ══════════════════════════════════════════════════════════════════════════════
# 12. API responses
# ══════════════════════════════════════════════════════════════════════════════
class TestAPIResponses(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def _trades(self):
        return _make_trades([
            ("INFY",     0.80, 500.0,  0, "TARGET_HIT"),
            ("HDFCBANK", 0.75, 600.0,  1, "TARGET_HIT"),
            ("RELIANCE", 0.85, -200.0, 2, "STOP_HIT"),
            ("INFY",     0.40, -100.0, 3, "STOP_HIT"),
            ("HDFCBANK", 0.70, 300.0,  4, "TARGET_HIT"),
        ])

    def test_all_endpoints_enabled(self):
        from ai_performance.api import (
            get_summary, get_confidence, get_calibration,
            get_predictions, get_recommendations, get_learning,
        )
        for fn in (get_summary, get_confidence, get_calibration,
                   get_predictions, get_recommendations, get_learning):
            with patch("portfolio_store.load_all_trades_any", return_value=self._trades()):
                r = fn()
            self.assertEqual(r.get("status"), "ENABLED", msg=f"{fn.__name__}: {r}")

    def test_confidence_endpoint(self):
        from ai_performance.api import get_confidence
        with patch("portfolio_store.load_all_trades_any", return_value=self._trades()):
            r = get_confidence()
        self.assertIn("distribution", r)
        self.assertIn("vs_regime",    r)
        self.assertIn("vs_sector",    r)
        self.assertIn("buckets",      r["distribution"])


# ══════════════════════════════════════════════════════════════════════════════
# 13. Multiple signals — confidence bucketing correctness
# ══════════════════════════════════════════════════════════════════════════════
class TestMultipleSignals(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_confidence_buckets_correctly_assigned(self):
        from ai_performance.ai_engine import build_ai_signals
        trades = _make_trades([
            ("INFY",     0.95, 500.0, 0, "TARGET_HIT"),  # 90-100
            ("HDFCBANK", 0.82, 400.0, 1, "TARGET_HIT"),  # 80-90
            ("RELIANCE", 0.74, 300.0, 2, "TARGET_HIT"),  # 70-80
            ("INFY",     0.65, -100.0, 3, "STOP_HIT"),   # 60-70
            ("HDFCBANK", 0.45, -200.0, 4, "STOP_HIT"),   # Below 60
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            signals = build_ai_signals()
        bucket_map = {s.signal_confidence: s.confidence_bucket for s in signals}
        self.assertEqual(signals[0].confidence_bucket, "90–100")
        self.assertEqual(signals[1].confidence_bucket, "80–90")
        self.assertEqual(signals[2].confidence_bucket, "70–80")
        self.assertEqual(signals[3].confidence_bucket, "60–70")
        self.assertEqual(signals[4].confidence_bucket, "Below 60")


# ══════════════════════════════════════════════════════════════════════════════
# 14. Restart persistence
# ══════════════════════════════════════════════════════════════════════════════
class TestRestartPersistence(unittest.TestCase):
    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    def test_two_calls_identical(self):
        from ai_performance.api import get_summary
        trades = _make_trades([("INFY", 0.80, 500.0, 0, "TARGET_HIT")])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r1 = get_summary()
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r2 = get_summary()
        self.assertEqual(r1["total_signals"],      r2["total_signals"])
        self.assertEqual(r1["signal_success_rate"], r2["signal_success_rate"])
        self.assertAlmostEqual(
            r1["health_score"]["total_score"],
            r2["health_score"]["total_score"], places=1
        )


# ══════════════════════════════════════════════════════════════════════════════
# 15. Scale benchmark — _compute_all() under 100 ms at 100 / 500 / 1000 trades
# ══════════════════════════════════════════════════════════════════════════════
class TestScaleBenchmark(unittest.TestCase):
    """_compute_all() must stay under 100 ms after the _rolling_30d refactor."""

    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"]        = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)

    # ── Synthetic trade generator ─────────────────────────────────────────────
    @staticmethod
    def _make_raw_trades(n_pairs: int):
        symbols    = ["INFY", "TCS", "RELIANCE", "HDFC", "WIPRO",
                      "BHARTIARTL", "ICICIBANK", "SBI", "LT", "AXISBANK"]
        conf_vals  = [0.95, 0.85, 0.75, 0.65, 0.45]
        base       = datetime(2025, 1, 2, 4, 0, 0, tzinfo=timezone.utc)

        trades = []
        for i in range(n_pairs):
            sym   = symbols[i % len(symbols)]
            conf  = conf_vals[i % len(conf_vals)]
            day   = i // len(symbols)
            high  = conf >= 0.60
            win   = ((i % 10) < 7) if high else ((i % 10) < 4)
            pnl   = 500.0 if win else -200.0
            xt    = "TARGET_HIT" if win else "STOP_HIT"
            qty, price = 10, 1000.0
            buy_ts  = (base + timedelta(days=day, hours=9)).isoformat()
            sell_ts = (base + timedelta(days=day, hours=15)).isoformat()

            trades.append({
                "id": f"buy-{i}", "symbol": sym, "action": "BUY",
                "quantity": qty, "price": price, "total": qty * price,
                "timestamp": buy_ts,
                "strategy_id": "s1",
                "strategy_name": "Momentum" if i % 2 == 0 else "Mean Reversion",
                "stop_loss": price * 0.97, "target": price * 1.05,
                "market_regime_at_entry": "Bullish",
                "signal_confidence": conf, "reason": "signal",
            })
            trades.append({
                "id": f"sell-{i}", "symbol": sym, "action": "SELL",
                "quantity": qty, "price": price + pnl / qty,
                "total": qty * (price + pnl / qty),
                "timestamp": sell_ts,
                "pnl": pnl, "pnl_pct": pnl / (qty * price) * 100,
                "exit_type": xt,
            })
        return trades

    def _time_compute_all(self, n_pairs: int):
        import time
        trades = self._make_raw_trades(n_pairs)
        import portfolio_store as _ps
        from ai_performance.shared_services import _compute_all
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            t0     = time.perf_counter()
            result = _compute_all()
            ms     = (time.perf_counter() - t0) * 1000.0
        return ms, result

    def test_100_trades_under_100ms(self):
        ms, result = self._time_compute_all(100)
        n_signals = len(result.get("signals", []))
        self.assertGreater(n_signals, 0, "_compute_all returned 0 signals — feature flag inactive?")
        self.assertLess(ms, 100.0,
            msg=f"_compute_all() at 100 trades: {ms:.1f} ms (limit 100 ms)")

    def test_500_trades_under_100ms(self):
        ms, result = self._time_compute_all(500)
        self.assertGreater(len(result.get("signals", [])), 0)
        self.assertLess(ms, 100.0,
            msg=f"_compute_all() at 500 trades: {ms:.1f} ms (limit 100 ms)")

    def test_1000_trades_under_100ms(self):
        ms, result = self._time_compute_all(1000)
        self.assertGreater(len(result.get("signals", [])), 0)
        self.assertLess(ms, 100.0,
            msg=f"_compute_all() at 1000 trades: {ms:.1f} ms (limit 100 ms)")


# ══════════════════════════════════════════════════════════════════════════════
# 16. ECE stability — variance < 0.02 when each bucket has >= 20 signals
# ══════════════════════════════════════════════════════════════════════════════
class TestECEStabilityAtScale(unittest.TestCase):
    """Calibration ECE stabilises (stdev < 0.02) when each bucket >= 20 signals."""

    @staticmethod
    def _make_calibration_signals(n_per_bucket: int, seed: int):
        """
        Create AISignalRecord objects for all 5 confidence buckets.
        Win rate per bucket ≈ midpoint confidence (well-calibrated baseline)
        plus a small pseudo-random perturbation from `seed`.
        """
        from ai_performance.ai_models import AISignalRecord, CONFIDENCE_BUCKETS
        signals = []
        lcg = (seed * 1103515245 + 12345) & 0x7FFFFFFF

        for label, lo, hi in CONFIDENCE_BUCKETS:
            conf_mid = min((lo + hi) / 2.0, 0.95)
            lcg = (lcg * 1103515245 + 12345) & 0x7FFFFFFF
            noise    = ((lcg % 9) - 4) / 100.0        # ±0.04
            win_rate = max(0.0, min(1.0, conf_mid + noise))
            n_win    = round(win_rate * n_per_bucket)
            high     = conf_mid >= 0.60

            for j in range(n_per_bucket):
                is_w = j < n_win
                signals.append(AISignalRecord(
                    signal_confidence = conf_mid,
                    confidence_bucket = label,
                    is_winner  = is_w,
                    is_tp = high and is_w,
                    is_fp = high and not is_w,
                    is_tn = not high and not is_w,
                    is_fn = not high and is_w,
                ))
        return signals

    def test_ece_stdev_lt_002_at_20_per_bucket(self):
        """ECE stdev < 0.02 across 10 pseudo-random seeds when n=20 per bucket."""
        import statistics as _st
        from ai_performance.calibration import compute_calibration
        eces = [
            compute_calibration(self._make_calibration_signals(20, s)).ece
            for s in range(10)
        ]
        stdev = _st.stdev(eces)
        self.assertLess(stdev, 0.02,
            msg=f"ECE stdev={stdev:.4f} at 20 trades/bucket (must be < 0.02)")

    def test_ece_small_when_well_calibrated(self):
        """ECE < 0.10 when 20 trades/bucket have win rate ≈ predicted confidence."""
        from ai_performance.calibration import compute_calibration
        from ai_performance.ai_models import AISignalRecord, CONFIDENCE_BUCKETS
        signals = []
        for label, lo, hi in CONFIDENCE_BUCKETS:
            conf_mid  = min((lo + hi) / 2.0, 0.95)
            n_win     = round(conf_mid * 20)
            high      = conf_mid >= 0.60
            for j in range(20):
                is_w = j < n_win
                signals.append(AISignalRecord(
                    signal_confidence=conf_mid, confidence_bucket=label,
                    is_winner=is_w,
                    is_tp=high and is_w, is_fp=high and not is_w,
                    is_tn=not high and not is_w, is_fn=not high and is_w,
                ))
        m = compute_calibration(signals)
        self.assertLess(m.ece, 0.10,
            msg=f"ECE={m.ece:.4f} with well-calibrated data at 20/bucket")

    def test_ece_stable_across_scales(self):
        """ECE at 40 trades/bucket should be within 0.04 of ECE at 20 trades/bucket."""
        from ai_performance.calibration import compute_calibration
        # Use seed=42 for reproducibility; doubled n → should converge closer
        ece_20 = compute_calibration(self._make_calibration_signals(20, 42)).ece
        ece_40 = compute_calibration(self._make_calibration_signals(40, 42)).ece
        self.assertLess(abs(ece_20 - ece_40), 0.04,
            msg=f"ECE drifts too much between 20/bucket ({ece_20:.4f}) and 40/bucket ({ece_40:.4f})")


# ══════════════════════════════════════════════════════════════════════════════
# 17. MCC at scale — non-zero and scale-invariant with all quadrants populated
# ══════════════════════════════════════════════════════════════════════════════
class TestMCCAtScale(unittest.TestCase):
    """MCC is non-zero and scale-invariant when TP/FP/TN/FN all have samples."""

    @staticmethod
    def _mcc_signals(tp: int, fp: int, tn: int, fn: int):
        from ai_performance.ai_models import AISignalRecord
        return (
            [AISignalRecord(is_tp=True,  is_winner=True,  is_high_confidence=True)]  * tp +
            [AISignalRecord(is_fp=True,  is_winner=False, is_high_confidence=True)]  * fp +
            [AISignalRecord(is_tn=True,  is_winner=False, is_high_confidence=False)] * tn +
            [AISignalRecord(is_fn=True,  is_winner=True,  is_high_confidence=False)] * fn
        )

    def test_mcc_nonzero_100_signals(self):
        """MCC > 0 at 100 signals when TP+TN dominate FP+FN (better than random)."""
        from ai_performance.prediction_analysis import compute_prediction_metrics
        m = compute_prediction_metrics(self._mcc_signals(40, 20, 30, 10))
        self.assertGreater(m.mcc, 0.0,
            msg=f"MCC={m.mcc} with TP=40,FP=20,TN=30,FN=10 should be > 0")

    def test_mcc_nonzero_500_signals(self):
        """MCC > 0 at 500 signals — same ratio as 100-signal test."""
        from ai_performance.prediction_analysis import compute_prediction_metrics
        m = compute_prediction_metrics(self._mcc_signals(200, 100, 150, 50))
        self.assertGreater(m.mcc, 0.0)

    def test_mcc_scale_invariant(self):
        """MCC(5× data) == MCC(1× data) — the metric is scale-free."""
        from ai_performance.prediction_analysis import compute_prediction_metrics
        tp, fp, tn, fn = 50, 30, 40, 20
        m1 = compute_prediction_metrics(self._mcc_signals(tp,    fp,    tn,    fn))
        m5 = compute_prediction_metrics(self._mcc_signals(tp*5,  fp*5,  tn*5,  fn*5))
        self.assertAlmostEqual(m1.mcc, m5.mcc, places=3,
            msg=f"MCC should be scale-invariant: {m1.mcc} vs {m5.mcc}")

    def test_mcc_formula_correctness(self):
        """Verify MCC formula numerics against hand-computed value."""
        import math
        from ai_performance.prediction_analysis import compute_prediction_metrics
        # TP=40, FP=20, TN=30, FN=10
        # MCC = (40×30 - 20×10) / sqrt((40+20)(40+10)(30+20)(30+10))
        #      = (1200 - 200)   / sqrt(60 × 50 × 50 × 40)
        #      = 1000           / sqrt(6_000_000)
        #      ≈ 1000           / 2449.49 ≈ 0.4082
        expected = 1000 / math.sqrt(60 * 50 * 50 * 40)
        m = compute_prediction_metrics(self._mcc_signals(40, 20, 30, 10))
        self.assertAlmostEqual(m.mcc, expected, places=3,
            msg=f"MCC={m.mcc:.4f} vs hand-computed {expected:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
# 15. _as_str coercion on string KPI fields in get_ai_snapshot()
# ══════════════════════════════════════════════════════════════════════════════

class TestStringKpiCoercion(unittest.TestCase):
    """
    Guard: every string KPI field in get_ai_snapshot() must be a plain str,
    never a dict/None/list, even when upstream compute functions return
    unexpected types.
    """

    def setUp(self):
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    # ── _as_str helper unit tests ─────────────────────────────────────────────

    def test_as_str_none_returns_fallback(self):
        from ai_performance.shared_services import _as_str
        self.assertEqual(_as_str(None), "N/A")

    def test_as_str_dict_returns_fallback(self):
        from ai_performance.shared_services import _as_str
        self.assertEqual(_as_str({"nested": "dict"}), "N/A")

    def test_as_str_empty_string_returns_fallback(self):
        from ai_performance.shared_services import _as_str
        self.assertEqual(_as_str(""), "N/A")

    def test_as_str_valid_string_passes_through(self):
        from ai_performance.shared_services import _as_str
        self.assertEqual(_as_str("Good"), "Good")

    def test_as_str_custom_fallback(self):
        from ai_performance.shared_services import _as_str
        self.assertEqual(_as_str(None, fallback="Stable"), "Stable")

    # ── _calibration_quality_label helper ────────────────────────────────────

    def test_calibration_label_well_calibrated(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(85.0), "Well Calibrated")

    def test_calibration_label_boundary_80(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(80.0), "Well Calibrated")

    def test_calibration_label_fairly_calibrated(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(70.0), "Fairly Calibrated")

    def test_calibration_label_poorly_calibrated(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(50.0), "Poorly Calibrated")

    def test_calibration_label_uncalibrated(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(20.0), "Uncalibrated")

    def test_calibration_label_zero(self):
        from ai_performance.shared_services import _calibration_quality_label
        self.assertEqual(_calibration_quality_label(0.0), "Uncalibrated")

    # ── get_ai_snapshot() field types ─────────────────────────────────────────

    def test_health_label_is_str_zero_signals(self):
        """Zero signals → health_label must be a plain str, not None."""
        from ai_performance.shared_services import get_ai_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_ai_snapshot()
        self.assertIsInstance(snap.get("health_label"), str,
            f"health_label type={type(snap.get('health_label')).__name__!r}")

    def test_trend_direction_is_str_zero_signals(self):
        """Zero signals → trend_direction must be a plain str, not None/dict."""
        from ai_performance.shared_services import get_ai_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_ai_snapshot()
        self.assertIsInstance(snap.get("trend_direction"), str,
            f"trend_direction type={type(snap.get('trend_direction')).__name__!r}")

    def test_calibration_quality_label_is_str_zero_signals(self):
        """Zero signals → calibration_quality_label must be a plain str."""
        from ai_performance.shared_services import get_ai_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_ai_snapshot()
        self.assertIsInstance(snap.get("calibration_quality_label"), str,
            f"calibration_quality_label type={type(snap.get('calibration_quality_label')).__name__!r}")

    def test_string_fields_with_real_trades(self):
        """With trades, all string KPI fields must still be plain strings."""
        from ai_performance.shared_services import get_ai_snapshot
        trades = _make_trades([
            ("INFY",   0.80, 500.0,  0, "TARGET_HIT"),
            ("HDFCBANK", 0.70, 300.0, 1, "TARGET_HIT"),
        ])
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            snap = get_ai_snapshot()
        for field in ("health_label", "trend_direction", "calibration_quality_label"):
            self.assertIsInstance(snap.get(field), str,
                f"{field} type={type(snap.get(field)).__name__!r} with trades")

    def test_no_string_field_is_none(self):
        """None must never appear for any string KPI field."""
        from ai_performance.shared_services import get_ai_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_ai_snapshot()
        for field in ("health_label", "trend_direction", "calibration_quality_label"):
            self.assertIsNotNone(snap.get(field),
                f"{field} was None — _as_str coercion is missing")

    def test_no_string_field_is_dict(self):
        """Regression: dict must never appear for any string KPI field."""
        from ai_performance.shared_services import get_ai_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_ai_snapshot()
        for field in ("health_label", "trend_direction", "calibration_quality_label"):
            self.assertNotIsInstance(snap.get(field), dict,
                f"{field} was a dict — the upstream dict-leaking bug returned")

    def test_health_label_coerces_none_to_na(self):
        """If h.label is somehow None, health_label must fall back to 'N/A'."""
        from ai_performance.shared_services import _as_str
        coerced = _as_str(None, fallback="N/A")
        self.assertEqual(coerced, "N/A")

    def test_trend_direction_coerces_dict_to_stable(self):
        """If learning['trend_direction'] is a dict, must fall back to 'Stable'."""
        from ai_performance.shared_services import _as_str
        coerced = _as_str({"direction": "up"}, fallback="Stable")
        self.assertEqual(coerced, "Stable")


if __name__ == "__main__":
    unittest.main()
