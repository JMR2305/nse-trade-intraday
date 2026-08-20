"""
test_pipeline_events.py — Phase 23 canonical Pipeline Event Store tests.

Runs against the file fallback (DATABASE_URL removed) so tests never touch
the dev database. Covers: append/query filters, batch emit, fail-safety,
stage summary counts, and latest_scan_id.
"""

import json
import os
import unittest
from unittest import mock

import pipeline_events as pe


class PipelineEventsBase(unittest.TestCase):
    def setUp(self):
        # Force file-fallback into a temp file; never touch Postgres.
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DATABASE_URL", None)
        self._tmp = pe.FALLBACK_FILE + ".test"
        self._orig_file = pe.FALLBACK_FILE
        pe.FALLBACK_FILE = self._tmp
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def tearDown(self):
        pe.FALLBACK_FILE = self._orig_file
        if os.path.exists(self._tmp):
            os.remove(self._tmp)
        self._env.stop()


class TestEmitAndQuery(PipelineEventsBase):
    def test_emit_and_query_roundtrip(self):
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="s1",
                payload={"universe_size": 50})
        pe.emit("SYMBOL_SCANNED", "scanner", scan_id="s1", symbol="TCS",
                payload={"bars": 250})
        evs = pe.query_events(scan_id="s1", limit=10)
        self.assertEqual([e["event_type"] for e in evs],
                         ["SCAN_STARTED", "SYMBOL_SCANNED"])
        # stage normalised to upper-case
        self.assertEqual(evs[1]["stage"], "SCANNER")
        self.assertEqual(evs[1]["payload"]["bars"], 250)

    def test_filters(self):
        pe.emit("RISK_REJECTED", "RISK", scan_id="s1", symbol="TCS")
        pe.emit("RISK_APPROVED", "RISK", scan_id="s1", symbol="INFY")
        pe.emit("RISK_REJECTED", "RISK", scan_id="s2", symbol="TCS")
        self.assertEqual(len(pe.query_events(scan_id="s1")), 2)
        self.assertEqual(len(pe.query_events(event_type="RISK_REJECTED")), 2)
        self.assertEqual(len(pe.query_events(symbol="tcs")), 2)
        self.assertEqual(
            len(pe.query_events(scan_id="s1", event_type="RISK_REJECTED")), 1)

    def test_since_id_and_newest_first(self):
        for i in range(5):
            pe.emit("SYMBOL_SCANNED", "SCANNER", scan_id="s1", symbol=f"S{i}")
        evs = pe.query_events(scan_id="s1")
        mid = evs[2]["id"]
        after = pe.query_events(scan_id="s1", since_id=mid)
        self.assertEqual(len(after), 2)
        newest = pe.query_events(scan_id="s1", newest_first=True, limit=1)
        self.assertEqual(newest[0]["symbol"], "S4")

    def test_mode_isolation(self):
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="live1")
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="bt1", mode="BACKTEST",
                run_id="run-9")
        self.assertEqual(len(pe.query_events(mode="LIVE")), 1)
        bt = pe.query_events(mode="BACKTEST")
        self.assertEqual(len(bt), 1)
        self.assertEqual(bt[0]["run_id"], "run-9")
        self.assertEqual(pe.latest_scan_id("LIVE"), "live1")
        self.assertEqual(pe.latest_scan_id("BACKTEST"), "bt1")

    def test_emit_many_batch(self):
        pe.emit_many([
            {"event_type": "SYMBOL_SCANNED", "stage": "SCANNER",
             "scan_id": "s1", "symbol": "A"},
            {"event_type": "SYMBOL_SCANNED", "stage": "SCANNER",
             "scan_id": "s1", "symbol": "B"},
        ])
        self.assertEqual(len(pe.query_events(scan_id="s1")), 2)

    def test_emit_never_raises(self):
        # Point the fallback file somewhere unwritable — emit must swallow it.
        pe.FALLBACK_FILE = "/nonexistent-dir/pe.json"
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="x")   # must not raise
        pe.emit_many([{"event_type": "A", "stage": "SCANNER"}])
        pe.FALLBACK_FILE = self._tmp
        self.assertEqual(pe.query_events(scan_id="x"), [])

    def test_dedupe_key_records_one_durable_event(self):
        """A repeated safety outcome must remain one append-only event."""
        key = "market-close-outcome:2026-08-20:P20-late-trent"
        self.assertTrue(pe.emit(
            "MARKET_CLOSE_EXIT_BLOCKED", "PORTFOLIO",
            symbol="TRENT", payload={"trade_id": "P20-late-trent"},
            dedupe_key=key,
        ))
        self.assertTrue(pe.emit(
            "MARKET_CLOSE_EXIT_BLOCKED", "PORTFOLIO",
            symbol="TRENT", payload={"trade_id": "P20-late-trent"},
            dedupe_key=key,
        ))
        events = pe.query_events(event_type="MARKET_CLOSE_EXIT_BLOCKED")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["symbol"], "TRENT")

    def test_query_returns_empty_on_missing_file(self):
        self.assertEqual(pe.query_events(scan_id="none"), [])


class TestStageSummary(PipelineEventsBase):
    def test_summary_counts(self):
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="s1")
        pe.emit("SYMBOL_SCANNED", "SCANNER", scan_id="s1", symbol="TCS")
        pe.emit("SYMBOL_REJECTED", "SCANNER", scan_id="s1", symbol="INFY",
                payload={"error": "fetch failed"})
        pe.emit("RISK_REJECTED", "RISK", scan_id="s1", symbol="TCS")
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s1", symbol="TCS")
        summ = pe.stage_summary(scan_id="s1")
        by = {s["stage"]: s for s in summ["stages"]}
        self.assertEqual(summ["total_events"], 5)
        self.assertEqual(by["SCANNER"]["completed"], 1)
        self.assertEqual(by["SCANNER"]["rejected"], 1)
        self.assertEqual(by["SCANNER"]["errors"], 1)
        self.assertEqual(by["RISK"]["rejected"], 1)
        self.assertEqual(by["AI_DECISION"]["completed"], 1)
        self.assertEqual(by["SCANNER"]["last_symbol"], "INFY")
        # All 11 canonical stages always present (incl. PORTFOLIO_PRECHECK)
        self.assertEqual(len(summ["stages"]), 11)
        self.assertIn("PORTFOLIO_PRECHECK", by)
        # PORTFOLIO_PRECHECK sits between STRATEGY and RISK in canonical order
        self.assertEqual(
            pe.STAGES.index("PORTFOLIO_PRECHECK"),
            pe.STAGES.index("STRATEGY") + 1)
        self.assertEqual(
            pe.STAGES.index("RISK"),
            pe.STAGES.index("PORTFOLIO_PRECHECK") + 1)

    def test_summary_empty(self):
        summ = pe.stage_summary(scan_id="nope")
        self.assertEqual(summ["total_events"], 0)
        self.assertTrue(all(s["events"] == 0 for s in summ["stages"]))


if __name__ == "__main__":
    unittest.main()
