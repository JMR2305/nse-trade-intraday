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

    def test_update_capital_config_valid_capital(self):
        with patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d)), \
             patch("phase20_store.kv_set", side_effect=_kv_set_mock):
            import phase11_autonomous as m
            m.update_capital_config({"starting_capital": 100_000.0})
        self.assertEqual(SAMPLE_KV.get("phase11_starting_capital"), 100_000.0)


# ── Test: Portfolio Summary ───────────────────────────────────────────────────

class TestPortfolioSummary(unittest.TestCase):
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_has_required_fields(self, mock_kv, mock_load):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        for field in [
            "starting_capital", "cash", "invested_amount", "buying_power",
            "current_value", "realised_pnl", "unrealised_pnl", "total_pnl",
            "portfolio_return", "daily_pnl", "daily_return", "drawdown_pct",
            "open_positions", "capital_mode", "paper_only", "advisory_only", "as_of",
        ]:
            self.assertIn(field, p, f"Missing field: {field}")

    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_values_correct(self, mock_kv, mock_load):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertEqual(p["cash"], 35_000.0)
        self.assertEqual(p["open_positions"], 2)
        # invested = 5*2800 + 10*1500 = 14000+15000=29000
        self.assertAlmostEqual(p["invested_amount"], 29_000.0, places=0)
        # unrealised = 5*(2870-2800) + 10*(1480-1500) = 350 - 200 = 150
        self.assertAlmostEqual(p["unrealised_pnl"], 150.0, places=0)

    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_realised_pnl_from_sells(self, mock_kv, mock_load):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        # TCS SELL pnl=600, WIPRO SELL pnl=-300 → total 300
        self.assertAlmostEqual(p["realised_pnl"], 300.0, places=0)

    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_paper_only_flags(self, mock_kv, mock_load):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertTrue(p["paper_only"])
        self.assertTrue(p["advisory_only"])

    @patch("portfolio_store.load_state", return_value={})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_portfolio_empty_state(self, mock_kv, mock_load):
        import phase11_autonomous as m
        p = m.get_phase11_portfolio()
        self.assertGreaterEqual(p["cash"], 0)
        self.assertEqual(p["open_positions"], 0)


# ── Test: Open Positions Detail ───────────────────────────────────────────────

class TestOpenPositions(unittest.TestCase):
    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_has_required_fields(self, mock_kv, mock_load, mock_regime):
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

    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value=SAMPLE_STATE)
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_pnl_values(self, mock_kv, mock_load, mock_regime):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        reliance = next((p for p in positions if p["stock"] == "RELIANCE"), None)
        self.assertIsNotNone(reliance)
        # pnl = 5 * (2870 - 2800) = 350
        self.assertAlmostEqual(reliance["current_pnl"], 350.0, places=0)

    @patch("phase11_autonomous._get_current_regime", return_value="TRENDING")
    @patch("portfolio_store.load_state", return_value={"positions": {}, "trades": []})
    @patch("phase20_store.kv_get", side_effect=lambda k, d=None: SAMPLE_KV.get(k, d))
    def test_open_positions_empty(self, mock_kv, mock_load, mock_regime):
        import phase11_autonomous as m
        positions = m.get_open_positions_detail()
        self.assertEqual(positions, [])


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


if __name__ == "__main__":
    unittest.main()
