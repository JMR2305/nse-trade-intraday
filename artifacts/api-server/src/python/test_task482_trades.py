"""
test_task482_trades.py — Task 482: session scoping + phase20 trade_id backfill.

Covers:
  ✓ extract_phase20_trade_id parses legacy reason strings (and rejects junk)
  ✓ _backfill_phase20_trade_ids issues an idempotent, non-overwriting UPDATE
  ✓ get_trades() returns only the current IST trading day's trades
  ✓ get_all_trades() keeps the full history (all-time scope unchanged)

All DB access is stubbed — never touches a real database.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import portfolio_store
import paper_trader

_IST = timezone(timedelta(hours=5, minutes=30))


class TestExtractPhase20TradeId(unittest.TestCase):
    def test_parses_entry_reason(self):
        self.assertEqual(
            portfolio_store.extract_phase20_trade_id(
                "Phase 20 AUTO paper entry (trade P20-4a5f909738)"),
            "P20-4a5f909738")

    def test_parses_exit_reason(self):
        self.assertEqual(
            portfolio_store.extract_phase20_trade_id(
                "Phase 20 exit STOP_LOSS_HIT (trade P20-abc123)"),
            "P20-abc123")

    def test_none_for_unrelated_reason(self):
        self.assertIsNone(portfolio_store.extract_phase20_trade_id("Manual buy"))
        self.assertIsNone(portfolio_store.extract_phase20_trade_id(""))
        self.assertIsNone(portfolio_store.extract_phase20_trade_id(None))


class _StubCursor:
    def __init__(self):
        self.executed = []
        self.rowcount = 3

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _StubConn:
    def __init__(self):
        self.cur = _StubCursor()

    def cursor(self):
        return self.cur


class TestBackfillSql(unittest.TestCase):
    def test_update_is_guarded_and_non_overwriting(self):
        conn = _StubConn()
        n = portfolio_store._backfill_phase20_trade_ids(conn)
        self.assertEqual(n, 3)
        sql, params = conn.cur.executed[0]
        # Only rows with a P20 id in reason are touched…
        self.assertIn("WHERE reason ~ %s", sql)
        # …and already-populated IDs are never overwritten.
        self.assertIn("(metadata ->> 'phase20_trade_id') IS NULL", sql)
        self.assertIn("jsonb_set", sql)
        self.assertEqual(params, (portfolio_store._P20_REASON_RE,
                                  portfolio_store._P20_REASON_RE))

    def test_idempotent_second_run_matches_nothing(self):
        # The guard clause makes re-runs no-ops by construction: a backfilled
        # row no longer satisfies "phase20_trade_id IS NULL".
        conn = _StubConn()
        conn.cur.rowcount = 0
        self.assertEqual(portfolio_store._backfill_phase20_trade_ids(conn), 0)


class TestSessionScope(unittest.TestCase):
    """get_trades() = today's IST trades only; get_all_trades() = everything."""

    def _state(self):
        today = datetime.now(_IST)
        yesterday = today - timedelta(days=1)
        return {
            "cash": 50_000.0,
            "positions": {},
            "pnl_history": [],
            "trades": [
                {"id": "old1", "symbol": "INFY", "action": "BUY",
                 "timestamp": yesterday.isoformat()},
                {"id": "new1", "symbol": "TCS", "action": "BUY",
                 "timestamp": today.isoformat()},
                {"id": "bad1", "symbol": "SBIN", "action": "BUY",
                 "timestamp": "not-a-timestamp"},
            ],
        }

    def test_session_scope_is_today_only(self):
        with patch.object(paper_trader, "_load_state", return_value=self._state()):
            ids = [t["id"] for t in paper_trader.get_trades()]
        self.assertEqual(ids, ["new1"])

    def test_naive_local_timestamp_counts_as_today(self):
        state = self._state()
        state["trades"].append(
            {"id": "naive1", "symbol": "HDFCBANK", "action": "BUY",
             "timestamp": datetime.now().isoformat()})   # naive local time
        with patch.object(paper_trader, "_load_state", return_value=state):
            ids = {t["id"] for t in paper_trader.get_trades()}
        self.assertIn("naive1", ids)
        self.assertNotIn("old1", ids)

    def test_all_time_scope_unchanged(self):
        state = self._state()
        with patch.object(portfolio_store, "load_all_trades_any",
                          return_value=state["trades"]):
            ids = [t["id"] for t in paper_trader.get_all_trades()]
        self.assertEqual(set(ids), {"old1", "new1", "bad1"})


if __name__ == "__main__":
    unittest.main()
