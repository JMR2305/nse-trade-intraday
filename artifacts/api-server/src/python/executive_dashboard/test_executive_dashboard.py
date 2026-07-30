"""
test_executive_dashboard.py — Phase 5D.5 unit tests.

All tests use mocked shared services — never call the real broker,
real database, or real market data.
"""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_flag(value: str):
    os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = value


def _clear_flag():
    os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)


def _make_strategy_data():
    return {
        "available": True,
        "snapshot": {
            "total_strategies": 3,
            "best_strategy": "MACD_CROSS",
            "best_regime": "BULL",
            "best_sector": "IT",
            "total_net_pnl": 4200.0,
            "overall_win_rate": 62.5,
        },
        "criterion": {
            "best_profit_factor": {"name": "MACD_CROSS", "profit_factor": 2.1},
            "best_win_rate":      {"name": "RSI_BOUNCE", "win_rate": 65.0},
            "best_net_pnl":       {"name": "MACD_CROSS", "net_pnl": 4200.0},
            "worst_net_pnl":      {"name": "VWAP_PULL",  "net_pnl": -300.0},
        },
        "recs": [
            {"verdict": "STRONG_BUY", "strategy": "MACD_CROSS"},
            {"verdict": "BUY",        "strategy": "RSI_BOUNCE"},
        ],
    }


def _make_ai_data():
    return {
        "available": True,
        "snapshot": {
            "health_score": 82.0, "health_label": "Good",
            "prediction_accuracy": 71.0, "precision": 78.0, "recall": 65.0,
            "avg_confidence": 74.0, "trend_direction": "Improving",
            "accuracy_delta": 4.5, "calibration_ece": 0.05, "total_signals": 50,
        },
        "components": {
            "prediction_accuracy": 75.0, "calibration_quality": 80.0,
            "consistency": 85.0, "execution_outcome": 70.0,
            "risk_awareness": 90.0, "recommendation_quality": 80.0,
        },
        "learning": {"recent_accuracy": 73.0, "trend_direction": "Improving"},
    }


def _make_eq_data():
    return {
        "available": True,
        "avg_execution_score": 78.5,
        "avg_entry_slippage_pct": 0.12,
        "avg_fill_delay_seconds": 0.45,
        "total_trades": 40,
        "best_execution_score": 95.0,
        "worst_execution_score": 55.0,
    }


def _make_portfolio_data():
    return {
        "available": True,
        "summary": {
            "total_portfolio_value": 510000.0,
            "total_net_pnl": 10000.0,
            "cash_available": 400000.0,
            "invested_capital": 110000.0,
            "win_rate_pct": 62.5,
            "profit_factor": 1.8,
            "max_drawdown_pct": 3.5,
            "current_drawdown_pct": 0.0,
            "total_return_pct": 2.0,
            "portfolio_utilisation_pct": 21.5,
            "initial_capital": 500000.0,
        },
        "portfolio": {"position_count": 3},
    }


def _make_preopen_data():
    return {
        "available": True,
        "status": {
            "provider_label": "NSE Official", "last_updated": "09:00",
            "symbols_analysed": 45, "trading_date": "2025-07-29",
        },
        "rankings": {"top_symbols": [
            {"symbol": "INFY", "gap_pct": 2.1, "imbalance_type": "BUY"},
            {"symbol": "TCS", "gap_pct": -1.5, "imbalance_type": "SELL"},
        ]},
        "sectors": {"leading_sector": "IT"},
    }


def _make_risk_data():
    return {
        "available": True,
        "risk": {
            "sector_allocation": [{"sector": "IT", "weight_pct": 60.0}],
            "diversification_score": 55.0,
            "portfolio_heat": 22.0,
            "kill_switch": {"active": False},
            "utilization_pct": 22.0,
        },
        "alerts": {"alerts": []},
    }


def _make_system_data():
    return {
        "available": True,
        "scheduler": {"status": "HEALTHY", "active_jobs": []},
        "meta": {
            "status": "HEALTHY", "database": "CONNECTED",
            "api": "HEALTHY", "market_status": "OPEN",
            "ist_time": "09:30", "market_regime": "BULL",
        },
    }


def _patch_engine(test_case, overrides: dict | None = None):
    base = {
        "strategy":         _make_strategy_data(),
        "ai":               _make_ai_data(),
        "execution_quality": _make_eq_data(),
        "portfolio":        _make_portfolio_data(),
        "preopen":          _make_preopen_data(),
        "risk":             _make_risk_data(),
        "signals":          {"available": True, "status": {}, "summary": {}},
        "system":           _make_system_data(),
    }
    if overrides:
        base.update(overrides)
    # Patch on shared_services.load_all (where it is actually called) because
    # shared_services.py imports load_all via `from .dashboard_engine import load_all`
    # which creates a local binding — patching dashboard_engine.load_all alone
    # would not affect the already-bound name in shared_services.
    return patch("executive_dashboard.shared_services.load_all", return_value=base)


# ---------------------------------------------------------------------------
# Test: Feature Flag
# ---------------------------------------------------------------------------

class TestFeatureFlag(unittest.TestCase):
    def setUp(self):
        _clear_flag()

    def test_disabled_summary(self):
        from executive_dashboard.api import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "DISABLED")

    def test_disabled_health(self):
        from executive_dashboard.api import get_health
        r = get_health()
        self.assertEqual(r["status"], "DISABLED")

    def test_disabled_widgets(self):
        from executive_dashboard.api import get_widgets
        r = get_widgets()
        self.assertEqual(r["status"], "DISABLED")

    def test_shared_services_disabled(self):
        from executive_dashboard.shared_services import get_executive_snapshot
        r = get_executive_snapshot()
        self.assertEqual(r["status"], "DISABLED")


# ---------------------------------------------------------------------------
# Test: Zero / empty data
# ---------------------------------------------------------------------------

class TestZeroData(unittest.TestCase):
    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def test_all_unavailable(self):
        empty = {k: {"available": False, "error": "no data"} for k in
                 ["strategy", "ai", "execution_quality", "portfolio",
                  "preopen", "risk", "signals", "system"]}
        with patch("executive_dashboard.dashboard_engine.load_all", return_value=empty):
            from executive_dashboard.api import get_summary
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("executive_score", r)

    def test_zero_portfolio_score_in_range(self):
        empty = {k: {"available": False} for k in
                 ["strategy", "ai", "execution_quality", "portfolio",
                  "preopen", "risk", "signals", "system"]}
        with patch("executive_dashboard.dashboard_engine.load_all", return_value=empty):
            from executive_dashboard.shared_services import get_executive_summary
            r = get_executive_summary()
        score = r["executive_score"]["total"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# Test: Full data
# ---------------------------------------------------------------------------

class TestFullData(unittest.TestCase):
    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def test_summary_has_all_sections(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        for key in ["executive_score", "header", "system_health", "portfolio_overview",
                    "ai_health", "strategy_overview", "execution_quality",
                    "preopen_intelligence", "portfolio_risk", "live_alerts",
                    "market_snapshot", "quick_actions", "sections"]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_executive_score_in_range(self):
        with _patch_engine(self):
            from executive_dashboard.shared_services import get_executive_summary
            r = get_executive_summary()
        score = r["executive_score"]["total"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_executive_score_components_present(self):
        with _patch_engine(self):
            from executive_dashboard.shared_services import get_executive_summary
            r = get_executive_summary()
        components = r["executive_score"]["components"]
        for key in ["portfolio_health", "ai_health", "strategy_health",
                    "execution_quality", "risk", "system_health"]:
            self.assertIn(key, components)

    def test_ai_health_widget_fields(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        ai = r["ai_health"]
        for f in ["health_score", "health_label", "prediction_accuracy",
                  "precision", "recall", "avg_confidence", "trend_direction"]:
            self.assertIn(f, ai, f"AI widget missing: {f}")

    def test_portfolio_widget_fields(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        port = r["portfolio_overview"]
        for f in ["portfolio_value", "net_pnl", "cash_available",
                  "win_rate", "profit_factor", "drawdown"]:
            self.assertIn(f, port, f"Portfolio widget missing: {f}")

    def test_strategy_widget_fields(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        strat = r["strategy_overview"]
        self.assertEqual(strat["best_strategy"], "MACD_CROSS")
        self.assertEqual(strat["best_regime"],  "BULL")
        self.assertEqual(strat["best_sector"],  "IT")

    def test_execution_quality_widget(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        eq = r["execution_quality"]
        self.assertAlmostEqual(eq["execution_score"], 78.5)
        self.assertAlmostEqual(eq["avg_slippage"], 0.12)

    def test_preopen_widget(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        po = r["preopen_intelligence"]
        self.assertEqual(po["top_gap_up"], "INFY")
        self.assertAlmostEqual(po["top_gap_up_pct"], 2.1)
        self.assertEqual(po["provider"], "NSE Official")

    def test_risk_widget(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        rk = r["portfolio_risk"]
        self.assertFalse(rk["kill_switch_active"])
        self.assertEqual(rk["top_sector"], "IT")

    def test_quick_actions(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        self.assertGreater(len(r["quick_actions"]), 0)
        self.assertIn("href", r["quick_actions"][0])

    def test_sections_ordered(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        orders = [s["order"] for s in r["sections"]]
        self.assertEqual(orders, sorted(orders))


# ---------------------------------------------------------------------------
# Test: Executive Score model
# ---------------------------------------------------------------------------

class TestExecutiveScoreModel(unittest.TestCase):
    def test_perfect_score(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(100, 100, 100, 100, 100, 100)
        self.assertAlmostEqual(s.total, 100.0)
        self.assertEqual(s.label, "Excellent")

    def test_zero_score(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(0, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(s.total, 0.0)
        self.assertEqual(s.label, "Critical")

    def test_weights_sum_to_one(self):
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS
        self.assertAlmostEqual(sum(SCORE_WEIGHTS.values()), 1.0)

    def test_mixed_score(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(
            portfolio_health  = 80,
            ai_health         = 82,
            strategy_health   = 70,
            execution_quality = 78,
            risk              = 90,
            system_health     = 100,
        )
        # Expected: 0.25*80 + 0.20*82 + 0.20*70 + 0.15*78 + 0.10*90 + 0.10*100
        #         = 20 + 16.4 + 14 + 11.7 + 9 + 10 = 81.1
        self.assertAlmostEqual(s.total, 81.1, places=0)
        self.assertEqual(s.label, "Good")


# ---------------------------------------------------------------------------
# Test: Shared service reuse (no recalculation)
# ---------------------------------------------------------------------------

class TestSharedServiceReuse(unittest.TestCase):
    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def test_strategy_intelligence_imported_not_recalculated(self):
        """Confirm dashboard_engine calls strategy_intelligence.shared_services."""
        with patch("executive_dashboard.dashboard_engine._load_strategy") as mock:
            mock.return_value = {"available": True, "snapshot": {}, "criterion": {}, "recs": []}
            with patch("executive_dashboard.dashboard_engine._load_ai", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_execution_quality", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_portfolio", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_preopen", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_risk", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_signal_validation", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_system_health", return_value={"available": False}):
                from executive_dashboard.dashboard_engine import load_all
                load_all()
            mock.assert_called_once()

    def test_ai_performance_imported_not_recalculated(self):
        """Confirm dashboard_engine calls ai_performance.shared_services."""
        with patch("executive_dashboard.dashboard_engine._load_ai") as mock:
            mock.return_value = {"available": True, "snapshot": {}, "components": {}, "learning": {}}
            with patch("executive_dashboard.dashboard_engine._load_strategy", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_execution_quality", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_portfolio", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_preopen", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_risk", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_signal_validation", return_value={"available": False}), \
                 patch("executive_dashboard.dashboard_engine._load_system_health", return_value={"available": False}):
                from executive_dashboard.dashboard_engine import load_all
                load_all()
            mock.assert_called_once()

    def test_snapshot_for_future_phases(self):
        """get_executive_snapshot() returns flat dict suitable for super-dashboard tiles."""
        with _patch_engine(self):
            from executive_dashboard.shared_services import get_executive_snapshot
            r = get_executive_snapshot()
        self.assertEqual(r["status"], "ENABLED")
        for key in ["executive_score", "executive_label", "portfolio_value",
                    "net_pnl", "win_rate", "ai_health_score", "ai_trend",
                    "execution_score", "open_positions"]:
            self.assertIn(key, r, f"Snapshot missing: {key}")


# ---------------------------------------------------------------------------
# Test: API responses
# ---------------------------------------------------------------------------

class TestAPIResponses(unittest.TestCase):
    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def test_health_endpoint(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_health
            r = get_health()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("application_health", r)

    def test_widgets_endpoint(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_widgets
            r = get_widgets()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("portfolio_overview", r)
        self.assertIn("ai_health", r)
        self.assertNotIn("executive_score", r)  # widgets endpoint omits the score

    def test_summary_endpoint_enabled(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("executive_score", r)


# ---------------------------------------------------------------------------
# Test: Restart persistence
# ---------------------------------------------------------------------------

class TestRestartPersistence(unittest.TestCase):
    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def test_two_calls_identical(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r1 = get_summary()
            r2 = get_summary()
        self.assertEqual(r1["executive_score"]["total"], r2["executive_score"]["total"])

    def test_widget_layout_stable(self):
        with _patch_engine(self):
            from executive_dashboard.api import get_summary
            r1 = get_summary()
            r2 = get_summary()
        self.assertEqual(r1["sections"], r2["sections"])


# ---------------------------------------------------------------------------
# Test: best_regime coercion in widget (regression guard for #217)
# ---------------------------------------------------------------------------

class TestBestRegimeWidgetCoercion(unittest.TestCase):
    """
    Guard: widget_strategy_overview() must always return best_regime as a str,
    even when the upstream snapshot sends a dict/None/empty-object.
    """

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    def _run_widget(self, best_regime_value):
        from executive_dashboard.widgets import widget_strategy_overview
        data = {
            "strategy": {
                "available": True,
                "snapshot": {
                    "total_strategies": 2,
                    "best_strategy": "MACD_CROSS",
                    "best_regime":  best_regime_value,   # ← value under test
                    "best_sector":  "IT",
                    "total_net_pnl":    3000.0,
                    "overall_win_rate": 60.0,
                },
                "criterion": {},
                "recs": [],
            }
        }
        return widget_strategy_overview(data)

    def test_empty_dict_coerced_to_na(self):
        """Regression: {} must yield 'N/A', not crash KpiCard."""
        result = self._run_widget({})
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "N/A")

    def test_non_empty_dict_coerced_to_na(self):
        """A dict with keys must also yield 'N/A', not '[object Object]'."""
        result = self._run_widget({"regime": "Bullish", "count": 3})
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "N/A")

    def test_none_coerced_to_na(self):
        result = self._run_widget(None)
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "N/A")

    def test_valid_string_passes_through(self):
        result = self._run_widget("Bullish")
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "Bullish")

    def test_empty_string_coerced_to_na(self):
        result = self._run_widget("")
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "N/A")

    def test_list_coerced_to_na(self):
        result = self._run_widget(["Bullish", "Bearish"])
        self.assertIsInstance(result["best_regime"], str)
        self.assertEqual(result["best_regime"], "N/A")


if __name__ == "__main__":
    unittest.main()
