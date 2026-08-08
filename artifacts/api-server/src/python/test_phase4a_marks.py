"""
Tests for Phase 4A open-position mark sourcing (task: live prices for open
positions).

Covers the honesty rules:
- full live: all marks from Kite, not stale
- partial live: mixed source, scan age reported honestly
- verified session + provider fallback/error: note says quote fetch failed,
  never "no session"
- no session: falls back to scan marks with the no-session note
"""
import sys
import types
import unittest

import phase4a_dashboard as d


OPEN_ROWS = [{"symbol": "AAA"}, {"symbol": "BBB"}]
SNAP = {"scan_id": "scan123"}


class TestMarkMeta(unittest.TestCase):
    def test_full_live(self):
        meta = d._mark_meta(OPEN_ROWS, {"AAA": 1.0, "BBB": 2.0},
                            "2026-08-08T05:00:00Z", SNAP, 2000,
                            session_verified=True)
        self.assertEqual(meta["mark_source"], "live quotes (Zerodha Kite)")
        self.assertFalse(meta["mark_stale"])
        self.assertIsNone(meta["mark_note"])
        self.assertTrue(meta["mark_session_verified"])
        self.assertEqual(meta["mark_age_s"], meta["live_mark_age_s"])

    def test_partial_live_reports_scan_age(self):
        meta = d._mark_meta(OPEN_ROWS, {"AAA": 1.0},
                            "2026-08-08T05:00:00Z", SNAP, 2000,
                            session_verified=True)
        self.assertIn("live quotes", meta["mark_source"])
        self.assertIn("BBB", meta["mark_source"])
        # mark_age_s must reflect the OLDER (scan) age, not the live age
        self.assertEqual(meta["mark_age_s"], 2000)
        self.assertEqual(meta["scan_mark_age_s"], 2000)
        self.assertIsNotNone(meta["live_mark_age_s"])
        self.assertTrue(meta["mark_stale"])  # scan age 2000 > 900
        self.assertIn("BBB", meta["mark_note"])

    def test_verified_session_quote_failure(self):
        meta = d._mark_meta(OPEN_ROWS, {}, None, SNAP, 2000,
                            session_verified=True,
                            quote_error="live quote fetch failed: boom")
        self.assertEqual(meta["mark_source"], "latest scan scan123")
        self.assertTrue(meta["mark_stale"])
        self.assertIn("broker session is active", meta["mark_note"])
        self.assertIn("boom", meta["mark_note"])
        self.assertNotIn("no live broker session", meta["mark_note"])
        self.assertEqual(meta["mark_quote_error"],
                         "live quote fetch failed: boom")

    def test_verified_session_provider_fallback(self):
        err = ("live quote fetch returned no usable Kite quotes "
               "(provider fell back to: yfinance_fallback)")
        meta = d._mark_meta(OPEN_ROWS, {}, None, SNAP, 100,
                            session_verified=True, quote_error=err)
        self.assertIn("broker session is active", meta["mark_note"])
        self.assertIn("yfinance_fallback", meta["mark_note"])
        self.assertFalse(meta["mark_stale"])  # scan is fresh

    def test_no_session(self):
        meta = d._mark_meta(OPEN_ROWS, {}, None, SNAP, 2000,
                            session_verified=False)
        self.assertIn("no live broker session", meta["mark_note"])
        self.assertFalse(meta["mark_session_verified"])
        self.assertEqual(meta["mark_age_s"], 2000)

    def test_no_open_positions_no_note(self):
        meta = d._mark_meta([], {}, None, SNAP, 2000, session_verified=False)
        self.assertIsNone(meta["mark_note"])


class TestBuildOverlay(unittest.TestCase):
    """Build-level checks with a stubbed kite_quote_provider."""

    def setUp(self):
        self._orig = sys.modules.get("kite_quote_provider")

    def tearDown(self):
        if self._orig is not None:
            sys.modules["kite_quote_provider"] = self._orig
        else:
            sys.modules.pop("kite_quote_provider", None)

    def _stub(self, verified, get_quotes):
        stub = types.ModuleType("kite_quote_provider")
        stub.kite_session_verified = lambda force=False: verified
        stub.get_quotes = get_quotes
        sys.modules["kite_quote_provider"] = stub

    def _open_positions(self):
        return d.build_phase4a_dashboard()["open_positions"]

    def test_live_marks_used_when_session_verified(self):
        self._stub(True, lambda syms, force_refresh=False: {
            s: {"ltp": 999.0, "data_source": "kite_live",
                "fetched_at": "2026-08-08T05:00:00Z"} for s in syms})
        op = self._open_positions()
        if op["count"] == 0:
            self.skipTest("no open positions in ledger")
        self.assertEqual(op["mark_source"], "live quotes (Zerodha Kite)")
        for p in op["positions"]:
            self.assertEqual(p["mark_source"], "live")
            self.assertEqual(p["mark_price"], 999.0)

    def test_provider_fallback_reports_quote_error_not_no_session(self):
        self._stub(True, lambda syms, force_refresh=False: {
            s: {"ltp": 100.0, "data_source": "yfinance_fallback"} for s in syms})
        op = self._open_positions()
        if op["count"] == 0:
            self.skipTest("no open positions in ledger")
        self.assertTrue(op["mark_session_verified"])
        self.assertIn("yfinance_fallback", op["mark_quote_error"])
        self.assertIn("broker session is active", op["mark_note"])
        for p in op["positions"]:
            self.assertNotEqual(p["mark_source"], "live")

    def test_quote_exception_reports_quote_error(self):
        def boom(syms, force_refresh=False):
            raise RuntimeError("kite exploded")
        self._stub(True, boom)
        op = self._open_positions()
        if op["count"] == 0:
            self.skipTest("no open positions in ledger")
        self.assertTrue(op["mark_session_verified"])
        self.assertIn("kite exploded", op["mark_quote_error"])
        self.assertIn("broker session is active", op["mark_note"])

    def test_no_session_uses_scan_marks(self):
        self._stub(False, lambda syms, force_refresh=False: {})
        op = self._open_positions()
        if op["count"] == 0:
            self.skipTest("no open positions in ledger")
        self.assertFalse(op["mark_session_verified"])
        self.assertIn("latest scan", op["mark_source"])
        self.assertIn("no live broker session", op["mark_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
