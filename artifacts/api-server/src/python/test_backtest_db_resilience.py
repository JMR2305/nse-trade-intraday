"""
test_backtest_db_resilience.py — Regression suite for Task #637.

Verifies that DB connectivity failures during a backtest run:
  1. Trigger a single retry in _connect_with_retry() on transient errors.
  2. Allow _emergency_mark_failed() to write FAILED via the file-store
     fallback when DB is also unavailable — and never raise.
  3. Leave execute_run() returning ok=False with "Database connection failed"
     in the error, and the run stored as FAILED (never stuck as RUNNING).

All DB access and subprocess spawning is mocked — no real Postgres or
psycopg2 connection is opened.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helper: build a minimal run dict the file-store path expects
# ---------------------------------------------------------------------------

def _make_run(run_id: str, status: str = "PENDING",
              config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "config": config or {
            "symbols": ["RELIANCE"],
            "start": "2024-01-02",
            "end": "2024-01-05",
            "interval": "1d",
            "capital": 100000.0,
        },
        "progress": {},
        "metrics": None,
        "missed": None,
        "validation": None,
        "error": None,
        "started_at": None,
        "completed_at": None,
        "created_at": "2024-01-01T00:00:00Z",
        "pending_at": "2024-01-01T00:00:00Z",
    }


def _write_runs(path: str, runs: List[Dict[str, Any]]) -> None:
    with open(path, "w") as f:
        json.dump(runs, f)


def _read_runs(path: str) -> List[Dict[str, Any]]:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Shared psycopg2 stubs — avoids ImportError in environments without it.
# ---------------------------------------------------------------------------

def _make_op_error(msg: str = "connection reset by peer") -> Exception:
    """Return a psycopg2.OperationalError if available, else a plain
    RuntimeError with the same message so tests are portable."""
    try:
        import psycopg2
        return psycopg2.OperationalError(msg)
    except ImportError:
        # Simulate: embed "connection" so _is_connection_error recognises it.
        return RuntimeError(f"connection error: {msg}")


# ---------------------------------------------------------------------------
# 1. _connect_with_retry — retry behaviour
# ---------------------------------------------------------------------------

class TestConnectWithRetry(unittest.TestCase):
    """_connect_with_retry() must attempt exactly one retry on a transient
    OperationalError and succeed when the second call returns a connection."""

    def test_retries_once_on_transient_error(self):
        """First _connect raises OperationalError; second succeeds.
        _connect_with_retry() must return the good connection."""
        from backtest_portfolio import _connect_with_retry

        mock_conn = mock.MagicMock()
        call_count = {"n": 0}

        def _flaky_connect():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _make_op_error("connection reset by peer")
            return mock_conn

        with mock.patch("backtest_portfolio._connect", side_effect=_flaky_connect):
            with mock.patch("time.sleep"):   # skip the 1 s delay
                conn = _connect_with_retry()

        self.assertIs(conn, mock_conn)
        self.assertEqual(call_count["n"], 2,
                         "_connect_with_retry must attempt exactly 2 calls "
                         "when the first raises a transient error")

    def test_succeeds_immediately_when_no_error(self):
        """When _connect succeeds first time, no retry and no sleep."""
        from backtest_portfolio import _connect_with_retry

        mock_conn = mock.MagicMock()
        with mock.patch("backtest_portfolio._connect", return_value=mock_conn):
            with mock.patch("time.sleep") as mock_sleep:
                conn = _connect_with_retry()

        self.assertIs(conn, mock_conn)
        mock_sleep.assert_not_called()

    def test_propagates_on_permanent_failure(self):
        """When both attempts raise, the exception must propagate so the caller
        knows the DB is down — we never silently return None."""
        from backtest_portfolio import _connect_with_retry

        err = _make_op_error("pg down permanently")
        with mock.patch("backtest_portfolio._connect", side_effect=err):
            with mock.patch("time.sleep"):
                with self.assertRaises(type(err)):
                    _connect_with_retry()

    def test_does_not_retry_non_connection_errors(self):
        """A ValueError (logic bug) must not be retried — raise immediately."""
        from backtest_portfolio import _connect_with_retry

        call_count = {"n": 0}

        def _bad_connect():
            call_count["n"] += 1
            raise ValueError("unexpected column count")

        with mock.patch("backtest_portfolio._connect", side_effect=_bad_connect):
            with mock.patch("time.sleep") as mock_sleep:
                with self.assertRaises(ValueError):
                    _connect_with_retry()

        self.assertEqual(call_count["n"], 1,
                         "Non-connection errors must not be retried")
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 2. _emergency_mark_failed — file-store fallback
# ---------------------------------------------------------------------------

class TestEmergencyMarkFailed(unittest.TestCase):
    """_emergency_mark_failed() must write FAILED to the file store when the
    DB is also unavailable, and must NEVER raise under any circumstances."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self._runs_file = os.path.join(self._tmpdir, "backtest_runs.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_writes_failed_to_file_when_db_unavailable(self):
        """DB unavailable → file-store fallback must record FAILED status."""
        from backtest_portfolio import _emergency_mark_failed

        run_id = "BT-emf001"
        _write_runs(self._runs_file, [_make_run(run_id, status="RUNNING")])

        with (
            mock.patch("backtest_portfolio.db_available", return_value=False),
            mock.patch("backtest_portfolio._RUNS_FILE", self._runs_file),
        ):
            _emergency_mark_failed(run_id, "DB connection lost mid-run")

        rows = _read_runs(self._runs_file)
        row = next(r for r in rows if r["run_id"] == run_id)
        self.assertEqual(row["status"], "FAILED",
                         "Run must be FAILED after _emergency_mark_failed")
        self.assertIn("DB connection lost", row.get("error", ""))

    def test_writes_failed_when_db_retry_also_fails(self):
        """DB available but _connect always raises → fallback to file store."""
        from backtest_portfolio import _emergency_mark_failed

        run_id = "BT-emf002"
        _write_runs(self._runs_file, [_make_run(run_id, status="RUNNING")])

        with (
            mock.patch("backtest_portfolio.db_available", return_value=True),
            mock.patch("backtest_portfolio._connect",
                       side_effect=_make_op_error("neon down")),
            mock.patch("backtest_portfolio._RUNS_FILE", self._runs_file),
            mock.patch("time.sleep"),
        ):
            _emergency_mark_failed(run_id, "DB down during replay")

        rows = _read_runs(self._runs_file)
        row = next(r for r in rows if r["run_id"] == run_id)
        self.assertEqual(row["status"], "FAILED")

    def test_does_not_raise_when_both_db_and_file_fail(self):
        """Must never raise even when file write also fails — truly best-effort."""
        from backtest_portfolio import _emergency_mark_failed

        with (
            mock.patch("backtest_portfolio.db_available", return_value=False),
            mock.patch("backtest_portfolio._RUNS_FILE", "/dev/null/no_such_file"),
        ):
            try:
                _emergency_mark_failed("BT-nonexistent", "total failure")
            except Exception as exc:
                self.fail(f"_emergency_mark_failed must never raise; got: {exc}")

    def test_does_not_overwrite_terminal_statuses(self):
        """A run already COMPLETED must NOT be changed to FAILED."""
        from backtest_portfolio import _emergency_mark_failed

        run_id = "BT-emf004"
        _write_runs(self._runs_file,
                    [_make_run(run_id, status="COMPLETED")])

        with (
            mock.patch("backtest_portfolio.db_available", return_value=False),
            mock.patch("backtest_portfolio._RUNS_FILE", self._runs_file),
        ):
            _emergency_mark_failed(run_id, "should not overwrite")

        rows = _read_runs(self._runs_file)
        row = next(r for r in rows if r["run_id"] == run_id)
        self.assertEqual(row["status"], "COMPLETED",
                         "COMPLETED must never be overwritten by emergency mark")


# ---------------------------------------------------------------------------
# 3. execute_run integration — mid-run DB failure → FAILED, not RUNNING
# ---------------------------------------------------------------------------

class TestExecuteRunDbFailure(unittest.TestCase):
    """execute_run() must return ok=False and write status=FAILED when the DB
    raises a connection error mid-run — the run must never stay RUNNING."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self._runs_file = os.path.join(self._tmpdir, "backtest_runs.json")
        self._trades_file = os.path.join(self._tmpdir, "backtest_trades.json")
        _write_runs(self._trades_file, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_with_hde_failure(self, run_id: str,
                               error: Exception) -> Dict[str, Any]:
        """Set up a PENDING run and call execute_run() with hde.ensure_candles
        raising `error` to simulate a mid-run DB failure."""
        from backtest_runner import execute_run

        _write_runs(self._runs_file, [_make_run(run_id, status="PENDING")])

        with (
            # File-store path throughout (no real DB)
            mock.patch("backtest_portfolio.db_available", return_value=False),
            mock.patch("backtest_portfolio._RUNS_FILE", self._runs_file),
            mock.patch("backtest_portfolio._TRADES_FILE", self._trades_file),
            # Simulate DB failure at the candle-fetch stage
            mock.patch("historical_data_engine.ensure_candles",
                       side_effect=error),
            # Suppress pipeline event DB writes
            mock.patch("backtest_runner.emit"),
            mock.patch("backtest_runner.emit_many"),
            # Suppress queue-draining subprocess spawn
            mock.patch("backtest_runner._spawn_next_queued"),
            # Skip the 1 s retry delay
            mock.patch("time.sleep"),
        ):
            return execute_run(run_id)

    def test_returns_ok_false_on_db_connection_error(self):
        """A DB connection error mid-run must produce ok=False."""
        run_id = "BT-int001"
        result = self._run_with_hde_failure(run_id, _make_op_error(
            "connection reset by peer"))
        self.assertFalse(result.get("ok"),
                         "execute_run must return ok=False on DB failure")

    def test_error_message_contains_actionable_text(self):
        """The error field must contain 'Database connection failed' so
        operators know immediately this is a Neon/Postgres issue, not a bug."""
        run_id = "BT-int002"
        result = self._run_with_hde_failure(run_id, _make_op_error(
            "SSL connection has been closed unexpectedly"))
        error = result.get("error", "")
        self.assertIn("Database connection failed", error,
                      "Actionable DB-error prefix must be present in the "
                      "returned error string")

    def test_run_status_is_failed_not_running(self):
        """After a DB failure the run stored in the file must be FAILED,
        never left stuck as RUNNING — the pre-fix bug that caused BT-67e6d27ff6."""
        run_id = "BT-int003"
        self._run_with_hde_failure(run_id, _make_op_error(
            "terminating connection due to administrator command"))

        rows = _read_runs(self._runs_file)
        row = next((r for r in rows if r["run_id"] == run_id), None)
        self.assertIsNotNone(row, "Run must still exist in the file store")
        self.assertEqual(row.get("status"), "FAILED",
                         "Run must be FAILED, not RUNNING — "
                         "a stuck RUNNING run is the exact bug this test guards against")

    def test_non_connection_error_also_marks_failed(self):
        """Non-DB errors (e.g. RuntimeError in pipeline logic) must also be
        caught and stored as FAILED — no run may stay RUNNING after an
        unhandled exception regardless of the error type."""
        run_id = "BT-int004"
        result = self._run_with_hde_failure(run_id,
                                             RuntimeError("unexpected NaN in indicators"))
        self.assertFalse(result.get("ok"))

        rows = _read_runs(self._runs_file)
        row = next((r for r in rows if r["run_id"] == run_id), None)
        self.assertEqual(row.get("status"), "FAILED")

    def test_non_connection_error_message_does_not_add_db_prefix(self):
        """A plain RuntimeError must NOT get the 'Database connection failed'
        prefix — only genuine DB connectivity errors deserve that classification."""
        run_id = "BT-int005"
        result = self._run_with_hde_failure(run_id,
                                             RuntimeError("unexpected NaN in indicators"))
        error = result.get("error", "")
        self.assertNotIn("Database connection failed", error,
                         "Non-connection RuntimeError must not be misclassified "
                         "as a DB connectivity issue")


# ---------------------------------------------------------------------------
# 4. execute_run integration — DB-backed path (db_available=True)
#    The reviewer's specific concern: when the DB is reachable but a mid-run
#    connection error occurs, _emergency_mark_failed must use the DB UPDATE
#    path (not the file fallback) and the returned result must reflect FAILED.
# ---------------------------------------------------------------------------

class TestExecuteRunDbBackedPath(unittest.TestCase):
    """When db_available() is True throughout, execute_run must:
      - read the PENDING run from the DB (get_run DB path)
      - claim it via an atomic UPDATE (claim_run DB path)
      - on a mid-run OperationalError, reconnect and issue a FAILED UPDATE
        via _emergency_mark_failed's DB path (the path the reviewer flagged)
      - return ok=False with the 'Database connection failed' prefix
    No file-store fallback is used in these tests."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cursor(fetchone_row=None, rowcount: int = 0) -> mock.MagicMock:
        """Return a cursor mock suitable for `with conn.cursor() as cur:`."""
        cur = mock.MagicMock()
        cur.rowcount = rowcount
        if fetchone_row is not None:
            cur.fetchone.return_value = fetchone_row
        return cur

    @staticmethod
    def _wrap_conn(cur: mock.MagicMock) -> mock.MagicMock:
        """Wrap *cur* in a connection mock so `with conn.cursor() as c:` yields cur."""
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)
        return conn

    def _pending_row(self, run_id: str) -> tuple:
        """Return a DB row tuple matching backtest_portfolio._RUN_COLS for a PENDING run."""
        config_json = json.dumps({
            "symbols": ["RELIANCE"],
            "start": "2024-01-02",
            "end": "2024-01-05",
            "interval": "1d",
            "capital": 100000.0,
        })
        return (
            run_id,                     # run_id
            "2024-01-01T00:00:00Z",     # created_at
            "PENDING",                  # status
            config_json,                # config  (JSONB → str in mock)
            "{}",                       # progress
            None,                       # metrics
            None,                       # missed
            None,                       # validation
            None,                       # error
            None,                       # started_at
            None,                       # completed_at
            None,                       # pending_at
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_emergency_mark_failed_issues_db_update_when_db_available(self):
        """Core regression: _emergency_mark_failed must call UPDATE … SET status='FAILED'
        on the DB connection when db_available()=True, even though the run itself
        failed from a connection error.  A broken DB update path would leave the
        real row as RUNNING indefinitely while all file-fallback tests still pass."""
        import backtest_portfolio

        run_id = "BT-dbp001"

        # Three DB connections are opened in order:
        #   conn_get   → get_run (SELECT)
        #   conn_claim → claim_run (UPDATE PENDING→RUNNING)
        #   conn_emf   → _emergency_mark_failed (UPDATE …SET status='FAILED')
        get_cur = self._make_cursor(fetchone_row=self._pending_row(run_id))
        claim_cur = self._make_cursor(rowcount=1)   # rowcount=1 → claimed=True
        emf_cur = self._make_cursor()

        conn_get = self._wrap_conn(get_cur)
        conn_claim = self._wrap_conn(claim_cur)
        conn_emf = self._wrap_conn(emf_cur)

        connections = iter([conn_get, conn_claim, conn_emf])

        from backtest_runner import execute_run

        with (
            mock.patch("backtest_portfolio.db_available", return_value=True),
            # Skip DDL so _ensure_schema returns immediately on every call
            mock.patch("backtest_portfolio._SCHEMA_READY", True),
            mock.patch("backtest_portfolio._connect",
                       side_effect=lambda: next(connections)),
            mock.patch("historical_data_engine.ensure_candles",
                       side_effect=_make_op_error("connection reset by peer")),
            mock.patch("backtest_runner.emit"),
            mock.patch("backtest_runner.emit_many"),
            mock.patch("backtest_runner._spawn_next_queued"),
            mock.patch("time.sleep"),
        ):
            result = execute_run(run_id)

        # Return value must be ok=False with actionable DB error prefix
        self.assertFalse(result.get("ok"),
                         "execute_run must return ok=False on a DB connection error")
        self.assertIn("Database connection failed", result.get("error", ""),
                      "Returned error must begin with the actionable DB-failure prefix")

        # _emergency_mark_failed must have issued a real DB UPDATE — not fallen
        # back to the file store — because db_available() was True.
        emf_cur.execute.assert_called()
        # Flatten all positional args across all execute() calls
        all_sql = " ".join(
            str(arg)
            for call in emf_cur.execute.call_args_list
            for arg in call.args
        )
        self.assertIn("FAILED", all_sql,
                      "_emergency_mark_failed must write FAILED to the DB via "
                      "UPDATE backtest_runs SET status='FAILED' when db_available()=True")
        # Confirm the target run_id was passed so the UPDATE is not a no-op
        self.assertIn(run_id, all_sql,
                      "The FAILED UPDATE must target the specific run_id, not a "
                      "wildcard or wrong row")

    def test_db_commit_called_on_successful_emergency_update(self):
        """conn.commit() must be called so the FAILED status is durable — an
        uncommitted UPDATE would evaporate on connection close."""
        import backtest_portfolio

        run_id = "BT-dbp002"

        get_cur = self._make_cursor(fetchone_row=self._pending_row(run_id))
        claim_cur = self._make_cursor(rowcount=1)
        emf_cur = self._make_cursor()

        conn_get = self._wrap_conn(get_cur)
        conn_claim = self._wrap_conn(claim_cur)
        conn_emf = self._wrap_conn(emf_cur)

        connections = iter([conn_get, conn_claim, conn_emf])

        from backtest_runner import execute_run

        with (
            mock.patch("backtest_portfolio.db_available", return_value=True),
            mock.patch("backtest_portfolio._SCHEMA_READY", True),
            mock.patch("backtest_portfolio._connect",
                       side_effect=lambda: next(connections)),
            mock.patch("historical_data_engine.ensure_candles",
                       side_effect=_make_op_error("SSL connection closed unexpectedly")),
            mock.patch("backtest_runner.emit"),
            mock.patch("backtest_runner.emit_many"),
            mock.patch("backtest_runner._spawn_next_queued"),
            mock.patch("time.sleep"),
        ):
            execute_run(run_id)

        conn_emf.commit.assert_called_once_with()

    def test_run_never_left_running_when_db_write_succeeds(self):
        """After a successful DB FAILED UPDATE the run must not be RUNNING from
        the DB's point of view — verified by checking commit was called AND
        _emergency_mark_failed returned (did not raise)."""
        import backtest_portfolio

        run_id = "BT-dbp003"

        get_cur = self._make_cursor(fetchone_row=self._pending_row(run_id))
        claim_cur = self._make_cursor(rowcount=1)
        emf_cur = self._make_cursor()

        connections = iter([
            self._wrap_conn(get_cur),
            self._wrap_conn(claim_cur),
            self._wrap_conn(emf_cur),
        ])

        from backtest_runner import execute_run

        with (
            mock.patch("backtest_portfolio.db_available", return_value=True),
            mock.patch("backtest_portfolio._SCHEMA_READY", True),
            mock.patch("backtest_portfolio._connect",
                       side_effect=lambda: next(connections)),
            mock.patch("historical_data_engine.ensure_candles",
                       side_effect=_make_op_error("terminating connection: auth timeout")),
            mock.patch("backtest_runner.emit"),
            mock.patch("backtest_runner.emit_many"),
            mock.patch("backtest_runner._spawn_next_queued"),
            mock.patch("time.sleep"),
        ):
            # Must not raise — any exception here would leave the caller unable
            # to determine run state and the run would appear stuck as RUNNING
            try:
                result = execute_run(run_id)
            except Exception as exc:
                self.fail(f"execute_run must not raise; got: {exc}")

        # Both the return value and the DB cursor confirm FAILED was written
        self.assertFalse(result["ok"])
        emf_calls = [str(a) for c in emf_cur.execute.call_args_list for a in c.args]
        self.assertTrue(any("FAILED" in s for s in emf_calls),
                        "DB must record FAILED before execute_run returns")


if __name__ == "__main__":
    unittest.main()
