"""
buy_audit_test.py — Unit tests for buy_audit.py.

Three scenarios:
  1. BUY generated OUTSIDE market hours, no auto-entry attempt.
  2. BUY generated INSIDE market hours with a successful ORDER_EXECUTED.
  3. BUY generated INSIDE market hours but blocked before ORDER_SUBMITTED
     (failed_gates non-empty).

All tests use in-memory stubs — no DB or network calls.

Run:  cd artifacts/api-server/src/python && python3 -m pytest tests/buy_audit_test.py -q
  or: cd artifacts/api-server/src/python && python3 tests/buy_audit_test.py
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

# Allow direct imports from the python directory.
_PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)


# ── Minimal module stubs ──────────────────────────────────────────────────────
# Stub heavy upstream modules so buy_audit.py can be imported without a DB,
# yfinance, pandas, etc.

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# scan_state_store: db_available returns False so the file-fallback path is used.
_stub_module("scan_state_store", db_available=lambda: False, _connect=None)

# pipeline_events: query_events returns [] by default (tests override per-case).
_pe_mod = _stub_module("pipeline_events", query_events=lambda **kw: [],
                       _ensure_schema=lambda conn: None)

# phase20_executor: get_ledger returns [] by default.
_exec_mod = _stub_module("phase20_executor", get_ledger=lambda limit=500: [])

# market_hours: expose market_state so buy_audit can import it.
def _market_state_stub(ts=None) -> str:
    """Stub: if ts is None, always returns CLOSED.  Tests set this themselves."""
    return "CLOSED"

_mh_mod = _stub_module("market_hours", market_state=_market_state_stub)


# ── Import the module under test ──────────────────────────────────────────────
import importlib
import buy_audit  # noqa: E402  (module is now importable after stubs)
importlib.reload(buy_audit)  # reload so it picks up the stubs set above


# ── Helpers ───────────────────────────────────────────────────────────────────

# A Friday inside market hours: 2026-08-07 10:00 IST  (UTC 04:30)
_INSIDE_IST  = "2026-08-07T04:30:00Z"   # 10:00 IST → OPEN
# A Saturday → WEEKEND
_OUTSIDE_IST = "2026-08-08T04:30:00Z"   # Saturday → CLOSED / WEEKEND

SCAN_A = "scan-aaa-111"
SCAN_B = "scan-bbb-222"
SCAN_C = "scan-ccc-333"
SYM_A  = "RELIANCE"
SYM_B  = "INFY"
SYM_C  = "TATAMOTORS"


def _make_buy_event(scan_id: str, symbol: str, ts: str) -> Dict[str, Any]:
    return {"id": 1, "ts": ts, "scan_id": scan_id, "symbol": symbol, "payload": {}}


# ── Test cases ────────────────────────────────────────────────────────────────

class TestBuyAuditOutsideHoursNoAttempt(unittest.TestCase):
    """Scenario 1: BUY generated outside market hours; no auto-entry attempt."""

    def test_record_outside_market_no_attempt(self):
        buy_events = [_make_buy_event(SCAN_A, SYM_A, _OUTSIDE_IST)]

        # market_state returns "WEEKEND" → market_open=False
        def _ms(ts=None): return "WEEKEND"

        with patch.object(buy_audit, "_fetch_buy_generated_file",
                          return_value=buy_events), \
             patch.object(buy_audit, "_fetch_order_events_file",
                          return_value=[]), \
             patch.object(buy_audit, "_fetch_trade_file",
                          return_value=None), \
             patch("market_hours.market_state", _ms):
            results = buy_audit.get_buy_audit(limit=1)

        self.assertEqual(len(results), 1)
        rec = results[0]
        self.assertEqual(rec["scan_id"], SCAN_A)
        self.assertEqual(rec["symbol"], SYM_A)
        self.assertFalse(rec["market_open"],
                         "market_open must be False for a weekend timestamp")
        self.assertFalse(rec["auto_entry_attempted"],
                         "auto_entry_attempted must be False when no trade row exists")
        self.assertEqual(rec["execution_outcome"], "NO_ATTEMPT")
        self.assertEqual(rec["failed_gates"], [])
        self.assertIsNone(rec["fill_price"])
        self.assertIsNone(rec["qty"])
        self.assertIsNone(rec["status"])


class TestBuyAuditInsideHoursExecuted(unittest.TestCase):
    """Scenario 2: BUY inside market hours; auto-entry attempted & ORDER_EXECUTED."""

    def test_record_executed(self):
        buy_events = [_make_buy_event(SCAN_B, SYM_B, _INSIDE_IST)]

        order_events = [
            {"event_type": "ORDER_SUBMITTED", "ts": _INSIDE_IST},
            {"event_type": "ORDER_EXECUTED",  "ts": _INSIDE_IST},
        ]
        trade = {
            "status": "OPEN",
            "fill_price": 1534.50,
            "qty": 5,
            "evidence": {"failed_gates": []},
        }

        def _ms(ts=None): return "OPEN"

        with patch.object(buy_audit, "_fetch_buy_generated_file",
                          return_value=buy_events), \
             patch.object(buy_audit, "_fetch_order_events_file",
                          return_value=order_events), \
             patch.object(buy_audit, "_fetch_trade_file",
                          return_value=trade), \
             patch("market_hours.market_state", _ms):
            results = buy_audit.get_buy_audit(limit=1)

        self.assertEqual(len(results), 1)
        rec = results[0]
        self.assertEqual(rec["scan_id"], SCAN_B)
        self.assertEqual(rec["symbol"], SYM_B)
        self.assertTrue(rec["market_open"])
        self.assertTrue(rec["auto_entry_attempted"])
        self.assertEqual(rec["execution_outcome"], "ORDER_EXECUTED")
        self.assertEqual(rec["failed_gates"], [])
        self.assertAlmostEqual(rec["fill_price"], 1534.50)
        self.assertEqual(rec["qty"], 5)
        self.assertEqual(rec["status"], "OPEN")


class TestBuyAuditInsideHoursBlockedBeforeSubmit(unittest.TestCase):
    """Scenario 3: BUY inside market hours but blocked before ORDER_SUBMITTED;
    failed_gates non-empty."""

    def test_record_blocked(self):
        buy_events = [_make_buy_event(SCAN_C, SYM_C, _INSIDE_IST)]

        # No ORDER_SUBMITTED emitted — execution was blocked before submission.
        order_events: List[Dict[str, Any]] = []
        # Trade row exists (claim was made) but gates failed.
        trade = {
            "status": "REJECTED",
            "fill_price": None,
            "qty": 0,
            "evidence": {
                "failed_gates": ["min_confidence", "min_opportunity_score"]
            },
        }

        def _ms(ts=None): return "OPEN"

        with patch.object(buy_audit, "_fetch_buy_generated_file",
                          return_value=buy_events), \
             patch.object(buy_audit, "_fetch_order_events_file",
                          return_value=order_events), \
             patch.object(buy_audit, "_fetch_trade_file",
                          return_value=trade), \
             patch("market_hours.market_state", _ms):
            results = buy_audit.get_buy_audit(limit=1)

        self.assertEqual(len(results), 1)
        rec = results[0]
        self.assertEqual(rec["scan_id"], SCAN_C)
        self.assertEqual(rec["symbol"], SYM_C)
        self.assertTrue(rec["market_open"])
        self.assertTrue(rec["auto_entry_attempted"])
        self.assertEqual(rec["execution_outcome"], "BLOCKED_BEFORE_SUBMIT")
        self.assertIn("min_confidence", rec["failed_gates"])
        self.assertIn("min_opportunity_score", rec["failed_gates"])


class TestLimitClamping(unittest.TestCase):
    """get_buy_audit clamps limit to [1, 50]."""

    def test_limit_clamped_high(self):
        with patch.object(buy_audit, "_fetch_buy_generated_file", return_value=[]):
            results = buy_audit.get_buy_audit(limit=999)
        self.assertEqual(results, [])

    def test_limit_clamped_low(self):
        with patch.object(buy_audit, "_fetch_buy_generated_file", return_value=[]):
            results = buy_audit.get_buy_audit(limit=0)
        self.assertEqual(results, [])


class TestOrderRejected(unittest.TestCase):
    """ORDER_REJECTED in pipeline events → execution_outcome == ORDER_REJECTED."""

    def test_order_rejected_outcome(self):
        buy_events = [_make_buy_event(SCAN_A, SYM_A, _INSIDE_IST)]
        order_events = [
            {"event_type": "ORDER_SUBMITTED", "ts": _INSIDE_IST},
            {"event_type": "ORDER_REJECTED",  "ts": _INSIDE_IST},
        ]
        trade = {
            "status": "REJECTED",
            "fill_price": None,
            "qty": 10,
            "evidence": {"failed_gates": []},
        }

        def _ms(ts=None): return "OPEN"

        with patch.object(buy_audit, "_fetch_buy_generated_file",
                          return_value=buy_events), \
             patch.object(buy_audit, "_fetch_order_events_file",
                          return_value=order_events), \
             patch.object(buy_audit, "_fetch_trade_file",
                          return_value=trade), \
             patch("market_hours.market_state", _ms):
            results = buy_audit.get_buy_audit(limit=1)

        self.assertEqual(results[0]["execution_outcome"], "ORDER_REJECTED")


class TestOrderSubmittedNoFill(unittest.TestCase):
    """ORDER_SUBMITTED emitted but no EXECUTED/REJECTED yet → ORDER_SUBMITTED."""

    def test_order_submitted_outcome(self):
        buy_events = [_make_buy_event(SCAN_B, SYM_B, _INSIDE_IST)]
        order_events = [{"event_type": "ORDER_SUBMITTED", "ts": _INSIDE_IST}]
        trade = {
            "status": "PENDING",
            "fill_price": None,
            "qty": 3,
            "evidence": {},
        }

        def _ms(ts=None): return "OPEN"

        with patch.object(buy_audit, "_fetch_buy_generated_file",
                          return_value=buy_events), \
             patch.object(buy_audit, "_fetch_order_events_file",
                          return_value=order_events), \
             patch.object(buy_audit, "_fetch_trade_file",
                          return_value=trade), \
             patch("market_hours.market_state", _ms):
            results = buy_audit.get_buy_audit(limit=1)

        self.assertEqual(results[0]["execution_outcome"], "ORDER_SUBMITTED")


if __name__ == "__main__":
    # Support direct execution: python3 tests/buy_audit_test.py
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestBuyAuditOutsideHoursNoAttempt,
        TestBuyAuditInsideHoursExecuted,
        TestBuyAuditInsideHoursBlockedBeforeSubmit,
        TestLimitClamping,
        TestOrderRejected,
        TestOrderSubmittedNoFill,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
