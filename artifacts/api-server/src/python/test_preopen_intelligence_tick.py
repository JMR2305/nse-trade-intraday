"""
test_preopen_intelligence_tick.py — Unit tests for the Phase 5A tick handler.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
import sys
import json
import types
import unittest
import unittest.mock as mock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_IST = timezone(timedelta(hours=5, minutes=30))


def _ist(h, m, s=0):
    return datetime(2026, 7, 28, h, m, s, tzinfo=_IST)


class TestPhaseWindowDetection(unittest.TestCase):
    def _phase(self, h, m):
        import preopen_intelligence_tick as t
        p = t._active_phase(_ist(h, m))
        return p[0] if p else None

    def test_init_window_start(self):
        self.assertEqual(self._phase(8, 43), "init")

    def test_init_window_mid(self):
        self.assertEqual(self._phase(8, 47), "init")

    def test_init_window_end(self):
        self.assertIsNone(self._phase(8, 51))  # end-exclusive boundary

    def test_gap_between_init_and_readiness(self):
        self.assertIsNone(self._phase(8, 52))

    def test_readiness_window(self):
        self.assertEqual(self._phase(8, 55), "readiness")

    def test_readiness_window_end(self):
        self.assertEqual(self._phase(9, 0), "collect")

    def test_collect_window_start(self):
        self.assertEqual(self._phase(9, 0), "collect")

    def test_collect_window_mid(self):
        self.assertEqual(self._phase(9, 7), "collect")

    def test_collect_window_end(self):
        self.assertEqual(self._phase(9, 15), "freeze")

    def test_freeze_window(self):
        self.assertEqual(self._phase(9, 16), "freeze")

    def test_reconcile_window(self):
        self.assertEqual(self._phase(9, 19), "reconcile")

    def test_reconcile_end(self):
        self.assertIsNone(self._phase(9, 23))

    def test_after_all_phases(self):
        self.assertIsNone(self._phase(9, 24))

    def test_before_all_phases(self):
        self.assertIsNone(self._phase(8, 30))

    def test_midday_no_phase(self):
        self.assertIsNone(self._phase(12, 0))


class TestNextPhaseLabel(unittest.TestCase):
    def _next(self, h, m):
        import preopen_intelligence_tick as t
        return t._next_phase_label(_ist(h, m))

    def test_before_market(self):
        result = self._next(7, 0)
        self.assertIn("init", result)

    def test_between_init_and_readiness(self):
        result = self._next(8, 52)
        self.assertIn("readiness", result)

    def test_after_all_phases(self):
        self.assertIsNone(self._next(10, 0))


class TestTickDisabled(unittest.TestCase):
    def test_disabled_no_run(self):
        import preopen_intelligence_tick as t
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=False):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("false", r["reason"].lower())
        self.assertTrue(r["auto_tick"])

    def test_disabled_even_inside_window(self):
        import preopen_intelligence_tick as t
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=False), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(8, 47)):
            r = t.run_tick()
        self.assertFalse(r["ran"])


class TestTickNonTradingDay(unittest.TestCase):
    def test_weekend_no_run(self):
        import preopen_intelligence_tick as t
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=False):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("trading day", r["reason"].lower())


class TestTickNoActivePhase(unittest.TestCase):
    def test_midday_no_run(self):
        import preopen_intelligence_tick as t
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(12, 0)):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("No phase window", r["reason"])


class TestInitPhase(unittest.TestCase):
    def test_init_runs_and_records(self):
        import preopen_intelligence_tick as t
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(8, 47)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value={}), \
             mock.patch("preopen_intelligence_tick._save_state"), \
             mock.patch("preopen_intelligence_tick._run_init",
                       return_value={"success": True, "provider_status": "LIVE", "session_status": "INITIALISED",
                                     "steps": {}}), \
             mock.patch.dict(sys.modules, {
                 "preopen_db": types.SimpleNamespace(
                     get_session_for_trading_date=lambda _: None,
                     update_phase_state=lambda *_, **__: True,
                 ),
             }):
            r = t.run_tick()
        self.assertTrue(r["ran"])
        self.assertEqual(r["phase"], "init")

    def test_init_idempotent(self):
        import preopen_intelligence_tick as t
        state = {
            "trading_date": "2026-07-28",
            "session_id":   "preopen-test-001",
            "phases_done":  {"init": {"ts": "2026-07-28T08:47:00+05:30"}},
            "collect_count": 0,
        }
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(8, 48)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("already completed", r["reason"])


class TestCollectPhase(unittest.TestCase):
    def test_collect_runs_every_tick(self):
        """collect is not deduplicated — should run on every tick in window."""
        import preopen_intelligence_tick as t
        state = {
            "trading_date":  "2026-07-28",
            "session_id":    "preopen-test-001",
            "phases_done":   {"init": {}, "readiness": {}},
            "collect_count": 3,
        }
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(9, 7)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state), \
             mock.patch("preopen_intelligence_tick._save_state"), \
             mock.patch("preopen_intelligence_tick._run_collect",
                        return_value={"success": True, "symbols_captured": 50}):
            r = t.run_tick()
        self.assertTrue(r["ran"])
        self.assertEqual(r["phase"], "collect")
        # collect_count incremented
        self.assertEqual(r["collect_count"], 4)

    def test_collect_not_idempotent(self):
        """Even when collect appeared in phases_done (shouldn't happen), still runs."""
        import preopen_intelligence_tick as t
        state = {
            "trading_date":  "2026-07-28",
            "session_id":    "preopen-test-001",
            # collect is once_only=False so it will never end up in phases_done
            "phases_done":   {"init": {}, "readiness": {}},
            "collect_count": 7,
        }
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(9, 10)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state), \
             mock.patch("preopen_intelligence_tick._save_state"), \
             mock.patch("preopen_intelligence_tick._run_collect",
                        return_value={"success": True, "symbols_captured": 50}):
            r = t.run_tick()
        self.assertTrue(r["ran"])
        self.assertEqual(r["phase"], "collect")


class TestFreezePhase(unittest.TestCase):
    def test_freeze_runs_once(self):
        import preopen_intelligence_tick as t
        state = {
            "trading_date":  "2026-07-28",
            "session_id":    "preopen-test-001",
            "phases_done":   {"init": {}, "readiness": {}},
            "collect_count": 15,
        }
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(9, 16)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state), \
             mock.patch("preopen_intelligence_tick._save_state"), \
             mock.patch("preopen_intelligence_tick._run_freeze",
                        return_value={"success": True, "phase": "FROZEN"}), \
             mock.patch("preopen_db.update_phase_state", return_value=True):
            r = t.run_tick()
        self.assertTrue(r["ran"])
        self.assertEqual(r["phase"], "freeze")

    def test_freeze_idempotent(self):
        import preopen_intelligence_tick as t
        state = {
            "trading_date":  "2026-07-28",
            "session_id":    "preopen-test-001",
            "phases_done":   {"init": {}, "readiness": {}, "freeze": {"ts": "09:15"}},
            "collect_count": 15,
        }
        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(9, 17)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state), \
             mock.patch("preopen_db.get_session_for_trading_date", return_value={
                 "session_id": "preopen-test-001",
                 "phase_state": {"freeze": {"completed": True}},
             }):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("already completed", r["reason"])


class TestProviderFailureIsolation(unittest.TestCase):
    def test_provider_error_returns_structured_result(self):
        """Provider failure must never raise; must return degraded status."""
        import preopen_intelligence_tick as t

        def _bad_init(*a, **kw):
            raise RuntimeError("Zerodha session expired")

        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(8, 47)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value={}), \
             mock.patch("preopen_intelligence_tick._save_state"), \
             mock.patch("preopen_intelligence_tick._run_init", side_effect=_bad_init), \
             mock.patch.dict(sys.modules, {
                 "preopen_db": types.SimpleNamespace(
                     get_session_for_trading_date=lambda _: None,
                 ),
             }):
            r = t.run_tick()
        # Must not raise; must return a structured result
        self.assertIsInstance(r, dict)
        self.assertFalse(r["ran"])
        self.assertIn("raised unexpectedly", r["reason"])

    def test_collect_provider_failure_structured(self):
        import preopen_intelligence_tick as t
        state = {
            "trading_date":  "2026-07-28",
            "session_id":    "preopen-test-001",
            "phases_done":   {"init": {}, "readiness": {}},
            "collect_count": 2,
        }

        def _bad_collect(*a, **kw):
            raise ConnectionError("Provider timeout")

        with mock.patch("preopen_intelligence_tick._is_enabled", return_value=True), \
             mock.patch("preopen_intelligence_tick._is_trading_day", return_value=True), \
             mock.patch("preopen_intelligence_tick._now_ist", return_value=_ist(9, 5)), \
             mock.patch("preopen_intelligence_tick._load_state", return_value=state), \
             mock.patch("preopen_intelligence_tick._run_collect", side_effect=_bad_collect):
            r = t.run_tick()
        self.assertFalse(r["ran"])
        self.assertIn("raised unexpectedly", r["reason"])


class TestGetTickStatus(unittest.TestCase):
    def test_always_registered(self):
        import preopen_intelligence_tick as t
        s = t.get_tick_status()
        self.assertTrue(s["registered"])
        self.assertTrue(s["auto_tick"])

    def test_has_required_fields(self):
        import preopen_intelligence_tick as t
        s = t.get_tick_status()
        for f in ["ist_time", "trading_date", "next_phase",
                  "phases_done", "all_phases", "collect_count"]:
            self.assertIn(f, s)

    def test_all_phases_listed(self):
        import preopen_intelligence_tick as t
        s = t.get_tick_status()
        self.assertEqual(
            s["all_phases"],
            ["init", "readiness", "collect", "freeze", "reconcile", "reconcile_0930"],
        )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    import sys; sys.exit(0 if result.wasSuccessful() else 1)
