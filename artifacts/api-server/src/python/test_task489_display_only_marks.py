"""
Task 489 — Confirm live-quote position marks stay display-only.

Deterministic build-level tests for build_phase4a_dashboard():
  1. Live Kite LTPs affect ONLY mark_price / unrealized P&L — never fill
     prices, cost basis, or exposure (which come from the immutable ledger).
  2. Dashboard builds never write to the phase20 ledger or portfolio store
     (write-guard stubs raise if any mutating function is touched).
  3. Mixed case: live marks for some symbols, scan marks for the rest.
  4. No-session fallback: scan marks with mark_stale / mark_note set.

Unlike test_phase4a_marks.py (which uses the real ledger and skips when it
has no open rows), these tests stub the snapshot and ledger loaders so open
positions always exist and every assertion runs.
"""
import copy
import sys
import types
import unittest
from unittest.mock import patch

import phase4a_dashboard as d


SNAP = {
    "scan_id": "scan_t489",
    "snapshot_ts": "2026-08-08T03:00:00+00:00",  # old => scan_stale True
    "summary": {},
    "timings": {},
    "provider_health": {},
    "safety": {},
    "recommendations": [
        {"symbol": "AAA", "entry_price": 100.0, "sector": "IT",
         "final_action": "WATCH"},
        {"symbol": "BBB", "entry_price": 200.0, "sector": "PHARMA",
         "final_action": "WATCH"},
    ],
}

LEDGER = [
    {"trade_id": "t1", "symbol": "AAA", "status": "OPEN",
     "quantity": 10, "fill_price": 95.0, "scan_id": "scan_prev"},
    {"trade_id": "t2", "symbol": "BBB", "status": "OPEN",
     "quantity": 5, "fill_price": 210.0, "scan_id": "scan_prev"},
]


def _write_guard(name):
    def _raise(*a, **k):
        raise AssertionError(f"dashboard build attempted a write via {name}")
    return _raise


def _guarded_portfolio_store():
    """Stub portfolio_store: read constants allowed, all writes forbidden."""
    m = types.ModuleType("portfolio_store")
    m.INITIAL_CAPITAL = 100_000.0
    for fn in ("save_state", "archive_all_trades", "load_state",
               "load_trades", "load_all_trades_any"):
        setattr(m, fn, _write_guard(f"portfolio_store.{fn}"))
    # loads guarded too: the dashboard must source rows via _load_ledger only
    return m


def _guarded_phase20_executor():
    """Stub phase20_executor: any attribute access beyond marker fails."""
    m = types.ModuleType("phase20_executor")
    for fn in ("get_ledger", "record_fill", "record_exit", "execute_entries",
               "save_trade", "update_trade", "insert_trade"):
        setattr(m, fn, _write_guard(f"phase20_executor.{fn}"))
    return m


class Task489Base(unittest.TestCase):
    def setUp(self):
        self.ledger = copy.deepcopy(LEDGER)
        self.snap = copy.deepcopy(SNAP)
        self._patches = [
            patch.object(d, "_load_snapshot", lambda: self.snap),
            patch.object(d, "_load_ledger", lambda: self.ledger),
            patch.object(d, "_build_replay_cached", lambda: None),
            patch.object(d, "_proc_system_metrics",
                         lambda: {"cpu_pct": None, "memory_pct": None,
                                  "memory_used_mb": None}),
            patch.dict(sys.modules, {
                "portfolio_store": _guarded_portfolio_store(),
                "phase20_executor": _guarded_phase20_executor(),
            }),
        ]
        for p in self._patches:
            p.start()
        self._kqp_orig = sys.modules.get("kite_quote_provider")

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        if self._kqp_orig is not None:
            sys.modules["kite_quote_provider"] = self._kqp_orig
        else:
            sys.modules.pop("kite_quote_provider", None)

    def stub_quotes(self, verified, quotes_by_symbol):
        stub = types.ModuleType("kite_quote_provider")
        stub.kite_session_verified = lambda force=False: verified
        stub.get_quotes = (lambda syms, force_refresh=False:
                           {s: quotes_by_symbol[s] for s in syms
                            if s in quotes_by_symbol})
        sys.modules["kite_quote_provider"] = stub

    def build(self):
        return d.build_phase4a_dashboard()


class TestLiveMarksDisplayOnly(Task489Base):
    def test_live_marks_move_unrealized_pnl_only(self):
        self.stub_quotes(True, {
            "AAA": {"ltp": 111.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
            "BBB": {"ltp": 222.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
        })
        op = self.build()["open_positions"]
        pos = {p["symbol"]: p for p in op["positions"]}
        # marks + unrealized P&L come from the live quotes …
        self.assertEqual(pos["AAA"]["mark_price"], 111.0)
        self.assertEqual(pos["AAA"]["mark_source"], "live")
        self.assertEqual(pos["AAA"]["unrealized_pnl"],
                         round((111.0 - 95.0) * 10, 2))
        self.assertEqual(pos["BBB"]["unrealized_pnl"],
                         round((222.0 - 210.0) * 5, 2))
        # … while fill price, cost basis, and exposure stay ledger-derived
        self.assertEqual(pos["AAA"]["fill_price"], 95.0)
        self.assertEqual(pos["AAA"]["cost"], 950.0)
        self.assertEqual(pos["BBB"]["fill_price"], 210.0)
        self.assertEqual(pos["BBB"]["cost"], 1050.0)
        self.assertEqual(op["exposure"], 2000.0)
        self.assertEqual(op["mark_source"], "live quotes (Zerodha Kite)")

    def test_ledger_rows_and_stores_untouched_by_build(self):
        self.stub_quotes(True, {
            "AAA": {"ltp": 111.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
            "BBB": {"ltp": 222.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
        })
        before = copy.deepcopy(self.ledger)
        self.build()  # write-guard stubs raise on any store mutation
        # ledger row dicts must not be mutated in place by the overlay
        self.assertEqual(self.ledger, before)

    def test_repeated_builds_are_idempotent_reads(self):
        self.stub_quotes(True, {
            "AAA": {"ltp": 111.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
        })
        op1 = self.build()["open_positions"]
        op2 = self.build()["open_positions"]
        self.assertEqual(op1["positions"], op2["positions"])
        self.assertEqual(op1["exposure"], op2["exposure"])


class TestMixedAndFallback(Task489Base):
    def test_mixed_live_and_scan_marks(self):
        # live quote only for AAA; BBB falls back to scan entry_price
        self.stub_quotes(True, {
            "AAA": {"ltp": 111.0, "data_source": "kite_live",
                    "fetched_at": "2026-08-08T05:00:00Z"},
        })
        op = self.build()["open_positions"]
        pos = {p["symbol"]: p for p in op["positions"]}
        self.assertEqual(pos["AAA"]["mark_source"], "live")
        self.assertEqual(pos["AAA"]["mark_price"], 111.0)
        self.assertEqual(pos["BBB"]["mark_source"], "scan")
        self.assertEqual(pos["BBB"]["mark_price"], 200.0)
        self.assertEqual(pos["BBB"]["unrealized_pnl"],
                         round((200.0 - 210.0) * 5, 2))
        self.assertIn("BBB", op["mark_note"])
        self.assertTrue(op["mark_stale"])  # scan snapshot is old
        # cost basis still ledger-derived for both
        self.assertEqual(pos["AAA"]["cost"], 950.0)
        self.assertEqual(pos["BBB"]["cost"], 1050.0)

    def test_no_session_fallback_sets_stale_and_note(self):
        self.stub_quotes(False, {})
        op = self.build()["open_positions"]
        self.assertFalse(op["mark_session_verified"])
        self.assertTrue(op["mark_stale"])
        self.assertIn("no live broker session", op["mark_note"])
        for p in op["positions"]:
            self.assertEqual(p["mark_source"], "scan")
        pos = {p["symbol"]: p for p in op["positions"]}
        self.assertEqual(pos["AAA"]["mark_price"], 100.0)
        self.assertEqual(pos["BBB"]["mark_price"], 200.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
