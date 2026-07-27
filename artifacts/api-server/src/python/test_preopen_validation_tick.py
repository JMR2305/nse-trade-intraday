"""
test_preopen_validation_tick.py — Unit tests for the Phase 5B tick handler.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
import sys
import json
import unittest
import unittest.mock as mock
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IST = ZoneInfo("Asia/Kolkata")


def _ist(h, m, s=0):
    return datetime(2026, 7, 28, h, m, s, tzinfo=IST)


class TestCheckpointWindowDetection(unittest.TestCase):
    def _cp(self, h, m):
        import preopen_validation_tick as t
        cp = t._current_checkpoint(_ist(h, m))
        return cp[0] if cp else None

    def test_09_20_window(self):
        self.assertEqual(self._cp(9, 20), "open_0920")

    def test_09_18_window_start(self):
        self.assertEqual(self._cp(9, 18), "open_0920")

    def test_09_26_window_end(self):
        self.assertEqual(self._cp(9, 26), "open_0920")

    def test_09_27_between_windows(self):
        self.assertIsNone(self._cp(9, 27))

    def test_09_30_window(self):
        self.assertEqual(self._cp(9, 30), "price_0930")

    def test_10_00_window(self):
        self.assertEqual(self._cp(10, 0), "price_1000")

    def test_10_30_window(self):
        self.assertEqual(self._cp(10, 30), "price_1030")

    def test_15_30_window(self):
        self.assertEqual(self._cp(15, 30), "eod_classify")

    def test_15_50_window_end(self):
        self.assertEqual(self._cp(15, 50), "eod_classify")

    def test_15_51_outside_window(self):
        self.assertIsNone(self._cp(15, 51))

    def test_15_50_inside_window(self):
        self.assertEqual(self._cp(15, 50), "eod_classify")

    def test_09_15_pre_open_no_checkpoint(self):
        self.assertIsNone(self._cp(9, 15))

    def test_midnight_no_checkpoint(self):
        self.assertIsNone(self._cp(0, 0))

    def test_13_00_no_checkpoint(self):
        self.assertIsNone(self._cp(13, 0))


class TestNextCheckpointLabel(unittest.TestCase):
    def _next(self, h, m):
        import preopen_validation_tick as t
        return t._next_checkpoint_label(_ist(h, m))

    def test_before_market(self):
        result = self._next(8, 0)
        self.assertIn("open_0920", result)

    def test_between_checkpoints(self):
        result = self._next(9, 27)
        self.assertIn("price_0930", result)

    def test_after_eod(self):
        result = self._next(16, 0)
        self.assertIsNone(result)


class TestTickDisabledFlag(unittest.TestCase):
    def test_disabled_returns_no_run(self):
        import preopen_validation_tick as t
        with mock.patch("preopen_validation_tick._is_enabled", return_value=False):
            result = t.run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("false", result["reason"].lower())

    def test_disabled_auto_tick_still_true(self):
        import preopen_validation_tick as t
        with mock.patch("preopen_validation_tick._is_enabled", return_value=False):
            result = t.run_tick()
        self.assertTrue(result["auto_tick"])


class TestTickNonTradingDay(unittest.TestCase):
    def test_weekend_no_run(self):
        import preopen_validation_tick as t
        with mock.patch("preopen_validation_tick._is_enabled", return_value=True), \
             mock.patch("preopen_validation_tick._is_trading_day", return_value=False):
            result = t.run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("trading day", result["reason"].lower())


class TestTickNoActiveWindow(unittest.TestCase):
    def test_outside_all_windows(self):
        import preopen_validation_tick as t
        with mock.patch("preopen_validation_tick._is_enabled", return_value=True), \
             mock.patch("preopen_validation_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_validation_tick._now_ist",
                        return_value=_ist(12, 0)):
            result = t.run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("No checkpoint", result["reason"])


class TestTickIdempotency(unittest.TestCase):
    def test_already_done_checkpoint_skipped(self):
        import preopen_validation_tick as t
        state = {
            "trading_date":    "2026-07-28",
            "session_id":      "val-test-001",
            "checkpoints_done": {"open_0920": {"ts": "2026-07-28T09:21:00+05:30"}},
        }
        with mock.patch("preopen_validation_tick._is_enabled", return_value=True), \
             mock.patch("preopen_validation_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_validation_tick._now_ist",
                        return_value=_ist(9, 22)), \
             mock.patch("preopen_validation_tick._load_state", return_value=state):
            result = t.run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("already completed", result["reason"])

    def test_second_checkpoint_runs_when_first_done(self):
        import preopen_validation_tick as t
        state = {
            "trading_date":    "2026-07-28",
            "session_id":      "val-test-001",
            "checkpoints_done": {"open_0920": {"ts": "09:21"}},
        }
        with mock.patch("preopen_validation_tick._is_enabled", return_value=True), \
             mock.patch("preopen_validation_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_validation_tick._now_ist",
                        return_value=_ist(9, 30)), \
             mock.patch("preopen_validation_tick._load_state", return_value=state), \
             mock.patch("preopen_validation_tick._save_state"), \
             mock.patch("preopen_validation_tick._ensure_candidates_initialised",
                        return_value=[{"symbol": "RELIANCE", "actual_open": 2500.0}]), \
             mock.patch("preopen_validation_tick._collect_price_checkpoint",
                        return_value={"fetched": 1, "symbols": 1, "updated": 1}), \
             mock.patch("preopen_validation_db.upsert_validation_session"):
            result = t.run_tick()
        self.assertTrue(result["ran"])
        self.assertEqual(result["checkpoint"], "price_0930")


class TestTickNoCandidates(unittest.TestCase):
    def test_no_candidates_skips_gracefully(self):
        import preopen_validation_tick as t
        with mock.patch("preopen_validation_tick._is_enabled", return_value=True), \
             mock.patch("preopen_validation_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_validation_tick._now_ist",
                        return_value=_ist(9, 20)), \
             mock.patch("preopen_validation_tick._load_state", return_value={}), \
             mock.patch("preopen_validation_tick._save_state"), \
             mock.patch("preopen_validation_tick._ensure_candidates_initialised",
                        return_value=[]), \
             mock.patch("preopen_validation_db.upsert_validation_session"):
            result = t.run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("candidates", result.get("reason", "").lower())


class TestGetTickStatus(unittest.TestCase):
    def test_always_registered(self):
        import preopen_validation_tick as t
        status = t.get_tick_status()
        self.assertTrue(status["registered"])
        self.assertTrue(status["auto_tick"])

    def test_has_required_fields(self):
        import preopen_validation_tick as t
        status = t.get_tick_status()
        for f in ["ist_time", "trading_date", "next_checkpoint",
                  "checkpoints_done", "all_checkpoints"]:
            self.assertIn(f, status)

    def test_all_checkpoints_listed(self):
        import preopen_validation_tick as t
        status = t.get_tick_status()
        self.assertEqual(len(status["all_checkpoints"]), 5)
        self.assertIn("eod_classify", status["all_checkpoints"])


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    import sys; sys.exit(0 if result.wasSuccessful() else 1)
