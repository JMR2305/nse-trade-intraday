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
import hashlib
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market_hours
import scan_state_store
import config
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


def _universe_context(key: str, symbols: list[str], version: int = 1):
    """Build the immutable pin written alongside a canonical scan."""
    enabled_symbols = sorted(symbols)
    exact_set_hash = hashlib.sha256(
        "\n".join(enabled_symbols).encode("utf-8")
    ).hexdigest()
    return {
        "universe_key": key,
        "enabled_symbols": enabled_symbols,
        "exact_set_hash": exact_set_hash,
        "version": version,
    }


def _meta_for_universe(meta, context):
    """Attach the scan's pin without mutating a shared fixture."""
    if meta is None:
        return None
    result = dict(meta)
    result["universe_context"] = {
        "exact_set_hash": context["exact_set_hash"],
        "version": context["version"],
    }
    return result


def _probe(state: str, now: datetime, meta):
    context = _universe_context(
        config.UniverseMode.NIFTY_50.value,
        list(config.NIFTY_50),
    )
    with patch.object(market_hours, "market_status",
                      return_value={"state": state}), \
         patch.object(market_hours, "now_ist", return_value=now), \
         patch("scanner_coverage._expected_universe",
               return_value=(
                   config.UniverseMode.NIFTY_50.value,
                   context["enabled_symbols"],
                   context,
               )), \
         patch.object(scan_state_store, "load_latest_meta",
                      return_value=_meta_for_universe(meta, context)):
        return coverage_probe()


class TestScannerCoverage(unittest.TestCase):

    def test_stale_prior_session_full_coverage_is_flagged(self):
        """Friday 50/50 must NOT report healthy on Monday during OPEN."""
        r = _probe("OPEN", MONDAY_10AM, _meta(50, ts=FRIDAY_SCAN_TS))
        self.assertFalse(r["ok"])
        self.assertFalse(r["scan_fresh_for_session"])
        self.assertEqual(
            r["readiness_state"], "stale_or_different_pinned_revision"
        )
        self.assertIn("previous session", r["warning"])

    def test_no_scan_at_all_during_open_is_flagged(self):
        r = _probe("OPEN", MONDAY_10AM, None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["readiness_state"], "no_current_version_scan")
        self.assertIn("No completed scan", r["warning"])

    def test_fresh_full_coverage_is_healthy(self):
        r = _probe("OPEN", MONDAY_10AM, _meta(MIN_SYMBOLS_EXPECTED))
        self.assertTrue(r["ok"])
        self.assertTrue(r["scan_fresh_for_session"])
        self.assertEqual(r["readiness_state"], "healthy_current_scan")
        self.assertIsNone(r["warning"])

    def test_fresh_low_coverage_is_flagged_with_missing_symbols(self):
        r = _probe("OPEN", MONDAY_10AM,
                   _meta(MIN_SYMBOLS_EXPECTED - 2, missing=["WIPRO", "TMPV"]))
        self.assertFalse(r["ok"])
        self.assertEqual(r["readiness_state"], "incomplete_current_scan")
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

    def test_durable_authority_failure_has_explicit_readiness_state(self):
        with patch.object(market_hours, "market_status",
                          return_value={"state": "OPEN"}), \
             patch.object(market_hours, "now_ist", return_value=MONDAY_10AM), \
             patch("scanner_coverage._expected_universe",
                   side_effect=RuntimeError("authority unavailable")):
            r = coverage_probe()

        self.assertFalse(r["success"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["readiness_state"], "durable_authority_unavailable")

    def test_scan_metadata_failure_is_not_reported_as_no_scan(self):
        context = _universe_context(
            config.UniverseMode.NIFTY_50.value,
            list(config.NIFTY_50),
        )
        with patch.object(market_hours, "market_status",
                          return_value={"state": "OPEN"}), \
             patch.object(market_hours, "now_ist", return_value=MONDAY_10AM), \
             patch("scanner_coverage._expected_universe",
                   return_value=(
                       config.UniverseMode.NIFTY_50.value,
                       context["enabled_symbols"],
                       context,
                   )), \
             patch.object(scan_state_store, "load_latest_meta",
                          side_effect=RuntimeError("metadata store unavailable")):
            r = coverage_probe()

        self.assertFalse(r["success"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["readiness_state"], "scan_metadata_unavailable")
        self.assertIn("metadata", r["warning"].lower())

    def test_different_pinned_revision_has_explicit_readiness_state(self):
        context = _universe_context(
            config.UniverseMode.NIFTY_50.value,
            list(config.NIFTY_50),
        )
        different_context = dict(context)
        different_context["version"] = context["version"] + 1
        with patch.object(market_hours, "market_status",
                          return_value={"state": "OPEN"}), \
             patch.object(market_hours, "now_ist", return_value=MONDAY_10AM), \
             patch("scanner_coverage._expected_universe",
                   return_value=(
                       config.UniverseMode.NIFTY_50.value,
                       context["enabled_symbols"],
                       context,
                   )), \
             patch.object(scan_state_store, "load_latest_meta",
                          return_value=_meta_for_universe(
                              _meta(MIN_SYMBOLS_EXPECTED), different_context
                          )):
            r = coverage_probe()

        self.assertFalse(r["success"])
        self.assertFalse(r["ok"])
        self.assertTrue(r["universe_mismatch"])
        self.assertEqual(
            r["readiness_state"], "stale_or_different_pinned_revision"
        )

    def test_custom_universe_full_coverage_is_healthy_at_its_active_size(self):
        """A healthy 23-symbol custom scan is not compared with NIFTY 50."""
        custom_symbols = [f"CUSTOM{i}" for i in range(23)]
        context = _universe_context(
            config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR.value,
            custom_symbols,
        )
        with patch.object(market_hours, "market_status",
                          return_value={"state": "OPEN"}), \
             patch.object(market_hours, "now_ist", return_value=MONDAY_10AM), \
             patch(
                 "scanner_coverage._expected_universe",
                 return_value=(
                     config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR.value,
                     context["enabled_symbols"],
                     context,
                 ),
             ), \
             patch.object(
                 scan_state_store,
                 "load_latest_meta",
                 return_value=_meta_for_universe(
                     _meta(23, requested=23), context
                 ),
             ):
            r = coverage_probe()

        self.assertTrue(r["ok"])
        self.assertEqual(r["active_universe"], "CUSTOM_LOW_PRICE_SECTOR")
        self.assertEqual(r["expected_symbols"], sorted(custom_symbols))
        self.assertEqual(r["min_symbols_expected"], 23)
        self.assertIsNone(r["warning"])

    def test_custom_universe_partial_coverage_still_fails_closed(self):
        custom_symbols = [f"CUSTOM{i}" for i in range(23)]
        context = _universe_context(
            config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR.value,
            custom_symbols,
        )
        with patch.object(market_hours, "market_status",
                          return_value={"state": "OPEN"}), \
             patch.object(market_hours, "now_ist", return_value=MONDAY_10AM), \
             patch(
                 "scanner_coverage._expected_universe",
                 return_value=(
                     config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR.value,
                     context["enabled_symbols"],
                     context,
                 ),
             ), \
             patch.object(
                 scan_state_store,
                 "load_latest_meta",
                 return_value=_meta_for_universe(
                     _meta(22, requested=22, missing=["CUSTOM22"]), context
                 ),
             ):
            r = coverage_probe()

        self.assertFalse(r["ok"])
        self.assertIn("22/23", r["warning"])

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
