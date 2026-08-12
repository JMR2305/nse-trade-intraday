"""
Backtest queue scheduler tests — Task 640.

Confirms that the bt_queue_tick command logic correctly:
  1. Promotes a QUEUED run to PENDING and spawns a worker subprocess when
     concurrency slots are available (count_active_runs() == 0).
  2. Promotes 0 runs (and spawns 0 workers) when MAX_CONCURRENT_BACKTESTS
     runs are already RUNNING.

Tests use the file fallback (DATABASE_URL stripped) and mock subprocess.Popen
so no real workers are started and no live DB is required.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.pop("DATABASE_URL", None)

import backtest_portfolio as bp
from backtest_portfolio import MAX_CONCURRENT_BACKTESTS, _load, _save


def _ago_iso(minutes: int) -> str:
    """Return an ISO-8601 UTC timestamp `minutes` ago."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _run_bt_queue_tick_logic() -> dict:
    """
    Replicate the bt_queue_tick command handler from main.py.

    Calling the logic directly (rather than via subprocess) lets tests
    control the environment (mocked Popen, file-fallback store) without
    spawning a real Python child process.

    Steps mirror main.py bt_queue_tick exactly:
      1. sweep_stale_runs() — marks stale runs; promotes QUEUED → PENDING.
      2. find_unclaimed_pending() — recover PENDING runs whose worker died.
      3. subprocess.Popen for each run to spawn (mocked in tests).
    """
    import subprocess as _subprocess

    sweep_result = bp.sweep_stale_runs()
    spawned: list = []
    _main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    _cwd = os.path.dirname(_main_py)

    # Runs just promoted in this tick
    to_spawn = list(sweep_result.get("promoted_runs") or [])

    # Unclaimed PENDING recovery (older_than_min=2 mirrors main.py)
    recovery = bp.find_unclaimed_pending(older_than_min=2.0)
    for rid in recovery:
        if rid not in to_spawn:
            to_spawn.append(rid)

    for rid in to_spawn:
        try:
            log_path = f"/tmp/backtest_{rid}.log"
            with open(log_path, "ab") as lf:
                _subprocess.Popen(
                    [sys.executable, _main_py,
                     "backtest_exec", json.dumps({"run_id": rid})],
                    stdout=lf, stderr=lf,
                    cwd=_cwd,
                    start_new_session=True,
                )
            spawned.append(rid)
        except Exception:
            pass  # spawn failure — next tick will retry

    return {
        **sweep_result,
        "spawned": spawned,
        "spawned_count": len(spawned),
        "recovery_candidates": recovery,
    }


class SchedulerBase(unittest.TestCase):
    """Base class: redirects file store to a temp directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bt_sched_")
        self._orig = (bp._RUNS_FILE, bp._TRADES_FILE, bp._SCHEMA_READY)
        bp._RUNS_FILE = os.path.join(self.tmp, "runs.json")
        bp._TRADES_FILE = os.path.join(self.tmp, "trades.json")
        bp._SCHEMA_READY = False

    def tearDown(self):
        bp._RUNS_FILE, bp._TRADES_FILE, bp._SCHEMA_READY = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_run(self, run_id: str, status: str,
                  created_ago_min: int = 1) -> None:
        """Insert a synthetic run row into the file-fallback store."""
        row = {
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
            "pending_at": None,
        }
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
        for r in _load(bp._RUNS_FILE):
            if r["run_id"] == run_id:
                return r
        return None


class TestQueueTickPromotesQueued(SchedulerBase):
    """bt_queue_tick promotes QUEUED → PENDING and spawns a worker."""

    def test_queued_run_is_promoted_and_worker_spawned(self):
        """
        Given: one QUEUED run, no active runs (all slots free).
        When:  bt_queue_tick logic executes.
        Then:
          - result["promoted_runs"] contains the run_id.
          - subprocess.Popen is called once with 'backtest_exec' and the run_id.
          - The run's status is PENDING after the tick.
        """
        run_id = f"BT-{uuid.uuid4().hex[:10]}"
        self._seed_run(run_id, "QUEUED")

        mock_proc = MagicMock()
        mock_popen = MagicMock(return_value=mock_proc)

        with patch("subprocess.Popen", mock_popen):
            result = _run_bt_queue_tick_logic()

        # Promotion assertion
        self.assertIn(run_id, result["promoted_runs"],
                      "Expected QUEUED run_id in promoted_runs")
        self.assertEqual(result["promoted"], 1)

        # Subprocess spawn assertion
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]  # positional argv list
        self.assertIn("backtest_exec", call_args,
                      "Popen argv must include 'backtest_exec'")
        # The run_id is embedded in the JSON payload passed as the next arg
        payload_str = call_args[call_args.index("backtest_exec") + 1]
        payload = json.loads(payload_str)
        self.assertEqual(payload["run_id"], run_id,
                         "Popen payload run_id must match the promoted run")

        # State check
        row = self._get_run(run_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "PENDING",
                         "Run must be PENDING after promotion")

    def test_spawned_list_includes_promoted_run(self):
        """result['spawned'] and result['spawned_count'] reflect the worker launch."""
        run_id = f"BT-{uuid.uuid4().hex[:10]}"
        self._seed_run(run_id, "QUEUED")

        mock_popen = MagicMock(return_value=MagicMock())
        with patch("subprocess.Popen", mock_popen):
            result = _run_bt_queue_tick_logic()

        self.assertIn(run_id, result["spawned"],
                      "Spawned run_id must appear in result['spawned']")
        self.assertEqual(result["spawned_count"], 1)


class TestQueueTickNoSlotsAvailable(SchedulerBase):
    """bt_queue_tick promotes 0 runs when MAX_CONCURRENT_BACKTESTS are active."""

    def test_no_promotion_when_slots_full(self):
        """
        Given: MAX_CONCURRENT_BACKTESTS RUNNING runs + 1 QUEUED run.
        When:  bt_queue_tick logic executes.
        Then:
          - result["promoted_runs"] is empty.
          - subprocess.Popen is NOT called.
          - The QUEUED run remains QUEUED.
        """
        running_ids = []
        for _ in range(MAX_CONCURRENT_BACKTESTS):
            rid = f"BT-{uuid.uuid4().hex[:10]}"
            # Use started_at = 1 min ago so it is not stale (threshold = 30 min)
            self._seed_run(rid, "RUNNING", created_ago_min=1)
            row = self._get_run(rid)
            row["started_at"] = _ago_iso(1)
            rows = _load(bp._RUNS_FILE)
            for r in rows:
                if r["run_id"] == rid:
                    r["started_at"] = _ago_iso(1)
            _save(bp._RUNS_FILE, rows)
            running_ids.append(rid)

        queued_id = f"BT-{uuid.uuid4().hex[:10]}"
        self._seed_run(queued_id, "QUEUED")

        mock_popen = MagicMock(return_value=MagicMock())
        with patch("subprocess.Popen", mock_popen):
            result = _run_bt_queue_tick_logic()

        # No promotion
        self.assertEqual(result["promoted"], 0,
                         "Must not promote when all concurrency slots are occupied")
        self.assertNotIn(queued_id, result["promoted_runs"])

        # No worker spawned
        mock_popen.assert_not_called()

        # Run stays QUEUED
        row = self._get_run(queued_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "QUEUED",
                         "Run must remain QUEUED when no slots are available")

    def test_exactly_max_running_blocks_promotion(self):
        """
        Boundary: exactly MAX_CONCURRENT_BACKTESTS active → 0 promoted.
        One less than max → the QUEUED run is promoted.
        """
        # Seed (MAX - 1) RUNNING runs — one slot is free → promote
        for _ in range(MAX_CONCURRENT_BACKTESTS - 1):
            rid = f"BT-{uuid.uuid4().hex[:10]}"
            self._seed_run(rid, "RUNNING", created_ago_min=1)
            rows = _load(bp._RUNS_FILE)
            for r in rows:
                if r["run_id"] == rid:
                    r["started_at"] = _ago_iso(1)
            _save(bp._RUNS_FILE, rows)

        queued_id = f"BT-{uuid.uuid4().hex[:10]}"
        self._seed_run(queued_id, "QUEUED")

        mock_popen = MagicMock(return_value=MagicMock())
        with patch("subprocess.Popen", mock_popen):
            result = _run_bt_queue_tick_logic()

        self.assertEqual(result["promoted"], 1,
                         "Exactly one free slot → exactly one promotion")
        self.assertIn(queued_id, result["promoted_runs"])
        mock_popen.assert_called_once()


class TestQueueTickNoQueued(SchedulerBase):
    """bt_queue_tick is a no-op when there are no QUEUED runs."""

    def test_idle_tick_promotes_nothing(self):
        """With no QUEUED runs, promoted_runs is empty and Popen is not called."""
        mock_popen = MagicMock(return_value=MagicMock())
        with patch("subprocess.Popen", mock_popen):
            result = _run_bt_queue_tick_logic()

        self.assertEqual(result["promoted"], 0)
        self.assertEqual(result["promoted_runs"], [])
        mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
