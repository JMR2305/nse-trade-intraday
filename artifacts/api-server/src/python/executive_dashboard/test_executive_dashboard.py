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


if __name__ == "__main__":
    unittest.main()
