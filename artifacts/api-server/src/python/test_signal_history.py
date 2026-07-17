"""
Tests for append-only signal history snapshots (signal_snapshots).

Runs against the local JSON fallback (DATABASE_URL unset) so no real DB is
touched — same code paths for idempotency, filtering and ordering logic.
"""

import os
import unittest
from datetime import datetime
from unittest import mock

import signals_store as ss
import intelligence


class SignalHistoryTests(unittest.TestCase):
    def setUp(self):
        # Force local-dev fallback + isolated history file
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DATABASE_URL", None)
        self._path = mock.patch.object(
            ss, "_SNAPSHOT_FALLBACK_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "test_signal_snapshots_tmp.json"))
        self._path.start()
        self._cleanup_file()

    def tearDown(self):
        self._cleanup_file()
        self._path.stop()
        self._env.stop()

    def _cleanup_file(self):
        try:
            os.remove(ss._SNAPSHOT_FALLBACK_PATH)
        except FileNotFoundError:
            pass

    SIGS = [{"stock": "TCS", "signal": "BUY", "confidence": 80, "price": 4100.0}]
    CTX = {"regime": "BULLISH"}

    def test_each_intelligence_run_appends_a_new_row(self):
        # Two runs WITHOUT any phase7 snapshot update must add two rows.
        intelligence._append_history_snapshot(self.SIGS, self.CTX, datetime.now())
        intelligence._append_history_snapshot(self.SIGS, self.CTX, datetime.now())
        rows = ss.load_signal_snapshots(limit=10)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["scan_id"], rows[1]["scan_id"])

    def test_duplicate_scan_id_is_ignored(self):
        self.assertTrue(ss.append_signal_snapshot("run-1", self.SIGS, self.CTX))
        self.assertFalse(ss.append_signal_snapshot("run-1", self.SIGS, self.CTX))
        self.assertEqual(len(ss.load_signal_snapshots(limit=10)), 1)

    def test_empty_scan_id_rejected(self):
        with self.assertRaises(ValueError):
            ss.append_signal_snapshot("", self.SIGS, self.CTX)

    def test_newest_first_and_limit(self):
        for i in range(5):
            ss.append_signal_snapshot(f"run-{i}", self.SIGS, self.CTX,
                                      snapshot_ts=f"2026-07-1{i}T10:00:00+05:30")
        rows = ss.load_signal_snapshots(limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["scan_id"] for r in rows], ["run-4", "run-3", "run-2"])

    def test_date_filters(self):
        ss.append_signal_snapshot("old", self.SIGS, self.CTX,
                                  snapshot_ts="2026-07-10T10:00:00+05:30")
        ss.append_signal_snapshot("new", self.SIGS, self.CTX,
                                  snapshot_ts="2026-07-15T10:00:00+05:30")
        rows = ss.load_signal_snapshots(limit=10, start="2026-07-12")
        self.assertEqual([r["scan_id"] for r in rows], ["new"])
        rows = ss.load_signal_snapshots(limit=10, end="2026-07-12")
        self.assertEqual([r["scan_id"] for r in rows], ["old"])

    def test_canonical_scan_id_stored_separately(self):
        ss.append_signal_snapshot("run-a", self.SIGS, self.CTX,
                                  canonical_scan_id="phase7-xyz")
        ss.append_signal_snapshot("run-b", self.SIGS, self.CTX,
                                  canonical_scan_id="phase7-xyz")
        rows = ss.load_signal_snapshots(limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["canonical_scan_id"] for r in rows}, {"phase7-xyz"})


if __name__ == "__main__":
    unittest.main()
