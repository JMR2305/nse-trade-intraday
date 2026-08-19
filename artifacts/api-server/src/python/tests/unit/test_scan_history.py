"""
test_scan_history.py — Unit tests for scan_state_store.build_scan_history_response().

Covers:
  - Aggregation logic: pairing STARTED/COMPLETED, duration, gap computation
  - Edge cases: empty, single entry, missing STARTED, limit clipping
  - DB unavailability and connection errors (fail-safe → empty)
  - IST day boundary: cutoff passed correctly to the SQL query

All DB calls are mocked; tests are fully hermetic.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(utc_str: str) -> datetime:
    """Parse an ISO-8601 UTC string to a timezone-aware datetime."""
    return datetime.fromisoformat(utc_str.replace("Z", "+00:00"))


def _make_rows(*events: tuple) -> list:
    """Build mock DB rows: list of (ts: datetime, event_type: str, payload: dict)."""
    return list(events)


def _call(
    rows: list,
    *,
    limit: int = 10,
    now_utc: datetime | None = None,
) -> dict:
    """
    Call the real build_scan_history_response() with a mocked DB cursor that
    returns `rows` and an optional fixed 'now' for IST cutoff computation.
    """
    import scan_state_store as sss

    if now_utc is None:
        now_utc = datetime(2026, 8, 14, 9, 0, 0, tzinfo=timezone.utc)  # 14:30 IST

    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch.object(sss, "db_available", return_value=True), \
         patch.object(sss, "_connect", return_value=mock_conn), \
         patch.object(sss, "_now_utc", return_value=now_utc):
        return sss.build_scan_history_response(limit=limit)


# ---------------------------------------------------------------------------
# 1. Basic structure
# ---------------------------------------------------------------------------

class TestBuildScanHistoryStructure(unittest.TestCase):

    def test_success_flag_is_true_on_empty(self):
        r = _call([])
        self.assertTrue(r["success"])

    def test_history_is_empty_list_when_no_events(self):
        r = _call([])
        self.assertEqual(r["history"], [])
        self.assertEqual(r["count"], 0)

    def test_ist_date_present(self):
        r = _call([])
        self.assertRegex(r["ist_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_all_required_keys_present(self):
        r = _call([])
        for k in ("success", "history", "count", "total_completed", "ist_date"):
            self.assertIn(k, r)

    def test_total_completed_is_not_limited_to_visible_history_rows(self):
        rows = []
        start = _dt("2026-08-14T04:00:00Z")
        for i in range(3):
            began = start + timedelta(minutes=i * 5)
            rows.extend([
                (began, "SCAN_STARTED", {}),
                (began + timedelta(minutes=1), "SCAN_COMPLETED", {}),
            ])
        r = _call(rows, limit=2)
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["total_completed"], 3)

    def test_db_unavailable_returns_empty(self):
        import scan_state_store as sss
        with patch.object(sss, "db_available", return_value=False):
            r = sss.build_scan_history_response()
        self.assertTrue(r["success"])
        self.assertEqual(r["history"], [])
        self.assertEqual(r["count"], 0)

    def test_db_connection_error_returns_empty(self):
        import scan_state_store as sss
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", side_effect=RuntimeError("refused")):
            r = sss.build_scan_history_response()
        self.assertTrue(r["success"])
        self.assertEqual(r["history"], [])


# ---------------------------------------------------------------------------
# 2. Single scan pairing
# ---------------------------------------------------------------------------

class TestSingleScan(unittest.TestCase):

    def _rows_one_scan(self):
        return _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:05:30Z"), "SCAN_COMPLETED", {"symbols_done": 51}),
        )

    def test_single_scan_produces_one_entry(self):
        r = _call(self._rows_one_scan())
        self.assertEqual(r["count"], 1)
        self.assertEqual(len(r["history"]), 1)

    def test_single_scan_duration_is_330s(self):
        r = _call(self._rows_one_scan())
        self.assertEqual(r["history"][0]["duration_s"], 330)

    def test_single_scan_gap_is_none(self):
        """First scan of the day has no gap-from-previous."""
        r = _call(self._rows_one_scan())
        self.assertIsNone(r["history"][0]["gap_from_prev_s"])

    def test_single_scan_status_is_completed(self):
        r = _call(self._rows_one_scan())
        self.assertEqual(r["history"][0]["status"], "COMPLETED")

    def test_single_scan_symbols_from_payload(self):
        r = _call(self._rows_one_scan())
        self.assertEqual(r["history"][0]["symbols_scanned"], 51)

    def test_single_scan_timestamps_present(self):
        r = _call(self._rows_one_scan())
        entry = r["history"][0]
        self.assertEqual(entry["started_at"],   "2026-08-14T04:00:00Z")
        self.assertEqual(entry["completed_at"], "2026-08-14T04:05:30Z")

    def test_completed_only_no_started_gives_none_duration(self):
        """SCAN_COMPLETED without a matching SCAN_STARTED: duration = None."""
        rows = _make_rows(
            (_dt("2026-08-14T04:05:30Z"), "SCAN_COMPLETED", {}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 1)
        self.assertIsNone(r["history"][0]["duration_s"])
        self.assertIsNone(r["history"][0]["started_at"])


# ---------------------------------------------------------------------------
# 3. Multiple scans — gap computation
# ---------------------------------------------------------------------------

class TestMultipleScans(unittest.TestCase):

    def _rows_three_scans(self):
        """
        Scan 1: start 04:00 → complete 04:05  (5 min, 330 s)
        Scan 2: start 04:09 → complete 04:14  (5 min, 300 s); gap = 4 min = 240 s
        Scan 3: start 04:18 → complete 04:24  (6 min, 360 s); gap = 4 min = 240 s
        """
        return _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", {"symbols_done": 50}),
            (_dt("2026-08-14T04:09:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:14:00Z"), "SCAN_COMPLETED", {"symbols_done": 51}),
            (_dt("2026-08-14T04:18:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:24:00Z"), "SCAN_COMPLETED", {"symbols_done": 49}),
        )

    def test_three_scans_count(self):
        r = _call(self._rows_three_scans())
        self.assertEqual(r["count"], 3)

    def test_newest_first_ordering(self):
        """History must be newest-first (scan 3, scan 2, scan 1)."""
        r = _call(self._rows_three_scans())
        times = [e["completed_at"] for e in r["history"]]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_scan1_gap_is_none(self):
        """Oldest scan has no gap-from-previous."""
        r = _call(self._rows_three_scans())
        oldest = r["history"][-1]  # newest-first, so oldest is last
        self.assertIsNone(oldest["gap_from_prev_s"])

    def test_scan2_gap_is_240s(self):
        """Scan 2 gap = 04:09 - 04:05 = 4 min = 240 s."""
        r = _call(self._rows_three_scans())
        middle = r["history"][1]  # second-newest
        self.assertEqual(middle["gap_from_prev_s"], 240)

    def test_scan3_gap_is_240s(self):
        """Scan 3 gap = 04:18 - 04:14 = 4 min = 240 s."""
        r = _call(self._rows_three_scans())
        newest = r["history"][0]
        self.assertEqual(newest["gap_from_prev_s"], 240)

    def test_durations_correct(self):
        r = _call(self._rows_three_scans())
        durations = {e["completed_at"]: e["duration_s"] for e in r["history"]}
        self.assertEqual(durations["2026-08-14T04:05:00Z"], 300)
        self.assertEqual(durations["2026-08-14T04:14:00Z"], 300)
        self.assertEqual(durations["2026-08-14T04:24:00Z"], 360)

    def test_symbols_from_each_completed_payload(self):
        r = _call(self._rows_three_scans())
        by_ts = {e["completed_at"]: e["symbols_scanned"] for e in r["history"]}
        self.assertEqual(by_ts["2026-08-14T04:05:00Z"], 50)
        self.assertEqual(by_ts["2026-08-14T04:14:00Z"], 51)
        self.assertEqual(by_ts["2026-08-14T04:24:00Z"], 49)


# ---------------------------------------------------------------------------
# 4. Limit and edge cases
# ---------------------------------------------------------------------------

class TestLimitAndEdgeCases(unittest.TestCase):

    def _rows_n_scans(self, n: int) -> list:
        """Generate n (started, completed) pairs, each 5 min long, 4 min apart."""
        rows = []
        base = _dt("2026-08-14T04:00:00Z")
        cursor = base
        for _ in range(n):
            rows.append((cursor, "SCAN_STARTED", {}))
            rows.append((cursor + timedelta(minutes=5), "SCAN_COMPLETED", {"symbols_done": 51}))
            cursor += timedelta(minutes=9)
        return rows

    def test_limit_clips_to_n(self):
        rows = self._rows_n_scans(15)
        r = _call(rows, limit=5)
        self.assertEqual(r["count"], 5)
        self.assertEqual(len(r["history"]), 5)

    def test_limit_1_returns_newest(self):
        rows = self._rows_n_scans(3)
        r = _call(rows, limit=1)
        self.assertEqual(r["count"], 1)
        # The single entry should be the newest scan
        self.assertIsNotNone(r["history"][0]["completed_at"])

    def test_symbols_none_when_payload_has_no_count(self):
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", {}),
        )
        r = _call(rows)
        self.assertIsNone(r["history"][0]["symbols_scanned"])

    def test_symbols_from_various_payload_keys(self):
        """Multiple fallback payload keys for symbol count."""
        for key in ("symbols_done", "symbols_received", "symbols_succeeded",
                    "symbols_scanned", "symbols_total", "universe_size"):
            with self.subTest(key=key):
                rows = _make_rows(
                    (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
                    (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", {key: 51}),
                )
                r = _call(rows)
                self.assertEqual(r["history"][0]["symbols_scanned"], 51,
                                 f"Failed to read symbols from key '{key}'")

    def test_only_started_events_produce_empty_history(self):
        """SCAN_STARTED events without matching COMPLETED → no history entries."""
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED", {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_STARTED", {}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 0)

    def test_query_uses_ist_midnight_cutoff(self):
        """The SQL query must filter on ts >= IST midnight cutoff (not raw UTC midnight)."""
        import scan_state_store as sss

        captured_params: list = []
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []

        def capture(sql, params):
            captured_params.append(params[0])

        mock_cur.execute.side_effect = capture
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # 20:00 UTC → 01:30 IST next day → IST midnight at 18:30 UTC same UTC date
        fixed_now = datetime(2026, 8, 14, 20, 0, 0, tzinfo=timezone.utc)
        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn), \
             patch.object(sss, "_now_utc", return_value=fixed_now):
            sss.build_scan_history_response()

        self.assertTrue(captured_params)
        cutoff: datetime = captured_params[0]
        # 01:30 IST on Aug 15 → midnight IST Aug 15 → 18:30 UTC Aug 14
        expected = datetime(2026, 8, 14, 18, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(cutoff, expected,
                         f"Expected cutoff {expected}, got {cutoff}")

    def test_query_targets_both_event_types(self):
        """The SQL must include both SCAN_STARTED and SCAN_COMPLETED."""
        import scan_state_store as sss

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(sss, "db_available", return_value=True), \
             patch.object(sss, "_connect", return_value=mock_conn), \
             patch.object(sss, "_now_utc",
                          return_value=datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)):
            sss.build_scan_history_response()

        sql = str(mock_cur.execute.call_args)
        self.assertIn("SCAN_STARTED",   sql)
        self.assertIn("SCAN_COMPLETED", sql)

    def test_json_string_payload_is_parsed(self):
        """psycopg2 may return JSONB as a string in some drivers."""
        import json
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   json.dumps({})),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", json.dumps({"symbols_done": 42})),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["history"][0]["symbols_scanned"], 42)

    def test_timezone_naive_ts_treated_as_utc(self):
        """psycopg2 may return naive datetimes; they must be treated as UTC."""
        naive_started   = datetime(2026, 8, 14, 4, 0, 0)   # no tzinfo
        naive_completed = datetime(2026, 8, 14, 4, 5, 0)   # no tzinfo
        rows = _make_rows(
            (naive_started,   "SCAN_STARTED",   {}),
            (naive_completed, "SCAN_COMPLETED", {"symbols_done": 51}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["history"][0]["duration_s"], 300)


# ---------------------------------------------------------------------------
# 5. Abandoned / failed scan lifecycle regressions
# ---------------------------------------------------------------------------

class TestAbandonedScanLifecycle(unittest.TestCase):
    """
    Regression suite for the state-machine pairing rule.

    An abandoned start means SCAN_STARTED was emitted but no matching
    SCAN_COMPLETED followed before the next SCAN_STARTED (e.g. because the
    scan hit SCAN_FAILED, the API restarted, or the process was killed).

    The state machine must supersede the abandoned start so that the *next*
    successful completion is paired with the *second* SCAN_STARTED, not the
    first — otherwise duration and gap are materially wrong.
    """

    def test_abandoned_start_uses_second_start_for_duration(self):
        """
        SCAN_STARTED 04:00 (abandoned) → SCAN_STARTED 04:10 → SCAN_COMPLETED 04:15

        Duration must be 5 min (04:10→04:15), NOT 15 min (04:00→04:15).
        """
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),   # abandoned
            (_dt("2026-08-14T04:10:00Z"), "SCAN_STARTED",   {}),   # fresh start
            (_dt("2026-08-14T04:15:00Z"), "SCAN_COMPLETED", {"symbols_done": 51}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["history"][0]["duration_s"], 300,
                         "Duration must use the second (live) STARTED, not the abandoned one")

    def test_abandoned_start_records_correct_started_at(self):
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:10:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:15:00Z"), "SCAN_COMPLETED", {}),
        )
        r = _call(rows)
        self.assertEqual(r["history"][0]["started_at"], "2026-08-14T04:10:00Z")

    def test_abandoned_scan_between_two_successful_scans(self):
        """
        Scan 1: STARTED 04:00 → COMPLETED 04:05  (success)
        Scan 2: STARTED 04:07 (abandoned, no COMPLETED)
        Scan 3: STARTED 04:15 → COMPLETED 04:20  (success)

        Result: 2 completed entries.
        Scan 3 gap = 04:15 − 04:05 = 10 min = 600 s (from scan 1's completion
        to scan 3's start — the abandoned scan does not count as a completion).
        """
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", {"symbols_done": 50}),
            (_dt("2026-08-14T04:07:00Z"), "SCAN_STARTED",   {}),   # abandoned
            (_dt("2026-08-14T04:15:00Z"), "SCAN_STARTED",   {}),   # fresh start
            (_dt("2026-08-14T04:20:00Z"), "SCAN_COMPLETED", {"symbols_done": 49}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 2, "Must produce exactly 2 completed entries")

        newest = r["history"][0]
        oldest = r["history"][1]

        # Scan 3 duration: 04:15 → 04:20 = 5 min = 300 s
        self.assertEqual(newest["duration_s"], 300)
        # Scan 3 gap: 04:15 − 04:05 = 10 min = 600 s (abandons the 04:07 start)
        self.assertEqual(newest["gap_from_prev_s"], 600)
        # Scan 1 has no gap (it is the oldest)
        self.assertIsNone(oldest["gap_from_prev_s"])

    def test_multiple_consecutive_abandoned_starts(self):
        """
        Three consecutive SCAN_STARTED events with no completions, then one
        final STARTED → COMPLETED.  Only the last STARTED should be paired.
        """
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED", {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_STARTED", {}),
            (_dt("2026-08-14T04:10:00Z"), "SCAN_STARTED", {}),
            (_dt("2026-08-14T04:15:00Z"), "SCAN_COMPLETED", {"symbols_done": 51}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["history"][0]["started_at"], "2026-08-14T04:10:00Z")
        self.assertEqual(r["history"][0]["duration_s"], 300)

    def test_scan_failed_event_does_not_generate_completed_entry(self):
        """
        SCAN_STARTED → SCAN_FAILED (unknown event type, not COMPLETED) should
        produce zero entries — only SCAN_COMPLETED creates a history row.
        """
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED", {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_FAILED",  {"error": "timeout"}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 0,
                         "SCAN_FAILED must not create a history entry")

    def test_interleaved_abandoned_and_successful_scans_ordering(self):
        """
        Verifies newest-first ordering is preserved even when abandoned scans
        are present in the middle of the event stream.

        Scan A (success): 04:00 → 04:05
        Scan B (abandoned): 04:08 (no COMPLETED)
        Scan C (success): 04:15 → 04:20
        Scan D (success): 04:25 → 04:30
        """
        rows = _make_rows(
            (_dt("2026-08-14T04:00:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:05:00Z"), "SCAN_COMPLETED", {"symbols_done": 50}),
            (_dt("2026-08-14T04:08:00Z"), "SCAN_STARTED",   {}),  # abandoned
            (_dt("2026-08-14T04:15:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:20:00Z"), "SCAN_COMPLETED", {"symbols_done": 51}),
            (_dt("2026-08-14T04:25:00Z"), "SCAN_STARTED",   {}),
            (_dt("2026-08-14T04:30:00Z"), "SCAN_COMPLETED", {"symbols_done": 49}),
        )
        r = _call(rows)
        self.assertEqual(r["count"], 3)
        times = [e["completed_at"] for e in r["history"]]
        self.assertEqual(times, sorted(times, reverse=True), "Must be newest-first")


if __name__ == "__main__":
    unittest.main()
