"""
test_scanner_coverage.py — market-hours coverage probe (Task: Monday recovery).

Covers the reviewer-required cases:
* stale prior-session FULL coverage during OPEN → flagged (Friday 50/50 must
  not mask a Monday failure)
* missing current-session scan / no scan at all during OPEN → flagged
* PRE_OPEN is in-session → same rules apply
* weekday holiday → not in-session, low coverage is expected (no warning)
* reduced requested universe (48 requested, 48 received) → still flagged
  against MIN_SYMBOLS_EXPECTED
* fresh full-coverage scan during OPEN → healthy

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market_hours
import scan_state_store
from scanner_coverage import coverage_probe
from config import MIN_SYMBOLS_EXPECTED

IST = ZoneInfo("Asia/Kolkata")

# Monday 2026-08-10 10:00 IST — market OPEN.
MONDAY_10AM = datetime(2026, 8, 10, 10, 0, tzinfo=IST)
# Monday 09:05 IST — PRE_OPEN.
MONDAY_PREOPEN = datetime(2026, 8, 10, 9, 5, tzinfo=IST)
# Friday 2026-08-07 20:45 UTC scan (previous session).
FRIDAY_SCAN_TS = "2026-08-07T20:45:00Z"
# Monday 04:00 UTC == 09:30 IST scan (current session).
MONDAY_SCAN_TS = "2026-08-10T04:00:00Z"


def _meta(received: int, requested: int = MIN_SYMBOLS_EXPECTED, ts: str = MONDAY_SCAN_TS,
          missing=None):
    return {
        "symbols_received": received,
        "symbols_requested": requested,
        "missing_symbols": missing or [],
        "scan_id": "test-scan",
        "snapshot_ts": ts,
        "completed_at": ts,
    }


def _probe(state: str, now: datetime, meta):
    with patch.object(market_hours, "market_status",
                      return_value={"state": state}), \
         patch.object(market_hours, "now_ist", return_value=now), \
         patch.object(scan_state_store, "load_latest_meta",
                      return_value=meta):
        return coverage_probe()


class TestScannerCoverage(unittest.TestCase):

    def test_stale_prior_session_full_coverage_is_flagged(self):
        """Friday 50/50 must NOT report healthy on Monday during OPEN."""
        r = _probe("OPEN", MONDAY_10AM, _meta(50, ts=FRIDAY_SCAN_TS))
        self.assertFalse(r["ok"])
        self.assertFalse(r["scan_fresh_for_session"])
        self.assertIn("previous session", r["warning"])

    def test_no_scan_at_all_during_open_is_flagged(self):
        r = _probe("OPEN", MONDAY_10AM, None)
        self.assertFalse(r["ok"])
        self.assertIn("No completed scan", r["warning"])

    def test_fresh_full_coverage_is_healthy(self):
        r = _probe("OPEN", MONDAY_10AM, _meta(MIN_SYMBOLS_EXPECTED))
        self.assertTrue(r["ok"])
        self.assertTrue(r["scan_fresh_for_session"])
        self.assertIsNone(r["warning"])

    def test_fresh_low_coverage_is_flagged_with_missing_symbols(self):
        r = _probe("OPEN", MONDAY_10AM,
                   _meta(MIN_SYMBOLS_EXPECTED - 2, missing=["WIPRO", "TMPV"]))
        self.assertFalse(r["ok"])
        self.assertIn(f"{MIN_SYMBOLS_EXPECTED - 2}/", r["warning"])
        self.assertIn("WIPRO", r["warning"])

    def test_preopen_counts_as_in_session(self):
        """PRE_OPEN applies the same rules — stale Friday scan is flagged."""
        r = _probe("PRE_OPEN", MONDAY_PREOPEN, _meta(50, ts=FRIDAY_SCAN_TS))
        self.assertTrue(r["in_session"])
        self.assertFalse(r["ok"])

    def test_reduced_requested_universe_cannot_fake_full_coverage(self):
        """48 requested / 48 received is still short of the configured 50."""
        r = _probe("OPEN", MONDAY_10AM, _meta(48, requested=48))
        self.assertFalse(r["ok"])
        self.assertIn(f"48/{MIN_SYMBOLS_EXPECTED}", r["warning"])

    def test_weekday_holiday_low_coverage_is_expected(self):
        """HOLIDAY is out of session — stale/low coverage is not a warning."""
        holiday_noon = datetime(2026, 8, 15, 12, 0, tzinfo=IST)
        r = _probe("HOLIDAY", holiday_noon,
                   _meta(48, ts=FRIDAY_SCAN_TS, missing=["WIPRO", "TMPV"]))
        self.assertTrue(r["ok"])
        self.assertFalse(r["in_session"])
        self.assertIsNone(r["warning"])
        self.assertIn("expected to self-resolve", r.get("note", ""))

    def test_weekend_low_coverage_is_expected(self):
        weekend = datetime(2026, 8, 9, 12, 0, tzinfo=IST)
        r = _probe("WEEKEND", weekend, _meta(48, ts=FRIDAY_SCAN_TS))
        self.assertTrue(r["ok"])
        self.assertIsNone(r["warning"])

    def test_session_boundary_scan_exactly_at_preopen_start_is_fresh(self):
        """A scan at exactly 09:00 IST today counts as this session."""
        ts = "2026-08-10T03:30:00Z"  # 09:00 IST
        r = _probe("OPEN", MONDAY_10AM, _meta(MIN_SYMBOLS_EXPECTED, ts=ts))
        self.assertTrue(r["ok"])
        self.assertTrue(r["scan_fresh_for_session"])

    def test_market_state_failure_fails_closed(self):
        with patch.object(market_hours, "market_status",
                          side_effect=RuntimeError("boom")):
            r = coverage_probe()
        self.assertFalse(r["ok"])
        self.assertFalse(r["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
