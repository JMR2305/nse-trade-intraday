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
                    "execution_quality", "risk", "system_health", "paper_analytics",
                    "data_quality"]:
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
        s = ExecutiveScore(100, 100, 100, 100, 100, 100, 100, 100)
        self.assertAlmostEqual(s.total, 100.0)
        self.assertEqual(s.label, "Excellent")

    def test_zero_score(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(0, 0, 0, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(s.total, 0.0)
        self.assertEqual(s.label, "Critical")

    def test_weights_sum_to_one(self):
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS
        self.assertAlmostEqual(sum(SCORE_WEIGHTS.values()), 1.0)

    def test_eight_components_in_weights(self):
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS
        self.assertIn("paper_analytics", SCORE_WEIGHTS)
        self.assertIn("data_quality", SCORE_WEIGHTS)
        self.assertEqual(len(SCORE_WEIGHTS), 8)

    def test_paper_analytics_weight_is_nine_percent(self):
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS
        self.assertAlmostEqual(SCORE_WEIGHTS["paper_analytics"], 0.09, places=3)

    def test_data_quality_weight_is_ten_percent(self):
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS
        self.assertAlmostEqual(SCORE_WEIGHTS["data_quality"], 0.10, places=3)

    def test_mixed_score(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(
            portfolio_health  = 80,
            ai_health         = 82,
            strategy_health   = 70,
            execution_quality = 78,
            risk              = 90,
            system_health     = 100,
            paper_analytics   = 75,
            data_quality      = 50,
        )
        # Expected (Task 259 weights — all prior weights × 0.9, data_quality = 0.10):
        #   0.2025*80 + 0.162*82 + 0.162*70 + 0.1215*78 + 0.081*90 + 0.081*100
        #   + 0.09*75 + 0.10*50
        # = 16.20 + 13.284 + 11.34 + 9.477 + 7.29 + 8.10 + 6.75 + 5.00 = 77.441 → 77.4
        self.assertAlmostEqual(s.total, 77.4, places=0)
        self.assertEqual(s.label, "Good")

    def test_paper_analytics_field_in_to_dict(self):
        from executive_dashboard.dashboard_models import ExecutiveScore
        s = ExecutiveScore(paper_analytics=72.0)
        d = s.to_dict()
        self.assertIn("paper_analytics", d["components"])
        self.assertIn("paper_analytics", d["weights"])
        self.assertAlmostEqual(d["components"]["paper_analytics"], 72.0, places=1)

    def test_paper_analytics_zero_reduces_total(self):
        """A paper_analytics score of 0 pulls the composite down vs the 50.0 neutral default."""
        from executive_dashboard.dashboard_models import ExecutiveScore
        s_neutral = ExecutiveScore(80, 80, 80, 80, 80, 80, paper_analytics=50.0)
        s_poor    = ExecutiveScore(80, 80, 80, 80, 80, 80, paper_analytics=0.0)
        self.assertGreater(s_neutral.total, s_poor.total)

    def test_paper_analytics_high_raises_total(self):
        """A paper_analytics score of 100 raises the composite vs the 50.0 neutral default."""
        from executive_dashboard.dashboard_models import ExecutiveScore
        s_neutral = ExecutiveScore(80, 80, 80, 80, 80, 80, paper_analytics=50.0)
        s_great   = ExecutiveScore(80, 80, 80, 80, 80, 80, paper_analytics=100.0)
        self.assertGreater(s_great.total, s_neutral.total)


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


# ---------------------------------------------------------------------------
# Test: _as_str guard on all remaining string KPI fields (Task #223)
# ---------------------------------------------------------------------------

class TestStringKpiCoercion(unittest.TestCase):
    """
    Verify that every string-typed KPI field in every widget function returns
    a plain str even when the upstream snapshot sends a dict, list, or None.

    One representative "bad value" test per widget is sufficient to confirm the
    guard is wired; the _as_str() unit itself is covered by the best_regime
    tests above.
    """

    def setUp(self):
        _set_flag("true")

    def tearDown(self):
        _clear_flag()

    # ── widget_strategy_overview ──────────────────────────────────────────────

    def _strategy_widget(self, overrides: dict) -> dict:
        from executive_dashboard.widgets import widget_strategy_overview
        snap = {
            "total_strategies": 2,
            "best_strategy":    "MACD_CROSS",
            "best_regime":      "BULL",
            "best_sector":      "IT",
            "total_net_pnl":    1000.0,
            "overall_win_rate": 55.0,
        }
        snap.update(overrides)
        data = {
            "strategy": {
                "available": True,
                "snapshot": snap,
                "criterion": {},
                "recs": [],
            }
        }
        return widget_strategy_overview(data)

    def test_best_strategy_dict_coerced(self):
        r = self._strategy_widget({"best_strategy": {}})
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_best_strategy_list_coerced(self):
        r = self._strategy_widget({"best_strategy": ["A", "B"]})
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_best_strategy_none_coerced(self):
        r = self._strategy_widget({"best_strategy": None})
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_best_strategy_valid_passes_through(self):
        r = self._strategy_widget({"best_strategy": "RSI_BOUNCE"})
        self.assertEqual(r["best_strategy"], "RSI_BOUNCE")

    def test_worst_strategy_dict_coerced(self):
        from executive_dashboard.widgets import widget_strategy_overview
        data = {
            "strategy": {
                "available": True,
                "snapshot": {"best_regime": "BULL"},
                "criterion": {
                    "worst_net_pnl": {"name": {}, "net_pnl": -100.0},
                },
                "recs": [],
            }
        }
        r = widget_strategy_overview(data)
        self.assertIsInstance(r["worst_strategy"], str)
        self.assertEqual(r["worst_strategy"], "N/A")

    def test_highest_win_rate_dict_coerced(self):
        from executive_dashboard.widgets import widget_strategy_overview
        data = {
            "strategy": {
                "available": True,
                "snapshot": {"best_regime": "BULL"},
                "criterion": {
                    "best_win_rate": {"name": {}, "win_rate": 70.0},
                },
                "recs": [],
            }
        }
        r = widget_strategy_overview(data)
        self.assertIsInstance(r["highest_win_rate"], str)
        self.assertEqual(r["highest_win_rate"], "N/A")

    def test_best_profit_factor_dict_coerced(self):
        from executive_dashboard.widgets import widget_strategy_overview
        data = {
            "strategy": {
                "available": True,
                "snapshot": {"best_regime": "BULL"},
                "criterion": {
                    "best_profit_factor": {"name": {}, "profit_factor": 2.5},
                },
                "recs": [],
            }
        }
        r = widget_strategy_overview(data)
        self.assertIsInstance(r["best_profit_factor"], str)
        self.assertEqual(r["best_profit_factor"], "N/A")

    def test_best_sector_dict_coerced(self):
        r = self._strategy_widget({"best_sector": {"sector": "IT", "weight": 0.4}})
        self.assertIsInstance(r["best_sector"], str)
        self.assertEqual(r["best_sector"], "N/A")

    def test_best_sector_none_coerced(self):
        r = self._strategy_widget({"best_sector": None})
        self.assertIsInstance(r["best_sector"], str)
        self.assertEqual(r["best_sector"], "N/A")

    def test_best_sector_valid_passes_through(self):
        r = self._strategy_widget({"best_sector": "TECHNOLOGY"})
        self.assertEqual(r["best_sector"], "TECHNOLOGY")

    # ── widget_ai_health ──────────────────────────────────────────────────────

    def _ai_widget(self, snap_overrides: dict) -> dict:
        from executive_dashboard.widgets import widget_ai_health
        snap = {
            "health_score": 75.0, "health_label": "Good",
            "prediction_accuracy": 65.0, "precision": 68.0, "recall": 60.0,
            "avg_confidence": 70.0, "trend_direction": "Stable",
            "accuracy_delta": 1.0, "calibration_ece": 0.05, "total_signals": 30,
        }
        snap.update(snap_overrides)
        return widget_ai_health({"ai": {"available": True, "snapshot": snap,
                                        "components": {}, "learning": {}}})

    def test_health_label_dict_coerced(self):
        r = self._ai_widget({"health_label": {"level": "Good"}})
        self.assertIsInstance(r["health_label"], str)
        self.assertEqual(r["health_label"], "N/A")

    def test_health_label_none_coerced(self):
        r = self._ai_widget({"health_label": None})
        self.assertIsInstance(r["health_label"], str)
        self.assertEqual(r["health_label"], "N/A")

    def test_health_label_valid_passes_through(self):
        r = self._ai_widget({"health_label": "Excellent"})
        self.assertEqual(r["health_label"], "Excellent")

    def test_trend_direction_dict_coerced_to_stable(self):
        r = self._ai_widget({"trend_direction": {"direction": "up"}})
        self.assertIsInstance(r["trend_direction"], str)
        self.assertEqual(r["trend_direction"], "Stable")

    def test_trend_direction_none_coerced_to_stable(self):
        r = self._ai_widget({"trend_direction": None})
        self.assertIsInstance(r["trend_direction"], str)
        self.assertEqual(r["trend_direction"], "Stable")

    def test_trend_direction_valid_passes_through(self):
        r = self._ai_widget({"trend_direction": "Improving"})
        self.assertEqual(r["trend_direction"], "Improving")

    # ── widget_preopen ────────────────────────────────────────────────────────

    def test_preopen_leading_sector_dict_coerced(self):
        from executive_dashboard.widgets import widget_preopen
        data = {"preopen": {
            "available": True,
            "status": {"provider_label": "NSE", "last_updated": "09:00",
                       "symbols_analysed": 10, "trading_date": "2026-07-30"},
            "rankings": {"top_symbols": []},
            "sectors": {"leading_sector": {"name": "IT", "weight": 0.4}},
        }}
        r = widget_preopen(data)
        self.assertIsInstance(r["leading_sector"], str)
        self.assertEqual(r["leading_sector"], "N/A")

    def test_preopen_provider_dict_coerced(self):
        from executive_dashboard.widgets import widget_preopen
        data = {"preopen": {
            "available": True,
            "status": {"provider_label": {"name": "NSE"}, "last_updated": "09:00",
                       "symbols_analysed": 10, "trading_date": "2026-07-30"},
            "rankings": {"top_symbols": []},
            "sectors": {},
        }}
        r = widget_preopen(data)
        self.assertIsInstance(r["provider"], str)
        self.assertEqual(r["provider"], "N/A")

    def test_preopen_trading_date_dict_coerced(self):
        from executive_dashboard.widgets import widget_preopen
        data = {"preopen": {
            "available": True,
            "status": {"provider_label": "NSE", "last_updated": "09:00",
                       "symbols_analysed": 10,
                       "trading_date": {"date": "2026-07-30"}},
            "rankings": {"top_symbols": []},
            "sectors": {},
        }}
        r = widget_preopen(data)
        self.assertIsInstance(r["trading_date"], str)
        self.assertEqual(r["trading_date"], "N/A")

    # ── widget_portfolio_risk ─────────────────────────────────────────────────

    def test_risk_top_sector_dict_coerced(self):
        from executive_dashboard.widgets import widget_portfolio_risk
        data = {"risk": {
            "available": True,
            "risk": {
                "sector_allocation": [{"sector": {"name": "IT"}, "weight_pct": 50.0}],
                "diversification_score": 60.0,
                "portfolio_heat": 20.0,
                "kill_switch": {"active": False},
                "utilization_pct": 20.0,
            },
            "alerts": {"alerts": []},
        }}
        r = widget_portfolio_risk(data)
        self.assertIsInstance(r["top_sector"], str)
        self.assertEqual(r["top_sector"], "N/A")

    def test_risk_top_sector_valid_passes_through(self):
        from executive_dashboard.widgets import widget_portfolio_risk
        data = {"risk": {
            "available": True,
            "risk": {
                "sector_allocation": [{"sector": "TECHNOLOGY", "weight_pct": 50.0}],
                "diversification_score": 60.0, "portfolio_heat": 20.0,
                "kill_switch": {"active": False}, "utilization_pct": 20.0,
            },
            "alerts": {"alerts": []},
        }}
        r = widget_portfolio_risk(data)
        self.assertEqual(r["top_sector"], "TECHNOLOGY")

    # ── widget_system_health ──────────────────────────────────────────────────

    def test_system_health_app_health_dict_coerced(self):
        from executive_dashboard.widgets import widget_system_health
        data = {"system": {
            "available": True,
            "scheduler": {"status": "HEALTHY", "active_jobs": []},
            "meta": {"status": {"level": "HEALTHY"}, "database": "CONNECTED",
                     "api": "UP"},
        }}
        r = widget_system_health(data)
        self.assertIsInstance(r["application_health"], str)
        self.assertEqual(r["application_health"], "UNKNOWN")

    def test_system_health_db_status_dict_coerced(self):
        from executive_dashboard.widgets import widget_system_health
        data = {"system": {
            "available": True,
            "scheduler": {"status": "HEALTHY", "active_jobs": []},
            "meta": {"status": "HEALTHY", "database": {"connected": True}, "api": "UP"},
        }}
        r = widget_system_health(data)
        self.assertIsInstance(r["database_status"], str)
        self.assertEqual(r["database_status"], "UNKNOWN")

    def test_system_health_valid_passes_through(self):
        from executive_dashboard.widgets import widget_system_health
        data = {"system": {
            "available": True,
            "scheduler": {"status": "HEALTHY", "active_jobs": []},
            "meta": {"status": "HEALTHY", "database": "CONNECTED",
                     "api": "UP"},
        }}
        r = widget_system_health(data)
        self.assertEqual(r["application_health"], "HEALTHY")
        self.assertEqual(r["database_status"], "CONNECTED")

    # ── widget_market_snapshot ────────────────────────────────────────────────

    def test_market_regime_dict_coerced(self):
        from executive_dashboard.widgets import widget_market_snapshot
        data = {"system": {"meta": {"market_regime": {"name": "BULL"}}}}
        r = widget_market_snapshot(data)
        self.assertIsInstance(r["market_regime"], str)
        self.assertEqual(r["market_regime"], "UNKNOWN")

    def test_market_status_dict_coerced(self):
        from executive_dashboard.widgets import widget_market_snapshot
        data = {"system": {"meta": {"market_status": {"open": True}}}}
        r = widget_market_snapshot(data)
        self.assertIsInstance(r["market_status"], str)
        self.assertEqual(r["market_status"], "UNKNOWN")

    def test_market_snapshot_valid_passes_through(self):
        from executive_dashboard.widgets import widget_market_snapshot
        data = {"system": {"meta": {
            "market_regime": "TRENDING", "market_status": "OPEN", "ist_time": "09:30",
        }}}
        r = widget_market_snapshot(data)
        self.assertEqual(r["market_regime"], "TRENDING")
        self.assertEqual(r["market_status"], "OPEN")

    # ── widget_readiness ──────────────────────────────────────────────────────

    def test_readiness_grade_dict_coerced(self):
        from executive_dashboard.widgets import widget_readiness
        data = {"readiness": {
            "available": True,
            "readiness_score": 75.0,
            "grade": {"letter": "B"},
            "verdict": "READY",
            "verdict_short": "GO",
        }}
        r = widget_readiness(data)
        self.assertIsInstance(r["grade"], str)
        self.assertEqual(r["grade"], "N/A")

    def test_readiness_verdict_dict_coerced(self):
        from executive_dashboard.widgets import widget_readiness
        data = {"readiness": {
            "available": True,
            "readiness_score": 75.0,
            "grade": "B",
            "verdict": {"text": "READY"},
            "verdict_short": "GO",
        }}
        r = widget_readiness(data)
        self.assertIsInstance(r["verdict"], str)
        self.assertEqual(r["verdict"], "NOT READY")

    def test_readiness_valid_passes_through(self):
        from executive_dashboard.widgets import widget_readiness
        data = {"readiness": {
            "available": True,
            "readiness_score": 84.0,
            "grade": "B",
            "verdict": "READY FOR EXTENDED PAPER TRADING",
            "verdict_short": "GO",
        }}
        r = widget_readiness(data)
        self.assertEqual(r["grade"], "B")
        self.assertEqual(r["verdict_short"], "GO")

    # ── widget_header ─────────────────────────────────────────────────────────

    def test_header_market_status_dict_coerced(self):
        from executive_dashboard.widgets import widget_header
        data = {
            "system":  {"meta": {"market_status": {"open": True},
                                 "ist_time": "09:30", "market_regime": "BULL"}},
            "preopen": {"status": {}},
        }
        r = widget_header(data)
        self.assertIsInstance(r["market_status"], str)
        self.assertEqual(r["market_status"], "UNKNOWN")

    def test_header_trading_date_dict_coerced(self):
        from executive_dashboard.widgets import widget_header
        data = {
            "system":  {"meta": {"market_status": "OPEN",
                                 "ist_time": "09:30", "market_regime": "BULL"}},
            "preopen": {"status": {"trading_date": {"date": "2026-07-30"}}},
        }
        r = widget_header(data)
        self.assertIsInstance(r["trading_date"], str)
        self.assertEqual(r["trading_date"], "N/A")

    def test_header_valid_passes_through(self):
        from executive_dashboard.widgets import widget_header
        data = {
            "system":  {"meta": {"market_status": "OPEN",
                                 "ist_time": "09:30", "market_regime": "TRENDING"}},
            "preopen": {"status": {"provider_label": "NSE Official",
                                   "trading_date": "2026-07-30",
                                   "symbols_analysed": 50}},
        }
        r = widget_header(data)
        self.assertEqual(r["market_status"],   "OPEN")
        self.assertEqual(r["market_regime"],   "TRENDING")
        self.assertEqual(r["active_provider"], "NSE Official")
        self.assertEqual(r["trading_date"],    "2026-07-30")


# ══════════════════════════════════════════════════════════════════════════════
# widget_paper_analytics — Phase 8.2
# ══════════════════════════════════════════════════════════════════════════════

class TestWidgetPaperAnalytics(unittest.TestCase):
    """
    Covers widget_paper_analytics() for all inputs:
      - missing / unavailable data  → disabled stub
      - full snapshot               → correct field mapping
      - string coercion             → grade / best_strategy / best_sector
      - advisory_only always True
    """

    def setUp(self):
        os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)

    def _pa(self, overrides: dict) -> dict:
        from executive_dashboard.widgets import widget_paper_analytics
        snap = {
            "available":       True,
            "analytics_score": 72.5,
            "grade":           "B",
            "win_rate":        58.0,
            "profit_factor":   1.8,
            "total_trades":    25,
            "total_pnl":       12_000.0,
            "sharpe_ratio":    1.2,
            "best_strategy":   "Momentum",
            "best_sector":     "IT",
        }
        snap.update(overrides)
        return widget_paper_analytics({"paper_analytics": snap})

    # ── disabled / missing ────────────────────────────────────────────────────

    def test_empty_data_returns_disabled(self):
        from executive_dashboard.widgets import widget_paper_analytics
        r = widget_paper_analytics({})
        self.assertFalse(r["available"])
        self.assertTrue(r["disabled"])
        self.assertEqual(r["analytics_score"], 0.0)
        self.assertEqual(r["grade"], "N/A")
        self.assertTrue(r["advisory_only"])

    def test_available_false_returns_disabled(self):
        from executive_dashboard.widgets import widget_paper_analytics
        r = widget_paper_analytics({"paper_analytics": {"available": False}})
        self.assertFalse(r["available"])
        self.assertTrue(r["disabled"])
        self.assertEqual(r["grade"], "N/A")
        self.assertEqual(r["best_strategy"], "N/A")
        self.assertTrue(r["advisory_only"])

    # ── happy path ────────────────────────────────────────────────────────────

    def test_analytics_score_passed_through(self):
        r = self._pa({})
        self.assertAlmostEqual(r["analytics_score"], 72.5, places=1)

    def test_win_rate_passed_through(self):
        r = self._pa({})
        self.assertAlmostEqual(r["win_rate"], 58.0, places=1)

    def test_profit_factor_passed_through(self):
        r = self._pa({})
        self.assertAlmostEqual(r["profit_factor"], 1.8, places=1)

    def test_total_trades_passed_through(self):
        r = self._pa({})
        self.assertEqual(r["total_trades"], 25)

    def test_total_pnl_passed_through(self):
        r = self._pa({})
        self.assertAlmostEqual(r["total_pnl"], 12_000.0, places=0)

    def test_sharpe_ratio_passed_through(self):
        r = self._pa({})
        self.assertAlmostEqual(r["sharpe_ratio"], 1.2, places=1)

    def test_available_true_when_enabled(self):
        r = self._pa({})
        self.assertTrue(r["available"])
        self.assertFalse(r["disabled"])

    def test_advisory_only_always_true(self):
        r = self._pa({})
        self.assertTrue(r["advisory_only"])

    # ── string coercion ───────────────────────────────────────────────────────

    def test_grade_dict_coerced_to_na(self):
        r = self._pa({"grade": {"letter": "B", "score": 72}})
        self.assertIsInstance(r["grade"], str)
        self.assertEqual(r["grade"], "N/A")

    def test_grade_none_coerced_to_na(self):
        r = self._pa({"grade": None})
        self.assertIsInstance(r["grade"], str)
        self.assertEqual(r["grade"], "N/A")

    def test_grade_valid_passes_through(self):
        r = self._pa({"grade": "A"})
        self.assertEqual(r["grade"], "A")

    def test_best_strategy_dict_coerced(self):
        r = self._pa({"best_strategy": {"name": "Momentum"}})
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_best_strategy_none_coerced(self):
        r = self._pa({"best_strategy": None})
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_best_strategy_valid_passes_through(self):
        r = self._pa({"best_strategy": "MACD_CROSS"})
        self.assertEqual(r["best_strategy"], "MACD_CROSS")

    def test_best_sector_dict_coerced(self):
        r = self._pa({"best_sector": {"sector": "IT", "weight": 0.4}})
        self.assertIsInstance(r["best_sector"], str)
        self.assertEqual(r["best_sector"], "N/A")

    def test_best_sector_none_coerced(self):
        r = self._pa({"best_sector": None})
        self.assertIsInstance(r["best_sector"], str)
        self.assertEqual(r["best_sector"], "N/A")

    def test_best_sector_valid_passes_through(self):
        r = self._pa({"best_sector": "Banking"})
        self.assertEqual(r["best_sector"], "Banking")

    # ── regression: no string field is ever dict or None ─────────────────────

    def test_no_string_field_is_none(self):
        r = self._pa({"grade": None, "best_strategy": None, "best_sector": None})
        for field in ("grade", "best_strategy", "best_sector"):
            self.assertIsNotNone(r.get(field), f"{field} was None")

    def test_no_string_field_is_dict(self):
        r = self._pa({
            "grade":         {"bad": "value"},
            "best_strategy": {"bad": "value"},
            "best_sector":   {"bad": "value"},
        })
        for field in ("grade", "best_strategy", "best_sector"):
            self.assertNotIsInstance(r.get(field), dict, f"{field} was a dict")

    # ── total_trades coercion from float ─────────────────────────────────────

    def test_total_trades_coerced_from_float(self):
        r = self._pa({"total_trades": 12.9})
        self.assertIsInstance(r["total_trades"], int)
        self.assertEqual(r["total_trades"], 12)

    def test_total_trades_coerced_from_none(self):
        r = self._pa({"total_trades": None})
        self.assertIsInstance(r["total_trades"], int)
        self.assertEqual(r["total_trades"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# Paper Analytics — end-to-end disabled-state pipeline tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPaperAnalyticsDisabledPipeline(unittest.TestCase):
    """
    Verifies the full pipeline from _load_paper_analytics() → widget_paper_analytics()
    → _build_widgets() → executive/summary payload when the feature flag is off.

    Patches _load_paper_analytics at the engine level so the tests exercise
    the full widget + shared_services stack without hitting the real DB or
    the paper_analytics module.
    """

    def setUp(self):
        os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)

    # ── 1. widget_paper_analytics with status: DISABLED snapshot ─────────────

    def test_status_disabled_snapshot_yields_disabled_widget(self):
        """_load_paper_analytics returning {available:False, status:'DISABLED'} → widget disabled."""
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertFalse(r["available"])
        self.assertTrue(r["disabled"])

    def test_status_disabled_grade_is_safe_string(self):
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertIsInstance(r["grade"], str)
        self.assertEqual(r["grade"], "N/A")

    def test_status_disabled_best_strategy_is_safe_string(self):
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertIsInstance(r["best_strategy"], str)
        self.assertEqual(r["best_strategy"], "N/A")

    def test_status_disabled_best_sector_is_safe_string(self):
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertIsInstance(r["best_sector"], str)
        self.assertEqual(r["best_sector"], "N/A")

    def test_status_disabled_numeric_fields_are_zero(self):
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertEqual(r["analytics_score"], 0.0)
        self.assertEqual(r["win_rate"], 0.0)
        self.assertEqual(r["profit_factor"], 0.0)
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["total_pnl"], 0.0)
        self.assertEqual(r["sharpe_ratio"], 0.0)

    def test_advisory_only_true_even_when_disabled(self):
        from executive_dashboard.widgets import widget_paper_analytics
        data = {"paper_analytics": {"available": False, "status": "DISABLED"}}
        r = widget_paper_analytics(data)
        self.assertTrue(r["advisory_only"])

    # ── 2. Full pipeline: _load_paper_analytics patched → build_widgets ───────

    def test_patched_disabled_load_reaches_build_widgets(self):
        """Patch _load_paper_analytics in load_all → verify paper_analytics widget in summary."""
        with patch("executive_dashboard.dashboard_engine._load_paper_analytics",
                   return_value={"available": False, "status": "DISABLED"}):
            with _patch_engine(self):
                # _patch_engine patches shared_services.load_all with a dict that has
                # no 'paper_analytics' key — we need to patch dashboard_engine.load_all directly
                pass
        # Patch dashboard_engine.load_all directly so shared_services.load_all also picks it up
        disabled_pa = {"available": False, "status": "DISABLED"}
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   disabled_pa,
        }
        with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
            from executive_dashboard.shared_services import _build_widgets
            widgets = _build_widgets(full_data)
        pa_widget = widgets.get("paper_analytics", {})
        self.assertFalse(pa_widget["available"])
        self.assertTrue(pa_widget["disabled"])

    def test_patched_disabled_load_in_executive_summary(self):
        """Disabled paper_analytics is present (not missing) in the full /executive/summary payload."""
        disabled_pa = {"available": False, "status": "DISABLED"}
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   disabled_pa,
        }
        with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
            from executive_dashboard.shared_services import get_executive_summary
            r = get_executive_summary()
        # Key must exist — not omitted — so the frontend always gets a well-formed object
        self.assertIn("paper_analytics", r)
        pa = r["paper_analytics"]
        self.assertFalse(pa["available"])
        self.assertTrue(pa["disabled"])

    def test_disabled_paper_analytics_all_string_fields_are_str(self):
        """Every string KPI field in the disabled widget is a plain str, never None or dict."""
        disabled_pa = {"available": False, "status": "DISABLED"}
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   disabled_pa,
        }
        with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
            from executive_dashboard.shared_services import get_executive_summary
            r = get_executive_summary()
        pa = r["paper_analytics"]
        for field in ("grade", "best_strategy", "best_sector"):
            self.assertIsInstance(pa[field], str, f"{field} was not a str")
            self.assertIsNotNone(pa[field], f"{field} was None")

    # ── 3. Missing paper_analytics key from load_all → disabled widget ────────

    def test_missing_key_in_load_all_yields_disabled_widget(self):
        """If load_all omits 'paper_analytics' entirely, widget_paper_analytics still returns disabled."""
        from executive_dashboard.widgets import widget_paper_analytics
        # Empty data — no paper_analytics key at all
        r = widget_paper_analytics({})
        self.assertFalse(r["available"])
        self.assertTrue(r["disabled"])
        self.assertEqual(r["grade"], "N/A")


# ══════════════════════════════════════════════════════════════════════════════
# Paper Analytics neutral fallback — regression guard
#
# Design invariant: when PAPER_ANALYTICS_ENABLED is off (or the module is
# unavailable for any reason), compute_executive_score() must use 50.0 as
# the paper_analytics component — never 0.0.  Using 0.0 would silently
# subtract 5 points (10% × 50) from every operator's Executive Score on any
# fresh deployment before paper trades exist.
#
# These tests pin that invariant so a future refactor can't break it quietly.
# ══════════════════════════════════════════════════════════════════════════════

def _base_widgets() -> dict:
    """Minimal widget dict with every component at a stable mid-range value."""
    return {
        "portfolio_overview": {
            "net_pnl":        1000.0,
            "drawdown":       2.0,
            "win_rate":       55.0,
            "profit_factor":  1.5,
        },
        "ai_health": {"health_score": 70.0},
        "strategy_overview": {
            "overall_win_rate": 55.0,
            "total_net_pnl":    1000.0,
            "strong_buy_count": 2,
        },
        "execution_quality": {"execution_score": 70.0},
        "portfolio_risk": {
            "alert_count":       0,
            "kill_switch_active": False,
            "utilisation":       30.0,
        },
        "system_health": {
            "application_health": "HEALTHY",
            "database_status":    "CONNECTED",
            "api_status":         "HEALTHY",
            "scheduler_health":   "HEALTHY",
        },
    }


class TestPaperAnalyticsNeutralFallback(unittest.TestCase):
    """
    Regression guard: disabled / unavailable paper_analytics must yield a
    50.0 component score in compute_executive_score(), never 0.0.
    """

    # ── 1. available=False → component is exactly 50.0 ───────────────────────

    def test_available_false_uses_neutral_fifty(self):
        """available=False → compute_executive_score uses paper_analytics=50.0."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": False, "analytics_score": 0.0}
        score = compute_executive_score(widgets)
        self.assertAlmostEqual(score.paper_analytics, 50.0, places=1)

    def test_available_false_with_status_disabled(self):
        """{available: False, status: 'DISABLED'} → neutral 50.0."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": False, "status": "DISABLED"}
        score = compute_executive_score(widgets)
        self.assertAlmostEqual(score.paper_analytics, 50.0, places=1)

    def test_missing_paper_analytics_key_uses_neutral_fifty(self):
        """Missing paper_analytics key in widgets dict → neutral 50.0 (not 0.0)."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        # Deliberately omit paper_analytics to simulate an old engine that
        # hasn't wired the key yet.
        widgets.pop("paper_analytics", None)
        score = compute_executive_score(widgets)
        self.assertAlmostEqual(score.paper_analytics, 50.0, places=1)

    def test_paper_analytics_none_uses_neutral_fifty(self):
        """paper_analytics mapped to None → neutral 50.0 (not crash or 0.0)."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = None  # type: ignore[assignment]
        # The engine calls .get() on the value so None triggers the disabled path.
        score = compute_executive_score(widgets)
        self.assertAlmostEqual(score.paper_analytics, 50.0, places=1)

    # ── 2. Total equivalence: disabled == explicit 50.0 ──────────────────────

    def test_disabled_total_equals_explicit_neutral_total(self):
        """
        The composite total with disabled paper_analytics must equal the total
        produced when paper_analytics=50.0 is passed directly to ExecutiveScore.
        """
        from executive_dashboard.layout import compute_executive_score
        from executive_dashboard.dashboard_models import ExecutiveScore, SCORE_WEIGHTS

        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": False, "status": "DISABLED"}

        score_disabled = compute_executive_score(widgets)

        # Manually construct an equivalent ExecutiveScore with paper_analytics=50.0
        score_explicit = ExecutiveScore(
            portfolio_health  = score_disabled.portfolio_health,
            ai_health         = score_disabled.ai_health,
            strategy_health   = score_disabled.strategy_health,
            execution_quality = score_disabled.execution_quality,
            risk              = score_disabled.risk,
            system_health     = score_disabled.system_health,
            paper_analytics   = 50.0,
        )

        self.assertAlmostEqual(score_disabled.total, score_explicit.total, places=1)

    def test_disabled_does_not_equal_zero_total(self):
        """
        The composite total with disabled paper_analytics must NOT equal the total
        produced when paper_analytics=0.0 — that would mean zero is being used.
        """
        from executive_dashboard.layout import compute_executive_score
        from executive_dashboard.dashboard_models import ExecutiveScore

        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": False, "status": "DISABLED"}

        score_disabled = compute_executive_score(widgets)

        score_if_zero = ExecutiveScore(
            portfolio_health  = score_disabled.portfolio_health,
            ai_health         = score_disabled.ai_health,
            strategy_health   = score_disabled.strategy_health,
            execution_quality = score_disabled.execution_quality,
            risk              = score_disabled.risk,
            system_health     = score_disabled.system_health,
            paper_analytics   = 0.0,
        )

        # The two totals must differ by the weight × 50 gap (≈ 5 points).
        self.assertNotAlmostEqual(score_disabled.total, score_if_zero.total, places=0)

    # ── 3. Enabled path still uses the real score ─────────────────────────────

    def test_available_true_uses_actual_analytics_score(self):
        """available=True → compute_executive_score uses analytics_score, not 50.0."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": True, "analytics_score": 85.0}
        score = compute_executive_score(widgets)
        self.assertAlmostEqual(score.paper_analytics, 85.0, places=1)

    def test_enabled_low_score_differs_from_neutral(self):
        """An enabled but poor analytics score (20) is below neutral (50) in the total."""
        from executive_dashboard.layout import compute_executive_score
        widgets_neutral = _base_widgets()
        widgets_neutral["paper_analytics"] = {"available": False}

        widgets_poor = _base_widgets()
        widgets_poor["paper_analytics"] = {"available": True, "analytics_score": 20.0}

        score_neutral = compute_executive_score(widgets_neutral)
        score_poor    = compute_executive_score(widgets_poor)

        self.assertGreater(score_neutral.total, score_poor.total)

    def test_enabled_high_score_exceeds_neutral(self):
        """An enabled and excellent analytics score (95) is above neutral (50) in the total."""
        from executive_dashboard.layout import compute_executive_score
        widgets_neutral = _base_widgets()
        widgets_neutral["paper_analytics"] = {"available": False}

        widgets_great = _base_widgets()
        widgets_great["paper_analytics"] = {"available": True, "analytics_score": 95.0}

        score_neutral = compute_executive_score(widgets_neutral)
        score_great   = compute_executive_score(widgets_great)

        self.assertGreater(score_great.total, score_neutral.total)

    # ── 4. Clamping guard ─────────────────────────────────────────────────────

    def test_analytics_score_above_100_clamped(self):
        """analytics_score > 100 is clamped to 100.0 — not passed through raw."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": True, "analytics_score": 999.0}
        score = compute_executive_score(widgets)
        self.assertLessEqual(score.paper_analytics, 100.0)

    def test_analytics_score_below_zero_clamped(self):
        """analytics_score < 0 is clamped to 0.0 — not passed through raw."""
        from executive_dashboard.layout import compute_executive_score
        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": True, "analytics_score": -50.0}
        score = compute_executive_score(widgets)
        self.assertGreaterEqual(score.paper_analytics, 0.0)

    # ── 5. ImportError at startup → neutral 50.0 throughout the pipeline ─────

    def test_import_error_in_load_paper_analytics_yields_enabled_status(self):
        """
        When _load_paper_analytics() catches an ImportError at startup it returns
        {"available": False, "error": "..."}. This test simulates that result
        propagating through the full pipeline and confirms get_executive_summary()
        still returns status="ENABLED", not "ERROR".

        shared_services.load_all is patched (not dashboard_engine.load_all) because
        shared_services.py binds `load_all` at import time via
        `from .dashboard_engine import load_all`, so patching the engine alone
        would not affect the already-bound name.
        """
        import_error_pa = {
            "available": False,
            "error": "No module named 'paper_analytics.shared_services'",
        }
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   import_error_pa,
        }
        os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = "true"
        try:
            with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
                from executive_dashboard.shared_services import get_executive_summary
                r = get_executive_summary()
        finally:
            os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)

        self.assertEqual(r.get("status"), "ENABLED",
                         f"Expected status=ENABLED, got: {r.get('status')} error={r.get('error')}")

    def test_import_error_in_load_paper_analytics_widget_is_disabled(self):
        """
        The paper_analytics widget built from the ImportError result must have
        available=False and disabled=True — it must never surface a partial or
        incorrect widget to the frontend.
        """
        import_error_pa = {
            "available": False,
            "error": "No module named 'paper_analytics.shared_services'",
        }
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   import_error_pa,
        }
        os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = "true"
        try:
            with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
                from executive_dashboard.shared_services import get_executive_summary
                r = get_executive_summary()
        finally:
            os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)

        pa_widget = r.get("paper_analytics", {})
        self.assertFalse(pa_widget.get("available"),
                         "paper_analytics widget must have available=False after ImportError")
        self.assertTrue(pa_widget.get("disabled"),
                        "paper_analytics widget must have disabled=True after ImportError")

    def test_import_error_in_load_paper_analytics_score_component_is_neutral(self):
        """
        The executive_score.components["paper_analytics"] must be 50.0 (the
        neutral fallback) when _load_paper_analytics returns the ImportError
        error dict — never 0.0, which would silently penalise the operator's
        score on any deployment where the paper_analytics module is not yet
        initialised.
        """
        import_error_pa = {
            "available": False,
            "error": "No module named 'paper_analytics.shared_services'",
        }
        full_data = {
            "strategy":          _make_strategy_data(),
            "ai":                _make_ai_data(),
            "execution_quality": _make_eq_data(),
            "portfolio":         _make_portfolio_data(),
            "preopen":           _make_preopen_data(),
            "risk":              _make_risk_data(),
            "signals":           {"available": True, "status": {}, "summary": {}},
            "system":            _make_system_data(),
            "readiness":         {"available": True, "readiness_score": 80.0, "grade": "B",
                                  "verdict": "READY", "verdict_short": "GO"},
            "paper_analytics":   import_error_pa,
        }
        os.environ["EXECUTIVE_DASHBOARD_ENABLED"] = "true"
        try:
            with patch("executive_dashboard.shared_services.load_all", return_value=full_data):
                from executive_dashboard.shared_services import get_executive_summary
                r = get_executive_summary()
        finally:
            os.environ.pop("EXECUTIVE_DASHBOARD_ENABLED", None)

        components = r.get("executive_score", {}).get("components", {})
        self.assertIn("paper_analytics", components,
                      "executive_score.components must contain paper_analytics key")
        self.assertAlmostEqual(
            components["paper_analytics"], 50.0, places=1,
            msg=(
                f"paper_analytics component must be 50.0 (neutral) after ImportError, "
                f"got {components.get('paper_analytics')}"
            ),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Paper Analytics score impact on Executive Score composite — regression guard
#
# These tests verify that the 10% weight produces a proportionally correct
# change in the composite total when paper_analytics.analytics_score moves —
# e.g. from poor (20) to excellent (90) mid-session.
# ══════════════════════════════════════════════════════════════════════════════

class TestPaperAnalyticsScoreImpact(unittest.TestCase):
    """
    Verifies compute_executive_score() total changes proportionally when the
    paper_analytics analytics_score improves or declines.

    Key invariant: the weight of paper_analytics is 0.10 (10%), so a change of
    Δ points in analytics_score should produce Δ × 0.10 change in the composite
    total (±0.5 for rounding).
    """

    # ── 1. Core proportionality: 20 → 90 delta ────────────────────────────────

    def test_score_delta_poor_to_excellent_matches_weight(self):
        """
        analytics_score 20 → 90: total delta ≈ (90-20) × 0.10 = 7.0 points.
        Verifies the 10% weight is applied, not ignored or doubled.
        """
        from executive_dashboard.layout import compute_executive_score
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS

        widgets_poor = _base_widgets()
        widgets_poor["paper_analytics"] = {"available": True, "analytics_score": 20.0}

        widgets_great = _base_widgets()
        widgets_great["paper_analytics"] = {"available": True, "analytics_score": 90.0}

        score_poor  = compute_executive_score(widgets_poor)
        score_great = compute_executive_score(widgets_great)

        expected_delta = (90.0 - 20.0) * SCORE_WEIGHTS["paper_analytics"]  # = 7.0
        actual_delta   = score_great.total - score_poor.total
        self.assertAlmostEqual(actual_delta, expected_delta, delta=0.5,
                               msg=f"Expected delta ≈{expected_delta:.1f}, got {actual_delta:.1f}")

    def test_excellent_score_higher_than_poor(self):
        """analytics_score=90 produces a strictly higher composite than score=20."""
        from executive_dashboard.layout import compute_executive_score

        widgets_poor = _base_widgets()
        widgets_poor["paper_analytics"] = {"available": True, "analytics_score": 20.0}

        widgets_great = _base_widgets()
        widgets_great["paper_analytics"] = {"available": True, "analytics_score": 90.0}

        self.assertGreater(
            compute_executive_score(widgets_great).total,
            compute_executive_score(widgets_poor).total,
        )

    # ── 2. Full range: 0 → 100 delta ─────────────────────────────────────────

    def test_full_range_delta_is_ten_points(self):
        """
        analytics_score 0 → 100: total delta ≈ 100 × 0.10 = 10.0 points.
        This is the maximum possible contribution of paper_analytics.
        """
        from executive_dashboard.layout import compute_executive_score
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS

        widgets_zero = _base_widgets()
        widgets_zero["paper_analytics"] = {"available": True, "analytics_score": 0.0}

        widgets_max = _base_widgets()
        widgets_max["paper_analytics"] = {"available": True, "analytics_score": 100.0}

        score_zero = compute_executive_score(widgets_zero)
        score_max  = compute_executive_score(widgets_max)

        expected_delta = 100.0 * SCORE_WEIGHTS["paper_analytics"]  # = 10.0
        actual_delta   = score_max.total - score_zero.total
        self.assertAlmostEqual(actual_delta, expected_delta, delta=0.5,
                               msg=f"Expected delta ≈{expected_delta:.1f}, got {actual_delta:.1f}")

    # ── 3. Only paper_analytics changed — other components untouched ──────────

    def test_other_components_unchanged_when_paper_analytics_moves(self):
        """
        Moving analytics_score does not affect any other component score.
        portfolio_health, ai_health, etc. must be identical in both payloads.
        """
        from executive_dashboard.layout import compute_executive_score

        widgets_poor = _base_widgets()
        widgets_poor["paper_analytics"] = {"available": True, "analytics_score": 20.0}

        widgets_great = _base_widgets()
        widgets_great["paper_analytics"] = {"available": True, "analytics_score": 90.0}

        score_poor  = compute_executive_score(widgets_poor)
        score_great = compute_executive_score(widgets_great)

        for attr in ("portfolio_health", "ai_health", "strategy_health",
                     "execution_quality", "risk", "system_health"):
            self.assertAlmostEqual(
                getattr(score_poor, attr), getattr(score_great, attr), places=1,
                msg=f"{attr} should be identical in both payloads",
            )

    # ── 4. Neutral → excellent: delta ≈ 5 points ─────────────────────────────

    def test_neutral_to_excellent_delta_matches_weight(self):
        """
        disabled (neutral 50) → enabled excellent (score=100):
        delta ≈ (100-50) × 0.10 = 5.0 points.
        """
        from executive_dashboard.layout import compute_executive_score
        from executive_dashboard.dashboard_models import SCORE_WEIGHTS

        widgets_neutral = _base_widgets()
        widgets_neutral["paper_analytics"] = {"available": False}

        widgets_excellent = _base_widgets()
        widgets_excellent["paper_analytics"] = {"available": True, "analytics_score": 100.0}

        score_neutral   = compute_executive_score(widgets_neutral)
        score_excellent = compute_executive_score(widgets_excellent)

        expected_delta = (100.0 - 50.0) * SCORE_WEIGHTS["paper_analytics"]  # = 5.0
        actual_delta   = score_excellent.total - score_neutral.total
        self.assertAlmostEqual(actual_delta, expected_delta, delta=0.5,
                               msg=f"Expected delta ≈{expected_delta:.1f}, got {actual_delta:.1f}")

    # ── 5. Monotonicity: score goes up as analytics_score improves ────────────

    def test_total_increases_monotonically_as_analytics_improves(self):
        """
        As analytics_score increases from 0 to 100 in steps of 20, the
        composite total must strictly increase each time (monotonic).
        """
        from executive_dashboard.layout import compute_executive_score

        previous_total = None
        for pa_score in (0, 20, 40, 60, 80, 100):
            widgets = _base_widgets()
            widgets["paper_analytics"] = {"available": True, "analytics_score": float(pa_score)}
            total = compute_executive_score(widgets).total
            if previous_total is not None:
                self.assertGreater(
                    total, previous_total,
                    msg=f"Total should increase: pa={pa_score}, total={total} <= prev={previous_total}",
                )
            previous_total = total

    # ── 6. Regression: component value recorded in to_dict() ─────────────────

    def test_paper_analytics_component_reflected_in_to_dict(self):
        """The paper_analytics component score exposed via to_dict() matches input."""
        from executive_dashboard.layout import compute_executive_score

        widgets = _base_widgets()
        widgets["paper_analytics"] = {"available": True, "analytics_score": 73.0}

        score = compute_executive_score(widgets)
        d = score.to_dict()

        self.assertAlmostEqual(
            d["components"]["paper_analytics"], 73.0, places=1,
            msg="to_dict() paper_analytics component should match input score",
        )


# ---------------------------------------------------------------------------
# Test: None-safe numeric coercion in widget functions (Task #407)
# ---------------------------------------------------------------------------

class TestNoneNumericFieldsInWidgets(unittest.TestCase):
    """
    Regression guard: each widget function must not raise TypeError when
    every numeric field in the upstream dict is explicitly set to None
    (i.e. the key exists but carries a None value — dict.get returns None,
    not the fallback default).

    Confirms _sf coercion is wired for all focus-area numeric reads.
    """

    # ── widget_portfolio_overview ─────────────────────────────────────────

    def test_portfolio_overview_all_numerics_none(self):
        from executive_dashboard.widgets import widget_portfolio_overview
        data = {
            "portfolio": {
                "summary": {
                    "total_portfolio_value": None,
                    "today_pnl":             None,
                    "total_net_pnl":         None,
                    "cash_available":        None,
                    "invested_capital":      None,
                    "win_rate_pct":          None,
                    "profit_factor":         None,
                    "max_drawdown_pct":      None,
                    "current_drawdown_pct":  None,
                    "total_return_pct":      None,
                    "portfolio_utilisation_pct": None,
                    "initial_capital":       None,
                },
                "portfolio": {"position_count": None},
            }
        }
        # Must not raise; all numerics fall back to 0.0 / 0
        r = widget_portfolio_overview(data)
        self.assertIsInstance(r, dict)
        for field in ("net_pnl", "win_rate", "profit_factor", "drawdown"):
            self.assertEqual(r[field], 0.0, f"{field} should be 0.0 when None")
        self.assertEqual(r["open_positions"], 0)
        # Values must be numeric, not None
        for field in ("portfolio_value", "today_pnl", "net_pnl", "cash_available",
                      "invested_capital", "win_rate", "profit_factor", "drawdown",
                      "current_drawdown", "total_return_pct", "portfolio_utilisation_pct"):
            self.assertIsNotNone(r[field], f"{field} must not be None")
            self.assertIsInstance(r[field], (int, float), f"{field} must be numeric")

    # ── widget_strategy_overview ──────────────────────────────────────────

    def test_strategy_overview_all_numerics_none(self):
        from executive_dashboard.widgets import widget_strategy_overview
        data = {
            "strategy": {
                "snapshot": {
                    "total_strategies":  None,
                    "best_strategy":     "MACD",
                    "best_regime":       "BULL",
                    "best_sector":       "IT",
                    "total_net_pnl":     None,
                    "overall_win_rate":  None,
                },
                "criterion": {},
                "recs": [],
            }
        }
        # Must not raise
        r = widget_strategy_overview(data)
        self.assertIsInstance(r, dict)
        self.assertEqual(r["total_strategies"],  0)
        self.assertEqual(r["total_net_pnl"],    0.0)
        self.assertEqual(r["overall_win_rate"], 0.0)
        self.assertEqual(r["strong_buy_count"], 0)
        self.assertIsInstance(r["total_strategies"], int)
        self.assertIsInstance(r["total_net_pnl"],    float)
        self.assertIsInstance(r["overall_win_rate"], float)

    # ── widget_portfolio_risk ─────────────────────────────────────────────

    def test_portfolio_risk_all_numerics_none(self):
        from executive_dashboard.widgets import widget_portfolio_risk
        data = {
            "risk": {
                "risk": {
                    "sector_allocation":     [],
                    "diversification_score": None,
                    "portfolio_heat":        None,
                    "kill_switch":           {"active": False},
                    "utilization_pct":       None,
                    "largest_position_pct":  None,
                    "daily_risk":            None,
                },
                "alerts": {"alerts": []},
            }
        }
        # Must not raise
        r = widget_portfolio_risk(data)
        self.assertIsInstance(r, dict)
        self.assertEqual(r["utilisation"],           0.0)
        self.assertEqual(r["alert_count"],           0)
        self.assertEqual(r["diversification_score"], 0.0)
        self.assertEqual(r["portfolio_heat"],        0.0)
        # All returned numerics must be numeric, not None
        for field in ("utilisation", "largest_position", "maximum_risk",
                      "sector_concentration", "diversification_score", "portfolio_heat"):
            self.assertIsNotNone(r[field], f"{field} must not be None")
            self.assertIsInstance(r[field], (int, float), f"{field} must be numeric")

    def test_portfolio_risk_utilisation_falls_back_to_portfolio_heat(self):
        """When utilization_pct is absent, utilisation falls back to portfolio_heat."""
        from executive_dashboard.widgets import widget_portfolio_risk
        data = {
            "risk": {
                "risk": {
                    "sector_allocation": [],
                    "portfolio_heat":    42.0,
                    "kill_switch":       {"active": False},
                    # utilization_pct omitted entirely
                },
                "alerts": {"alerts": []},
            }
        }
        r = widget_portfolio_risk(data)
        self.assertAlmostEqual(r["utilisation"], 42.0)

    def test_portfolio_risk_utilisation_non_numeric_falls_back(self):
        """Non-numeric utilization_pct (e.g. a string) must not raise and must fall back."""
        from executive_dashboard.widgets import widget_portfolio_risk
        data = {
            "risk": {
                "risk": {
                    "sector_allocation": [],
                    "portfolio_heat":    15.0,
                    "kill_switch":       {"active": False},
                    "utilization_pct":   "bad-value",   # non-numeric string
                },
                "alerts": {"alerts": []},
            }
        }
        # Must not raise ValueError/TypeError
        r = widget_portfolio_risk(data)
        # Falls back to portfolio_heat
        self.assertAlmostEqual(r["utilisation"], 15.0)
        self.assertIsInstance(r["utilisation"], float)

    # ── widget_execution_quality ──────────────────────────────────────────

    def test_execution_quality_all_numerics_none(self):
        from executive_dashboard.widgets import widget_execution_quality
        data = {
            "execution_quality": {
                "avg_execution_score":      None,
                "avg_entry_slippage_pct":   None,
                "avg_fill_delay_seconds":   None,
                "total_trades":             None,
                "best_execution_score":     None,
                "worst_execution_score":    None,
                "avg_exit_slippage_pct":    None,
            }
        }
        # Must not raise
        r = widget_execution_quality(data)
        self.assertIsInstance(r, dict)
        self.assertEqual(r["execution_score"], 0.0)
        self.assertEqual(r["total_trades"],    0)
        for field in ("execution_score", "avg_slippage", "avg_fill_delay",
                      "best_execution", "worst_execution", "exit_slippage"):
            self.assertIsNotNone(r[field], f"{field} must not be None")
            self.assertIsInstance(r[field], (int, float), f"{field} must be numeric")

    # ── widget_ai_health calibration_quality arithmetic ───────────────────

    def test_ai_health_calibration_ece_none_key_present(self):
        """calibration_quality must be None when calibration_ece key exists but is None.

        Regression guard: before the fix, _sf(snap, 'calibration_ece', 0.0) silently
        fell back to 0.0, making (1 - 0.0) * 100 = 100.0 — a misleading perfect score
        for a model that has never been calibration-evaluated.
        """
        from executive_dashboard.widgets import widget_ai_health
        data = {
            "ai": {
                "snapshot": {
                    "health_score": 75.0,
                    "calibration_ece": None,   # key present, value None
                },
                "components": {},
                "learning": {},
            }
        }
        r = widget_ai_health(data)
        self.assertIsInstance(r, dict)
        # calibration_ece=None (never evaluated) → quality must be None, NOT 100.0
        self.assertIsNone(
            r["calibration_quality"],
            "calibration_quality must be None when ECE was never measured, not 100.0",
        )

    def test_ai_health_calibration_ece_key_absent(self):
        """calibration_quality must be None when calibration_ece key is entirely absent."""
        from executive_dashboard.widgets import widget_ai_health
        data = {
            "ai": {
                "snapshot": {"health_score": 70.0},  # no calibration_ece key at all
                "components": {},
                "learning": {},
            }
        }
        r = widget_ai_health(data)
        self.assertIsNone(
            r["calibration_quality"],
            "calibration_quality must be None when calibration_ece key is absent",
        )
        # calibration_ece itself should also be None (not 0.0)
        self.assertIsNone(r["calibration_ece"])

    def test_ai_health_calibration_ece_measured_value(self):
        """calibration_quality is correctly derived when ECE has a real measurement."""
        from executive_dashboard.widgets import widget_ai_health
        data = {
            "ai": {
                "snapshot": {
                    "health_score": 82.0,
                    "calibration_ece": 0.05,   # measured: 5% error
                },
                "components": {},
                "learning": {},
            }
        }
        r = widget_ai_health(data)
        # (1 - 0.05) * 100 = 95.0
        self.assertIsNotNone(r["calibration_quality"])
        self.assertAlmostEqual(r["calibration_quality"], 95.0, places=1)

    def test_ai_health_calibration_ece_zero_measured(self):
        """ECE=0.0 that was actually measured must yield quality=100.0, not None."""
        from executive_dashboard.widgets import widget_ai_health
        data = {
            "ai": {
                "snapshot": {
                    "health_score": 90.0,
                    "calibration_ece": 0.0,   # measured perfect calibration
                },
                "components": {},
                "learning": {},
            }
        }
        r = widget_ai_health(data)
        # key is present and value is 0.0 — this IS a measurement, so quality=100.0
        self.assertIsNotNone(r["calibration_quality"])
        self.assertAlmostEqual(r["calibration_quality"], 100.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# widget_preopen — None numeric fields (Task #408)
# ══════════════════════════════════════════════════════════════════════════════

class TestPreopenNoneNumericFields(unittest.TestCase):
    """
    Guard: widget_preopen() must never raise TypeError when numeric fields
    (gap_pct, symbols_analysed, highest_exec_qty) are present in the upstream
    snapshot but carry a None value instead of a number.
    """

    def _run(self, status_overrides=None, symbol_overrides=None, ranks_overrides=None) -> dict:
        from executive_dashboard.widgets import widget_preopen
        symbol = {
            "symbol": "INFY",
            "gap_pct": 2.1,
            "imbalance_type": "BUY",
        }
        if symbol_overrides:
            symbol.update(symbol_overrides)
        ranks = {
            "top_symbols": [symbol],
            "highest_exec_qty": 5000,
        }
        if ranks_overrides:
            ranks.update(ranks_overrides)
        status = {
            "provider_label": "NSE Official",
            "last_updated": "09:00",
            "symbols_analysed": 45,
            "trading_date": "2026-08-06",
        }
        if status_overrides:
            status.update(status_overrides)
        data = {"preopen": {
            "available": True,
            "status": status,
            "rankings": ranks,
            "sectors": {"leading_sector": "IT"},
        }}
        return widget_preopen(data)

    def test_gap_pct_none_no_type_error(self):
        """gap_pct=None must not raise TypeError during > / < comparison."""
        r = self._run(symbol_overrides={"gap_pct": None})
        self.assertIsInstance(r, dict)

    def test_gap_pct_none_top_gap_up_pct_is_zero(self):
        """When the only symbol has gap_pct=None it is treated as 0.0, so no gap-up is found."""
        r = self._run(symbol_overrides={"gap_pct": None})
        self.assertIsInstance(r["top_gap_up_pct"], float)
        # Symbol with gap_pct=None is filtered out; top_gap_up falls back to empty dict → 0.0
        self.assertAlmostEqual(r["top_gap_up_pct"], 0.0)

    def test_gap_pct_none_top_gap_down_pct_is_zero(self):
        r = self._run(symbol_overrides={"gap_pct": None})
        self.assertIsInstance(r["top_gap_down_pct"], float)
        self.assertAlmostEqual(r["top_gap_down_pct"], 0.0)

    def test_symbols_analysed_none_returns_float_zero(self):
        """symbols_analysed=None (key present) must yield 0.0, not None."""
        r = self._run(status_overrides={"symbols_analysed": None})
        self.assertIsNotNone(r["symbols_analysed"])
        self.assertIsInstance(r["symbols_analysed"], float)
        self.assertAlmostEqual(r["symbols_analysed"], 0.0)

    def test_highest_exec_qty_none_returns_float_zero(self):
        """highest_exec_qty=None (key present) must yield 0.0, not None."""
        r = self._run(ranks_overrides={"highest_exec_qty": None})
        self.assertIsNotNone(r["highest_exec_qty"])
        self.assertIsInstance(r["highest_exec_qty"], float)
        self.assertAlmostEqual(r["highest_exec_qty"], 0.0)

    def test_all_three_none_no_crash(self):
        """All three numeric fields None simultaneously must not crash."""
        r = self._run(
            status_overrides={"symbols_analysed": None},
            symbol_overrides={"gap_pct": None},
            ranks_overrides={"highest_exec_qty": None},
        )
        self.assertIsInstance(r, dict)
        self.assertAlmostEqual(r["top_gap_up_pct"],   0.0)
        self.assertAlmostEqual(r["top_gap_down_pct"],  0.0)
        self.assertAlmostEqual(r["symbols_analysed"],  0.0)
        self.assertAlmostEqual(r["highest_exec_qty"],  0.0)

    def test_normal_gap_pct_still_works(self):
        """Regression: positive gap_pct must still be found correctly after the fix."""
        r = self._run()
        self.assertAlmostEqual(r["top_gap_up_pct"], 2.1)
        self.assertEqual(r["top_gap_up"], "INFY")


# ══════════════════════════════════════════════════════════════════════════════
# widget_readiness — None readiness_score (Task #408)
# ══════════════════════════════════════════════════════════════════════════════

class TestReadinessNoneScore(unittest.TestCase):
    """
    Guard: widget_readiness() must return readiness_score=0.0 when the
    upstream snapshot delivers readiness_score=None (key present, value None),
    rather than propagating None into downstream arithmetic.
    """

    def _run(self, overrides: dict) -> dict:
        from executive_dashboard.widgets import widget_readiness
        base = {
            "available": True,
            "readiness_score": 75.0,
            "grade": "B",
            "verdict": "READY",
            "verdict_short": "GO",
        }
        base.update(overrides)
        return widget_readiness({"readiness": base})

    def test_readiness_score_none_returns_zero(self):
        """readiness_score=None (key present) must yield 0.0, not None."""
        r = self._run({"readiness_score": None})
        self.assertIsNotNone(r["readiness_score"])
        self.assertIsInstance(r["readiness_score"], float)
        self.assertAlmostEqual(r["readiness_score"], 0.0)

    def test_readiness_score_none_no_type_error(self):
        """widget_readiness must not raise any exception when readiness_score is None."""
        try:
            r = self._run({"readiness_score": None})
        except TypeError as exc:
            self.fail(f"widget_readiness raised TypeError: {exc}")

    def test_readiness_score_normal_passes_through(self):
        """Regression: a valid float score must still pass through unchanged."""
        r = self._run({"readiness_score": 84.5})
        self.assertAlmostEqual(r["readiness_score"], 84.5)

    def test_readiness_score_zero_explicit_is_zero(self):
        """Explicit 0.0 must not be replaced by a different default."""
        r = self._run({"readiness_score": 0.0})
        self.assertAlmostEqual(r["readiness_score"], 0.0)

    def test_readiness_available_preserved_when_score_is_none(self):
        """available must remain True even when score is None."""
        r = self._run({"readiness_score": None})
        self.assertTrue(r["available"])
        self.assertFalse(r["disabled"])


if __name__ == "__main__":
    unittest.main()
