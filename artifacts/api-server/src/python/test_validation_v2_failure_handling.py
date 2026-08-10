"""
Validation V2 background-failure handling tests (core backtesting fix).

Covers:
  * mark_run_failed persists FAILED + error text (and never downgrades COMPLETED)
  * execute_backtest_pipeline crash wrapper marks the run FAILED with traceback
  * stuck-run watchdog fails RUNNING runs with no recent progress
  * list/get surface the error so the UI never shows endless RUNNING

Uses the real dev DB with throwaway run_ids; all rows are deleted in teardown.
"""
import json
import unittest
from unittest.mock import patch

import validation_v2_engine as v2


def _db_available() -> bool:
    conn = v2._get_conn()
    if not conn:
        return False
    conn.close()
    return True


@unittest.skipUnless(_db_available(), "DB unavailable")
class TestV2FailureHandling(unittest.TestCase):
    def setUp(self):
        self.run_ids = []

    def tearDown(self):
        conn = v2._get_conn()
        if conn:
            try:
                for rid in self.run_ids:
                    v2._exec(conn, "DELETE FROM validation_v2_runs WHERE run_id = %s", (rid,))
            finally:
                conn.close()

    def _insert_run(self, rid, status="RUNNING", progress_age_min=0):
        self.run_ids.append(rid)
        conn = v2._get_conn()
        try:
            v2._ensure_tables(conn)
            v2._exec(conn, """
                INSERT INTO validation_v2_runs (run_id, status, last_progress_at)
                VALUES (%s, %s, NOW() - (%s * INTERVAL '1 minute'))
            """, (rid, status, progress_age_min))
        finally:
            conn.close()

    def _get_row(self, rid):
        conn = v2._get_conn()
        try:
            return v2._q1(conn, "SELECT * FROM validation_v2_runs WHERE run_id = %s", (rid,))
        finally:
            conn.close()

    def test_mark_run_failed_persists_error(self):
        rid = "test-fail-01"
        self._insert_run(rid)
        out = v2.mark_run_failed(rid, "boom: executor crashed")
        self.assertTrue(out.get("ok"))
        row = self._get_row(rid)
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("boom", row["error"])
        self.assertIsNotNone(row["completed_at"])

    def test_mark_run_failed_never_downgrades_completed(self):
        rid = "test-fail-02"
        self._insert_run(rid, status="COMPLETED")
        v2.mark_run_failed(rid, "late crash report")
        row = self._get_row(rid)
        self.assertEqual(row["status"], "COMPLETED")

    def test_executor_crash_marks_run_failed(self):
        rid = "test-fail-03"
        self._insert_run(rid)
        with patch.object(v2, "_execute_backtest_impl",
                          side_effect=RuntimeError("simulated executor crash")):
            out = v2.execute_backtest_pipeline(rid, "{}")
        self.assertIn("error", out)
        row = self._get_row(rid)
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("simulated executor crash", row["error"])

    def test_executor_error_result_marks_run_failed(self):
        rid = "test-fail-06"
        self._insert_run(rid)
        with patch.object(v2, "_execute_backtest_impl",
                          return_value={"error": "Run test-fail-06 not found"}):
            v2.execute_backtest_pipeline(rid, "{}")
        row = self._get_row(rid)
        self.assertEqual(row["status"], "FAILED")

    def test_stuck_run_watchdog(self):
        rid_stuck = "test-fail-04"
        rid_fresh = "test-fail-05"
        self._insert_run(rid_stuck, progress_age_min=v2.STUCK_RUN_TIMEOUT_MINUTES + 5)
        self._insert_run(rid_fresh, progress_age_min=1)
        listing = v2.list_backtest_runs()  # triggers _fail_stuck_runs
        by_id = {r["run_id"]: r for r in listing["runs"]}
        self.assertEqual(by_id[rid_stuck]["status"], "FAILED")
        self.assertIn("No progress", by_id[rid_stuck]["error"])
        self.assertEqual(by_id[rid_fresh]["status"], "RUNNING")

    def test_completion_never_overwrites_failed(self):
        """Watchdog race: a FAILED run must not be resurrected to COMPLETED."""
        rid = "test-fail-08"
        self._insert_run(rid)
        v2.mark_run_failed(rid, "watchdog fired")
        conn = v2._get_conn()
        try:
            # Same guarded terminal UPDATE the executor uses on completion.
            v2._exec(conn, """
                UPDATE validation_v2_runs
                SET status = 'COMPLETED', error = NULL, completed_at = NOW()
                WHERE run_id = %s AND status = 'RUNNING'
            """, (rid,))
        finally:
            conn.close()
        row = self._get_row(rid)
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("watchdog", row["error"])

    def test_get_run_surfaces_error(self):
        rid = "test-fail-07"
        self._insert_run(rid)
        v2.mark_run_failed(rid, "visible in detail endpoint")
        detail = v2.get_backtest_run(rid)
        self.assertEqual(detail["status"], "FAILED")
        self.assertIn("visible in detail endpoint", detail["run_error"])


if __name__ == "__main__":
    unittest.main()
