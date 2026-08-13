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


def _orphan_count(scan_id: str) -> int:
    """Return the number of BUY_GENERATED symbols that have no terminal event.

    This mirrors the exact query the Agent Journey uses to detect orphans:
      orphans = {BUY_GENERATED symbols} - {symbols with a terminal event}
    After a successful seal the result must be 0.
    """
    buys = pe.query_events(scan_id=scan_id, event_type="BUY_GENERATED", limit=200)
    buy_symbols = {str(e["symbol"]).upper() for e in buys if e.get("symbol")}
    if not buy_symbols:
        return 0
    terminal_symbols: set = set()
    for et in _EXECUTION_TERMINAL_TYPES:
        evs = pe.query_events(scan_id=scan_id, event_type=et,
                              stage="EXECUTION", limit=200)
        terminal_symbols.update(
            str(e["symbol"]).upper() for e in evs if e.get("symbol")
        )
    return len(buy_symbols - terminal_symbols)


class TestOrphanCheckQueryReturnsZero(SealBase):
    """Core regression: after seal_execution_outcomes runs, the orphan-check
    query must return 0 rows — for every call pattern.

    This is the direct guard for the 'last scan of session' boundary described
    in Task #680: the orphan-check query is BUY_GENERATED minus terminal events;
    the seal guarantees that set is empty.
    """

    def test_orphan_count_zero_after_seal_auto_entries_off(self):
        """auto_paper_entries OFF path — seal_execution_outcomes fills the gap."""
        scan_id = "q_auto_off"
        for sym in ("RELIANCE", "TCS", "INFY"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol=sym)

        # Before seal: 3 orphans
        self.assertEqual(_orphan_count(scan_id), 3)

        seal_execution_outcomes(scan_id, reason="auto_paper_entries_off")

        # After seal: 0 orphans
        self.assertEqual(_orphan_count(scan_id), 0,
                         "Orphan-check query must return 0 rows after seal")

    def test_orphan_count_zero_after_seal_some_executed(self):
        """Some symbols executed, some skipped — all must have a terminal event."""
        scan_id = "q_partial"
        for sym in ("HDFCBANK", "WIPRO", "SBIN"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol=sym)
        # HDFCBANK got an actual order
        pe.emit("ORDER_EXECUTED", "EXECUTION", scan_id=scan_id, symbol="HDFCBANK")
        # WIPRO was rejected by the risk gate
        pe.emit("ORDER_REJECTED", "EXECUTION", scan_id=scan_id, symbol="WIPRO")
        # SBIN is the orphan — no executor tick fired for it

        self.assertEqual(_orphan_count(scan_id), 1)   # just SBIN

        seal_execution_outcomes(scan_id, reason="post_auto_entry_seal")

        self.assertEqual(_orphan_count(scan_id), 0)

    def test_orphan_count_zero_when_no_buys(self):
        """No BUY_GENERATED events → orphan count is already 0; seal is a no-op."""
        scan_id = "q_no_buys"
        pe.emit("SCAN_STARTED", "SUPERVISOR", scan_id=scan_id)

        self.assertEqual(_orphan_count(scan_id), 0)
        result = seal_execution_outcomes(scan_id)
        self.assertEqual(result["sealed"], 0)
        self.assertEqual(_orphan_count(scan_id), 0)

    def test_orphan_count_zero_after_repeated_calls(self):
        """Idempotency: calling seal twice must not create extra events and
        must keep orphan count at 0."""
        scan_id = "q_idem"
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol="AXISBANK")

        seal_execution_outcomes(scan_id, reason="first_call")
        self.assertEqual(_orphan_count(scan_id), 0)

        # Second call (simulates a retry after process restart or late tick)
        result2 = seal_execution_outcomes(scan_id, reason="second_call")
        self.assertEqual(result2["sealed"], 0,
                         "Second seal must not emit duplicate events")
        self.assertEqual(_orphan_count(scan_id), 0,
                         "Orphan count must remain 0 after repeated seal")
        total_terminal = pe.query_events(
            scan_id=scan_id, event_type="EXECUTION_SKIPPED_WITH_REASON")
        self.assertEqual(len(total_terminal), 1,
                         "Exactly one terminal event must exist, not two")


class TestPostCloseSealBoundary(SealBase):
    """Confirms the 'last tick of session' boundary:

    When the scheduler tick fires after 15:30 (mstate=POST_CLOSE), the
    _manage_paper() path is bypassed. The post-close seal must still run and
    produce 0 orphans for the last scan's BUY_GENERATED events.

    These tests call seal_execution_outcomes() directly with a scan_id derived
    via the same build_scan_context() fallback path the scheduler uses when
    auto_paper_entries is OFF.  The scheduler code that calls this is:

        from phase15_scan_context import build_scan_context as _bsc
        _seal_scan_id = (_bsc() or {}).get("scan_id")
        seal_execution_outcomes(_seal_scan_id, reason="post_close_seal")
    """

    def test_post_close_seal_clears_all_orphans(self):
        """Simulate the last scan BUYs arriving, then a post-close seal tick."""
        scan_id = "pc_last_scan"
        for sym in ("MARUTI", "BAJFINANCE"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol=sym)

        # Market closed; no executor tick ran. Orphan count is 2.
        self.assertEqual(_orphan_count(scan_id), 2)

        # Post-close seal (the scheduler uses build_scan_context to get this id)
        result = seal_execution_outcomes(scan_id, reason="post_close_seal")

        self.assertEqual(result["sealed"], 2)
        self.assertEqual(sorted(result["orphans"]), ["BAJFINANCE", "MARUTI"])
        self.assertEqual(result["reason"], "post_close_seal")
        self.assertEqual(_orphan_count(scan_id), 0,
                         "Orphan-check query must return 0 after post-close seal")

    def test_post_close_seal_when_scan_id_none_is_noop(self):
        """If build_scan_context returns no scan_id (e.g. first day, no scans yet),
        the seal must not raise and must return sealed=0."""
        result = seal_execution_outcomes(None, reason="post_close_seal")  # type: ignore
        self.assertEqual(result["sealed"], 0)
        self.assertIn("reason", result)

    def test_post_close_seal_already_sealed_by_open_tick_is_idempotent(self):
        """If the OPEN tick already sealed the scan (normal path), the post-close
        tick calling seal again must return sealed=0 (no duplicate events)."""
        scan_id = "pc_already_sealed"
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol="HINDUNILVR")

        # OPEN tick sealed it
        r1 = seal_execution_outcomes(scan_id, reason="auto_paper_entries_off")
        self.assertEqual(r1["sealed"], 1)
        self.assertEqual(_orphan_count(scan_id), 0)

        # POST_CLOSE tick tries again — must be a no-op
        r2 = seal_execution_outcomes(scan_id, reason="post_close_seal")
        self.assertEqual(r2["sealed"], 0,
                         "Post-close seal must be a no-op when OPEN tick already sealed")
        self.assertEqual(_orphan_count(scan_id), 0)

    def test_post_close_seal_does_not_affect_other_scans(self):
        """The seal for one scan_id must not emit events for a different scan."""
        scan_a = "pc_scan_a"
        scan_b = "pc_scan_b"
        for sym in ("ICICIBANK", "KOTAKBANK"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_a, symbol=sym)
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_b, symbol="TITAN")

        # Seal only scan_a (post-close)
        seal_execution_outcomes(scan_a, reason="post_close_seal")

        # scan_a orphans gone
        self.assertEqual(_orphan_count(scan_a), 0)
        # scan_b is untouched — still 1 orphan
        self.assertEqual(_orphan_count(scan_b), 1,
                         "Post-close seal must not affect events from other scans")


class TestSkippedActiveScanBoundary(SealBase):
    """Confirms the SKIPPED_ACTIVE_SCAN boundary:

    When a tick skips because another scan is in progress, _manage_paper()
    is not called and no seal runs.  This is CORRECT: the active scan has not
    yet emitted all its BUY_GENERATED events — sealing now would produce false
    EXECUTION_SKIPPED_WITH_REASON events for symbols that are still being
    evaluated.

    The seal must run on the NEXT tick once the active scan completes.
    """

    def test_seal_not_called_mid_scan_orphans_remain(self):
        """While a scan is in progress (no final scan_id yet), orphans remain."""
        scan_id = "skip_scan"
        pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol="ONGC")

        # Mid-scan: seal is intentionally skipped (no scan_id from context yet).
        # We simulate this by not calling seal at all, as the scheduler does
        # when it returns early on SKIPPED_ACTIVE_SCAN.
        self.assertEqual(_orphan_count(scan_id), 1,
                         "Orphan must remain while scan is still active")

    def test_seal_runs_after_scan_completes_clearing_orphans(self):
        """Once the scan completes and returns its scan_id, the next tick seals."""
        scan_id = "skip_then_seal"
        for sym in ("POWERGRID", "NTPC"):
            pe.emit("BUY_GENERATED", "AI_DECISION", scan_id=scan_id, symbol=sym)

        # Tick fires while SKIPPED_ACTIVE_SCAN → seal not called (orphans = 2).
        self.assertEqual(_orphan_count(scan_id), 2)

        # Next tick: scan completed, scan_id now available → seal runs.
        result = seal_execution_outcomes(scan_id, reason="post_auto_entry_seal")
        self.assertEqual(result["sealed"], 2)
        self.assertEqual(_orphan_count(scan_id), 0,
                         "Orphan-check must return 0 once seal fires after scan completes")


class TestPersistSealResultKv(unittest.TestCase):
    """Unit tests for _persist_seal_result() idempotency guard.

    All four phase20_store KV/notification functions are mocked via
    unittest.mock.patch so no real files (phase20_kv.json,
    phase20_notifications.json) or DB connections are touched.

    Verifies the three properties the reviewer required:
    1. OPEN tick stores the nonzero seal; POST_CLOSE idempotent call (same
       scan_id, sealed=0) does NOT overwrite the record.
    2. A seal error is persisted with an 'error' field so the UI can show
       'unavailable' instead of a misleading zero.
    3. A new scan_id with sealed=0 (clean session) still advances the record.
    """

    def _make_claim_fn(self, claimed: set):
        """Returns a kv_claim_once side_effect that is True only on the first claim."""
        def _claim(key: str) -> bool:
            if key in claimed:
                return False
            claimed.add(key)
            return True
        return _claim

    def _run_persist(
        self,
        seal_result: dict,
        scan_id: str,
        reason: str,
        *,
        kv_store: dict,
        claimed: set,
        notifications: list,
    ) -> None:
        """Call _persist_seal_result with mocked store layer."""
        from phase20_scheduler import _persist_seal_result
        with (
            mock.patch("phase20_store.kv_get", side_effect=lambda k: kv_store.get(k)),
            mock.patch("phase20_store.kv_set", side_effect=lambda k, v: kv_store.update({k: v})),
            mock.patch("phase20_store.kv_claim_once", side_effect=self._make_claim_fn(claimed)),
            mock.patch("phase20_store.add_notification",
                       side_effect=lambda *a, **kw: notifications.append((a, kw))),
        ):
            _persist_seal_result(seal_result, scan_id, reason)

    # ------------------------------------------------------------------

    def test_open_tick_nonzero_seal_is_stored(self):
        """OPEN-path seal with sealed=2 must be written to KV."""
        kv: dict = {}
        self._run_persist(
            {"sealed": 2, "scan_id": "op1", "orphans": ["RELIANCE", "TCS"]},
            "op1", "auto_paper_entries_off",
            kv_store=kv, claimed=set(), notifications=[],
        )
        stored = kv.get("last_execution_seal") or {}
        self.assertEqual(stored.get("sealed"), 2)
        self.assertIn("RELIANCE", stored.get("orphans", []))
        self.assertEqual(stored.get("scan_id"), "op1")

    def test_post_close_idempotent_zero_preserves_nonzero_open_record(self):
        """POST_CLOSE tick (same scan_id, sealed=0) must NOT overwrite sealed=2.

        seal_execution_outcomes() is idempotent: the POST_CLOSE call for the
        same scan_id always returns 0 because the OPEN tick already handled the
        orphans.  The KV record must still show the real nonzero count so
        operators can see the gap that occurred.
        """
        kv: dict = {}
        claimed: set = set()
        notifs: list = []

        # OPEN tick: seal 2 orphans.
        self._run_persist(
            {"sealed": 2, "scan_id": "idem1", "orphans": ["INFY", "WIPRO"]},
            "idem1", "auto_paper_entries_off",
            kv_store=kv, claimed=claimed, notifications=notifs,
        )
        self.assertEqual(kv["last_execution_seal"]["sealed"], 2)

        # POST_CLOSE tick: idempotent call returns sealed=0 for same scan_id.
        self._run_persist(
            {"sealed": 0, "scan_id": "idem1", "orphans": []},
            "idem1", "post_close_seal",
            kv_store=kv, claimed=claimed, notifications=notifs,
        )
        self.assertEqual(
            kv["last_execution_seal"]["sealed"], 2,
            "Idempotent POST_CLOSE zero must not overwrite the nonzero OPEN record",
        )
        self.assertIn("INFY", kv["last_execution_seal"]["orphans"])

    def test_seal_error_is_stored_with_error_field(self):
        """A seal result with an 'error' key must be stored including that field.

        Without this, an internal failure inside seal_execution_outcomes()
        (which returns sealed=0 on error) would look identical to a clean zero,
        making the dashboard silently claim full coverage.
        """
        kv: dict = {}
        self._run_persist(
            {"sealed": 0, "scan_id": "err1", "orphans": [],
             "error": "DB connection lost"},
            "err1", "auto_paper_entries_off",
            kv_store=kv, claimed=set(), notifications=[],
        )
        stored = kv.get("last_execution_seal") or {}
        self.assertIn("error", stored,
                      "Error field must be propagated into the stored KV record")
        self.assertEqual(stored["error"], "DB connection lost")
        self.assertEqual(stored.get("scan_id"), "err1")

    def test_new_scan_id_with_zero_advances_stored_record(self):
        """A new scan_id with sealed=0 (clean session) must replace the old record.

        Operators need to see coverage data for the *current* scan, not a
        stale record from the previous session.
        """
        kv: dict = {}
        claimed: set = set()
        notifs: list = []

        # Seed an old-scan record.
        self._run_persist(
            {"sealed": 0, "scan_id": "old1", "orphans": []},
            "old1", "auto_paper_entries_off",
            kv_store=kv, claimed=claimed, notifications=notifs,
        )
        self.assertEqual(kv["last_execution_seal"]["scan_id"], "old1")

        # New session, clean scan — sealed=0 but a genuinely new scan_id.
        self._run_persist(
            {"sealed": 0, "scan_id": "new1", "orphans": []},
            "new1", "auto_paper_entries_off",
            kv_store=kv, claimed=claimed, notifications=notifs,
        )
        self.assertEqual(
            kv["last_execution_seal"]["scan_id"], "new1",
            "New scan_id with sealed=0 must advance the stored record",
        )


if __name__ == "__main__":
    unittest.main()
