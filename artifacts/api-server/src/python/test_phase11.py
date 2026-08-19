"""
test_phase11.py — Phase 11 Autonomous Paper Trading Platform Tests
Tests capital modes, portfolio, recommendation queue, timeline, calendar,
replay, reports, AI performance, and learning.

Run: python -m pytest test_phase11.py -v
PAPER ONLY — no live orders, no real money.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_STATE = {
    "cash": 35_000.0,
    "positions": {
        "RELIANCE": {
            "qty": 5,
            "avg_price": 2800.0,
            "current_price": 2870.0,
            "stop_loss": 2720.0,
            "target": 2980.0,
            "strategy": "BREAKOUT",
            "confidence": 78.0,
            "risk_level": "MEDIUM",
            "buy_ts": "2025-08-01T04:25:00Z",
        },
        "INFY": {
            "qty": 10,
            "avg_price": 1500.0,
            "current_price": 1480.0,
            "stop_loss": 1450.0,
            "target": 1600.0,
            "strategy": "MOMENTUM",
            "confidence": 65.0,
            "risk_level": "LOW",
            "buy_ts": "2025-08-01T05:30:00Z",
        },
    },
    "trades": [
        {
            "symbol": "TCS", "action": "BUY", "quantity": 5,
            "price": 3500.0, "pnl": 0,
            "buy_ts": "2025-08-01T04:20:00Z",
            "trade_ts": "2025-08-01T04:20:00Z",
            "strategy": "BREAKOUT", "confidence": 80.0,
        },
        {
            "symbol": "TCS", "action": "SELL", "quantity": 5,
            "price": 3620.0, "pnl": 600.0,
            "buy_ts": "2025-08-01T04:20:00Z",
            "trade_ts": "2025-08-01T08:30:00Z",
            "strategy": "BREAKOUT", "confidence": 80.0,
            "entry_price": 3500.0, "exit_reason": "TARGET_HIT",
        },
        {
            "symbol": "WIPRO", "action": "SELL", "quantity": 20,
            "price": 450.0, "pnl": -300.0,
            "buy_ts": "2025-08-01T05:00:00Z",
            "trade_ts": "2025-08-01T09:00:00Z",
            "strategy": "MOMENTUM", "confidence": 55.0,
            "entry_price": 465.0, "exit_reason": "STOP_LOSS",
        },
    ],
    "pnl_history": [
        {"value": 51_000.0}, {"value": 52_500.0}, {"value": 50_800.0},
    ],
    "daily_pnl": 300.0,
}

SAMPLE_KV: dict = {}


def _kv_get_mock(key, default=None):
    return SAMPLE_KV.get(key, default)


def _kv_set_mock(key, value):
    SAMPLE_KV[key] = value


# ── Test: Capital Config ──────────────────────────────────────────────────────

class TestCapitalConfig(unittest.TestCase):
    def setUp(self):
        SAMPLE_KV.clear()

    @patch("phase11_autonomous.kv_get", side_effect=_kv_get_mock)
    @patch("phase11_autonomous.kv_set", side_effect=_kv_set_mock)
    def _import_with_mocks(self, mock_set, mock_get):
        import importlib
        import phase11_autonomous as m
        importlib.reload(m)
        return m

    def test_get_capital_config_defaults(self):
        with patch("phase20_store.kv_get", side_effect=_kv_get_mock):
            import phase11_autonomous as m
            cfg = m.get_capital_config()
        self.assertEqual(cfg["mode"], "A")
        self.assertEqual(cfg["starting_capital"], m.PHASE11_DEFAULT_CAPITAL)
        self.assertIn("mode_label", cfg)
        self.assertTrue(cfg["paper_only"])
        self.assertTrue(cfg["advisory_only"])

    def test_get_capital_config_mode_b(self):
        SAMPLE_KV[("phase11_capital_mode")] = "B"
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            import phase11_autonomous as m
            cfg = m.get_capital_config()
        self.assertEqual(cfg["mode"], "B")
        self.assertIn("top-up", cfg["mode_label"].lower())

    def test_update_capital_config_mode(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            cfg = m.update_capital_config({"mode": "B"})
        self.assertEqual(SAMPLE_KV.get("phase11_capital_mode"), "B")

    def test_update_capital_config_bad_mode_raises(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            with self.assertRaises(ValueError):
                m.update_capital_config({"mode": "C"})

    def test_update_capital_config_low_capital_raises(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            with self.assertRaises(ValueError):
                m.update_capital_config({"starting_capital": 500})

    def test_update_capital_config_cannot_bypass_guarded_migration(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            with self.assertRaisesRegex(ValueError, "guarded"):
                m.update_capital_config({"starting_capital": 100_000.0})
        self.assertNotIn("phase11_starting_capital", SAMPLE_KV)

    def test_update_capital_config_cannot_change_topup_target(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            with self.assertRaisesRegex(ValueError, "topup_target.*guarded"):
                m.update_capital_config({"topup_target": 250_000.0})
        self.assertNotIn("phase11_topup_target", SAMPLE_KV)

    def test_guarded_capital_rejection_is_atomic_with_mode_patch(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            with self.assertRaisesRegex(ValueError, "guarded"):
                m.update_capital_config({
                    "mode": "B",
                    "starting_capital": 100_000.0,
                })
        self.assertNotIn("phase11_capital_mode", SAMPLE_KV)


# ── Test: Portfolio Summary ───────────────────────────────────────────────────

# Canonical (phase20 ledger) portfolio fixture matching SAMPLE_STATE semantics:
# invested = 5*2800 + 10*1500 = 29,000; unreal = 350 - 200 = 150; realized = 300
SAMPLE_CANON = {
    "source": "phase20_ledger",
    "scan_id": "scan-test",
    "portfolio_version": "4:2025-08-01T05:30:00Z",
    "initial_capital": 64_000.0,
    "cash": 35_000.0 + 300.0,  # cap − invested + realized
    "invested_value": 29_000.0,
    "equity": 64_000.0 + 300.0 + 150.0,
    "equity_complete": True,
    "realized_pnl": 300.0,
    "unrealized_pnl": 150.0,
    "unrealized_note": None,
    "open_position_count": 2,
    "closed_trade_count": 2,
    "positions": [
        {"trade_id": "T1", "symbol": "RELIANCE", "quantity": 5, "avg_price": 2800.0,
         "cost": 14_000.0, "mark_price": 2870.0, "mark_source": "scan",
         "market_value": 14_350.0, "unrealized_pnl": 350.0, "status": "OPEN",
         "sector": "ENERGY", "strategy_id": "BREAKOUT",
         "opened_at": "2025-08-01T04:25:00Z", "stop_loss": 2720.0, "target": 2980.0,
         "scan_id": "scan-test"},
        {"trade_id": "T2", "symbol": "INFY", "quantity": 10, "avg_price": 1500.0,
         "cost": 15_000.0, "mark_price": 1480.0, "mark_source": "scan",
         "market_value": 14_800.0, "unrealized_pnl": -200.0, "status": "OPEN",
         "sector": "IT", "strategy_id": "MOMENTUM",
         "opened_at": "2025-08-01T05:30:00Z", "stop_loss": 1450.0, "target": 1600.0,
         "scan_id": "scan-test"},
    ],
    "sector_exposure": {"IT": 15_000.0, "ENERGY": 14_000.0},
    "mark_basis": "scan",
}

EMPTY_CANON = {
    **SAMPLE_CANON,
    "cash": 64_000.0, "invested_value": 0.0, "equity": 64_000.0,
    "realized_pnl": 0.0, "unrealized_pnl": 0.0,
    "open_position_count": 0, "closed_trade_count": 0,
    "positions": [], "sector_exposure": {}, "portfolio_version": "0:",
}


class TestPortfolioSummary(unittest.TestCase):
    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_has_required_fields(self, mock_kv, mock_load, mock_canon):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        for field in [
            "starting_capital", "cash", "invested_amount", "buying_power",
            "current_value", "realised_pnl", "unrealised_pnl", "total_pnl",
            "portfolio_return", "daily_pnl", "daily_return", "drawdown_pct",
            "open_positions", "capital_mode", "paper_only", "advisory_only", "as_of",
        ]:
            self.assertIn(field, p, f"Missing field: {field}")

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_values_correct(self, mock_kv, mock_load, mock_canon):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertEqual(p["cash"], 35_300.0)
        self.assertEqual(p["open_positions"], 2)
        # invested = 5*2800 + 10*1500 = 14000+15000=29000
        self.assertAlmostEqual(p["invested_amount"], 29_000.0, places=0)
        # unrealised = 5*(2870-2800) + 10*(1480-1500) = 350 - 200 = 150
        self.assertAlmostEqual(p["unrealised_pnl"], 150.0, places=0)

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_realised_pnl_from_sells(self, mock_kv, mock_load, mock_canon):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        # TCS SELL pnl=600, WIPRO SELL pnl=-300 → total 300
        self.assertAlmostEqual(p["realised_pnl"], 300.0, places=0)

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_paper_only_flags(self, mock_kv, mock_load, mock_canon):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertTrue(p["paper_only"])
        self.assertTrue(p["advisory_only"])

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=EMPTY_CANON)
    @patch("portfolio_store.load_state", return_value={})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_empty_state(self, mock_kv, mock_load, mock_canon):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertGreaterEqual(p["cash"], 0)
        self.assertEqual(p["open_positions"], 0)


# ── Test: Open Positions Detail ───────────────────────────────────────────────

class TestOpenPositions(unittest.TestCase):
    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_has_required_fields(self, mock_kv, mock_load, mock_regime, mock_canon):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        self.assertEqual(len(positions), 2)
        required = [
            "stock", "buy_time", "buy_price", "current_price", "quantity",
            "current_value", "current_pnl", "current_pnl_pct", "ai_confidence",
            "target", "stop_loss", "strategy", "market_regime", "risk_level",
            "holding_label",
        ]
        for pos in positions:
            for f in required:
                self.assertIn(f, pos, f"Missing field {f} in position")

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_pnl_values(self, mock_kv, mock_load, mock_regime, mock_canon):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        reliance = next((p for p in positions if p["stock"] == "RELIANCE"), None)
        self.assertIsNotNone(reliance)
        # pnl = 5 * (2870 - 2800) = 350
        self.assertAlmostEqual(reliance["current_pnl"], 350.0, places=0)

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=EMPTY_CANON)
    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value={"positions": {}, "trades": []})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_empty(self, mock_kv, mock_load, mock_regime, mock_canon):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        self.assertEqual(positions, [])

    @patch("canonical_portfolio.build_canonical_portfolio", return_value=SAMPLE_CANON)
    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    @patch("phase20_executor.get_open_trades", return_value=[{
        "symbol": "RELIANCE",
        "trigger_source": "AUTO",
        "fill_model": "LAST_TRADED_PRICE",
        "evidence": {
            "quality_allocation_override": {
                "tier": "HIGH_QUALITY_2X",
                "reason": "HIGH_QUALITY_2X_APPROVED",
                "requested_multiplier": 2.0,
                "effective_multiplier": 1.8,
                "base_notional": 10_000.0,
                "final_notional": 18_000.0,
                "final_risk_amount": 1_200.0,
                "final_risk_pct": 1.2,
                "limiting_caps": ["sector"],
                "exposure_after": {
                    "stock_pct": 18.0,
                    "sector_pct": 40.0,
                    "portfolio_deployed_pct": 68.0,
                },
            }
        },
    }])
    def test_open_position_propagates_immutable_allocation_evidence(
        self, mock_trades, mock_kv, mock_load, mock_regime, mock_canon
    ):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        reliance = next(p for p in positions if p["stock"] == "RELIANCE")
        self.assertEqual(reliance["allocation_tier"], "HIGH_QUALITY_2X")
        self.assertEqual(reliance["allocation_effective_multiplier"], 1.8)
        self.assertEqual(reliance["allocation_final_notional"], 18_000.0)
        self.assertEqual(reliance["allocation_sector_exposure_pct"], 40.0)
        self.assertEqual(reliance["allocation_limiting_caps"], ["sector"])


# ── Test: Closed Positions Detail ─────────────────────────────────────────────

class TestClosedPositions(unittest.TestCase):
    @patch("phase11_autonomous._get_phase20_closed_trades", return_value=[])
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_closed_positions_has_required_fields(self, mock_load, mock_p20):
        import phase11_autonomous as m
        closed = m.get_closed_positions_detail()
        required = [
            "symbol", "buy_time", "sell_time", "entry_price", "exit_price",
            "quantity", "pnl", "pnl_pct", "holding_label", "exit_reason",
            "ai_confidence", "strategy", "lesson_learned",
        ]
        for pos in closed:
            for f in required:
                self.assertIn(f, pos, f"Missing field {f} in closed position")

    @patch("phase11_autonomous._get_phase20_closed_trades", return_value=[])
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_only_sell_actions_in_closed(self, mock_load, mock_p20):
        import phase11_autonomous as m
        closed = m.get_closed_positions_detail()
        for pos in closed:
            self.assertIn(pos["symbol"], ["TCS", "WIPRO"])

    @patch("phase11_autonomous._get_phase20_closed_trades", return_value=[])
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_loss_trade_has_lesson(self, mock_load, mock_p20):
        import phase11_autonomous as m
        closed = m.get_closed_positions_detail()
        wipro = next((c for c in closed if c["symbol"] == "WIPRO"), None)
        self.assertIsNotNone(wipro)
        self.assertTrue(len(wipro["lesson_learned"]) > 0)


# ── Test: Recommendation Queue ────────────────────────────────────────────────

class TestRecommendationQueue(unittest.TestCase):
    @patch("phase11_autonomous._get_ai_decision_recs", return_value=[
        {"symbol": "HDFC", "action": "BUY", "confidence": 82.0,
         "risk_level": "MEDIUM", "expected_return": 5.5,
         "estimated_holding": "2 days", "entry": 1700.0,
         "stop_loss": 1650.0, "target": 1800.0, "reasoning": "Breakout", "strategy": "BREAKOUT"},
        {"symbol": "ICICI", "action": "SELL", "confidence": 70.0,
         "risk_level": "HIGH", "expected_return": -2.0,
         "estimated_holding": "1 day", "entry": 950.0,
         "stop_loss": 980.0, "target": 920.0, "reasoning": "Reversal", "strategy": "REVERSAL"},
    ])
    def test_recommendation_queue_filters_buy_only(self, mock_recs):
        import phase11_autonomous as m
        result = m.get_recommendation_queue()
        self.assertIn("items", result)
        # Only BUY/STRONG BUY pass
        for item in result["items"]:
            self.assertIn(item["action"].upper().replace(" ", "_"),
                          ("BUY", "STRONG_BUY", "STRONG BUY"))

    @patch("phase11_autonomous._get_ai_decision_recs", return_value=[
        {"symbol": "HDFC", "action": "BUY", "confidence": 82.0,
         "risk_level": "MEDIUM", "expected_return": 5.5,
         "estimated_holding": "2 days", "entry": 1700.0,
         "stop_loss": 1650.0, "target": 1800.0, "reasoning": "Breakout", "strategy": "BREAKOUT"},
        {"symbol": "RELIANCE", "action": "STRONG BUY", "confidence": 91.0,
         "risk_level": "LOW", "expected_return": 7.0,
         "estimated_holding": "3 days", "entry": 2800.0,
         "stop_loss": 2720.0, "target": 3000.0, "reasoning": "Momentum", "strategy": "MOMENTUM"},
    ])
    def test_recommendation_queue_sorted_by_confidence(self, mock_recs):
        import phase11_autonomous as m
        result = m.get_recommendation_queue()
        items = result["items"]
        if len(items) >= 2:
            self.assertGreaterEqual(items[0]["confidence"], items[1]["confidence"])

    @patch("phase11_autonomous._get_ai_decision_recs", return_value=[])
    @patch("phase11_autonomous._get_scan_signal_recs", return_value=[])
    def test_recommendation_queue_empty(self, mock_scan, mock_ai):
        import phase11_autonomous as m
        result = m.get_recommendation_queue()
        self.assertEqual(result["count"], 0)
        self.assertTrue(result["paper_only"])

    def test_recommendation_queue_has_required_keys(self):
        import phase11_autonomous as m
        with patch("phase11_autonomous._get_ai_decision_recs", return_value=[]), \
             patch("phase11_autonomous._get_scan_signal_recs", return_value=[]):
            result = m.get_recommendation_queue()
        for key in ["items", "count", "advisory_only", "paper_only", "as_of"]:
            self.assertIn(key, result)

    def test_recommendation_merges_latest_real_allocation_preview(self):
        import phase11_autonomous as m

        def _kv_get(key, default=None):
            if key == "last_entry_evaluation":
                return {
                    "evaluated_at": "2026-08-19T04:00:05Z",
                    "scan_id": "scan-current",
                    "snapshot_ts": "2026-08-19T04:00:00Z",
                    "settings_config_hash": "cfg-current",
                    "candidates": [{
                        "symbol": "TCS",
                        "allocation_override_preview": {
                            "tier": "EXCEPTIONAL_QUALITY_3X",
                            "reason": "EXCEPTIONAL_QUALITY_3X_APPROVED",
                            "requested_multiplier": 3.0,
                            "effective_multiplier": 2.5,
                            "base_notional": 8_000.0,
                            "final_notional": 20_000.0,
                            "final_risk_amount": 1_600.0,
                            "final_risk_pct": 1.6,
                            "limiting_caps": ["per_stock"],
                            "exposure_after": {
                                "stock_pct": 25.0,
                                "sector_pct": 36.0,
                                "portfolio_deployed_pct": 72.0,
                            },
                        },
                    }]
                }
            return default

        with patch("phase11_autonomous._get_ai_decision_recs", return_value=[{
            "symbol": "TCS",
            "action": "STRONG BUY",
            "confidence": 92.0,
        }]), patch("phase20_store.kv_get", side_effect=_kv_get), \
             patch("phase20_store.get_settings",
                   return_value={"config_hash": "cfg-current"}), \
             patch("phase15_scan_context.build_scan_context",
                   return_value={
                       "is_today_session": True,
                       "scan_id": "scan-current",
                       "snapshot_ts": "2026-08-19T04:00:00Z",
                   }):
            result = m.get_recommendation_queue()

        item = result["items"][0]
        self.assertEqual(item["allocation_tier"], "EXCEPTIONAL_QUALITY_3X")
        self.assertEqual(item["allocation_effective_multiplier"], 2.5)
        self.assertEqual(item["allocation_final_notional"], 20_000.0)
        self.assertEqual(item["allocation_stock_exposure_pct"], 25.0)
        self.assertTrue(item["allocation_preview"])
        self.assertTrue(item["allocation_preview_not_executed"])
        self.assertEqual(item["allocation_scan_id"], "scan-current")

    def test_recommendation_does_not_merge_stale_allocation_preview(self):
        import phase11_autonomous as m

        stale_eval = {
            "evaluated_at": "2026-08-19T03:55:05Z",
            "scan_id": "scan-old",
            "snapshot_ts": "2026-08-19T03:55:00Z",
            "settings_config_hash": "cfg-current",
            "candidates": [{
                "symbol": "TCS",
                "allocation_override_preview": {
                    "tier": "EXCEPTIONAL_QUALITY_3X",
                    "effective_multiplier": 3.0,
                },
            }],
        }
        with patch(
            "phase11_autonomous._get_ai_decision_recs",
            return_value=[{
                "symbol": "TCS",
                "action": "STRONG BUY",
                "confidence": 92.0,
            }],
        ), patch(
            "phase20_store.kv_get",
            return_value=stale_eval,
        ), patch(
            "phase20_store.get_settings",
            return_value={"config_hash": "cfg-current"},
        ), patch(
            "phase15_scan_context.build_scan_context",
            return_value={
                "is_today_session": True,
                "scan_id": "scan-current",
                "snapshot_ts": "2026-08-19T04:00:00Z",
            },
        ):
            item = m.get_recommendation_queue()["items"][0]

        self.assertNotIn("allocation_tier", item)
        self.assertNotIn("allocation_preview", item)


# ── Test: Session Timeline ────────────────────────────────────────────────────

class TestSessionTimeline(unittest.TestCase):
    @patch("phase11_autonomous._notification_events", return_value=[])
    @patch("phase11_autonomous._trade_events", return_value=[])
    def test_timeline_has_milestones(self, mock_te, mock_ne):
        import phase11_autonomous as m
        result = m.get_session_timeline("2025-08-04")  # Monday
        events = result["events"]
        types = [e["type"] for e in events]
        self.assertIn("MARKET_OPEN", types)
        self.assertIn("SCAN", types)

    @patch("phase11_autonomous._notification_events", return_value=[])
    @patch("phase11_autonomous._trade_events", return_value=[])
    def test_timeline_weekend_has_no_market_milestones(self, mock_te, mock_ne):
        import phase11_autonomous as m
        result = m.get_session_timeline("2025-08-03")  # Sunday
        market_events = [e for e in result["events"] if e.get("category") == "MARKET"]
        self.assertEqual(len(market_events), 0)

    @patch("phase11_autonomous._notification_events", return_value=[])
    @patch("phase11_autonomous._trade_events", return_value=[
        {"ts": "2025-08-04T04:30:00Z", "type": "BUY", "label": "BUY HDFC @ ₹1700",
         "symbol": "HDFC", "price": 1700, "pnl": 0, "strategy": "BREAKOUT", "category": "TRADE"},
    ])
    def test_timeline_includes_trade_events(self, mock_te, mock_ne):
        import phase11_autonomous as m
        result = m.get_session_timeline("2025-08-04")
        trade_events = [e for e in result["events"] if e.get("category") == "TRADE"]
        self.assertGreater(len(trade_events), 0)

    @patch("phase11_autonomous._notification_events", return_value=[])
    @patch("phase11_autonomous._trade_events", return_value=[])
    def test_timeline_sorted_chronologically(self, mock_te, mock_ne):
        import phase11_autonomous as m
        result = m.get_session_timeline("2025-08-04")
        events = result["events"]
        tss = [e["ts"] for e in events if e.get("ts")]
        self.assertEqual(tss, sorted(tss))

    @patch("phase11_autonomous._notification_events", return_value=[])
    @patch("phase11_autonomous._trade_events", return_value=[])
    def test_timeline_has_required_fields(self, mock_te, mock_ne):
        import phase11_autonomous as m
        result = m.get_session_timeline("2025-08-04")
        for key in ["session_date", "events", "event_count", "advisory_only", "paper_only"]:
            self.assertIn(key, result)


# ── Test: Calendar Data ───────────────────────────────────────────────────────

class TestCalendarData(unittest.TestCase):
    @patch("phase11_autonomous._all_trades_in_range", return_value=[
        {"trade_ts": "2025-08-01T09:00:00Z", "action": "SELL", "pnl": 500.0},
        {"trade_ts": "2025-08-01T10:00:00Z", "action": "SELL", "pnl": -200.0},
        {"trade_ts": "2025-08-04T09:00:00Z", "action": "SELL", "pnl": 800.0},
    ])
    def test_calendar_structure(self, mock_trades):
        import phase11_autonomous as m
        result = m.get_calendar_data(2025, 8)
        self.assertIn("days", result)
        self.assertIn("year", result)
        self.assertIn("month", result)
        self.assertIn("trading_days", result)
        self.assertIn("total_pnl", result)

    @patch("phase11_autonomous._all_trades_in_range", return_value=[
        {"trade_ts": "2025-08-01T09:00:00Z", "action": "SELL", "pnl": 500.0},
    ])
    def test_calendar_day_has_required_fields(self, mock_trades):
        import phase11_autonomous as m
        result = m.get_calendar_data(2025, 8)
        day = result["days"][0]
        for f in ["date", "weekday", "has_trades", "trade_count", "pnl", "wins", "losses"]:
            self.assertIn(f, day)

    @patch("phase11_autonomous._all_trades_in_range", return_value=[
        {"trade_ts": "2025-08-01T09:00:00Z", "action": "SELL", "pnl": 300.0},
        {"trade_ts": "2025-08-01T10:00:00Z", "action": "SELL", "pnl": -100.0},
    ])
    def test_calendar_pnl_aggregated(self, mock_trades):
        import phase11_autonomous as m
        result = m.get_calendar_data(2025, 8)
        aug1 = next((d for d in result["days"] if d["date"] == "2025-08-01"), None)
        self.assertIsNotNone(aug1)
        self.assertTrue(aug1["has_trades"])
        self.assertAlmostEqual(aug1["pnl"], 200.0, places=0)

    @patch("phase11_autonomous._all_trades_in_range", return_value=[])
    def test_calendar_no_trades(self, mock_trades):
        import phase11_autonomous as m
        result = m.get_calendar_data(2025, 8)
        self.assertEqual(result["trading_days"], 0)
        self.assertEqual(result["total_pnl"], 0.0)


# ── Test: Daily Summary ───────────────────────────────────────────────────────

class TestDailySummary(unittest.TestCase):
    SAMPLE_TRADES = [
        {"symbol": "HDFC", "action": "BUY", "quantity": 5, "price": 1700,
         "pnl": 0, "trade_ts": "2025-08-01T04:20:00Z", "confidence": 80.0, "strategy": "BREAKOUT"},
        {"symbol": "HDFC", "action": "SELL", "quantity": 5, "price": 1760,
         "pnl": 300.0, "trade_ts": "2025-08-01T08:00:00Z",
         "confidence": 80.0, "strategy": "BREAKOUT", "entry_price": 1700.0, "exit_reason": "TARGET_HIT"},
        {"symbol": "ICICI", "action": "SELL", "quantity": 10, "price": 940,
         "pnl": -200.0, "trade_ts": "2025-08-01T09:00:00Z",
         "confidence": 60.0, "strategy": "MOMENTUM", "entry_price": 960.0, "exit_reason": "STOP_LOSS"},
    ]

    @patch("phase11_autonomous.get_session_timeline",
           return_value={"events": [], "session_date": "2025-08-01"})
    @patch("phase11_autonomous._get_market_summary", return_value={})
    @patch("phase11_autonomous._get_learning_for_date", return_value={})
    @patch("phase11_autonomous._all_trades_in_range", return_value=SAMPLE_TRADES)
    def test_daily_summary_has_required_keys(self, mock_t, mock_l, mock_m, mock_tl):
        import phase11_autonomous as m
        result = m.get_daily_summary("2025-08-01")
        for key in ["date", "summary", "closed_trades", "best_trade",
                    "worst_trade", "timeline", "learning"]:
            self.assertIn(key, result)

    @patch("phase11_autonomous.get_session_timeline",
           return_value={"events": [], "session_date": "2025-08-01"})
    @patch("phase11_autonomous._get_market_summary", return_value={})
    @patch("phase11_autonomous._get_learning_for_date", return_value={})
    @patch("phase11_autonomous._all_trades_in_range", return_value=SAMPLE_TRADES)
    def test_daily_summary_stats_correct(self, mock_t, mock_l, mock_m, mock_tl):
        import phase11_autonomous as m
        result = m.get_daily_summary("2025-08-01")
        s = result["summary"]
        self.assertEqual(s["total_trades"], 3)
        self.assertEqual(s["closed"], 2)
        self.assertEqual(s["wins"], 1)
        self.assertEqual(s["losses"], 1)
        self.assertAlmostEqual(s["win_rate"], 50.0, places=0)
        self.assertAlmostEqual(s["total_pnl"], 100.0, places=0)  # 300 - 200


# ── Test: Replay Data ─────────────────────────────────────────────────────────

class TestReplayData(unittest.TestCase):
    @patch("phase11_autonomous._get_ai_decisions_for_date", return_value=[])
    @patch("phase11_autonomous.get_session_timeline",
           return_value={"events": [], "session_date": "2025-08-01"})
    @patch("phase11_autonomous._all_trades_in_range", return_value=[
        {"symbol": "HDFC", "action": "BUY", "quantity": 5, "price": 1700,
         "pnl": 0, "trade_ts": "2025-08-01T04:20:00Z"},
        {"symbol": "HDFC", "action": "SELL", "quantity": 5, "price": 1760,
         "pnl": 300.0, "trade_ts": "2025-08-01T08:00:00Z"},
    ])
    def test_replay_has_snapshots(self, mock_t, mock_tl, mock_ai):
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.get_replay_data("2025-08-01")
        self.assertIn("trade_snapshots", result)
        self.assertIn("events", result)
        self.assertIn("final_pnl", result)
        self.assertEqual(len(result["trade_snapshots"]), 2)

    @patch("phase11_autonomous._get_ai_decisions_for_date", return_value=[])
    @patch("phase11_autonomous.get_session_timeline",
           return_value={"events": [], "session_date": "2025-08-01"})
    @patch("phase11_autonomous._all_trades_in_range", return_value=[
        {"symbol": "HDFC", "action": "BUY", "quantity": 5, "price": 1700,
         "pnl": 0, "trade_ts": "2025-08-01T04:20:00Z"},
        {"symbol": "HDFC", "action": "SELL", "quantity": 5, "price": 1760,
         "pnl": 300.0, "trade_ts": "2025-08-01T08:00:00Z"},
    ])
    def test_replay_portfolio_value_tracked(self, mock_t, mock_tl, mock_ai):
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.get_replay_data("2025-08-01")
        snapshots = result["trade_snapshots"]
        # After BUY: positions opened, cash decreased
        buy_snap  = snapshots[0]
        sell_snap = snapshots[1]
        self.assertGreater(buy_snap["open_positions"], 0)
        # After SELL: position closed
        self.assertEqual(sell_snap["open_positions"], 0)

    @patch("phase11_autonomous._get_ai_decisions_for_date", return_value=[])
    @patch("phase11_autonomous.get_session_timeline",
           return_value={"events": [], "session_date": "2025-08-01"})
    @patch("phase11_autonomous._all_trades_in_range", return_value=[])
    def test_replay_empty_day(self, mock_t, mock_tl, mock_ai):
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.get_replay_data("2025-08-01")
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["final_pnl"], 0.0)


# ── Test: Reports ─────────────────────────────────────────────────────────────

class TestReports(unittest.TestCase):
    CLOSED_TRADES = [
        {"symbol": "HDFC", "action": "SELL", "quantity": 5, "price": 1760, "pnl": 300.0,
         "trade_ts": "2025-08-01T08:00:00Z", "confidence": 80.0, "strategy": "BREAKOUT",
         "entry_price": 1700.0, "exit_reason": "TARGET_HIT"},
        {"symbol": "WIPRO", "action": "SELL", "quantity": 20, "price": 450, "pnl": -200.0,
         "trade_ts": "2025-08-01T09:00:00Z", "confidence": 55.0, "strategy": "MOMENTUM",
         "entry_price": 460.0, "exit_reason": "STOP_LOSS"},
    ]

    @patch("phase11_autonomous.get_daily_summary", return_value={
        "summary": {"total_trades": 3, "opened": 1, "closed": 2, "total_pnl": 100.0,
                    "wins": 1, "losses": 1, "win_rate": 50.0, "avg_confidence": 70.0},
        "best_trade": None, "worst_trade": None,
        "closed_trades": [], "learning": {}, "market_summary": {},
    })
    @patch("phase11_autonomous.get_topup_log", return_value=[])
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_daily_report_has_required_fields(self, mock_kv, mock_tl, mock_sum):
        import phase11_autonomous as m
        report = m.generate_daily_report("2025-08-01")
        for f in ["report_type", "date", "capital_mode", "starting_capital",
                  "pnl", "win_rate", "advisory_only", "paper_only", "generated_at"]:
            self.assertIn(f, report)
        self.assertEqual(report["report_type"], "DAILY")

    @patch("phase11_autonomous._all_trades_in_range", return_value=CLOSED_TRADES)
    @patch("phase11_autonomous.get_topup_log", return_value=[])
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_weekly_report_has_required_fields(self, mock_kv, mock_tl, mock_trades):
        import phase11_autonomous as m
        report = m.generate_weekly_report()
        for f in ["report_type", "week_start", "week_end", "total_pnl",
                  "win_rate", "advisory_only", "paper_only", "generated_at"]:
            self.assertIn(f, report)
        self.assertEqual(report["report_type"], "WEEKLY")

    @patch("phase11_autonomous._all_trades_in_range", return_value=CLOSED_TRADES)
    @patch("phase11_autonomous.get_topup_log", return_value=[])
    @patch("phase11_autonomous.get_calendar_data", return_value={"days": []})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_monthly_report_has_required_fields(self, mock_kv, mock_cal, mock_tl, mock_trades):
        import phase11_autonomous as m
        report = m.generate_monthly_report(2025, 8)
        for f in ["report_type", "year", "month", "month_label", "total_pnl",
                  "win_rate", "profit_factor", "advisory_only", "paper_only"]:
            self.assertIn(f, report)
        self.assertEqual(report["report_type"], "MONTHLY")
        self.assertEqual(report["month_label"], "August 2025")


# ── Test: AI Performance ──────────────────────────────────────────────────────

class TestAIPerformance(unittest.TestCase):
    @patch("paper_analytics.shared_services.get_paper_analytics_snapshot", return_value={})
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_ai_performance_has_required_fields(self, mock_load, mock_snap):
        import phase11_autonomous as m
        result = m.get_ai_performance_metrics()
        for f in [
            "trades_analysed", "trades_executed", "closed_trades", "win_rate",
            "avg_gain", "avg_loss", "profit_factor", "recommendation_accuracy",
            "avg_confidence", "avg_holding_mins", "avg_holding_label",
            "best_strategy", "worst_strategy", "advisory_only", "as_of",
        ]:
            self.assertIn(f, result, f"Missing field: {f}")

    @patch("paper_analytics.shared_services.get_paper_analytics_snapshot", return_value={})
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_ai_performance_win_rate(self, mock_load, mock_snap):
        import phase11_autonomous as m
        result = m.get_ai_performance_metrics()
        # TCS SELL pnl=600 (win), WIPRO SELL pnl=-300 (loss) → 50% win rate
        self.assertAlmostEqual(result["win_rate"], 50.0, places=0)

    @patch("paper_analytics.shared_services.get_paper_analytics_snapshot", return_value={})
    @patch("portfolio_store.load_state", return_value={"trades": []})
    def test_ai_performance_empty_trades(self, mock_load, mock_snap):
        import phase11_autonomous as m
        result = m.get_ai_performance_metrics()
        self.assertEqual(result["win_rate"], 0.0)
        self.assertEqual(result["closed_trades"], 0)


# ── Test: Learning Summary ────────────────────────────────────────────────────

class TestLearningSummary(unittest.TestCase):
    @patch("paper_analytics.shared_services.get_paper_analytics_snapshot", return_value={})
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_learning_has_required_fields(self, mock_load, mock_snap):
        import phase11_autonomous as m
        with patch("phase11_autonomous._get_watch_candidates", return_value=[]):
            result = m.get_learning_summary()
        for f in [
            "best_trade", "worst_trade", "most_reliable_strategy",
            "common_mistakes", "tomorrow_watchlist", "lessons_learned", "advisory_only",
        ]:
            self.assertIn(f, result, f"Missing field: {f}")

    @patch("paper_analytics.shared_services.get_paper_analytics_snapshot", return_value={})
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_learning_identifies_best_trade(self, mock_load, mock_snap):
        import phase11_autonomous as m
        with patch("phase11_autonomous._get_watch_candidates", return_value=[]):
            result = m.get_learning_summary()
        best = result["best_trade"]
        self.assertIsNotNone(best)
        self.assertEqual(best["symbol"], "TCS")  # pnl=600 is best


# ── Test: Snapshot ────────────────────────────────────────────────────────────

class TestPhase11Snapshot(unittest.TestCase):
    @patch("phase11_autonomous.get_phase11_portfolio", return_value={
        "current_value": 52_000.0, "cash": 35_000.0, "daily_pnl": 400.0,
        "daily_return": 0.8, "unrealised_pnl": 150.0, "realised_pnl": 300.0,
        "open_positions": 2, "buying_power": 35_000.0, "portfolio_return": 4.0,
        "drawdown_pct": 1.5,
    })
    @patch("phase11_autonomous.get_recommendation_queue",
           return_value={"count": 3, "items": [{"symbol": "HDFC", "confidence": 85.0}]})
    @patch("phase11_autonomous.get_ai_performance_metrics",
           return_value={"win_rate": 65.0, "avg_confidence": 75.0})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_snapshot_has_required_fields(self, mock_kv, mock_perf, mock_recs, mock_port):
        import phase11_autonomous as m
        snap = m.get_phase11_snapshot()
        for f in [
            "portfolio_value", "cash", "today_pnl", "today_return", "open_positions",
            "buying_power", "portfolio_return", "recommendations", "top_opportunity",
            "win_rate", "capital_mode", "date", "advisory_only", "paper_only", "as_of",
        ]:
            self.assertIn(f, snap, f"Missing field: {f}")

    @patch("phase11_autonomous.get_phase11_portfolio", return_value={
        "current_value": 52_000.0, "cash": 35_000.0, "daily_pnl": 400.0,
        "daily_return": 0.8, "unrealised_pnl": 150.0, "realised_pnl": 300.0,
        "open_positions": 2, "buying_power": 35_000.0, "portfolio_return": 4.0,
        "drawdown_pct": 1.5,
    })
    @patch("phase11_autonomous.get_recommendation_queue",
           return_value={"count": 3, "items": [{"symbol": "HDFC", "confidence": 85.0}]})
    @patch("phase11_autonomous.get_ai_performance_metrics",
           return_value={"win_rate": 65.0, "avg_confidence": 75.0})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_snapshot_paper_only(self, mock_kv, mock_perf, mock_recs, mock_port):
        import phase11_autonomous as m
        snap = m.get_phase11_snapshot()
        self.assertTrue(snap["paper_only"])
        self.assertTrue(snap["advisory_only"])


# ── Test: Helpers ─────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_fmt_holding_minutes(self):
        import phase11_autonomous as m
        self.assertEqual(m._fmt_holding(45), "45m")
        self.assertEqual(m._fmt_holding(60), "1h")
        self.assertEqual(m._fmt_holding(90), "1h 30m")
        self.assertEqual(m._fmt_holding(0), "0m")
        self.assertEqual(m._fmt_holding(-1), "—")

    def test_calc_holding_mins(self):
        import phase11_autonomous as m
        mins = m._calc_holding_mins("2025-08-01T04:20:00Z", "2025-08-01T08:20:00Z")
        self.assertEqual(mins, 240)

    def test_calc_holding_mins_bad_input(self):
        import phase11_autonomous as m
        self.assertEqual(m._calc_holding_mins("", ""), 0)
        self.assertEqual(m._calc_holding_mins(None, None), 0)

    def test_trade_brief_none(self):
        import phase11_autonomous as m
        self.assertIsNone(m._trade_brief(None))

    def test_trade_brief_valid(self):
        import phase11_autonomous as m
        brief = m._trade_brief({"symbol": "HDFC", "pnl": 500.0, "strategy": "BREAKOUT",
                                 "action": "SELL", "price": 1760.0})
        self.assertEqual(brief["symbol"], "HDFC")
        self.assertAlmostEqual(brief["pnl"], 500.0)


# ── Test: Capital Mode B Top-up ───────────────────────────────────────────────

class TestCapitalModeB(unittest.TestCase):
    def setUp(self):
        SAMPLE_KV.clear()
        SAMPLE_KV["phase11_capital_mode"]     = "B"
        SAMPLE_KV["phase11_starting_capital"] = 50_000.0
        SAMPLE_KV["phase11_topup_threshold"]  = 10_000.0
        SAMPLE_KV["phase11_topup_target"]     = 50_000.0

    @patch("phase11_autonomous.record_topup")
    @patch("portfolio_store.save_state")
    @patch("portfolio_store.load_state", return_value={"cash": 8_000.0, "positions": {}, "trades": []})
    def test_topup_applied_when_below_threshold(self, mock_load, mock_save, mock_record):
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.check_and_apply_topup()
        # Should top up from 8000 to 50000
        if result:
            self.assertTrue(result["applied"])
            self.assertAlmostEqual(result["amount"], 42_000.0, places=0)

    @patch("portfolio_store.load_state", return_value={"cash": 30_000.0, "positions": {}, "trades": []})
    def test_no_topup_when_above_threshold(self, mock_load):
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.check_and_apply_topup()
        self.assertIsNone(result)

    @patch("portfolio_store.load_state", return_value={"cash": 5_000.0, "positions": {}, "trades": []})
    def test_no_topup_in_mode_a(self, mock_load):
        SAMPLE_KV["phase11_capital_mode"] = "A"
        import phase11_autonomous as m
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)):
            result = m.check_and_apply_topup()
        self.assertIsNone(result)


# ── Test: Price Snapshots ─────────────────────────────────────────────────────

class TestPriceSnapshots(unittest.TestCase):
    """
    Tests for record_price_snapshots() and get_price_history().
    All DB calls are mocked — no live Postgres required.
    """

    def _make_cursor(self, inserted_count=1, existing_syms=None):
        """Return a mock cursor whose rowcount tracks INSERT … ON CONFLICT."""
        existing_syms = existing_syms or set()
        cur = MagicMock()

        def _execute(sql, params=None):
            # Simulate ON CONFLICT DO NOTHING: rowcount = 0 if already present.
            # INSERT params order: (symbol, price, scan_id) → params[0] = symbol
            if "ON CONFLICT" in sql and params:
                sym = params[0] if len(params) > 0 else ""
                cur.rowcount = 0 if sym in existing_syms else 1
            else:
                cur.rowcount = inserted_count

        cur.execute.side_effect = _execute
        cur.fetchall.return_value = []
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        return cur

    def _make_conn(self, cur):
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    @patch("phase11_autonomous._db_available", return_value=False)
    def test_no_db_returns_gracefully(self, _mock_db):
        import phase11_autonomous as m
        result = m.record_price_snapshots("scan-abc")
        self.assertEqual(result["recorded"], 0)
        self.assertEqual(result["reason"], "no_db")

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("portfolio_store.load_state", return_value={"positions": {}})
    def test_no_open_positions_returns_gracefully(self, _mock_state, _mock_db):
        import phase11_autonomous as m
        result = m.record_price_snapshots("scan-abc")
        self.assertEqual(result["recorded"], 0)
        self.assertIn("no_open_positions", result.get("reason", ""))

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("phase11_autonomous._ensure_price_snapshots_table")
    @patch("phase11_autonomous._connect")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_records_one_row_per_open_position(
        self, _mock_state, mock_connect, mock_ensure, _mock_db
    ):
        import phase11_autonomous as m
        cur = self._make_cursor(inserted_count=1)
        mock_connect.return_value = self._make_conn(cur)

        result = m.record_price_snapshots("scan-001")

        self.assertEqual(result["scan_id"], "scan-001")
        # SAMPLE_STATE has RELIANCE + INFY open
        self.assertEqual(result["recorded"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertIn("RELIANCE", result["symbols"])
        self.assertIn("INFY", result["symbols"])

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("phase11_autonomous._ensure_price_snapshots_table")
    @patch("phase11_autonomous._connect")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_concurrent_call_with_same_scan_id_skips_duplicates(
        self, _mock_state, mock_connect, mock_ensure, _mock_db
    ):
        """
        Simulates ON CONFLICT DO NOTHING returning rowcount=0 for already-
        recorded symbols (e.g. from a concurrent call with the same scan_id).
        """
        import phase11_autonomous as m
        # Both RELIANCE and INFY already recorded → rowcount=0 for both
        cur = self._make_cursor(existing_syms={"RELIANCE", "INFY"})
        mock_connect.return_value = self._make_conn(cur)

        result = m.record_price_snapshots("scan-001")

        self.assertEqual(result["recorded"], 0)
        self.assertEqual(result["skipped"], 2)

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("phase11_autonomous._ensure_price_snapshots_table")
    @patch("phase11_autonomous._connect")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_second_scan_id_records_fresh_rows(
        self, _mock_state, mock_connect, mock_ensure, _mock_db
    ):
        """A different scan_id should produce new rows, not collide."""
        import phase11_autonomous as m
        cur = self._make_cursor(inserted_count=1)
        mock_connect.return_value = self._make_conn(cur)

        result = m.record_price_snapshots("scan-002")

        self.assertEqual(result["recorded"], 2)
        self.assertEqual(result["skipped"], 0)

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("phase11_autonomous._ensure_price_snapshots_table")
    @patch("phase11_autonomous._connect")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    def test_get_price_history_all_symbols(
        self, _mock_state, mock_connect, mock_ensure, _mock_db
    ):
        """get_price_history() with no symbol returns snapshots dict."""
        import phase11_autonomous as m
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)
        cur = MagicMock()
        cur.fetchall.return_value = [
            ("RELIANCE", 2870.0, now),
            ("RELIANCE", 2875.0, now),
            ("INFY", 1480.0, now),
        ]
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = self._make_conn(cur)

        result = m.get_price_history()

        self.assertIn("snapshots", result)
        self.assertIn("RELIANCE", result["snapshots"])
        self.assertEqual(len(result["snapshots"]["RELIANCE"]), 2)
        self.assertIn("INFY", result["snapshots"])

    @patch("phase11_autonomous._db_available", return_value=True)
    @patch("phase11_autonomous._ensure_price_snapshots_table")
    @patch("phase11_autonomous._connect")
    def test_get_price_history_single_symbol(
        self, mock_connect, mock_ensure, _mock_db
    ):
        """get_price_history(symbol=X) returns prices list."""
        import phase11_autonomous as m
        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)
        cur = MagicMock()
        cur.fetchall.return_value = [
            (2870.0, now),
            (2880.0, now),
            (2875.0, now),
        ]
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = self._make_conn(cur)

        result = m.get_price_history("RELIANCE", limit=50)

        self.assertEqual(result["symbol"], "RELIANCE")
        self.assertEqual(result["prices"], [2870.0, 2880.0, 2875.0])
        self.assertEqual(result["count"], 3)


# ── Test: Age column fallback chain & clamping ────────────────────────────────

def _make_pos(opened_at: str | None, age_ts_source: str | None) -> dict:
    """Minimal canonical position fixture."""
    return {
        "trade_id": "T-age-test",
        "symbol": "TESTCO",
        "quantity": 1,
        "avg_price": 100.0,
        "cost": 100.0,
        "mark_price": 105.0,
        "mark_source": "scan",
        "market_value": 105.0,
        "unrealized_pnl": 5.0,
        "status": "OPEN",
        "sector": "TEST",
        "strategy_id": "BREAKOUT",
        "opened_at": opened_at,
        "age_ts_source": age_ts_source,
        "stop_loss": 90.0,
        "target": 120.0,
        "scan_id": "scan-age-test",
    }


def _canon_with_pos(pos: dict) -> dict:
    return {
        **EMPTY_CANON,
        "cash": 50_000.0,
        "initial_capital": 50_000.0,
        "equity": 50_105.0,
        "open_position_count": 1,
        "positions": [pos],
    }


class TestAgeColumnCanonicalPortfolio(unittest.TestCase):
    """Verify canonical_portfolio opens_at fallback chain & age_ts_source."""

    def _build(self, ledger_row: dict) -> list:
        """Run build_canonical_portfolio() with a single open ledger row mocked."""
        import canonical_portfolio as cp
        import portfolio_store

        with patch.object(cp, "_ledger_rows", return_value=[ledger_row]), \
             patch.object(cp, "_scan_marks",
                          return_value=({"TESTCO": 105.0}, {"TESTCO": "TEST"}, "s1")), \
             patch.object(cp, "_live_marks", return_value={}), \
             patch.object(portfolio_store, "INITIAL_CAPITAL", 50_000.0):
            snap = cp.build_canonical_portfolio()
        return snap["positions"]

    def _base_row(self, **overrides) -> dict:
        row = {
            "trade_id": "T1",
            "symbol": "TESTCO",
            "status": "OPEN",
            "fill_ts":      None,
            "signal_ts":    None,
            "snapshot_ts":  None,
            "created_at":   None,
            "fill_price":   100.0,
            "quantity":     1,
            "stop_loss":    90.0,
            "target":       120.0,
            "strategy_id":  "BREAKOUT",
            "sector":       "TEST",
            "scan_id":      "s1",
            "realized_pnl": None,
        }
        row.update(overrides)
        return row

    def test_fill_ts_is_primary_source(self):
        """Normal case: fill_ts present → opened_at = fill_ts, source = fill_ts."""
        positions = self._build(self._base_row(fill_ts="2025-08-10T05:00:00Z"))
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T05:00:00Z")
        self.assertEqual(pos["age_ts_source"], "fill_ts")

    def test_signal_ts_fallback_when_fill_ts_null(self):
        """fill_ts missing → fall back to signal_ts."""
        positions = self._build(
            self._base_row(fill_ts=None, signal_ts="2025-08-10T06:00:00Z"))
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T06:00:00Z")
        self.assertEqual(pos["age_ts_source"], "signal_ts")

    def test_snapshot_ts_fallback_when_fill_and_signal_null(self):
        """fill_ts + signal_ts both missing → fall back to snapshot_ts."""
        positions = self._build(
            self._base_row(fill_ts=None, signal_ts=None,
                           snapshot_ts="2025-08-10T07:00:00Z"))
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T07:00:00Z")
        self.assertEqual(pos["age_ts_source"], "snapshot_ts")

    def test_created_at_fallback_when_all_others_null(self):
        """fill_ts, signal_ts, snapshot_ts all missing → fall back to created_at."""
        positions = self._build(
            self._base_row(fill_ts=None, signal_ts=None, snapshot_ts=None,
                           created_at="2025-08-10T08:00:00Z"))
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T08:00:00Z")
        self.assertEqual(pos["age_ts_source"], "created_at")

    def test_age_ts_source_none_when_all_timestamps_null(self):
        """All timestamp fields null → opened_at=None, age_ts_source=None."""
        positions = self._build(
            self._base_row(fill_ts=None, signal_ts=None, snapshot_ts=None,
                           created_at=None))
        pos = positions[0]
        self.assertIsNone(pos["opened_at"])
        self.assertIsNone(pos["age_ts_source"])

    def test_malformed_fill_ts_falls_back_to_signal_ts(self):
        """Malformed (non-empty, unparseable) fill_ts must be skipped;
        the first valid fallback (signal_ts) is used instead."""
        positions = self._build(
            self._base_row(fill_ts="N/A",  # non-empty but unparseable
                           signal_ts="2025-08-10T06:00:00Z"))
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T06:00:00Z")
        self.assertEqual(pos["age_ts_source"], "signal_ts")

    def test_malformed_fill_ts_falls_back_to_snapshot_ts(self):
        """Malformed fill_ts + null signal_ts → snapshot_ts used."""
        positions = self._build(
            self._base_row(fill_ts="invalid-date",
                           signal_ts=None,
                           snapshot_ts="2025-08-10T07:30:00Z"))
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T07:30:00Z")
        self.assertEqual(pos["age_ts_source"], "snapshot_ts")

    def test_naive_fill_ts_is_accepted(self):
        """Naive ISO timestamp (no UTC offset) is treated as UTC and accepted."""
        positions = self._build(
            self._base_row(fill_ts="2025-08-10T08:00:00"))  # no offset
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T08:00:00")
        self.assertEqual(pos["age_ts_source"], "fill_ts")

    def test_naive_fill_ts_malformed_falls_back_to_naive_signal_ts(self):
        """Malformed fill_ts, then naive signal_ts → signal_ts selected."""
        positions = self._build(
            self._base_row(fill_ts="not-a-date",
                           signal_ts="2025-08-10T09:00:00"))  # naive
        pos = positions[0]
        self.assertEqual(pos["opened_at"], "2025-08-10T09:00:00")
        self.assertEqual(pos["age_ts_source"], "signal_ts")


class TestAgeColumnPhase11Detail(unittest.TestCase):
    """Verify phase11 get_open_positions_detail() propagates age_ts_source
    correctly and clamps holding_days to >= 0."""

    _common_patches = [
        ("phase11_autonomous._get_current_regime", "TRENDING"),
        ("portfolio_store.load_state", {}),
    ]

    @staticmethod
    def _kv_mock(k, d=None):
        return d

    def _call(self, canon_override: dict) -> list:
        import phase11_autonomous as m
        with patch("canonical_portfolio.build_canonical_portfolio",
                   return_value=canon_override), \
             patch("phase11_autonomous._get_current_regime", return_value="TRENDING"), \
             patch("phase20_store.kv_get", side_effect=self._kv_mock), \
             patch("phase20_executor.get_open_trades", return_value=[]):
            return m.get_open_positions_detail()

    def test_holding_days_positive_with_fill_ts(self):
        """A position opened in the past has holding_days > 0."""
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        pos = _make_pos(opened_at=past, age_ts_source="fill_ts")
        result = self._call(_canon_with_pos(pos))
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertIsNotNone(item["holding_days"])
        self.assertGreaterEqual(item["holding_days"], 2.9)
        self.assertEqual(item["age_ts_source"], "fill_ts")

    def test_holding_days_none_when_no_timestamp(self):
        """No usable timestamp → holding_days is None, age_ts_source is None."""
        pos = _make_pos(opened_at=None, age_ts_source=None)
        result = self._call(_canon_with_pos(pos))
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertIsNone(item["holding_days"])
        self.assertIsNone(item["age_ts_source"])
        # near_time_exit must be False (not raise) when holding_days is None
        self.assertFalse(item["near_time_exit"])

    def test_holding_days_clamped_to_zero_for_future_timestamp(self):
        """Future fill_ts (clock skew) → holding_days is 0.0, never negative."""
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        pos = _make_pos(opened_at=future, age_ts_source="fill_ts")
        result = self._call(_canon_with_pos(pos))
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertIsNotNone(item["holding_days"])
        self.assertEqual(item["holding_days"], 0.0)
        self.assertFalse(item["near_time_exit"])

    def test_fallback_source_propagated_to_output(self):
        """age_ts_source from canonical portfolio is forwarded in the output."""
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        pos = _make_pos(opened_at=past, age_ts_source="snapshot_ts")
        result = self._call(_canon_with_pos(pos))
        self.assertEqual(result[0]["age_ts_source"], "snapshot_ts")


if __name__ == "__main__":
    unittest.main()
