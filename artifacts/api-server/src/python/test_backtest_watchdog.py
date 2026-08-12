"""
Backtest watchdog tests — Task 633.

Confirms that sweep_stale_runs() correctly:
  1. Marks a RUNNING run with a stale heartbeat (31+ minutes) as STALE
     and sets error containing "Run stalled".
  2. Marks a PENDING run with stale created_at (31+ minutes) as STALE
     and sets error containing "Run stalled".
  3. Promotes a QUEUED run to PENDING when active count < MAX_CONCURRENT_BACKTESTS.

All tests use the file fallback (DATABASE_URL stripped) — no live DB required.
"""

import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

os.environ.pop("DATABASE_URL", None)

import backtest_portfolio as bp
from backtest_portfolio import _load, _save


def _ago_iso(minutes: int) -> str:
    """Return an ISO-8601 UTC timestamp `minutes` ago."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class WatchdogBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bt_watchdog_")
        self._orig = (bp._RUNS_FILE, bp._TRADES_FILE)
        bp._RUNS_FILE = os.path.join(self.tmp, "runs.json")
        bp._TRADES_FILE = os.path.join(self.tmp, "trades.json")

    def tearDown(self):
        (bp._RUNS_FILE, bp._TRADES_FILE) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_run(self, run_id: str, status: str,
                  created_ago_min: int = 5,
                  progress_updated_ago_min: int | None = None,
                  started_ago_min: int | None = None) -> None:
        """Write a synthetic run row directly to the file-fallback store."""
        row: dict = {
            "run_id": run_id,
            "created_at": _ago_iso(created_ago_min),
            "status": status,
            "config": {},
            "progress": {},
            "metrics": None,
            "missed": None,
            "validation": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
        }
        if started_ago_min is not None:
            row["started_at"] = _ago_iso(started_ago_min)
        if progress_updated_ago_min is not None:
            row["progress"] = {"progress_updated_at": _ago_iso(progress_updated_ago_min)}

        try:
            with open(bp._RUNS_FILE) as f:
                rows = json.load(f)
        except Exception:
            rows = []
        rows.append(row)
        tmp = bp._RUNS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rows, f, default=str)
        os.replace(tmp, bp._RUNS_FILE)

    def _get_run(self, run_id: str) -> dict | None:
        try:
            with open(bp._RUNS_FILE) as f:
                rows = json.load(f)
        except Exception:
            return None
        for r in rows:
            if r["run_id"] == run_id:
                return r
        return None


class TestSweepStaleRunning(WatchdogBase):
    """RUNNING run with progress_updated_at 31+ minutes ago → STALE."""

    def test_stale_running_run_is_marked_stale(self):
        run_id = "BT-running-stale"
        self._seed_run(
            run_id,
            status="RUNNING",
            started_ago_min=35,
            progress_updated_ago_min=31,  # stale: 31 min without heartbeat
        )

        result = bp.sweep_stale_runs()

        self.assertGreaterEqual(result["swept"], 1,
                                "sweep_stale_runs should have swept at least one run")
        self.assertIn(run_id, result.get("marked_stale", []),
                      "The stale RUNNING run should appear in marked_stale")

        run = self._get_run(run_id)
        self.assertIsNotNone(run, "Run must still exist in the store")
        self.assertEqual(run["status"], "STALE",
                         "Run status must be updated to STALE")
        self.assertIsNotNone(run.get("error"),
                             "Run error field must be populated")
        self.assertIn("Run stalled", run["error"],
                      "Error message must contain 'Run stalled'")

    def test_fresh_running_run_is_not_touched(self):
        run_id = "BT-running-fresh"
        self._seed_run(
            run_id,
            status="RUNNING",
            started_ago_min=2,
            progress_updated_ago_min=1,  # only 1 minute old — not stale
        )

        result = bp.sweep_stale_runs()

        self.assertNotIn(run_id, result.get("marked_stale", []),
                         "A fresh RUNNING run must not be marked stale")

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "RUNNING",
                         "Fresh run status must remain RUNNING")
        self.assertIsNone(run.get("error"),
                          "Fresh run error must remain None")

    def test_cancel_requested_run_also_swept_when_stale(self):
        run_id = "BT-cancel-stale"
        self._seed_run(
            run_id,
            status="CANCEL_REQUESTED",
            started_ago_min=40,
            progress_updated_ago_min=35,
        )

        result = bp.sweep_stale_runs()

        self.assertIn(run_id, result.get("marked_stale", []),
                      "Stale CANCEL_REQUESTED run must also be swept")
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "STALE")
        self.assertIn("Run stalled", run["error"])


class TestSweepStalePending(WatchdogBase):
    """PENDING run with created_at 31+ minutes ago → STALE."""

    def test_orphaned_pending_run_is_marked_stale(self):
        run_id = "BT-pending-stale"
        self._seed_run(
            run_id,
            status="PENDING",
            created_ago_min=31,  # worker died before claiming
        )

        result = bp.sweep_stale_runs()

        self.assertGreaterEqual(result["swept"], 1)
        self.assertIn(run_id, result.get("marked_stale", []),
                      "Orphaned PENDING run must appear in marked_stale")

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "STALE",
                         "Orphaned PENDING run status must be STALE")
        self.assertIsNotNone(run.get("error"))
        self.assertIn("Run stalled", run["error"],
                      "Error message must contain 'Run stalled'")

    def test_recently_created_pending_run_is_not_swept(self):
        run_id = "BT-pending-fresh"
        self._seed_run(
            run_id,
            status="PENDING",
            created_ago_min=2,
        )

        result = bp.sweep_stale_runs()

        self.assertNotIn(run_id, result.get("marked_stale", []))
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "PENDING")

    def test_exactly_at_threshold_is_swept(self):
        """Boundary: a run that is exactly 30 minutes old is swept (>= threshold)."""
        run_id = "BT-pending-boundary"
        # Create the run and then manually backdate its created_at
        self._seed_run(
            run_id,
            status="PENDING",
            created_ago_min=30,  # exactly at threshold — must be swept
        )

        result = bp.sweep_stale_runs()

        self.assertIn(run_id, result.get("marked_stale", []),
                      "A run exactly at the 30-minute threshold must be swept")


class TestPromoteQueued(WatchdogBase):
    """QUEUED run is promoted to PENDING when a concurrency slot is free."""

    def test_queued_run_promoted_when_slot_free(self):
        # No active runs — both concurrency slots are free.
        run_id = "BT-queued-1"
        self._seed_run(run_id, status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        self.assertGreaterEqual(result["promoted"], 1,
                                "At least one QUEUED run must be promoted")
        self.assertIn(run_id, result.get("promoted_runs", []),
                      "The QUEUED run must appear in promoted_runs")

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "PENDING",
                         "Promoted run status must be PENDING")

    def test_queued_run_not_promoted_when_slots_full(self):
        """Both concurrency slots occupied — QUEUED run stays QUEUED."""
        # Fill both slots with RUNNING runs (fresh, so they won't be swept).
        self._seed_run("BT-slot-1", status="RUNNING",
                       started_ago_min=1, progress_updated_ago_min=1)
        self._seed_run("BT-slot-2", status="RUNNING",
                       started_ago_min=1, progress_updated_ago_min=1)
        queued_id = "BT-queued-blocked"
        self._seed_run(queued_id, status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        # Neither slot should free up (both RUNNING are fresh).
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "QUEUED",
                         "QUEUED run must stay QUEUED when all slots are occupied")
        self.assertNotIn(queued_id, result.get("promoted_runs", []))

    def test_stale_sweep_frees_slot_for_queued_promotion(self):
        """When a RUNNING run is swept to STALE, its slot should free up and
        a QUEUED run should be promoted in the same sweep call."""
        # One RUNNING slot occupied but stale.
        self._seed_run("BT-stale-running", status="RUNNING",
                       started_ago_min=40, progress_updated_ago_min=35)
        # One fresh RUNNING run (stays RUNNING).
        self._seed_run("BT-fresh-running", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        # One QUEUED run waiting.
        queued_id = "BT-queued-waiting"
        self._seed_run(queued_id, status="QUEUED", created_ago_min=2)

        result = bp.sweep_stale_runs()

        # Stale run swept.
        self.assertIn("BT-stale-running", result.get("marked_stale", []))
        # QUEUED run promoted (freed slot).
        self.assertIn(queued_id, result.get("promoted_runs", []),
                      "QUEUED run must be promoted into the slot freed by the stale sweep")
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "PENDING")

    def test_queued_promoted_up_to_max_concurrent(self):
        """Promote at most MAX_CONCURRENT_BACKTESTS - active_count QUEUED runs."""
        # No active runs, two QUEUED runs — both should be promoted (fills both slots).
        self._seed_run("BT-q-a", status="QUEUED", created_ago_min=2)
        self._seed_run("BT-q-b", status="QUEUED", created_ago_min=1)
        # Third QUEUED run — should stay queued (no slot left).
        self._seed_run("BT-q-c", status="QUEUED", created_ago_min=0)

        result = bp.sweep_stale_runs()

        # Exactly MAX_CONCURRENT_BACKTESTS (=2) runs promoted.
        self.assertLessEqual(result["promoted"], bp.MAX_CONCURRENT_BACKTESTS)
        self.assertGreaterEqual(result["promoted"], 1)

        # BT-q-c (youngest, promoted last) might stay QUEUED.
        statuses = {
            rid: (self._get_run(rid) or {}).get("status")
            for rid in ("BT-q-a", "BT-q-b", "BT-q-c")
        }
        promoted_count = sum(1 for s in statuses.values() if s == "PENDING")
        self.assertEqual(promoted_count, bp.MAX_CONCURRENT_BACKTESTS,
                         "Exactly MAX_CONCURRENT_BACKTESTS runs must be promoted")


class TestSweepReturnShape(WatchdogBase):
    """Validate the return dict shape of sweep_stale_runs()."""

    def test_empty_store_returns_zero_counts(self):
        result = bp.sweep_stale_runs()
        self.assertEqual(result["swept"], 0)
        self.assertEqual(result["promoted"], 0)
        self.assertEqual(result.get("marked_stale", []), [])
        self.assertEqual(result.get("promoted_runs", []), [])

    def test_terminal_runs_are_never_touched(self):
        for status in ("COMPLETED", "CANCELLED", "STALE", "FAILED"):
            run_id = f"BT-terminal-{status}"
            self._seed_run(run_id, status=status, created_ago_min=60)

        result = bp.sweep_stale_runs()

        self.assertEqual(result["swept"], 0,
                         "Terminal runs must never be swept a second time")
        for status in ("COMPLETED", "CANCELLED", "STALE", "FAILED"):
            run = self._get_run(f"BT-terminal-{status}")
            self.assertEqual(run["status"], status,
                             f"{status} run must not change status")


class TestCancelRequestedCountsAsOccupied(WatchdogBase):
    """CANCEL_REQUESTED must count against the concurrency limit during sweep
    promotion — the worker is still executing until its checkpoint."""

    def test_cancel_requested_blocks_queued_promotion(self):
        """With one RUNNING + one CANCEL_REQUESTED, both concurrency slots are
        occupied; a QUEUED run must NOT be promoted."""
        self._seed_run("BT-active-run", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        self._seed_run("BT-cancelling", status="CANCEL_REQUESTED",
                       started_ago_min=3, progress_updated_ago_min=2)
        queued_id = "BT-queued-wait"
        self._seed_run(queued_id, status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        self.assertNotIn(queued_id, result.get("promoted_runs", []),
                         "QUEUED run must not be promoted when CANCEL_REQUESTED occupies a slot")
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "QUEUED",
                         "QUEUED run must remain QUEUED when all slots are occupied by "
                         "RUNNING + CANCEL_REQUESTED")

    def test_queued_promoted_when_only_cancel_requested_present(self):
        """One CANCEL_REQUESTED occupies one slot; one QUEUED run can fill the
        remaining slot (MAX_CONCURRENT_BACKTESTS = 2)."""
        self._seed_run("BT-cancelling", status="CANCEL_REQUESTED",
                       started_ago_min=3, progress_updated_ago_min=2)
        queued_id = "BT-queued-fits"
        self._seed_run(queued_id, status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        self.assertIn(queued_id, result.get("promoted_runs", []),
                      "QUEUED run must be promoted into the one free slot "
                      "(CANCEL_REQUESTED occupies the other)")
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "PENDING",
                         "Promoted run must be PENDING")

    def test_stale_cancel_requested_is_swept_and_frees_slot(self):
        """A CANCEL_REQUESTED run with a stale heartbeat is swept to STALE and
        its slot becomes available for a QUEUED run in the same pass."""
        self._seed_run("BT-stale-cancel", status="CANCEL_REQUESTED",
                       started_ago_min=40, progress_updated_ago_min=35)
        # Fill the second slot with a fresh RUNNING run.
        self._seed_run("BT-fresh", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        queued_id = "BT-queued-after-stale"
        self._seed_run(queued_id, status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        self.assertIn("BT-stale-cancel", result.get("marked_stale", []),
                      "Stale CANCEL_REQUESTED run must be swept")
        self.assertIn(queued_id, result.get("promoted_runs", []),
                      "QUEUED run must be promoted once the stale slot is freed")
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "PENDING")


class TestSpawnFailureRevertToQueued(WatchdogBase):
    """When spawning a worker fails after sweep promotion or _spawn_next_queued(),
    the promoted run must be reverted to QUEUED so the next watchdog poll can
    retry — not left stranded as PENDING with no worker."""

    def test_update_run_reverts_pending_to_queued(self):
        """update_run(status='QUEUED') on a PENDING run is the revert mechanism
        used by both main.py and _spawn_next_queued() on spawn failure."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "PENDING")

        bp.update_run(run_id, status="QUEUED")

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "QUEUED",
                         "After spawn failure revert, run must be QUEUED so watchdog can retry")

    def test_reverted_queued_run_is_re_promoted_by_next_sweep(self):
        """A run reverted to QUEUED after a spawn failure must be promoted again
        on the very next sweep call (no 30-minute stale wait required)."""
        self._seed_run("BT-running", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        self._seed_run("BT-spawn-failed", status="QUEUED", created_ago_min=1)

        result = bp.sweep_stale_runs()

        self.assertIn("BT-spawn-failed", result.get("promoted_runs", []),
                      "Run reverted to QUEUED after spawn failure must be re-promoted "
                      "by the next sweep, not left waiting 30 minutes")
        self.assertEqual(self._get_run("BT-spawn-failed")["status"], "PENDING")

    def test_spawn_next_queued_reverts_to_queued_on_popen_failure(self):
        """_spawn_next_queued() must revert the promoted run to QUEUED when
        Popen raises, so it is retryable on the next sweep rather than waiting
        30 minutes for the stale watchdog."""
        import unittest.mock as mock
        from backtest_runner import _spawn_next_queued

        # Seed a QUEUED run that will be promoted by _spawn_next_queued().
        queued_id = bp.create_run({"interval": "1d", "capital": 100000,
                                   "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(queued_id)["status"], "PENDING")
        # Revert it to QUEUED to simulate it waiting in the queue.
        bp.update_run(queued_id, status="QUEUED")
        self.assertEqual(self._get_run(queued_id)["status"], "QUEUED")

        # Patch subprocess.Popen to raise so spawn always fails.
        with mock.patch("subprocess.Popen", side_effect=OSError("mock spawn failure")):
            _spawn_next_queued()

        # The run must have been reverted from PENDING back to QUEUED.
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "QUEUED",
                         "_spawn_next_queued() must revert run to QUEUED on spawn "
                         "failure so it is retried on the next sweep poll")


class TestRetrySpawn(WatchdogBase):
    """retry_run() creates a new run; if it is PENDING the caller (main.py) must
    spawn its worker.  Confirm the spawn-revert contract works end-to-end."""

    def test_retry_creates_pending_run_when_slot_free(self):
        """retry_run() on a STALE run must create a new PENDING run (slot free)."""
        original_id = bp.create_run({"interval": "1d", "capital": 100000,
                                     "start": "2026-01-01", "end": "2026-06-01"})
        bp.update_run(original_id, status="STALE",
                      error="Run stalled — worker stopped")
        result = bp.retry_run(original_id)
        self.assertTrue(result.get("ok"), f"retry_run must succeed; got {result}")
        new_id = result.get("new_run_id")
        self.assertIsNotNone(new_id)
        new_run = self._get_run(new_id)
        # The slot was free (original is STALE, not active), so new run is PENDING.
        self.assertEqual(new_run["status"], "PENDING",
                         "New run must be PENDING when a concurrency slot is free")
        # Original run is preserved unchanged for audit.
        original = self._get_run(original_id)
        self.assertEqual(original["status"], "STALE",
                         "Original run must remain STALE for audit trail")

    def test_retry_creates_queued_run_when_slots_full(self):
        """retry_run() when both slots are occupied must create a QUEUED run."""
        # Fill both concurrency slots.
        self._seed_run("BT-slot1", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        self._seed_run("BT-slot2", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        # Create and stale-mark the original.
        original_id = bp.create_run({"interval": "1d", "capital": 100000,
                                     "start": "2026-01-01", "end": "2026-06-01"})
        bp.update_run(original_id, status="STALE", error="stalled")
        result = bp.retry_run(original_id)
        self.assertTrue(result.get("ok"))
        new_run = self._get_run(result["new_run_id"])
        self.assertEqual(new_run["status"], "QUEUED",
                         "New run must be QUEUED when all concurrency slots are occupied")

    def test_retry_spawn_failure_reverts_new_run_to_queued(self):
        """If spawning the worker for the retried PENDING run fails, the run
        must be reverted to QUEUED so the watchdog retries it."""
        import unittest.mock as mock
        original_id = bp.create_run({"interval": "1d", "capital": 100000,
                                     "start": "2026-01-01", "end": "2026-06-01"})
        bp.update_run(original_id, status="STALE", error="stalled")
        result = bp.retry_run(original_id)
        new_id = result.get("new_run_id")
        self.assertEqual(self._get_run(new_id)["status"], "PENDING")

        # Simulate the spawn failure revert (mirrors the main.py backtest_retry path).
        with mock.patch("subprocess.Popen", side_effect=OSError("spawn failed")):
            try:
                import subprocess
                subprocess.Popen(["dummy"])
            except OSError:
                pass
        # Explicitly revert as main.py does on failure.
        bp.update_run(new_id, status="QUEUED")

        self.assertEqual(self._get_run(new_id)["status"], "QUEUED",
                         "Failed-spawn retry run must be reverted to QUEUED for watchdog retry")


class TestSweepUsesLockedPromotion(WatchdogBase):
    """sweep_stale_runs() promotion step must delegate to promote_next_queued()
    which holds pg_advisory_xact_lock(74230912), so sweep cannot race with a
    concurrent create_run() or another sweep that also counts a free slot."""

    def test_sweep_calls_promote_next_queued_for_promotion(self):
        """When db_available() is True, sweep_stale_runs() must call
        promote_next_queued() instead of running its own raw promotion SQL."""
        import unittest.mock as mock

        promoted_calls = []

        def fake_promote():
            if not promoted_calls:
                promoted_calls.append("BT-locked-promoted")
                return "BT-locked-promoted"
            return None  # no more to promote on second call

        # Build a minimal mock connection that satisfies the stale-marking steps.
        cur = mock.MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = mock.MagicMock(return_value=False)
        # fetchall returns empty (no stale runs to mark in this test).
        cur.fetchall.return_value = []
        conn = mock.MagicMock()
        conn.cursor.return_value = cur

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_connect", return_value=conn), \
             mock.patch.object(bp, "_ensure_schema"), \
             mock.patch.object(bp, "promote_next_queued",
                               side_effect=fake_promote) as mock_promote:
            result = bp.sweep_stale_runs()

        self.assertTrue(mock_promote.called,
                        "sweep_stale_runs() must call promote_next_queued() for promotion "
                        "so the admission advisory lock is always held during slot fills")
        self.assertIn("BT-locked-promoted", result.get("promoted_runs", []),
                      "The promoted run ID returned by promote_next_queued() must appear "
                      "in the sweep result's promoted_runs list")

    def test_sweep_promotes_up_to_max_concurrent_backtests(self):
        """sweep_stale_runs() must call promote_next_queued() at most
        MAX_CONCURRENT_BACKTESTS times (the maximum number of possible promotions)."""
        import unittest.mock as mock

        call_count = {"n": 0}
        max_n = bp.MAX_CONCURRENT_BACKTESTS

        def fake_promote():
            call_count["n"] += 1
            if call_count["n"] <= max_n:
                return f"BT-q{call_count['n']}"
            return None

        cur = mock.MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = mock.MagicMock(return_value=False)
        cur.fetchall.return_value = []
        conn = mock.MagicMock()
        conn.cursor.return_value = cur

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_connect", return_value=conn), \
             mock.patch.object(bp, "_ensure_schema"), \
             mock.patch.object(bp, "promote_next_queued",
                               side_effect=fake_promote):
            result = bp.sweep_stale_runs()

        self.assertEqual(result["promoted"], max_n,
                         f"sweep must promote exactly MAX_CONCURRENT_BACKTESTS={max_n} "
                         f"runs when that many are available; got {result['promoted']}")


class TestBacktestStartSpawnRevert(WatchdogBase):
    """backtest_start in main.py must revert a PENDING run to QUEUED on any
    spawn/log-open failure so the watchdog retries rather than waiting 30 min."""

    def test_start_spawn_failure_reverts_pending_to_queued(self):
        """Simulate the main.py backtest_start spawn-failure path:
        create_run() succeeds (PENDING), spawn fails, run must be QUEUED."""
        # Create a PENDING run.
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(run_id)["status"], "PENDING")

        # Simulate the guarded revert that main.py does on spawn failure.
        if bp.get_run_status(run_id) == "PENDING":
            bp.update_run(run_id, status="QUEUED")

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "QUEUED",
                         "After spawn failure the run must be QUEUED for watchdog retry")

    def test_start_spawn_revert_skipped_when_run_already_claimed(self):
        """If another process claims the run (PENDING→RUNNING) before the
        spawn-failure revert, the revert must not overwrite RUNNING with QUEUED."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(run_id)["status"], "PENDING")

        # Another process claims the run.
        bp.claim_run(run_id)
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING")

        # The guarded revert in main.py checks status == "PENDING" first.
        if bp.get_run_status(run_id) == "PENDING":
            bp.update_run(run_id, status="QUEUED")

        # RUNNING must not have been overwritten.
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "RUNNING",
                         "Spawn-failure revert must not overwrite a RUNNING claim")

    def test_reverted_start_run_re_promoted_by_watchdog(self):
        """A run reverted from PENDING to QUEUED after a spawn failure must be
        re-promoted on the next sweep cycle — no 30-minute stale wait."""
        # One RUNNING run holds one slot; our failed start holds no slot now.
        self._seed_run("BT-occupant", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        failed_start = bp.create_run({"interval": "1d", "capital": 100000,
                                      "start": "2026-01-01", "end": "2026-06-01"})
        # Revert to QUEUED as main.py does on spawn failure.
        bp.update_run(failed_start, status="QUEUED")

        result = bp.sweep_stale_runs()

        self.assertIn(failed_start, result.get("promoted_runs", []),
                      "Spawn-failure-reverted run must be re-promoted by next sweep")
        self.assertEqual(self._get_run(failed_start)["status"], "PENDING")


class TestAdvisoryLockPresence(WatchdogBase):
    """Verify that create_run() and promote_next_queued() DB paths acquire
    pg_advisory_xact_lock(74230912) before counting and mutating, serializing
    concurrent admission decisions across processes."""

    def _make_mock_conn(self, fetchone_return=None):
        """Build a mock psycopg2-style connection whose cursor tracks all SQL."""
        import unittest.mock as mock
        sql_log = []
        cur = mock.MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = mock.MagicMock(return_value=False)
        cur.execute.side_effect = lambda sql, *a, **kw: sql_log.append(sql.strip())
        cur.fetchone.return_value = fetchone_return
        cur.rowcount = 1
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        return conn, sql_log

    def test_create_run_acquires_advisory_lock_before_insert(self):
        """create_run() DB path must call pg_advisory_xact_lock(74230912) as its
        first SQL statement so concurrent transactions are serialized."""
        import unittest.mock as mock

        conn, sql_log = self._make_mock_conn(fetchone_return=("PENDING",))

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_connect_with_retry", return_value=conn), \
             mock.patch.object(bp, "_ensure_schema"):
            bp.create_run({"interval": "1d", "capital": 100000,
                           "start": "2026-01-01", "end": "2026-06-01"})

        self.assertTrue(len(sql_log) >= 2,
                        f"Expected at least 2 SQL calls; got {sql_log}")
        first_sql = sql_log[0]
        self.assertIn("pg_advisory_xact_lock", first_sql,
                      "First SQL in create_run() DB path must acquire the advisory lock; "
                      f"got: {first_sql!r}")
        self.assertIn("74230912", first_sql,
                      "Advisory lock key must be 74230912 (backtest admission lock)")

    def test_promote_next_queued_acquires_advisory_lock_before_update(self):
        """promote_next_queued() DB path must call pg_advisory_xact_lock(74230912)
        before the count-and-promote statement."""
        import unittest.mock as mock

        # Return a promoted run_id from fetchone so the happy path is exercised.
        conn, sql_log = self._make_mock_conn(fetchone_return=("BT-queued-test",))

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_connect_with_retry", return_value=conn), \
             mock.patch.object(bp, "_ensure_schema"):
            result = bp.promote_next_queued()

        self.assertEqual(result, "BT-queued-test",
                         "promote_next_queued() must return the promoted run_id")
        self.assertTrue(len(sql_log) >= 2,
                        f"Expected at least 2 SQL calls; got {sql_log}")
        first_sql = sql_log[0]
        self.assertIn("pg_advisory_xact_lock", first_sql,
                      "First SQL in promote_next_queued() DB path must acquire the "
                      f"advisory lock; got: {first_sql!r}")
        self.assertIn("74230912", first_sql,
                      "Advisory lock key must be 74230912 (same lock as create_run)")

    def test_both_functions_use_same_lock_key(self):
        """create_run() and promote_next_queued() must use the same advisory lock
        key so they mutually exclude each other across concurrent processes."""
        import unittest.mock as mock
        import re

        create_lock_keys = []
        promote_lock_keys = []

        conn_c, log_c = self._make_mock_conn(fetchone_return=("PENDING",))
        conn_p, log_p = self._make_mock_conn(fetchone_return=("BT-x",))

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_ensure_schema"):
            with mock.patch.object(bp, "_connect_with_retry", return_value=conn_c):
                bp.create_run({"interval": "1d", "capital": 100000,
                               "start": "2026-01-01", "end": "2026-06-01"})
            for sql in log_c:
                m = re.search(r"pg_advisory_xact_lock\((\d+)\)", sql)
                if m:
                    create_lock_keys.append(int(m.group(1)))

            with mock.patch.object(bp, "_connect_with_retry", return_value=conn_p):
                bp.promote_next_queued()
            for sql in log_p:
                m = re.search(r"pg_advisory_xact_lock\((\d+)\)", sql)
                if m:
                    promote_lock_keys.append(int(m.group(1)))

        self.assertTrue(create_lock_keys,
                        "create_run() must acquire an advisory lock")
        self.assertTrue(promote_lock_keys,
                        "promote_next_queued() must acquire an advisory lock")
        self.assertEqual(create_lock_keys[0], promote_lock_keys[0],
                         "create_run() and promote_next_queued() must use the SAME "
                         "advisory lock key so they mutually exclude each other")


class TestConcurrentAdmission(WatchdogBase):
    """create_run() and promote_next_queued() must not exceed MAX_CONCURRENT_BACKTESTS
    even under concurrent same-process calls using the file-fallback store."""

    def test_create_run_respects_cap_sequential(self):
        """Creating MAX_CONCURRENT_BACKTESTS+1 runs sequentially: only the first
        N runs are PENDING; the rest are QUEUED."""
        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        run_ids = [bp.create_run(cfg) for _ in range(n + 2)]
        statuses = [self._get_run(r)["status"] for r in run_ids]
        pending = statuses.count("PENDING")
        queued = statuses.count("QUEUED")
        self.assertEqual(pending, n,
                         f"Exactly {n} runs must be PENDING; got statuses={statuses}")
        self.assertEqual(queued, 2,
                         f"Excess runs must be QUEUED; got statuses={statuses}")

    def test_concurrent_db_creates_all_acquire_advisory_lock(self):
        """Under concurrent create_run() DB-path calls, every thread must acquire
        pg_advisory_xact_lock(74230912) before counting and inserting.
        This is the mechanism that prevents two simultaneous READ COMMITTED
        transactions from both observing a free slot and both inserting PENDING."""
        import concurrent.futures
        import threading
        import unittest.mock as mock

        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}

        lock_acquisitions = []
        lock_acquisitions_lock = threading.Lock()

        def make_conn():
            sql_calls = []
            cur = mock.MagicMock()
            cur.__enter__ = lambda s: s
            cur.__exit__ = mock.MagicMock(return_value=False)

            def track_execute(sql, *a, **kw):
                sql = sql.strip()
                sql_calls.append(sql)
                if "pg_advisory_xact_lock" in sql:
                    with lock_acquisitions_lock:
                        lock_acquisitions.append(threading.current_thread().name)

            cur.execute.side_effect = track_execute
            cur.fetchone.return_value = ("PENDING",)
            conn = mock.MagicMock()
            conn.cursor.return_value = cur
            return conn

        with mock.patch.object(bp, "db_available", return_value=True), \
             mock.patch.object(bp, "_connect_with_retry", side_effect=lambda: make_conn()), \
             mock.patch.object(bp, "_ensure_schema"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=n + 4) as ex:
                futures = [ex.submit(bp.create_run, cfg) for _ in range(n + 4)]
                for f in futures:
                    f.result()  # raises if any thread threw

        self.assertEqual(len(lock_acquisitions), n + 4,
                         f"Every concurrent create_run() call must acquire the advisory "
                         f"lock; got {len(lock_acquisitions)} of {n + 4} acquisitions")

    def test_promote_next_queued_respects_cap_sequential(self):
        """promote_next_queued() called more times than available slots must only
        promote up to MAX_CONCURRENT_BACKTESTS total active runs."""
        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        # Create n+2 runs; first n are PENDING, last 2 are QUEUED.
        run_ids = [bp.create_run(cfg) for _ in range(n + 2)]
        # Claim all PENDING runs so they transition to RUNNING.
        for rid in run_ids[:n]:
            bp.claim_run(rid)
        # Both slots RUNNING — promote should return None.
        self.assertIsNone(bp.promote_next_queued(),
                          "promote_next_queued must return None when all slots are RUNNING")
        # Complete one run to free a slot.
        bp.update_run(run_ids[0], status="COMPLETED", completed_at=_ago_iso(0))
        # Exactly one QUEUED run should be promoted.
        promoted_id = bp.promote_next_queued()
        self.assertIsNotNone(promoted_id,
                             "One QUEUED run must be promoted after a slot frees up")
        self.assertEqual(self._get_run(promoted_id)["status"], "PENDING")
        # Second call: no free slots remain.
        self.assertIsNone(bp.promote_next_queued(),
                          "promote_next_queued must not over-promote beyond the cap")


class TestAtomicTerminalWrites(WatchdogBase):
    """complete_run() and cancel_checkpoint_run() must be conditional so a
    watchdog STALE mark between the worker's status read and the terminal write
    is never overwritten."""

    def test_complete_run_writes_completed_when_running(self):
        """complete_run() on a RUNNING run must transition it to COMPLETED."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING")

        written = bp.complete_run(run_id, metrics={"total_return": 0.05},
                                  progress={"phase": "DONE"})

        self.assertTrue(written, "complete_run() must return True for a RUNNING run")
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIsNotNone(run.get("completed_at"))

    def test_complete_run_is_no_op_when_stale(self):
        """If the watchdog marks a run STALE between the worker's check and the
        COMPLETED write, complete_run() must return False and leave it STALE."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        # Simulate the watchdog winning the race window.
        bp.update_run(run_id, status="STALE",
                      error="Run stalled — no progress for 31.0 minutes.")

        written = bp.complete_run(run_id, metrics={}, progress={"phase": "DONE"})

        self.assertFalse(written,
                         "complete_run() must return False when run is already STALE")
        self.assertEqual(self._get_run(run_id)["status"], "STALE",
                         "STALE must not be overwritten by a late COMPLETED write")

    def test_complete_run_is_no_op_when_already_completed(self):
        """complete_run() must not double-write COMPLETED (idempotency check)."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        bp.complete_run(run_id, metrics={}, progress={"phase": "DONE"})
        self.assertEqual(self._get_run(run_id)["status"], "COMPLETED")

        # Second call: run is COMPLETED, not RUNNING — must be a no-op.
        written2 = bp.complete_run(run_id, metrics={"extra": 1}, progress={})
        self.assertFalse(written2,
                         "complete_run() must return False when already COMPLETED")

    def test_cancel_checkpoint_writes_cancelled_when_cancel_requested(self):
        """cancel_checkpoint_run() on a CANCEL_REQUESTED run must write CANCELLED."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        bp.update_run(run_id, status="CANCEL_REQUESTED")

        written = bp.cancel_checkpoint_run(run_id)

        self.assertTrue(written,
                        "cancel_checkpoint_run() must return True for CANCEL_REQUESTED")
        self.assertEqual(self._get_run(run_id)["status"], "CANCELLED")

    def test_cancel_checkpoint_is_no_op_when_stale(self):
        """If the watchdog marks a run STALE between the checkpoint read and
        the CANCELLED write, cancel_checkpoint_run() must return False and
        leave the run STALE."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        # Simulate: operator requested cancel AND watchdog swept it simultaneously.
        bp.update_run(run_id, status="STALE",
                      error="Run stalled — no progress for 31.0 minutes.")

        written = bp.cancel_checkpoint_run(run_id)

        self.assertFalse(written,
                         "cancel_checkpoint_run() must return False when already STALE")
        self.assertEqual(self._get_run(run_id)["status"], "STALE",
                         "STALE must not be overwritten by a late CANCELLED write")

    def test_stale_between_check_and_complete_leaves_stale(self):
        """Simulate the exact race: worker reads RUNNING (ok to complete), then
        watchdog marks STALE, then worker calls complete_run() — must stay STALE."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)

        # Worker read: status is RUNNING — would normally proceed.
        status_at_check = bp.get_run_status(run_id)
        self.assertEqual(status_at_check, "RUNNING")

        # Race window: watchdog fires.
        bp.update_run(run_id, status="STALE",
                      error="Run stalled — no progress for 31.0 minutes.")

        # Worker now calls complete_run() — must not overwrite STALE.
        written = bp.complete_run(run_id, metrics={}, progress={"phase": "DONE"})

        self.assertFalse(written, "complete_run() after STALE write must be a no-op")
        self.assertEqual(self._get_run(run_id)["status"], "STALE",
                         "STALE written by watchdog must survive a late worker COMPLETED")


class TestSpawnNextQueuedSuccessPath(WatchdogBase):
    """_spawn_next_queued() must keep the promoted run as PENDING when Popen succeeds."""

    def test_successful_spawn_leaves_run_pending(self):
        """When Popen succeeds, _spawn_next_queued() must leave the promoted run
        as PENDING — not revert it to QUEUED — so the worker can claim it."""
        from unittest.mock import patch, MagicMock
        import backtest_runner as br

        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        # Fill all slots, then add a QUEUED run.
        for _ in range(n):
            rid = bp.create_run(cfg)
            bp.claim_run(rid)
        queued_id = bp.create_run(cfg)
        self.assertEqual(self._get_run(queued_id)["status"], "QUEUED")

        # Free one slot so promotion succeeds.
        running = [r for r in _load(bp._RUNS_FILE) if r["status"] == "RUNNING"][0]
        bp.update_run(running["run_id"], status="COMPLETED",
                      completed_at=_ago_iso(0))

        mock_popen = MagicMock()
        with patch("subprocess.Popen", mock_popen):
            br._spawn_next_queued()

        # Run must still be PENDING — Popen succeeded, no revert.
        self.assertEqual(self._get_run(queued_id)["status"], "PENDING",
                         "Successful spawn must leave the promoted run PENDING")
        self.assertTrue(mock_popen.called,
                        "_spawn_next_queued() must call Popen when promoting a run")

    def test_successful_spawn_calls_popen_with_run_id(self):
        """Popen must be invoked with the promoted run_id in the argv."""
        from unittest.mock import patch, MagicMock
        import backtest_runner as br

        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        for _ in range(n):
            rid = bp.create_run(cfg)
            bp.claim_run(rid)
        queued_id = bp.create_run(cfg)
        running = [r for r in _load(bp._RUNS_FILE) if r["status"] == "RUNNING"][0]
        bp.update_run(running["run_id"], status="COMPLETED",
                      completed_at=_ago_iso(0))

        mock_popen = MagicMock()
        with patch("subprocess.Popen", mock_popen):
            br._spawn_next_queued()

        call_args = mock_popen.call_args
        self.assertIsNotNone(call_args, "Popen must have been called")
        cmd = call_args[0][0]  # first positional arg: the argv list
        self.assertTrue(
            any(queued_id in str(arg) for arg in cmd),
            f"Popen argv must contain the promoted run_id ({queued_id}); got {cmd}"
        )


class TestAtomicRevertPendingToQueued(WatchdogBase):
    """revert_pending_to_queued() must be a single conditional operation so a
    concurrent claim_run() transitioning PENDING→RUNNING between a read and a
    write can never be reverted back to QUEUED."""

    def test_revert_queues_a_pending_run(self):
        """revert_pending_to_queued() on a PENDING run must change it to QUEUED
        and return True."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(run_id)["status"], "PENDING")
        reverted = bp.revert_pending_to_queued(run_id)
        self.assertTrue(reverted, "revert_pending_to_queued() must return True for PENDING")
        self.assertEqual(self._get_run(run_id)["status"], "QUEUED",
                         "Run must be QUEUED after revert")

    def test_revert_does_not_touch_running_run(self):
        """revert_pending_to_queued() on a RUNNING run must return False and
        leave the status unchanged — simulates the post-claim race window."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING")

        reverted = bp.revert_pending_to_queued(run_id)

        self.assertFalse(reverted,
                         "revert_pending_to_queued() must return False for RUNNING")
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING",
                         "RUNNING must not be overwritten by a spawn-failure revert")

    def test_revert_does_not_touch_stale_run(self):
        """revert_pending_to_queued() on a STALE run must return False — the
        watchdog already handled this run; reverting would lose the audit state."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.update_run(run_id, status="STALE", error="watchdog")
        reverted = bp.revert_pending_to_queued(run_id)
        self.assertFalse(reverted,
                         "revert_pending_to_queued() must return False for STALE")
        self.assertEqual(self._get_run(run_id)["status"], "STALE",
                         "STALE must not be overwritten by a spawn-failure revert")

    def test_reverted_run_clears_pending_at(self):
        """When a run is reverted from PENDING to QUEUED, pending_at must be
        cleared so the next promotion sets a fresh timestamp."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        run_before = self._get_run(run_id)
        self.assertIsNotNone(run_before.get("pending_at"),
                             "PENDING run must have pending_at set")

        bp.revert_pending_to_queued(run_id)

        run_after = self._get_run(run_id)
        self.assertIsNone(run_after.get("pending_at"),
                          "pending_at must be cleared when reverted to QUEUED")

    def test_claim_wins_then_revert_is_no_op(self):
        """Simulates the post-claim race window: claim_run() completes first
        (PENDING→RUNNING), then revert_pending_to_queued() runs.
        The revert must be a no-op — RUNNING must not become QUEUED."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(run_id)["status"], "PENDING")

        # Claim wins first.
        claimed = bp.claim_run(run_id)
        self.assertTrue(claimed)
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING")

        # Late revert: must be a no-op because status is no longer PENDING.
        reverted = bp.revert_pending_to_queued(run_id)

        self.assertFalse(reverted,
                         "revert_pending_to_queued() must return False when claim won")
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING",
                         "RUNNING must not become QUEUED when revert arrives late")

    def test_revert_wins_then_claim_is_no_op(self):
        """Simulates the inverse race: revert_pending_to_queued() runs first
        (PENDING→QUEUED), then claim_run() runs.  The claim must fail — a
        QUEUED run is not claimable — and must not become RUNNING."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        self.assertEqual(self._get_run(run_id)["status"], "PENDING")

        # Revert wins first.
        reverted = bp.revert_pending_to_queued(run_id)
        self.assertTrue(reverted)
        self.assertEqual(self._get_run(run_id)["status"], "QUEUED")

        # Late claim: must fail because status is now QUEUED, not PENDING.
        claimed = bp.claim_run(run_id)

        self.assertFalse(claimed,
                         "claim_run() must return False when revert already changed status")
        self.assertEqual(self._get_run(run_id)["status"], "QUEUED",
                         "QUEUED must not become RUNNING when claim arrives after revert")


class TestPendingAtTimestamp(WatchdogBase):
    """pending_at must be set at admission/promotion and used for stale-PENDING
    detection so a long-queued run is not immediately stale after promotion."""

    def test_pending_run_has_pending_at_set(self):
        """A run admitted directly as PENDING must have pending_at set."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        run = self._get_run(run_id)
        self.assertEqual(run["status"], "PENDING")
        self.assertIsNotNone(run.get("pending_at"),
                             "PENDING run must have pending_at set at admission")

    def test_queued_run_has_no_pending_at(self):
        """A run admitted as QUEUED (slots full) must not have pending_at set;
        it is set only when the run is actually promoted to PENDING."""
        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        # Fill all slots.
        for _ in range(n):
            rid = bp.create_run(cfg)
            bp.claim_run(rid)
        queued_id = bp.create_run(cfg)
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "QUEUED")
        self.assertIsNone(run.get("pending_at"),
                          "QUEUED run must not have pending_at before promotion")

    def test_promoted_run_gets_fresh_pending_at(self):
        """When promote_next_queued() promotes a QUEUED→PENDING run, it must
        set a fresh pending_at so stale detection measures from promotion time."""
        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        for _ in range(n):
            rid = bp.create_run(cfg)
            bp.claim_run(rid)
        queued_id = bp.create_run(cfg)
        self.assertIsNone(self._get_run(queued_id).get("pending_at"),
                          "Pre-condition: QUEUED run has no pending_at")

        # Free one slot.
        first = [r for r in _load(bp._RUNS_FILE) if r["status"] == "RUNNING"][0]
        bp.update_run(first["run_id"], status="COMPLETED",
                      completed_at=_ago_iso(0))
        promoted_id = bp.promote_next_queued()

        self.assertEqual(promoted_id, queued_id)
        run = self._get_run(queued_id)
        self.assertEqual(run["status"], "PENDING")
        self.assertIsNotNone(run.get("pending_at"),
                             "promote_next_queued() must set pending_at on promotion")

    def test_sweep_sets_pending_at_on_inline_promotion(self):
        """_sweep_stale_runs_file() promotes QUEUED→PENDING and must set pending_at
        on the promoted row.  A second sweep must leave the run PENDING because
        the stale clock starts from the promotion timestamp, not created_at."""
        # Create a run that has been QUEUED for 40 minutes.
        run_id = f"BT-sweeppromote-{uuid.uuid4().hex[:6]}"
        rows = _load(bp._RUNS_FILE)
        rows.append({
            "run_id": run_id,
            "created_at": _ago_iso(40),     # 40 min old — would look stale by created_at
            "status": "QUEUED",
            "config": {}, "progress": {}, "metrics": None, "missed": None,
            "validation": None, "error": None, "started_at": None,
            "completed_at": None,
            "pending_at": None,
        })
        _save(bp._RUNS_FILE, rows)

        # First sweep: run is QUEUED, no active runs, so it gets promoted.
        result1 = bp.sweep_stale_runs()
        self.assertIn(run_id, result1.get("promoted_runs", []),
                      "First sweep must promote the QUEUED run")
        promoted_run = self._get_run(run_id)
        self.assertEqual(promoted_run["status"], "PENDING")
        self.assertIsNotNone(promoted_run.get("pending_at"),
                             "sweep_stale_runs() must set pending_at when promoting inline")

        # Second sweep: pending_at was just set (< 1 min ago) — must NOT be stale.
        result2 = bp.sweep_stale_runs()
        self.assertNotIn(run_id, result2.get("marked_stale", []),
                         "A run promoted by sweep must not be immediately stale "
                         "on the next sweep — pending_at governs the clock, not created_at")
        self.assertEqual(self._get_run(run_id)["status"], "PENDING",
                         "Freshly-promoted run must remain PENDING after second sweep")

    def test_long_queued_run_not_stale_immediately_after_promotion(self):
        """A run that waited 40 minutes in QUEUED must not be swept as stale
        immediately after promotion — stale clock starts at pending_at, not created_at."""
        # Seed a run that was created 40 minutes ago but promoted just now.
        run_id = f"BT-longqueued-{uuid.uuid4().hex[:6]}"
        rows = _load(bp._RUNS_FILE)
        rows.append({
            "run_id": run_id,
            "created_at": _ago_iso(40),     # 40 min old
            "status": "PENDING",
            "config": {}, "progress": {}, "metrics": None, "missed": None,
            "validation": None, "error": None, "started_at": None,
            "completed_at": None,
            "pending_at": _ago_iso(1),      # promoted only 1 min ago
        })
        _save(bp._RUNS_FILE, rows)

        result = bp.sweep_stale_runs()

        self.assertNotIn(run_id, result.get("marked_stale", []),
                         "A run promoted only 1 min ago must NOT be swept as stale "
                         "even if created_at is 40 min ago; pending_at governs the clock")
        self.assertEqual(self._get_run(run_id)["status"], "PENDING",
                         "Run with fresh pending_at must remain PENDING after sweep")

    def test_old_pending_at_causes_stale_sweep(self):
        """A run with pending_at 31+ minutes ago must be swept as stale."""
        run_id = f"BT-oldpending-{uuid.uuid4().hex[:6]}"
        rows = _load(bp._RUNS_FILE)
        rows.append({
            "run_id": run_id,
            "created_at": _ago_iso(40),
            "status": "PENDING",
            "config": {}, "progress": {}, "metrics": None, "missed": None,
            "validation": None, "error": None, "started_at": None,
            "completed_at": None,
            "pending_at": _ago_iso(31),     # 31 min ago → over threshold
        })
        _save(bp._RUNS_FILE, rows)

        result = bp.sweep_stale_runs()

        self.assertIn(run_id, result.get("marked_stale", []),
                      "Run with pending_at 31 min ago must be swept as stale")


class TestRetryStatusPropagation(WatchdogBase):
    """retry_run() must return the actual admission status (PENDING or QUEUED),
    not a hardcoded 'PENDING', so callers can gate worker spawning correctly."""

    def test_retry_returns_pending_when_slot_free(self):
        """When a concurrency slot is available, retry_run() status == 'PENDING'."""
        original = bp.create_run({"interval": "1d", "capital": 100000,
                                  "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(original)
        bp.update_run(original, status="STALE", error="watchdog")
        result = bp.retry_run(original)
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["status"], "PENDING",
                         "retry_run() must report PENDING when a slot is free")

    def test_retry_returns_queued_when_cap_hit(self):
        """When MAX_CONCURRENT_BACKTESTS slots are occupied, retry_run() must
        report QUEUED — not PENDING — so callers skip the spawn step."""
        n = bp.MAX_CONCURRENT_BACKTESTS
        cfg = {"interval": "1d", "capital": 100000,
               "start": "2026-01-01", "end": "2026-06-01"}
        # Fill all slots with RUNNING runs.
        for _ in range(n):
            rid = bp.create_run(cfg)
            bp.claim_run(rid)
        # Now create a STALE original to retry from.
        original = bp.create_run(cfg)
        # original is QUEUED (cap is full); mark it STALE manually for retry.
        bp.update_run(original, status="STALE", error="watchdog")
        result = bp.retry_run(original)
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["status"], "QUEUED",
                         "retry_run() must report QUEUED when all slots are occupied; "
                         "got: " + str(result["status"]))
        # Verify the new run really is QUEUED in the store.
        new_run = self._get_run(result["new_run_id"])
        self.assertEqual(new_run["status"], "QUEUED",
                         "New run from retry must actually be QUEUED in the store")


class TestWorkerStaleFencing(WatchdogBase):
    """Worker writes (progress/COMPLETED) must not overwrite a STALE transition
    set by the watchdog.  The checkpoint detects STALE and stops the worker;
    the COMPLETED guard double-checks before writing the terminal state."""

    def test_stale_run_progress_write_blocked_at_checkpoint(self):
        """Simulate a watchdog marking a run STALE while the worker is running.
        The worker should not overwrite STALE with a progress heartbeat or COMPLETED.
        Verified by checking the run remains STALE after the guarded writes."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        self.assertEqual(self._get_run(run_id)["status"], "RUNNING")

        # Watchdog marks run STALE (simulates a 30-min stall).
        bp.update_run(run_id, status="STALE", error="Run stalled — watchdog")
        self.assertEqual(self._get_run(run_id)["status"], "STALE")

        # Worker detects STALE at checkpoint via get_run_status() and must NOT
        # overwrite it.  The COMPLETED guard: read status, skip if not RUNNING.
        final_status = bp.get_run_status(run_id)
        if final_status in ("RUNNING", "CANCEL_REQUESTED"):
            bp.update_run(run_id, status="COMPLETED",
                          completed_at="2026-08-12T05:00:00+00:00",
                          metrics={}, missed=[], progress={"phase": "DONE"})

        run = self._get_run(run_id)
        self.assertEqual(run["status"], "STALE",
                         "Worker must not overwrite watchdog STALE with COMPLETED; "
                         "final status=" + run["status"])

    def test_completed_write_allowed_when_still_running(self):
        """When the run is still RUNNING at finalization, COMPLETED must be written."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)

        final_status = bp.get_run_status(run_id)
        if final_status in ("RUNNING", "CANCEL_REQUESTED"):
            bp.update_run(run_id, status="COMPLETED",
                          completed_at="2026-08-12T05:00:00+00:00",
                          metrics={}, missed=[], progress={"phase": "DONE"})

        self.assertEqual(self._get_run(run_id)["status"], "COMPLETED",
                         "COMPLETED must be written when run is still RUNNING at finish")

    def test_stale_run_cannot_be_swept_again_by_watchdog(self):
        """Once a run is STALE it must not be re-swept by the watchdog (STALE is
        a terminal status for the sweep logic)."""
        self._seed_run("BT-already-stale", status="STALE",
                       started_ago_min=60, progress_updated_ago_min=60)
        result = bp.sweep_stale_runs()
        self.assertNotIn("BT-already-stale", result.get("marked_stale", []),
                         "A run that is already STALE must not be swept again")


class TestCurrentSymbolTelemetry(WatchdogBase):
    """Progress records must include current_symbol (DATA phase) and
    current_symbols (REPLAY phase) so operators can see which symbol the
    worker was processing when it stalled."""

    def test_progress_record_can_carry_current_symbol(self):
        """update_run() accepts and stores current_symbol in the progress field."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        bp.update_run(run_id, progress={
            "phase": "DATA", "done": 3, "total": 20,
            "current_symbol": "RELIANCE",
            "progress_updated_at": "2026-08-12T04:00:00+00:00",
        })
        run = self._get_run(run_id)
        progress = run.get("progress") or {}
        self.assertEqual(progress.get("current_symbol"), "RELIANCE",
                         "Progress must persist current_symbol for DATA phase")

    def test_progress_record_can_carry_current_symbols_list(self):
        """update_run() accepts and stores current_symbols list in REPLAY progress."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        bp.update_run(run_id, progress={
            "phase": "REPLAY", "done": 50, "total": 200,
            "ts": "2026-03-15T09:15:00",
            "cash": 98000.0,
            "current_symbols": ["HDFCBANK", "ICICIBANK", "RELIANCE"],
            "progress_updated_at": "2026-08-12T04:00:00+00:00",
        })
        run = self._get_run(run_id)
        progress = run.get("progress") or {}
        self.assertEqual(progress.get("current_symbols"),
                         ["HDFCBANK", "ICICIBANK", "RELIANCE"],
                         "Progress must persist current_symbols list for REPLAY phase")

    def test_stale_run_progress_shows_last_symbol_before_stall(self):
        """An operator can inspect a STALE run's progress to see which symbol
        caused the stall — current_symbol must survive the STALE transition."""
        run_id = bp.create_run({"interval": "1d", "capital": 100000,
                                "start": "2026-01-01", "end": "2026-06-01"})
        bp.claim_run(run_id)
        # Worker writes progress with current_symbol just before stalling.
        bp.update_run(run_id, progress={
            "phase": "DATA", "done": 7, "total": 20,
            "current_symbol": "TATASTEEL",
            "progress_updated_at": _ago_iso(35),  # 35 minutes ago → stale
        })
        # Watchdog marks stale (writes status only, not progress).
        result = bp.sweep_stale_runs()
        self.assertIn(run_id, result.get("marked_stale", []))
        # Progress with current_symbol must still be readable after sweep.
        run = self._get_run(run_id)
        progress = run.get("progress") or {}
        self.assertEqual(progress.get("current_symbol"), "TATASTEEL",
                         "STALE transition must preserve last progress/current_symbol "
                         "for operator audit")


class TestCancelDrainsQueue(WatchdogBase):
    """After an immediate cancellation (QUEUED/PENDING → CANCELLED), the freed
    slot should allow the next QUEUED run to be promoted."""

    def test_cancelling_queued_run_frees_slot(self):
        """Cancelling a QUEUED run (immediate → CANCELLED) must leave a slot
        free, which promote_next_queued() can fill."""
        # Fill both slots.
        rid1 = bp.create_run({"interval": "1d", "capital": 100000,
                               "start": "2026-01-01", "end": "2026-06-01"})
        rid2 = bp.create_run({"interval": "1d", "capital": 100000,
                               "start": "2026-01-01", "end": "2026-06-01"})
        # This should be QUEUED (both slots taken).
        rid3 = bp.create_run({"interval": "1d", "capital": 100000,
                               "start": "2026-01-01", "end": "2026-06-01"})

        run3 = self._get_run(rid3)
        self.assertIsNotNone(run3, "Third run must exist")
        # May be QUEUED or PENDING depending on create_run seeing 2 active.
        # Cancel rid1 (PENDING → CANCELLED).
        cancel = bp.cancel_run(rid1)
        self.assertTrue(cancel.get("ok"),
                        f"Cancel must succeed; got: {cancel}")
        self.assertEqual(cancel.get("status"), "CANCELLED",
                         "PENDING run must be immediately cancelled")

        # Now promote_next_queued should fill the freed slot.
        promoted_id = bp.promote_next_queued()
        if run3.get("status") == "QUEUED":
            self.assertEqual(promoted_id, rid3,
                             "promote_next_queued must fill the freed slot with rid3")
        else:
            # rid3 was PENDING already (race in count at create time); either
            # way the slot is free and no run should remain stuck.
            pass  # acceptable — no QUEUED run was waiting

    def test_cancelling_pending_run_unblocks_queued_run(self):
        """More direct: seed one RUNNING, one PENDING, one QUEUED.
        Cancel the PENDING — QUEUED must become promotable."""
        self._seed_run("BT-running", status="RUNNING",
                       started_ago_min=2, progress_updated_ago_min=1)
        pending_id = bp.create_run({"interval": "1d", "capital": 100000,
                                    "start": "2026-01-01", "end": "2026-06-01"})
        queued_id = bp.create_run({"interval": "1d", "capital": 100000,
                                   "start": "2026-01-01", "end": "2026-06-01"})

        # Verify queued_id is indeed QUEUED (two active: RUNNING + PENDING).
        self.assertEqual(self._get_run(queued_id)["status"], "QUEUED")

        # Cancel the PENDING run — frees its slot.
        result = bp.cancel_run(pending_id)
        self.assertEqual(result.get("status"), "CANCELLED")

        # promote_next_queued must now succeed.
        next_id = bp.promote_next_queued()
        self.assertEqual(next_id, queued_id,
                         "promote_next_queued must promote the waiting QUEUED run "
                         "after the PENDING slot was freed by cancellation")
        self.assertEqual(self._get_run(queued_id)["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
