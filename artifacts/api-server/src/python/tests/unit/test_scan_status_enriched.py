"""
test_scan_status_enriched.py — Unit tests for scan_state_store enrichment.

Tests the actual production functions (not reimplemented copies):
  - build_scan_status_response()  — exercises the real dispatch-level function
  - count_scans_today_ist()       — IST boundary logic, DB edge cases

Both are the same code invoked by main.py's ``scan_status`` command, so these
tests provide genuine regression coverage of the endpoint.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers — shared fixtures
# ---------------------------------------------------------------------------

_META_FIXTURE = {
    "scan_id": "abc123",
    "status": "SUCCESS",
    "snapshot_ts": "2026-08-14T04:00:00Z",
    "provider": "yahoo_finance",
    "symbols_requested": 51,
    "symbols_received": 50,
}

_PROGRESS_FIXTURE = {
    "stage": "FETCHING",
    "scan_id": "abc123",
    "symbols_total": 51,
    "symbols_done": 20,
    "current_symbol": "RELIANCE.NS",
    "started_at": "2026-08-14T04:25:00Z",
}


# ---------------------------------------------------------------------------
# 1.  build_scan_status_response() — dispatch-level tests
#     These exercise the real production function in scan_state_store, which
#     is the exact code called by main.py's scan_status branch.
# ---------------------------------------------------------------------------

class TestBuildScanStatusResponse(unittest.TestCase):
    """
    Tests for scan_state_store.build_scan_status_response().

    All DB / KV calls are mocked so tests are hermetic.
    """

    def _call(
        self,
        *,
        meta=None,
        count_today: int = 3,
        started_today: int | None = None,
        scheduler_ticks_today: int = 0,
        lock_busy_skips_today: int = 0,
        cadence: int = 5,
        progress=None,
        now_utc: datetime | None = None,
    ) -> dict:
        """
        Call the real build_scan_status_response() with mocked dependencies.
        """
        import scan_state_store as sss

        if meta is None:
            meta = dict(_META_FIXTURE)
        if now_utc is None:
            # 30 minutes after the snapshot_ts fixture (04:00 Z → 04:30 Z)
            now_utc = datetime(2026, 8, 14, 4, 30, 0, tzinfo=timezone.utc)
        if started_today is None:
            started_today = count_today

        with patch.object(sss, "load_latest_meta", return_value=meta), \
             patch.object(
                 sss,
                 "scan_observability_counts_today_ist",
                 return_value={
                     "completed_scans_today": count_today,
                     "started_scans_today": started_today,
                     "scheduler_ticks_today": scheduler_ticks_today,
                     "lock_busy_skips_today": lock_busy_skips_today,
                 },
             ), \
             patch.object(sss, "_now_utc", return_value=now_utc), \
             patch("phase20_store.get_settings",
                   return_value={"scan_interval_minutes": cadence}), \
              patch("phase20_store.get_scheduler_health", return_value={
                    "owner": "test-host:123",
                    "process_start_at": "2026-08-14T03:00:00Z",
                    "status": "OK",
                    "heartbeat_at": "2026-08-14T04:30:00Z",
              }), \
             patch("phase20_store.kv_get", return_value=progress):
            return sss.build_scan_status_response()

    # ── Structure ────────────────────────────────────────────────────────────

    def test_success_flag_is_true(self):
        self.assertTrue(self._call()["success"])

    def test_all_required_keys_present(self):
        expected = {"success", "latest_scan", "age_minutes",
                    "scan_count_today", "rotation", "completed_scans_today",
                    "started_scans_today", "scheduler_ticks_today",
                    "lock_busy_skips_today", "runtime", "cadence_minutes", "progress"}
        self.assertTrue(expected.issubset(self._call().keys()),
                        f"Missing: {expected - self._call().keys()}")

    def test_latest_scan_is_the_meta_returned_by_load_latest_meta(self):
        meta = dict(_META_FIXTURE)
        r = self._call(meta=meta)
        self.assertEqual(r["latest_scan"], meta)

    # ── age_minutes ──────────────────────────────────────────────────────────

    def test_age_minutes_is_30_when_30_min_after_snapshot(self):
        snap_ts = "2026-08-14T04:00:00Z"
        now = datetime(2026, 8, 14, 4, 30, 0, tzinfo=timezone.utc)
        r = self._call(meta={"snapshot_ts": snap_ts}, now_utc=now)
        self.assertAlmostEqual(r["age_minutes"], 30.0, places=0)

    def test_age_minutes_is_none_when_snapshot_ts_is_missing(self):
        r = self._call(meta={"scan_id": "x", "snapshot_ts": None})
        self.assertIsNone(r["age_minutes"])

    def test_age_minutes_is_none_for_unparseable_ts(self):
        r = self._call(meta={"snapshot_ts": "not-a-date"})
        self.assertIsNone(r["age_minutes"])

    def test_age_minutes_falls_back_to_completed_at_when_no_snapshot_ts(self):
        snap_ts = "2026-08-14T04:00:00Z"
        now = datetime(2026, 8, 14, 4, 10, 0, tzinfo=timezone.utc)
        r = self._call(meta={"snapshot_ts": None, "completed_at": snap_ts}, now_utc=now)
        self.assertAlmostEqual(r["age_minutes"], 10.0, places=0)

    # ── scan_count_today / rotation ──────────────────────────────────────────

    def test_scan_count_today_equals_count_scans_today_ist_return_value(self):
        self.assertEqual(self._call(count_today=7)["scan_count_today"], 7)

    def test_explicit_observability_counts_remain_separate(self):
        r = self._call(
            count_today=4,
            started_today=6,
            scheduler_ticks_today=7,
            lock_busy_skips_today=2,
        )
        self.assertEqual(r["completed_scans_today"], 4)
        self.assertEqual(r["started_scans_today"], 6)
        self.assertEqual(r["scheduler_ticks_today"], 7)
        self.assertEqual(r["lock_busy_skips_today"], 2)
        self.assertEqual(r["scan_count_today"], 4)  # compatibility alias only

    def test_runtime_is_scheduler_identity_not_a_scan_count(self):
        r = self._call()
        self.assertEqual(r["runtime"]["owner"], "test-host:123")
        self.assertEqual(r["runtime"]["status"], "OK")

    def test_rotation_always_equals_scan_count_today(self):
        r = self._call(count_today=12)
        self.assertEqual(r["rotation"], r["scan_count_today"])

    def test_scan_count_zero_is_valid(self):
        r = self._call(count_today=0)
        self.assertEqual(r["scan_count_today"], 0)
        self.assertEqual(r["rotation"], 0)

    # ── cadence_minutes ──────────────────────────────────────────────────────

    def test_cadence_minutes_comes_from_settings(self):
        self.assertEqual(self._call(cadence=4)["cadence_minutes"], 4)

    def test_cadence_minutes_default_is_5(self):
        self.assertEqual(self._call(cadence=5)["cadence_minutes"], 5)

    def test_cadence_minutes_is_none_when_settings_raises(self):
        import scan_state_store as sss
        with patch.object(sss, "load_latest_meta", return_value=_META_FIXTURE), \
              patch.object(sss, "scan_observability_counts_today_ist", return_value={
                  "completed_scans_today": 0, "started_scans_today": 0,
                  "scheduler_ticks_today": 0, "lock_busy_skips_today": 0,
              }), \
             patch.object(sss, "_now_utc",
                          return_value=datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)), \
             patch("phase20_store.get_settings", side_effect=RuntimeError("db down")), \
              patch("phase20_store.get_scheduler_health", return_value={}), \
             patch("phase20_store.kv_get", return_value=None):
            r = sss.build_scan_status_response()
        self.assertIsNone(r["cadence_minutes"])

    # ── progress ─────────────────────────────────────────────────────────────

    def test_progress_is_none_when_scanner_idle(self):
        self.assertIsNone(self._call(progress=None)["progress"])

    def test_progress_dict_returned_when_scan_in_flight(self):
        r = self._call(progress=_PROGRESS_FIXTURE)
        self.assertIsNotNone(r["progress"])
        self.assertEqual(r["progress"]["stage"], "FETCHING")
        self.assertEqual(r["progress"]["current_symbol"], "RELIANCE.NS")

    def test_progress_non_dict_is_coerced_to_none(self):
        # kv_get may return a non-dict (e.g. a JSON null decoded as None string)
        for bad in ("null", 42, [], True):
            with self.subTest(bad=bad):
                self.assertIsNone(self._call(progress=bad)["progress"])


# ---------------------------------------------------------------------------
# 2.  count_scans_today_ist() — IST boundary and DB edge-case tests
# ---------------------------------------------------------------------------

class TestCountScansToday(unittest.TestCase):
    """
    Unit tests for scan_state_store.count_scans_today_ist().

    Covers the IST midnight cutoff on BOTH sides of 18:30 UTC (the rollover
    point where IST's calendar day changes while UTC's does not).
    """

    # ── Short-circuit: DB unavailable ────────────────────────────────────────

    def test_returns_zero_when_db_unavailable(self):
        import scan_state_store as sss
        with patch.object(sss, "db_available", return_value=False):
            self.assertEqual(sss.count_scans_today_ist(), 0)

    def test_returns_zero_on_db_connection_error(self):
        import scan_state_store as sss
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", side_effect=RuntimeError("conn refused")):
            self.assertEqual(sss.count_scans_today_ist(), 0)

    # ── DB query and result handling ─────────────────────────────────────────

    def _make_mock_conn(self, rows):
        """Return a mock psycopg2 connection whose cursor yields grouped rows."""
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = rows
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        return mock_conn, mock_cur

    def test_returns_count_from_pipeline_events(self):
        import scan_state_store as sss
        mock_conn, _ = self._make_mock_conn([
            ("SCAN_COMPLETED", 5), ("SCAN_STARTED", 6),
            ("SCHEDULER_TICK", 7), ("SCAN_SKIPPED_BUSY", 1),
        ])
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn):
            self.assertEqual(sss.count_scans_today_ist(), 5)

    def test_query_targets_all_durable_scan_observability_event_types(self):
        import scan_state_store as sss
        mock_conn, mock_cur = self._make_mock_conn([])
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn):
            result = sss.scan_observability_counts_today_ist()
        sql = str(mock_cur.execute.call_args)
        self.assertIn("SCAN_COMPLETED", sql)
        self.assertIn("SCAN_STARTED", sql)
        self.assertIn("SCHEDULER_TICK", sql)
        self.assertIn("SCAN_SKIPPED_BUSY", sql)
        self.assertEqual(result["completed_scans_today"], 0)

    def test_returns_zero_when_query_has_no_rows(self):
        import scan_state_store as sss
        mock_conn, _ = self._make_mock_conn([])
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn):
            self.assertEqual(sss.count_scans_today_ist(), 0)

    def test_returns_zero_when_pipeline_events_table_missing(self):
        import scan_state_store as sss
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.execute.side_effect = Exception(
            "relation pipeline_events does not exist")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn):
            self.assertEqual(sss.count_scans_today_ist(), 0)

    # ── IST midnight cutoff: BOTH sides of 18:30 UTC ─────────────────────────
    #
    # The correct algorithm is:
    #   now_ist  = now_utc + 05:30
    #   cutoff   = (now_ist date at 00:00) - 05:30  [back to UTC]
    #
    # BEFORE 18:30 UTC: now_utc and now_ist are on the same IST day.
    #   e.g. now_utc=2026-08-14 05:00 → now_ist=2026-08-14 10:30
    #        IST midnight → 2026-08-14 00:00 IST = 2026-08-13 18:30 UTC ✓
    #
    # AFTER 18:30 UTC: IST has already rolled into the next calendar day.
    #   e.g. now_utc=2026-08-14 20:00 → now_ist=2026-08-15 01:30
    #        IST midnight → 2026-08-15 00:00 IST = 2026-08-14 18:30 UTC ✓
    #   The WRONG (previous) algorithm would return 2026-08-13 18:30 UTC here.

    def _capture_cutoff(self, now_utc: datetime) -> datetime:
        """Run count_scans_today_ist with a fixed 'now' and capture the cutoff
        passed to the SQL query."""
        import scan_state_store as sss

        captured: list[datetime] = []
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []

        def capture_execute(sql, params):
            captured.append(params[0])

        mock_cur.execute.side_effect = capture_execute
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn), \
             patch.object(sss, "_now_utc", return_value=now_utc):
            sss.count_scans_today_ist()

        self.assertTrue(captured, "execute() was never called — cutoff not captured")
        return captured[0]

    def test_cutoff_before_1830_utc_is_previous_day_at_1830(self):
        """
        Before 18:30 UTC: IST is still on the same UTC calendar date.
        now_utc = 2026-08-14 05:00 → IST = 10:30 (Aug 14)
        IST midnight = Aug 14 00:00 IST = Aug 13 18:30 UTC.
        """
        now_utc = datetime(2026, 8, 14, 5, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 8, 13, 18, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(self._capture_cutoff(now_utc), expected)

    def test_cutoff_after_1830_utc_advances_to_same_day_at_1830(self):
        """
        After 18:30 UTC: IST has rolled to the next calendar day.
        now_utc = 2026-08-14 20:00 → IST = 01:30 (Aug 15)
        IST midnight = Aug 15 00:00 IST = Aug 14 18:30 UTC.
        The old algorithm (subtract 5h30m from UTC midnight) would wrongly
        return Aug 13 18:30 UTC — an entire IST day behind.
        """
        now_utc = datetime(2026, 8, 14, 20, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 8, 14, 18, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(self._capture_cutoff(now_utc), expected)

    def test_cutoff_exactly_at_1830_utc_is_same_day_at_1830(self):
        """
        Exactly 18:30 UTC = exactly IST midnight (00:00 next IST day).
        Cutoff should be the same 18:30 UTC (current day), not 24 h earlier.
        """
        now_utc = datetime(2026, 8, 14, 18, 30, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 8, 14, 18, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(self._capture_cutoff(now_utc), expected)

    def test_cutoff_at_1829_utc_is_previous_day_at_1830(self):
        """
        One minute before rollover: IST is 23:59, still Aug 14.
        Cutoff = Aug 13 18:30 UTC.
        """
        now_utc = datetime(2026, 8, 14, 18, 29, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 8, 13, 18, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(self._capture_cutoff(now_utc), expected)


if __name__ == "__main__":
    unittest.main()
