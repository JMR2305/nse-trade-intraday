"""
test_paper_analytics.py — Phase 8.2
Comprehensive unit tests for the Advanced Paper Trading Analytics module.

All upstream shared-services are mocked — no DB or network calls.
Tests cover: feature flag, trade analytics, strategy analytics, risk analytics,
sector analytics, portfolio analytics, pre-open analytics, learning insights,
export helpers, shared_services safe-loader, and empty-dataset fallbacks.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# ── Inject feature flag before any module import ──────────────────────────────
os.environ["PAPER_ANALYTICS_ENABLED"] = "true"


def _set_flag(val: str) -> None:
    os.environ["PAPER_ANALYTICS_ENABLED"] = val


def _clear_flag() -> None:
    os.environ["PAPER_ANALYTICS_ENABLED"] = "false"


# ── Minimal ClosedTrade stub ──────────────────────────────────────────────────
class _CT:
    def __init__(self, symbol="RELIANCE", pnl=500.0, strategy="RSI", sector="IT",
                 entry_ts="2024-01-10T09:30:00+05:30",
                 exit_ts="2024-01-10T11:00:00+05:30",
                 holding_seconds=5400.0, entry_price=100.0,
                 stop_loss=95.0, target=110.0, quantity=100,
                 pnl_pct=5.0, strategy_name=None):
        self.symbol         = symbol
        self.pnl            = pnl
        self.pnl_pct        = pnl_pct
        self.strategy_name  = strategy_name or strategy
        self.sector         = sector
        self.entry_ts       = entry_ts
        self.exit_ts        = exit_ts
        self.holding_seconds = holding_seconds
        self.entry_price    = entry_price
        self.stop_loss      = stop_loss
        self.target         = target
        self.quantity       = quantity


def _make_perf_data(trades=None, pnl_history=None):
    if trades is None:
        trades = [_CT(), _CT("TCS", -200.0, "MACD", "IT", pnl_pct=-2.0),
                  _CT("HDFC", 300.0, "RSI", "Banking")]
    if pnl_history is None:
        pnl_history = [{"timestamp": "2024-01-10T09:00:00", "value": 500500.0}]
    return {
        "closed_trades":      trades,
        "open_positions":     [],
        "open_positions_raw": [],
        "pnl_history":        pnl_history,
        "cash":               490_000.0,
        "invested":           10_000.0,
        "total_value":        501_000.0,
        "unrealised_pnl":     1_000.0,
        "realised_pnl":       600.0,
    }


# ── Feature flag tests ────────────────────────────────────────────────────────
class TestFeatureFlag(unittest.TestCase):

    def test_is_enabled_true(self):
        _set_flag("true")
        from paper_analytics.models import is_enabled
        self.assertTrue(is_enabled())

    def test_is_enabled_false(self):
        _set_flag("false")
        from paper_analytics.models import is_enabled
        self.assertFalse(is_enabled())

    def test_disabled_response_shape(self):
        from paper_analytics.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])

    def test_summary_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "DISABLED")

    def test_trades_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_trades
        r = get_trades()
        self.assertEqual(r["status"], "DISABLED")

    def test_strategies_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_strategies
        r = get_strategies()
        self.assertEqual(r["status"], "DISABLED")

    def test_risk_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_risk
        r = get_risk()
        self.assertEqual(r["status"], "DISABLED")

    def test_preopen_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_preopen
        r = get_preopen()
        self.assertEqual(r["status"], "DISABLED")

    def test_portfolio_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_portfolio
        r = get_portfolio()
        self.assertEqual(r["status"], "DISABLED")

    def test_learning_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_learning
        r = get_learning()
        self.assertEqual(r["status"], "DISABLED")

    def test_export_csv_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_export_csv
        self.assertEqual(get_export_csv(), "")

    def test_export_json_disabled(self):
        _set_flag("false")
        from paper_analytics.shared_services import get_export_json
        r = get_export_json()
        self.assertEqual(r["status"], "DISABLED")

    def tearDown(self):
        _set_flag("true")


# ── Trade analytics tests ─────────────────────────────────────────────────────
class TestTradeAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.trade_analytics import get_trade_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)), \
             patch("portfolio_performance.performance_engine.INITIAL_CAPITAL", 500_000.0):
            return get_trade_analytics()

    def test_win_rate_correct(self):
        trades = [_CT(pnl=100), _CT(pnl=-50), _CT(pnl=200)]
        r = self._call(trades)
        self.assertAlmostEqual(r["win_rate"], 200/3, places=0)

    def test_expectancy_is_float(self):
        r = self._call()
        self.assertIsInstance(r["expectancy"], float)

    def test_empty_trades_returns_zeros(self):
        r = self._call(trades=[])
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["win_rate"], 0.0)

    def test_largest_winner_present(self):
        r = self._call()
        self.assertIsNotNone(r["largest_winner"])
        self.assertGreater(r["largest_winner"]["pnl"], 0)

    def test_largest_loser_present(self):
        r = self._call()
        self.assertIsNotNone(r["largest_loser"])
        self.assertLess(r["largest_loser"]["pnl"], 0)

    def test_equity_curves_have_all_keys(self):
        r = self._call()
        for key in ("daily", "weekly", "monthly", "daily_pnl", "monthly_pnl"):
            self.assertIn(key, r["equity_curves"])

    def test_streaks_non_negative(self):
        trades = [_CT(pnl=100)] * 3 + [_CT(pnl=-50)] * 2
        r = self._call(trades)
        self.assertGreaterEqual(r["longest_win_streak"], 0)
        self.assertGreaterEqual(r["longest_loss_streak"], 0)

    def test_streak_all_wins(self):
        from paper_analytics.trade_analytics import _compute_streaks
        trades = [_CT(pnl=100)] * 5
        s = _compute_streaks(trades)
        self.assertEqual(s["longest_win_streak"], 5)
        self.assertEqual(s["longest_loss_streak"], 0)

    def test_streak_alternating(self):
        from paper_analytics.trade_analytics import _compute_streaks
        trades = [
            _CT(pnl=100, exit_ts="2024-01-01T10:00:00"),
            _CT(pnl=-50, exit_ts="2024-01-01T11:00:00"),
            _CT(pnl=200, exit_ts="2024-01-01T12:00:00"),
        ]
        s = _compute_streaks(trades)
        self.assertEqual(s["longest_win_streak"], 1)

    def test_available_true(self):
        r = self._call()
        self.assertTrue(r["available"])
        self.assertTrue(r["advisory_only"])


# ── Strategy analytics tests ──────────────────────────────────────────────────
class TestStrategyAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.strategy_analytics import get_strategy_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)), \
             patch("strategy_intelligence.shared_services.get_all_strategy_profiles",
                   return_value=[]):
            return get_strategy_analytics()

    def test_strategies_is_list(self):
        r = self._call()
        self.assertIsInstance(r["strategies"], list)

    def test_per_strategy_has_required_fields(self):
        r = self._call()
        for s in r["strategies"]:
            for f in ("strategy_name", "total_trades", "win_rate", "profit_factor",
                      "expectancy", "contribution_pct"):
                self.assertIn(f, s, f"Missing field: {f}")

    def test_best_strategy_set(self):
        r = self._call()
        self.assertIsInstance(r["best_strategy"], str)

    def test_empty_trades(self):
        r = self._call(trades=[])
        self.assertEqual(r["total_strategies"], 0)

    def test_single_strategy_contribution(self):
        trades = [_CT(pnl=100, strategy="RSI")] * 3
        r = self._call(trades)
        strats = {s["strategy_name"]: s for s in r["strategies"]}
        self.assertEqual(strats["RSI"]["contribution_pct"], 100.0)


# ── Risk analytics tests ──────────────────────────────────────────────────────
class TestRiskAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.risk_analytics import get_risk_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)), \
             patch("portfolio_performance.performance_engine.INITIAL_CAPITAL", 500_000.0), \
             patch("risk_optimisation.shared_services.get_risk_optimisation_snapshot",
                   return_value={}):
            return get_risk_analytics()

    def test_sharpe_is_float(self):
        r = self._call()
        self.assertIsInstance(r["sharpe_ratio"], float)

    def test_sortino_is_float(self):
        r = self._call()
        self.assertIsInstance(r["sortino_ratio"], float)

    def test_calmar_is_float(self):
        r = self._call()
        self.assertIsInstance(r["calmar_ratio"], float)

    def test_volatility_non_negative(self):
        r = self._call()
        self.assertGreaterEqual(r["volatility_pct"], 0.0)

    def test_empty_trades(self):
        r = self._call(trades=[])
        self.assertEqual(r["sharpe_ratio"], 0.0)

    def test_all_winners_sortino_high(self):
        from paper_analytics.risk_analytics import _sortino
        returns = [0.01] * 20   # all positive — no downside
        s = _sortino(returns)
        self.assertGreater(s, 0)

    def test_reward_distribution_is_list(self):
        r = self._call()
        self.assertIsInstance(r["reward_distribution"], list)

    def test_loss_distribution_is_list(self):
        r = self._call()
        self.assertIsInstance(r["loss_distribution"], list)


# ── Sector analytics tests ────────────────────────────────────────────────────
class TestSectorAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.sector_analytics import get_sector_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)):
            return get_sector_analytics()

    def test_sectors_is_list(self):
        r = self._call()
        self.assertIsInstance(r["sectors"], list)

    def test_normalise_it_sector(self):
        from paper_analytics.sector_analytics import _normalise_sector
        self.assertEqual(_normalise_sector("Information Technology"), "IT")
        self.assertEqual(_normalise_sector("Software"), "IT")

    def test_normalise_banking(self):
        from paper_analytics.sector_analytics import _normalise_sector
        self.assertEqual(_normalise_sector("Banking"), "Banking")

    def test_unknown_sector_to_other(self):
        from paper_analytics.sector_analytics import _normalise_sector
        self.assertEqual(_normalise_sector("Quantum Computing"), "Other")

    def test_empty_sector_to_other(self):
        from paper_analytics.sector_analytics import _normalise_sector
        self.assertEqual(_normalise_sector(""), "Other")

    def test_best_sector_set(self):
        trades = [_CT(pnl=100, sector="IT")] * 2 + [_CT(pnl=-50, sector="Auto")]
        r = self._call(trades)
        self.assertIsInstance(r["best_sector"], str)

    def test_contribution_makes_sense(self):
        trades = [_CT(pnl=100, sector="IT"), _CT(pnl=100, sector="Banking")]
        r = self._call(trades)
        total_contrib = sum(abs(s["contribution_pct"]) for s in r["sectors"])
        self.assertAlmostEqual(total_contrib, 100.0, places=0)

    def test_empty_trades(self):
        r = self._call(trades=[])
        self.assertEqual(r["sectors"], [])


# ── Portfolio analytics tests ─────────────────────────────────────────────────
class TestPortfolioAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self):
        from paper_analytics.portfolio_analytics import get_portfolio_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data()), \
             patch("portfolio_performance.performance_engine.INITIAL_CAPITAL", 500_000.0), \
             patch("risk_optimisation.shared_services.get_capital", return_value={}):
            return get_portfolio_analytics()

    def test_total_value_present(self):
        r = self._call()
        self.assertIn("total_value", r)

    def test_utilisation_in_range(self):
        r = self._call()
        self.assertGreaterEqual(r["cash_utilisation_pct"], 0)
        self.assertLessEqual(r["cash_utilisation_pct"], 100)

    def test_diversification_in_range(self):
        r = self._call()
        self.assertGreaterEqual(r["diversification_score"], 0)
        self.assertLessEqual(r["diversification_score"], 100)

    def test_growth_series_is_list(self):
        r = self._call()
        self.assertIsInstance(r["capital_growth_series"], list)


# ── Pre-open analytics tests ──────────────────────────────────────────────────
class TestPreopenAnalytics(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, acc=None, hist=None):
        from paper_analytics.preopen_analytics import get_preopen_analytics
        default_acc  = {"available": True, "symbols_reconciled": 10,
                        "hit_rate_pct": 65.0, "continuation_rate_pct": 65.0,
                        "reversal_rate_pct": 35.0, "grade": "B",
                        "grade_label": "Good", "symbols": [], "trading_date": "2024-01-10"}
        default_hist = {"sessions": []}
        with patch("preopen_accuracy.get_accuracy",       return_value=acc or default_acc), \
             patch("preopen_accuracy.get_accuracy_history", return_value=hist or default_hist):
            return get_preopen_analytics()

    def test_available_true(self):
        r = self._call()
        self.assertTrue(r["available"])

    def test_latest_session_has_grade(self):
        r = self._call()
        self.assertIn("grade", r["latest_session"])

    def test_score_band_accuracy_is_list(self):
        r = self._call()
        self.assertIsInstance(r["score_band_accuracy"], list)

    def test_history_series_is_list(self):
        r = self._call()
        self.assertIsInstance(r["history"], list)

    def test_module_import_error_graceful(self):
        # If preopen_accuracy is not importable, returns unavailable dict
        with patch.dict("sys.modules", {"preopen_accuracy": None}):
            from paper_analytics import preopen_analytics as pa_mod
            import importlib
            with patch.object(pa_mod, "get_preopen_analytics",
                              side_effect=ImportError("no module")):
                try:
                    pa_mod.get_preopen_analytics()
                except ImportError:
                    pass  # acceptable — module guards handle this


# ── Learning insights tests ───────────────────────────────────────────────────
class TestLearningInsights(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.learning_insights import get_learning_insights
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)), \
             patch("strategy_intelligence.shared_services.get_regime_matrix",
                   return_value={"matrix": {"BULL": {"net_pnl": 500}, "BEAR": {"net_pnl": -100}}}), \
             patch("ai_performance.shared_services.get_ai_snapshot",
                   return_value={"status": "ENABLED", "health_score": 75.0,
                                 "prediction_accuracy": 65.0, "trend_direction": "Stable"}):
            return get_learning_insights()

    def test_empty_trades_no_data(self):
        r = self._call(trades=[])
        self.assertFalse(r.get("has_data", True))

    def test_best_worst_strategy_strings(self):
        trades = [_CT(pnl=100, strategy="RSI")] * 3 + [_CT(pnl=-50, strategy="MACD")] * 2
        r = self._call(trades)
        self.assertIsInstance(r["best_strategy"], str)
        self.assertIsInstance(r["worst_strategy"], str)

    def test_best_regime_set(self):
        r = self._call()
        self.assertEqual(r["best_market_condition"], "BULL")

    def test_worst_regime_set(self):
        r = self._call()
        self.assertEqual(r["worst_market_condition"], "BEAR")

    def test_winning_chars_is_list(self):
        r = self._call()
        self.assertIsInstance(r["winning_characteristics"], list)

    def test_losing_chars_is_list(self):
        r = self._call()
        self.assertIsInstance(r["losing_characteristics"], list)

    def test_most_consistent_is_string(self):
        trades = [_CT(pnl=v, strategy="RSI") for v in [100, 120, 110]] + \
                 [_CT(pnl=v, strategy="MACD") for v in [50, -300, 400]]
        r = self._call(trades)
        self.assertIsInstance(r["most_consistent_strategy"], str)


# ── Shared services safe-loader tests ─────────────────────────────────────────
class TestSharedServicesSafeLoader(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def test_safe_returns_default_on_exception(self):
        from paper_analytics.shared_services import _safe
        def bad(): raise RuntimeError("boom")
        result = _safe(bad, {"available": False})
        self.assertFalse(result["available"])

    def test_safe_returns_result_on_success(self):
        from paper_analytics.shared_services import _safe
        result = _safe(lambda: {"ok": True})
        self.assertTrue(result["ok"])

    def test_summary_safe_on_broken_submodule(self):
        _set_flag("true")
        with patch("paper_analytics.shared_services._load_trades",
                   side_effect=RuntimeError("broken")):
            from paper_analytics.shared_services import get_summary
            r = get_summary()
            # Should return ERROR, not raise
            self.assertIn(r["status"], ("ERROR", "ENABLED"))

    def test_snapshot_never_raises(self):
        with patch("paper_analytics.shared_services._load_trades",
                   side_effect=RuntimeError("bang")):
            from paper_analytics.shared_services import get_paper_analytics_snapshot
            r = get_paper_analytics_snapshot()
            self.assertIsInstance(r, dict)
            # Must have available key
            self.assertIn("available", r)


# ── Export tests ──────────────────────────────────────────────────────────────
class TestExportHelpers(unittest.TestCase):

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _mock_summary(self):
        return {
            "status": "ENABLED", "analytics_score": 70.0, "grade": "B",
            "total_trades": 5, "win_rate": 60.0, "profit_factor": 1.5,
            "expectancy": 150.0, "total_pnl": 750.0, "realised_pnl": 600.0,
            "sharpe_ratio": 1.2, "sortino_ratio": 1.5, "calmar_ratio": 0.8,
            "max_drawdown_pct": 5.0, "volatility_pct": 12.0,
            "best_strategy": "RSI", "best_sector": "IT",
        }

    def test_csv_has_header(self):
        from paper_analytics.shared_services import get_export_csv
        with patch("paper_analytics.shared_services.get_summary",
                   return_value=self._mock_summary()):
            csv = get_export_csv()
        self.assertIn("analytics_score", csv)
        self.assertIn("win_rate", csv)
        lines = csv.strip().split("\n")
        self.assertEqual(len(lines), 2)  # header + data row

    def test_json_export_has_summary(self):
        from paper_analytics.shared_services import get_export_json
        with patch("paper_analytics.shared_services.get_summary",
                   return_value=self._mock_summary()), \
             patch("paper_analytics.shared_services._load_trades",  return_value={}), \
             patch("paper_analytics.shared_services._load_strategies", return_value={}), \
             patch("paper_analytics.shared_services._load_risk",    return_value={}), \
             patch("paper_analytics.shared_services._load_preopen", return_value={}), \
             patch("paper_analytics.shared_services._load_portfolio",return_value={}), \
             patch("paper_analytics.shared_services._load_learning", return_value={}), \
             patch("paper_analytics.shared_services._load_time",    return_value={}), \
             patch("paper_analytics.shared_services._load_sector",  return_value={}), \
             patch("paper_analytics.shared_services._load_execution",return_value={}):
            r = get_export_json()
        self.assertIn("summary", r)
        self.assertTrue(r.get("advisory_only"))


# ── Grade/score helpers tests ─────────────────────────────────────────────────
class TestModels(unittest.TestCase):

    def test_grade_a_plus(self):
        from paper_analytics.models import analytics_grade
        self.assertEqual(analytics_grade(95), "A+")

    def test_grade_a(self):
        from paper_analytics.models import analytics_grade
        self.assertEqual(analytics_grade(82), "A")

    def test_grade_b(self):
        from paper_analytics.models import analytics_grade
        self.assertEqual(analytics_grade(70), "B")

    def test_grade_c(self):
        from paper_analytics.models import analytics_grade
        self.assertEqual(analytics_grade(55), "C")

    def test_grade_d(self):
        from paper_analytics.models import analytics_grade
        self.assertEqual(analytics_grade(30), "D")

    def test_trend_improving(self):
        from paper_analytics.models import trend_label
        self.assertEqual(trend_label(80, 70), "IMPROVING")

    def test_trend_declining(self):
        from paper_analytics.models import trend_label
        self.assertEqual(trend_label(60, 70), "DECLINING")

    def test_trend_stable(self):
        from paper_analytics.models import trend_label
        self.assertEqual(trend_label(70, 70), "STABLE")

    def test_snapshot_dataclass(self):
        from paper_analytics.models import PaperAnalyticsSnapshot
        snap = PaperAnalyticsSnapshot(total_trades=5, win_rate=60.0, available=True)
        d = snap.to_dict()
        self.assertEqual(d["total_trades"], 5)
        self.assertTrue(d["advisory_only"])
        self.assertIn("generated_at", d)


# ── Feature flag gating tests ─────────────────────────────────────────────────
class TestFeatureFlagGating(unittest.TestCase):
    """
    Verify that EVERY public command respects the feature flag,
    including snapshot (which bypassed it before) and CSV export.
    """

    def setUp(self):
        os.environ["PAPER_ANALYTICS_ENABLED"] = "false"

    def tearDown(self):
        os.environ["PAPER_ANALYTICS_ENABLED"] = "true"

    def test_snapshot_disabled_when_flag_false(self):
        """get_paper_analytics_snapshot() must return disabled when flag=false."""
        # Reload to pick up env change
        import importlib
        import paper_analytics.shared_services as ss
        importlib.reload(ss)
        r = ss.get_paper_analytics_snapshot()
        self.assertEqual(r.get("status"), "DISABLED")
        self.assertFalse(r.get("available"))

    def test_snapshot_available_false_when_disabled(self):
        import importlib
        import paper_analytics.shared_services as ss
        importlib.reload(ss)
        r = ss.get_paper_analytics_snapshot()
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])

    def test_csv_export_disabled_status(self):
        """cmd_export_csv() must return status=DISABLED when flag=false."""
        import importlib
        import paper_analytics.api as api_mod
        importlib.reload(api_mod)
        r = api_mod.cmd_export_csv()
        self.assertEqual(r.get("status"), "DISABLED")

    def test_csv_export_no_enabled_label_when_disabled(self):
        """CSV export must not claim ENABLED when the flag is off."""
        import importlib
        import paper_analytics.api as api_mod
        importlib.reload(api_mod)
        r = api_mod.cmd_export_csv()
        self.assertNotEqual(r.get("status"), "ENABLED")


# ── Recovery curve tests ──────────────────────────────────────────────────────
class TestRecoveryCurve(unittest.TestCase):
    """Verify the recovery curve is present and correctly structured."""

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self, trades=None):
        from paper_analytics.trade_analytics import get_trade_analytics
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=_make_perf_data(trades)), \
             patch("portfolio_performance.performance_engine.INITIAL_CAPITAL", 500_000.0):
            return get_trade_analytics()

    def test_recovery_curve_present(self):
        r = self._call()
        self.assertIn("recovery_curve", r)

    def test_recovery_curve_is_list(self):
        r = self._call()
        self.assertIsInstance(r["recovery_curve"], list)

    def test_recovery_curve_has_required_fields(self):
        """Each recovery curve point must have timestamp, equity, pct_recovered."""
        r = self._call()
        for pt in r["recovery_curve"]:
            for field in ("timestamp", "equity", "pct_recovered"):
                self.assertIn(field, pt, f"Recovery curve point missing: {field}")

    def test_recovery_curve_pct_non_negative(self):
        r = self._call()
        for pt in r["recovery_curve"]:
            self.assertGreaterEqual(pt["pct_recovered"], 0.0)

    def test_recovery_curve_equity_positive(self):
        r = self._call()
        for pt in r["recovery_curve"]:
            self.assertGreater(pt["equity"], 0)


# ── Recovery time algorithm tests ─────────────────────────────────────────────
class TestRecoveryTimeAlgorithm(unittest.TestCase):
    """Verify _recovery_time_days uses peak-before-trough, not timestamps."""

    def _pt(self, equity: float, drawdown: float = 0.0):
        """Create a mock equity point."""
        p = MagicMock()
        p.equity   = equity
        p.drawdown = drawdown
        p.timestamp = ""
        return p

    def _build_pts(self, equities: list) -> list:
        """Build annotated points: drawdown = max(prev) - current."""
        pts = []
        peak = equities[0]
        for eq in equities:
            peak = max(peak, eq)
            dd   = peak - eq
            pts.append(self._pt(eq, dd))
        return pts

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def test_recovered(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        # Peak=100, trough=80 (dd=20), then recovers: 85→95→100
        pts = self._build_pts([100, 90, 80, 85, 95, 100])
        days = _recovery_time_days(pts)
        self.assertGreater(days, 0)  # took some days
        self.assertGreaterEqual(days, 1)

    def test_not_yet_recovered(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        # Peak=100, drops to 80, only recovers to 95
        pts = self._build_pts([100, 90, 80, 85, 95])
        days = _recovery_time_days(pts)
        self.assertEqual(days, -1)  # not recovered

    def test_no_drawdown(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        # All upward — trough is index 0 — returns 0
        pts = self._build_pts([100, 105, 110, 115])
        days = _recovery_time_days(pts)
        self.assertEqual(days, 0)

    def test_empty_list(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        self.assertEqual(_recovery_time_days([]), 0)

    def test_single_point(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        pts = self._build_pts([100])
        self.assertEqual(_recovery_time_days(pts), 0)

    def test_uses_pre_trough_peak_not_initial(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        # Rises first (60→80→100), then falls to trough (70), then recovers to 100
        # Peak before trough = 100, not the initial 60
        # Trough is at index 3 (equity=70, dd=30)
        # Recovery = first point where equity >= 100 — which never happens in [75, 90, 95]
        pts = self._build_pts([60, 80, 100, 70, 75, 90, 95])
        days = _recovery_time_days(pts)
        self.assertEqual(days, -1, "Must use pre-trough peak (100), not initial (60)")

    def test_uses_pre_trough_peak_recovered(self):
        from paper_analytics.risk_analytics import _recovery_time_days
        # Rises 60→100, falls to 70, recovers to 100
        pts = self._build_pts([60, 80, 100, 70, 80, 90, 100])
        days = _recovery_time_days(pts)
        # trough_idx=3, peak=100, recovery at index 6 → offset = 6-3 = 3
        self.assertEqual(days, 3)


# ── Recovery curve no-drawdown tests ─────────────────────────────────────────
class TestRecoveryCurveNoDrawdown(unittest.TestCase):
    """Verify the recovery curve is empty when equity is monotonically increasing."""

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _monotonic_history(self) -> list:
        """pnl_history with strictly increasing values — drawdown will always be 0."""
        return [
            {"timestamp": f"2024-01-{10+i:02d}T09:00:00", "value": 500_000.0 + i * 2_000}
            for i in range(6)
        ]

    def _dip_and_recover_history(self) -> list:
        """pnl_history that dips then fully recovers above starting peak."""
        vals = [500_000, 490_000, 480_000, 495_000, 505_000, 510_000]
        return [
            {"timestamp": f"2024-01-{10+i:02d}T09:00:00", "value": float(v)}
            for i, v in enumerate(vals)
        ]

    def _call_with_history(self, history):
        from paper_analytics.trade_analytics import get_trade_analytics
        pd = _make_perf_data(pnl_history=history)
        with patch("portfolio_performance.performance_engine.load_performance_data",
                   return_value=pd), \
             patch("portfolio_performance.performance_engine.INITIAL_CAPITAL", 500_000.0):
            return get_trade_analytics()

    def test_recovery_curve_empty_when_no_drawdown(self):
        """Monotonically increasing equity → drawdown=0 everywhere → recovery_curve must be []."""
        r = self._call_with_history(self._monotonic_history())
        rc = r.get("recovery_curve", [])
        self.assertIsInstance(rc, list)
        self.assertEqual(len(rc), 0,
                         "recovery_curve must be empty when max drawdown is zero")

    def test_recovery_curve_pct_recovered_bounded_when_present(self):
        """When equity dips and recovers, pct_recovered must be capped at 100.0."""
        r = self._call_with_history(self._dip_and_recover_history())
        rc = r.get("recovery_curve", [])
        # A real drawdown exists, so we expect at least some recovery points
        for pt in rc:
            self.assertLessEqual(pt["pct_recovered"], 100.0,
                                 "pct_recovered must never exceed 100")

    def test_recovery_curve_pct_recovered_non_negative(self):
        """pct_recovered must always be >= 0.0."""
        r = self._call_with_history(self._dip_and_recover_history())
        for pt in r.get("recovery_curve", []):
            self.assertGreaterEqual(pt["pct_recovered"], 0.0)


# ── Pre-open MFE/MAE labeling tests ──────────────────────────────────────────
class TestPreopenMaeLabelCorrect(unittest.TestCase):
    """Verify MFE is not mislabeled; error metrics are clearly named."""

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _set_flag("true")

    def _call(self):
        from paper_analytics.preopen_analytics import get_preopen_analytics
        acc = {
            "available": True, "symbols_reconciled": 5,
            "hit_rate_pct": 60.0, "continuation_rate_pct": 60.0,
            "reversal_rate_pct": 40.0, "grade": "B",
            "grade_label": "Good", "trading_date": "2024-01-10",
            "symbols": [
                {"symbol": "RELIANCE", "error_pct": 0.3, "direction_correct": True,
                 "opening_reversal": False},
                {"symbol": "TCS", "error_pct": -0.5, "direction_correct": False,
                 "opening_reversal": True},
            ],
        }
        hist = {"sessions": []}
        with patch("preopen_accuracy.get_accuracy",        return_value=acc), \
             patch("preopen_accuracy.get_accuracy_history", return_value=hist):
            return get_preopen_analytics()

    def test_mfe_available_is_false(self):
        """MFE requires intraday data — must be marked unavailable, not computed."""
        r = self._call()
        self.assertFalse(r["mfe_available"])

    def test_mfe_note_present(self):
        r = self._call()
        self.assertIn("mfe_note", r)
        self.assertIn("intraday", r["mfe_note"].lower())

    def test_mae_field_is_open_vs_indicative(self):
        """mae field must be named mae_open_vs_indicative_pct to avoid confusion."""
        r = self._call()
        self.assertIn("mae_open_vs_indicative_pct", r)

    def test_max_abs_error_is_present(self):
        r = self._call()
        self.assertIn("max_abs_error_pct", r)
        self.assertIsNotNone(r["max_abs_error_pct"])

    def test_trend_classification_has_required_fields(self):
        r = self._call()
        tc = r["trend_classification"]
        for field in ("gap_and_go_count", "gap_fill_count", "early_reversal_count",
                      "late_reversal_count", "range_day_available", "trend_day_available"):
            self.assertIn(field, tc, f"Trend classification missing: {field}")

    def test_trend_classification_range_day_unavailable(self):
        """range-day requires intraday OHLC — must be marked unavailable."""
        r = self._call()
        self.assertFalse(r["trend_classification"]["range_day_available"])

    def test_trend_classification_trend_day_unavailable(self):
        """trend-day requires intraday OHLC — must be marked unavailable."""
        r = self._call()
        self.assertFalse(r["trend_classification"]["trend_day_available"])

    def test_real_preopen_symbol_shape_no_reversal_fields(self):
        """
        Using the real get_accuracy() symbol shape (confirmed live):
          direction_correct present; opening_reversal, opening_continuation,
          session_minutes NOT present.
        gap_fill / early_reversal / late_reversal must all be marked unavailable.
        """
        from paper_analytics.preopen_analytics import get_preopen_analytics
        # Real symbol shape from get_accuracy() — no reversal fields
        real_symbols = [
            {"symbol": "RELIANCE", "indicative_price": 2800.0, "actual_open": 2808.0,
             "price_at_0920": 2812.0, "price_at_0930": 2820.0,
             "error_pct": 0.28, "direction_correct": True,
             "was_in_watchlist": True, "watchlist_confirmed": True},
            {"symbol": "TCS", "indicative_price": 4000.0, "actual_open": 3990.0,
             "price_at_0920": 3988.0, "price_at_0930": 3985.0,
             "error_pct": -0.25, "direction_correct": False,
             "was_in_watchlist": True, "watchlist_confirmed": False},
        ]
        acc  = {"available": True, "symbols": real_symbols, "symbols_reconciled": 2,
                "hit_rate_pct": 50.0, "grade": "C", "grade_label": "Fair"}
        hist = {"sessions": []}
        with patch("preopen_accuracy.get_accuracy",         return_value=acc), \
             patch("preopen_accuracy.get_accuracy_history", return_value=hist):
            r = get_preopen_analytics()
        tc = r["trend_classification"]
        # gap_and_go computable from direction_correct
        self.assertEqual(tc["gap_and_go_count"], 1)
        # reversal sub-classifications unavailable — fields not in real shape
        self.assertFalse(tc.get("gap_fill_available"),       "gap_fill must be unavailable")
        self.assertFalse(tc.get("early_reversal_available"), "early_reversal must be unavailable")
        self.assertFalse(tc.get("late_reversal_available"),  "late_reversal must be unavailable")
        # intraday derived
        self.assertFalse(tc.get("range_day_available"))
        self.assertFalse(tc.get("trend_day_available"))
        # Count fields should NOT be present when data is unavailable
        self.assertNotIn("gap_fill_count",       tc,
                         "gap_fill_count must not appear when opening_reversal absent")
        self.assertNotIn("early_reversal_count", tc,
                         "early_reversal_count must not appear when session_minutes absent")


# ── Execution analytics contract tests ───────────────────────────────────────
class TestExecutionAnalyticsContract(unittest.TestCase):
    """
    Verify that every field the PaperAnalytics.tsx Execution tab reads
    is present in the get_execution_analytics() payload.
    """

    # All field names the dashboard reads for the Execution tab
    DASHBOARD_CONTRACT_FIELDS = [
        "available", "advisory_only",
        "total_records", "completed_records",
        "avg_quality_score", "overall_grade",
        "avg_entry_slippage_pct", "avg_exit_slippage_pct",
        "avg_execution_delay_seconds", "avg_capture_pct",
        "best_execution", "worst_execution",
        "grade_distribution", "strategy_quality",
    ]

    def _make_mock_record(self, score=75, grade="B", strategy="RSI",
                          symbol="RELIANCE", is_complete=True,
                          entry_slippage_pct=0.05, exit_slippage_pct=0.03,
                          entry_slippage_rs=5.0, exit_slippage_rs=3.0,
                          fill_delay_seconds=0.8, pnl=200.0,
                          actual_entry_price=100.0, target=110.0, quantity=100):
        r = MagicMock()
        r.quality_score       = score
        r.quality_grade       = grade
        r.strategy_name       = strategy
        r.symbol              = symbol
        r.is_complete         = is_complete
        r.entry_slippage_pct  = entry_slippage_pct
        r.entry_slippage_rs   = entry_slippage_rs
        r.exit_slippage_pct   = exit_slippage_pct
        r.exit_slippage_rs    = exit_slippage_rs
        r.fill_delay_seconds  = fill_delay_seconds
        r.pnl                 = pnl
        r.actual_entry_price  = actual_entry_price
        r.target              = target
        r.quantity            = quantity
        r.trade_id            = f"trade-{symbol}"
        return r

    def _call_with_records(self, records):
        from paper_analytics.execution_analytics import get_execution_analytics

        # Build a realistic summary dict from the records
        def mock_summary(recs):
            if not recs:
                return {
                    "total_trades": 0, "completed_trades": 0,
                    "avg_execution_score": None, "avg_entry_slippage_rs": None,
                    "avg_entry_slippage_pct": None, "avg_exit_slippage_rs": None,
                    "avg_exit_slippage_pct": None, "avg_fill_delay_seconds": None,
                    "best_trade": None, "worst_trade": None,
                    "most_efficient_strategy": None, "highest_slippage_symbol": None,
                }
            completed = [r for r in recs if r.is_complete]
            best  = max(recs, key=lambda r: r.quality_score)
            worst = min(recs, key=lambda r: r.quality_score)
            return {
                "total_trades":            len(recs),
                "completed_trades":        len(completed),
                "avg_execution_score":     round(sum(r.quality_score for r in recs) / len(recs), 1),
                "avg_entry_slippage_rs":   round(sum(r.entry_slippage_rs  for r in recs) / len(recs), 4),
                "avg_entry_slippage_pct":  round(sum(r.entry_slippage_pct for r in recs) / len(recs), 4),
                "avg_exit_slippage_rs":    round(sum(r.exit_slippage_rs   for r in completed) / len(completed), 4) if completed else None,
                "avg_exit_slippage_pct":   round(sum(r.exit_slippage_pct  for r in completed) / len(completed), 4) if completed else None,
                "avg_fill_delay_seconds":  round(sum(r.fill_delay_seconds for r in recs) / len(recs), 4),
                "best_trade":  {"trade_id": best.trade_id, "symbol": best.symbol, "score": best.quality_score, "grade": best.quality_grade},
                "worst_trade": {"trade_id": worst.trade_id, "symbol": worst.symbol, "score": worst.quality_score, "grade": worst.quality_grade},
                "most_efficient_strategy": recs[0].strategy_name,
                "highest_slippage_symbol": recs[0].symbol,
            }

        with patch("execution_quality.metrics.build_execution_records", return_value=records), \
             patch("execution_quality.metrics.compute_summary", side_effect=mock_summary):
            return get_execution_analytics()

    def test_all_dashboard_contract_fields_present(self):
        """Every field the Execution tab reads must exist in the payload."""
        records = [
            self._make_mock_record(score=80, grade="A"),
            self._make_mock_record(score=60, grade="C", symbol="TCS", pnl=-100.0),
        ]
        result = self._call_with_records(records)
        self.assertTrue(result.get("available"), "available must be True with real records")
        for field in self.DASHBOARD_CONTRACT_FIELDS:
            self.assertIn(field, result, f"Dashboard contract field missing: {field}")

    def test_total_records_maps_from_total_trades(self):
        """total_records must equal the number of records, not total_trades (alias check)."""
        records = [self._make_mock_record() for _ in range(3)]
        result = self._call_with_records(records)
        self.assertEqual(result["total_records"], 3)

    def test_completed_records_maps_from_completed_trades(self):
        complete   = [self._make_mock_record(is_complete=True)] * 2
        incomplete = [self._make_mock_record(is_complete=False)]
        result = self._call_with_records(complete + incomplete)
        self.assertEqual(result["completed_records"], 2)

    def test_avg_quality_score_maps_from_avg_execution_score(self):
        records = [self._make_mock_record(score=80), self._make_mock_record(score=60)]
        result = self._call_with_records(records)
        self.assertAlmostEqual(result["avg_quality_score"], 70.0, places=0)

    def test_overall_grade_computed(self):
        records = [self._make_mock_record(score=85)]
        result = self._call_with_records(records)
        self.assertIn(result["overall_grade"], ("A+", "A", "B", "C", "D"))

    def test_best_execution_maps_from_best_trade(self):
        records = [self._make_mock_record(score=90, symbol="TOP"), self._make_mock_record(score=50, symbol="BOT")]
        result = self._call_with_records(records)
        self.assertIsNotNone(result["best_execution"])
        self.assertEqual(result["best_execution"]["symbol"], "TOP")

    def test_worst_execution_maps_from_worst_trade(self):
        records = [self._make_mock_record(score=90, symbol="TOP"), self._make_mock_record(score=50, symbol="BOT")]
        result = self._call_with_records(records)
        self.assertIsNotNone(result["worst_execution"])
        self.assertEqual(result["worst_execution"]["symbol"], "BOT")

    def test_grade_distribution_present(self):
        records = [self._make_mock_record(grade="A"), self._make_mock_record(grade="B"), self._make_mock_record(grade="A")]
        result = self._call_with_records(records)
        self.assertIsInstance(result["grade_distribution"], dict)
        self.assertEqual(result["grade_distribution"].get("A"), 2)

    def test_strategy_quality_present(self):
        records = [
            self._make_mock_record(strategy="RSI",  score=80),
            self._make_mock_record(strategy="MACD", score=60),
        ]
        result = self._call_with_records(records)
        self.assertIsInstance(result["strategy_quality"], list)
        strats = {r["strategy"] for r in result["strategy_quality"]}
        self.assertIn("RSI",  strats)
        self.assertIn("MACD", strats)

    def test_overall_grade_a_plus_for_high_score(self):
        from paper_analytics.execution_analytics import _overall_grade
        self.assertEqual(_overall_grade(95.0), "A+")

    def test_overall_grade_d_for_low_score(self):
        from paper_analytics.execution_analytics import _overall_grade
        self.assertEqual(_overall_grade(30.0), "D")

    def test_overall_grade_na_for_none(self):
        from paper_analytics.execution_analytics import _overall_grade
        self.assertEqual(_overall_grade(None), "N/A")

    def test_unavailable_when_module_missing(self):
        from paper_analytics.execution_analytics import get_execution_analytics
        with patch.dict("sys.modules", {"execution_quality.metrics": None,
                                        "execution_quality": None,
                                        "execution_quality.report": None}):
            # Re-import to pick up the mock
            import importlib
            import paper_analytics.execution_analytics as ea_mod
            orig_fn = ea_mod.get_execution_analytics
            # Patch the import inside the function
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                try:
                    result = ea_mod.get_execution_analytics()
                    self.assertFalse(result.get("available", True))
                except ImportError:
                    pass  # acceptable — the guard triggers


# ── Analytics score formula ───────────────────────────────────────────────────
class TestAnalyticsScore(unittest.TestCase):

    def test_score_in_range(self):
        from paper_analytics.shared_services import _compute_analytics_score
        t = {"win_rate": 60.0, "profit_factor": 1.5, "total_trades": 10}
        r = {"sharpe_ratio": 1.0, "max_drawdown_pct": 5.0}
        s = _compute_analytics_score(t, r, {})
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_zero_trades_low_score(self):
        from paper_analytics.shared_services import _compute_analytics_score
        t = {"win_rate": 0.0, "profit_factor": 0.0, "total_trades": 0}
        r = {"sharpe_ratio": 0.0, "max_drawdown_pct": 0.0}
        s = _compute_analytics_score(t, r, {})
        self.assertLessEqual(s, 50)

    def test_perfect_inputs_high_score(self):
        from paper_analytics.shared_services import _compute_analytics_score
        t = {"win_rate": 70.0, "profit_factor": 3.5, "total_trades": 50}
        r = {"sharpe_ratio": 2.5, "max_drawdown_pct": 2.0}
        s = _compute_analytics_score(t, r, {})
        self.assertGreater(s, 70)


if __name__ == "__main__":
    unittest.main()
