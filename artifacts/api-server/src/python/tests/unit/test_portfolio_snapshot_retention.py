"""Unit tests for portfolio_snapshot retention / pruning (Task 550).

Verifies that _maybe_prune:
  1. Deletes old snapshots outside the retention window.
  2. Always keeps the MIN_SNAPSHOTS_TO_KEEP most-recent rows by serial id,
     so the newest snapshot is never deleted.
  3. Rate-limits pruning via PRUNE_INTERVAL_SECONDS so it doesn't run on
     every fill, but re-runs after the interval so aging rows are collected.
  4. Records the successful-prune timestamp ONLY after a successful commit,
     leaving the portfolio eligible to retry when pruning fails.
  5. Swallows DB errors so a failed prune never breaks a save or recovery read.

All tests are hermetic — they stub the DB connection so they never touch the
development database.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("PORTFOLIO_SNAPSHOT_DB_DISABLED", "1")

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

from src.portfolio.repositories.portfolio_snapshot import (  # noqa: E402
    PortfolioSnapshotRepository,
)


def _make_repo() -> PortfolioSnapshotRepository:
    """Return a fresh repo with a clean _LAST_PRUNED dict."""
    repo = PortfolioSnapshotRepository()
    # Each test gets an isolated class-level cooldown dict so prior tests
    # don't interfere.
    PortfolioSnapshotRepository._LAST_PRUNED = {}
    return repo


def _mock_conn():
    """Return a (conn, cursor) pair backed by MagicMock."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


class TestMaybePrune:
    def test_prune_sql_contains_retention_and_min_keep_guards(self):
        """The DELETE must filter by age AND exclude the N newest rows."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        repo._maybe_prune(conn, "default")

        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args[0]

        # Age guard
        assert "snapshotted_at < NOW() - make_interval" in sql
        # Serial-id guard that preserves newest rows
        assert "ORDER BY id DESC" in sql
        assert "LIMIT" in sql

        # Parameters carry the right values in order
        pid, retention_days, pid2, min_keep = params
        assert pid == "default"
        assert retention_days == repo.RETENTION_DAYS
        assert pid2 == "default"
        assert min_keep == repo.MIN_SNAPSHOTS_TO_KEEP

        conn.commit.assert_called_once()

    def test_newest_snapshots_protected_by_serial_id_guard(self):
        """MIN_SNAPSHOTS_TO_KEEP rows are always excluded from the DELETE
        via the NOT IN (... ORDER BY id DESC LIMIT N) subquery, so the
        newest snapshot can never be deleted even if it is older than
        RETENTION_DAYS."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        repo._maybe_prune(conn, "p1")

        _, params = cursor.execute.call_args[0]
        min_keep = params[3]
        assert min_keep == repo.MIN_SNAPSHOTS_TO_KEEP
        assert min_keep >= 1, "Must always protect at least one snapshot"

    def test_prune_reruns_after_interval_expires(self):
        """Pruning is rate-limited, not permanently suppressed. A second call
        that arrives after PRUNE_INTERVAL_SECONDS must issue a new DELETE so
        snapshots that aged after the first prune are eventually collected."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        # First prune — succeeds and records the timestamp.
        repo._maybe_prune(conn, "default")
        assert cursor.execute.call_count == 1

        # Simulate the interval having elapsed by back-dating the record.
        repo._LAST_PRUNED["default"] = time.monotonic() - repo.PRUNE_INTERVAL_SECONDS - 1

        # Second prune — interval has expired so a new DELETE must fire.
        repo._maybe_prune(conn, "default")
        assert cursor.execute.call_count == 2, (
            "A second prune after interval expiry must issue a new DELETE"
        )

    def test_prune_skipped_within_cooldown_window(self):
        """A prune call within the cooldown window must be a no-op."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        repo._maybe_prune(conn, "default")
        assert cursor.execute.call_count == 1

        # Timestamp was just recorded — still within cooldown.
        repo._maybe_prune(conn, "default")
        assert cursor.execute.call_count == 1, (
            "DELETE should not re-fire while still within the cooldown window"
        )

    def test_different_portfolios_each_get_independent_cooldown(self):
        """Each distinct portfolio_id has its own cooldown; pruning one
        portfolio must not suppress pruning of another."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        repo._maybe_prune(conn, "alpha")
        repo._maybe_prune(conn, "beta")

        assert cursor.execute.call_count == 2

    def test_none_portfolio_id_skips_prune(self):
        """A None portfolio_id must silently skip without touching the DB."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        repo._maybe_prune(conn, None)

        cursor.execute.assert_not_called()

    def test_successful_prune_timestamp_recorded_after_commit(self):
        """The cooldown timestamp must be set only after commit() succeeds."""
        repo = _make_repo()
        conn, cursor = _mock_conn()

        assert "default" not in repo._LAST_PRUNED

        repo._maybe_prune(conn, "default")

        # Commit succeeded → timestamp must now be present.
        assert "default" in repo._LAST_PRUNED

    def test_failed_commit_leaves_portfolio_eligible_for_retry(self):
        """If the commit fails, the portfolio must NOT be marked as pruned so
        the next save can retry retention — the unbounded-growth failure case
        must not be triggered by a single transient DB error."""
        repo = _make_repo()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        # commit() raises — simulates a transient DB problem.
        conn.commit.side_effect = Exception("connection reset")

        repo._maybe_prune(conn, "default")

        # Must NOT record a cooldown timestamp — the prune did not complete.
        assert "default" not in repo._LAST_PRUNED

        conn.rollback.assert_called_once()

    def test_db_execute_error_leaves_portfolio_eligible_for_retry(self):
        """A DB error during the DELETE itself must also leave the portfolio
        eligible so the next save can retry pruning."""
        repo = _make_repo()
        conn = MagicMock()
        bad_cursor = MagicMock()
        bad_cursor.__enter__ = MagicMock(return_value=bad_cursor)
        bad_cursor.__exit__ = MagicMock(return_value=False)
        bad_cursor.execute.side_effect = Exception("DB timeout")
        conn.cursor.return_value = bad_cursor

        # Must not raise.
        repo._maybe_prune(conn, "default")

        assert "default" not in repo._LAST_PRUNED, (
            "A failed prune must not record a cooldown timestamp"
        )
        conn.rollback.assert_called_once()

    def test_prune_called_inside_db_save(self):
        """_maybe_prune must be called from _db_save so it runs on every
        fill/mark write path without callers needing to invoke it manually."""
        repo = _make_repo()

        prune_calls: list[str] = []

        def _fake_prune(conn, portfolio_id):
            prune_calls.append(portfolio_id or "")

        import datetime
        import uuid

        snap = MagicMock()
        snap.portfolio_id = "default"
        snap.snapshot_id = uuid.uuid4()
        snap.status.value = "ACTIVE"
        snap.version = 1
        snap.paper_mode = True
        snap.cash.available = "50000"
        snap.cash.blocked = "0"
        snap.cash.total = "50000"
        snap.buying_power.net = "50000"
        snap.pnl.current_equity = "50000"
        snap.open_positions = []
        snap.pending_order_count = 0
        snap.pnl.realised = "0"
        snap.pnl.unrealised = "0"
        snap.pnl.daily_pnl = "0"
        snap.pnl.drawdown = "0"
        snap.checksum = None
        snap.snapshotted_at = datetime.datetime.now(datetime.timezone.utc)
        snap.event_cursor = None

        with patch.object(repo, "_maybe_prune", side_effect=_fake_prune), \
             patch(
                 "src.portfolio.repositories.portfolio_snapshot._connect"
             ) as mock_connect, \
             patch(
                 "src.portfolio.repositories.portfolio_snapshot._ensure_schema"
             ), \
             patch(
                 "src.portfolio.repositories.portfolio_snapshot._snapshot_to_payload",
                 return_value=None,
             ):
            conn = MagicMock()
            cursor = MagicMock()
            cursor.__enter__ = MagicMock(return_value=cursor)
            cursor.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value = cursor
            mock_connect.return_value = conn

            repo._db_save(snap)

        assert "default" in prune_calls, "_maybe_prune was not called from _db_save"
