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


class SignalHistoryPruneTests(SignalHistoryTests):
    """Retention: keep recent fully, thin old history to one row per day."""

    def test_recent_snapshots_untouched(self):
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        for i in range(4):
            ss.append_signal_snapshot(
                f"recent-{i}", self.SIGS, self.CTX,
                snapshot_ts=(now - timedelta(days=2, hours=i)).isoformat())
        result = ss.prune_signal_snapshots(retention_days=30)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(ss.load_signal_snapshots(limit=50)), 4)

    def test_old_snapshots_thinned_to_one_per_day(self):
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        # 3 snapshots on each of 2 old days (60 and 61 days ago)
        for d in (60, 61):
            day = now - timedelta(days=d)
            for h in (9, 12, 15):
                ss.append_signal_snapshot(
                    f"old-{d}-{h}", self.SIGS, self.CTX,
                    snapshot_ts=day.replace(hour=h, minute=0,
                                            second=0).isoformat())
        # one recent row
        ss.append_signal_snapshot("recent", self.SIGS, self.CTX,
                                  snapshot_ts=now.isoformat())
        result = ss.prune_signal_snapshots(retention_days=30)
        self.assertEqual(result["deleted"], 4)  # 6 old -> 2 survivors
        rows = ss.load_signal_snapshots(limit=50)
        ids = {r["scan_id"] for r in rows}
        # the LATEST snapshot of each old day survives (hour 15)
        self.assertEqual(ids, {"recent", "old-60-15", "old-61-15"})

    def test_prune_idempotent(self):
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        for h in (9, 15):
            ss.append_signal_snapshot(
                f"old-{h}", self.SIGS, self.CTX,
                snapshot_ts=(now - timedelta(days=45)).replace(
                    hour=h, minute=0, second=0).isoformat())
        self.assertEqual(ss.prune_signal_snapshots()["deleted"], 1)
        self.assertEqual(ss.prune_signal_snapshots()["deleted"], 0)
        self.assertEqual(len(ss.load_signal_snapshots(limit=50)), 1)

    def test_scan_pipeline_append_triggers_prune(self):
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        for h in (9, 15):
            ss.append_signal_snapshot(
                f"old-{h}", self.SIGS, self.CTX,
                snapshot_ts=(now - timedelta(days=45)).replace(
                    hour=h, minute=0, second=0).isoformat())
        intelligence._append_history_snapshot(self.SIGS, self.CTX,
                                              datetime.now())
        rows = ss.load_signal_snapshots(limit=50)
        # 1 new + 1 surviving old-day row (old-9 pruned)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("old-9", {r["scan_id"] for r in rows})

    def test_prune_failure_never_breaks_scan_append(self):
        with mock.patch.object(ss, "prune_signal_snapshots",
                               side_effect=RuntimeError("db down")):
            intelligence._append_history_snapshot(self.SIGS, self.CTX,
                                                  datetime.now())
        self.assertEqual(len(ss.load_signal_snapshots(limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
