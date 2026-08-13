"""
test_seal_execution_outcomes.py — Unit tests for phase20_executor.seal_execution_outcomes.

Verifies that seal_execution_outcomes:
- emits EXECUTION_SKIPPED_WITH_REASON for every BUY_GENERATED symbol that
  has no terminal execution outcome event
- does NOT emit a duplicate when a terminal event already exists
- handles edge cases: no BUY_GENERATED events, no scan_id, etc.
- returns a correct summary dict in all paths

All tests use the pipeline_events file-fallback (DATABASE_URL absent) and a
temporary fallback file so no DB is required. PAPER TRADING / RESEARCH ONLY.
"""

import os
import unittest
from unittest import mock

import pipeline_events as pe
from phase20_executor import seal_execution_outcomes, _EXECUTION_TERMINAL_TYPES


class SealBase(unittest.TestCase):
    """Base that redirects pipeline_events to a temp file and clears DATABASE_URL."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DATABASE_URL", None)
        self._tmp = pe.FALLBACK_FILE + ".seal_test"
        self._orig = pe.FALLBACK_FILE
        pe.FALLBACK_FILE = self._tmp
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def tearDown(self):
        pe.FALLBACK_FILE = self._orig
        if os.path.exists(self._tmp):
            os.remove(self._tmp)
        self._env.stop()


class TestSealNoScanId(SealBase):
    def test_empty_scan_id_returns_immediately(self):
        result = seal_execution_outcomes("")
        self.assertEqual(result["sealed"], 0)
        self.assertIn("reason", result)

    def test_none_scan_id_returns_immediately(self):
        result = seal_execution_outcomes(None)  # type: ignore[arg-type]
        self.assertEqual(result["sealed"], 0)


class TestSealNoBuyGenerated(SealBase):
    def test_no_buy_generated_seals_nothing(self):
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id="s1")
        result = seal_execution_outcomes("s1")
        self.assertEqual(result["sealed"], 0)
        self.assertEqual(result.get("reason"), "no BUY_GENERATED events")


class TestSealOrphanBuys(SealBase):
    """BUY_GENERATED events with no terminal execution outcome → sealed."""

    def test_single_orphan_is_sealed(self):
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s2", symbol="RELIANCE")
        result = seal_execution_outcomes("s2", reason="auto_paper_entries_off")
        self.assertEqual(result["sealed"], 1)
        self.assertIn("RELIANCE", result["orphans"])
        # Confirm EXECUTION_SKIPPED_WITH_REASON event was emitted
        evs = pe.query_events(scan_id="s2", event_type="EXECUTION_SKIPPED_WITH_REASON",
                               stage="EXECUTION")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["symbol"], "RELIANCE")
        self.assertEqual(evs[0]["payload"]["reason"], "auto_paper_entries_off")

    def test_multiple_orphans_all_sealed(self):
        for sym in ("TCS", "INFY", "HDFCBANK"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s3", symbol=sym)
        result = seal_execution_outcomes("s3")
        self.assertEqual(result["sealed"], 3)
        self.assertEqual(sorted(result["orphans"]), ["HDFCBANK", "INFY", "TCS"])
        sealed_evs = pe.query_events(scan_id="s3",
                                     event_type="EXECUTION_SKIPPED_WITH_REASON",
                                     stage="EXECUTION")
        self.assertEqual(len(sealed_evs), 3)

    def test_symbol_case_normalised(self):
        """Lower-case symbol in BUY_GENERATED must still be found as an orphan."""
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s4", symbol="reliance")
        result = seal_execution_outcomes("s4")
        self.assertEqual(result["sealed"], 1)
        self.assertIn("RELIANCE", result["orphans"])


class TestSealAlreadyHasTerminalEvent(SealBase):
    """When a terminal event already exists the symbol must NOT be re-emitted."""

    def _run_for_terminal(self, terminal_type: str):
        scan_id = f"s_{terminal_type.lower()[:6]}"
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol="TCS")
        pe.emit(terminal_type, "EXECUTION", scan_id=scan_id, symbol="TCS")
        # Capture event count BEFORE seal so we can verify no duplicate is added
        before = pe.query_events(scan_id=scan_id,
                                 event_type="EXECUTION_SKIPPED_WITH_REASON")
        result = seal_execution_outcomes(scan_id)
        self.assertEqual(result["sealed"], 0,
                         msg=f"Should not seal when {terminal_type} exists")
        after = pe.query_events(scan_id=scan_id,
                                event_type="EXECUTION_SKIPPED_WITH_REASON")
        self.assertEqual(len(after), len(before),
                         msg=f"No extra event should be emitted for {terminal_type}")

    def test_order_executed_suppresses_seal(self):
        self._run_for_terminal("ORDER_EXECUTED")

    def test_order_rejected_suppresses_seal(self):
        self._run_for_terminal("ORDER_REJECTED")

    def test_order_cancelled_suppresses_seal(self):
        self._run_for_terminal("ORDER_CANCELLED")

    def test_execution_skipped_suppresses_seal(self):
        self._run_for_terminal("EXECUTION_SKIPPED_WITH_REASON")


class TestSealMixedSymbols(SealBase):
    """Some symbols have terminal events, some don't — only orphans sealed."""

    def test_partial_coverage_sealed_correctly(self):
        scan_id = "s_mix"
        for sym in ("TCS", "INFY", "WIPRO"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol=sym)
        # TCS already has an execution outcome
        pe.emit("ORDER_EXECUTED", "EXECUTION", scan_id=scan_id, symbol="TCS")
        # INFY already skipped
        pe.emit("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                scan_id=scan_id, symbol="INFY")
        # WIPRO is the orphan
        result = seal_execution_outcomes(scan_id, reason="test_mix")
        self.assertEqual(result["sealed"], 1)
        self.assertEqual(result["orphans"], ["WIPRO"])
        sealed = pe.query_events(scan_id=scan_id,
                                 event_type="EXECUTION_SKIPPED_WITH_REASON",
                                 stage="EXECUTION", symbol="WIPRO")
        self.assertEqual(len(sealed), 1)


class TestSealScanIsolation(SealBase):
    """Events from a different scan_id must not pollute the seal check."""

    def test_terminal_event_from_other_scan_does_not_suppress_seal(self):
        # RELIANCE bought in scan s_a
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s_a", symbol="RELIANCE")
        # terminal event for RELIANCE but in a DIFFERENT scan
        pe.emit("ORDER_EXECUTED", "EXECUTION", scan_id="s_b", symbol="RELIANCE")
        # seal for s_a — RELIANCE has no terminal in s_a → should be sealed
        result = seal_execution_outcomes("s_a")
        self.assertEqual(result["sealed"], 1)
        self.assertIn("RELIANCE", result["orphans"])


class TestSealIdempotent(SealBase):
    """Calling seal twice must not produce duplicate events."""

    def test_idempotent_second_call(self):
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s_idem", symbol="SBIN")
        seal_execution_outcomes("s_idem")
        # Second call: SBIN now has EXECUTION_SKIPPED_WITH_REASON → not orphan
        result2 = seal_execution_outcomes("s_idem")
        self.assertEqual(result2["sealed"], 0)
        total = pe.query_events(scan_id="s_idem",
                                event_type="EXECUTION_SKIPPED_WITH_REASON")
        self.assertEqual(len(total), 1, "Duplicate seal event must not be emitted")


class TestSealReasonPropagated(SealBase):
    def test_reason_appears_in_payload(self):
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id="s_reason", symbol="AXISBANK")
        seal_execution_outcomes("s_reason", reason="post_auto_entry_seal")
        evs = pe.query_events(scan_id="s_reason",
                               event_type="EXECUTION_SKIPPED_WITH_REASON",
                               stage="EXECUTION")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["reason"], "post_auto_entry_seal")
        self.assertFalse(evs[0]["payload"]["auto_entry_attempted"])


class TestTerminalTypeSet(unittest.TestCase):
    """Sanity-check the constant so a future rename is caught immediately."""

    def test_required_terminal_types_present(self):
        for t in ("ORDER_EXECUTED", "ORDER_REJECTED", "ORDER_CANCELLED",
                  "EXECUTION_SKIPPED_WITH_REASON"):
            self.assertIn(t, _EXECUTION_TERMINAL_TYPES)


if __name__ == "__main__":
    unittest.main()
