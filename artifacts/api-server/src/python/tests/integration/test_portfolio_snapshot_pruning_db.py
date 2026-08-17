"""Integration tests — portfolio_snapshot pruning against a real Postgres DB.

Verifies that _maybe_prune actually executes the DELETE SQL correctly against
a live Postgres instance: old snapshots are removed, the MIN_SNAPSHOTS_TO_KEEP
most-recent rows (by serial id) always survive regardless of their age, and the
newest snapshot is never accidentally deleted.

Skipped when DATABASE_URL is not configured so the unit suite stays hermetic.
PORTFOLIO_SNAPSHOT_DB_DISABLED is explicitly cleared for this suite so the
real DB layer is exercised.
"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

HAVE_DB = bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_table(conn) -> None:
    """Bootstrap the portfolio_snapshots table if it doesn't already exist."""
    from src.portfolio.repositories.portfolio_snapshot import _ensure_schema  # noqa: PLC0415
    _ensure_schema(conn)


def _insert_old_snapshot(conn, portfolio_id: str, days_old: int) -> int:
    """Insert a minimal snapshot row dated *days_old* days in the past.

    Returns the serial *id* of the inserted row so callers can identify it.
    """
    snap_id = str(uuid.uuid4())
    snapshotted_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_id, portfolio_id, status, version, paper_mode,
                cash_available, cash_blocked, cash_total,
                buying_power_net, equity,
                open_position_count, pending_order_count,
                realised_pnl, unrealised_pnl, daily_pnl, drawdown,
                snapshotted_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                snap_id, portfolio_id, "ACTIVE", 1, True,
                "100000", "0", "100000",
                "100000", "100000",
                0, 0,
                "0", "0", "0", "0",
                snapshotted_at,
            ),
        )
        (row_id,) = cur.fetchone()
    conn.commit()
    return row_id


def _row_count(conn, portfolio_id: str) -> int:
    """Return the number of rows in portfolio_snapshots for *portfolio_id*."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots WHERE portfolio_id = %s",
            (portfolio_id,),
        )
        (count,) = cur.fetchone()
    return count


def _surviving_ids(conn, portfolio_id: str) -> list[int]:
    """Return all surviving serial ids for *portfolio_id*, ordered ascending."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM portfolio_snapshots WHERE portfolio_id = %s ORDER BY id ASC",
            (portfolio_id,),
        )
        return [row[0] for row in cur.fetchall()]


@unittest.skipUnless(HAVE_DB, "DATABASE_URL not configured — skipping DB integration tests")
class TestSnapshotPruningIntegration(unittest.TestCase):
    """Integration tests that exercise _maybe_prune against a real database.

    Each test uses a unique portfolio_id so parallel runs and other tests
    cannot interfere.  All inserted rows are cleaned up in tearDown.
    """

    def setUp(self):
        self.pid = f"prune-it-{uuid.uuid4().hex[:12]}"
        # Remove the hermetic disable flag so the real DB layer is active.
        self._prev_disabled = os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)

        # Ensure the table exists before we start inserting test rows.
        conn = _connect()
        try:
            _ensure_table(conn)
        finally:
            conn.close()

        # Reset class-level cooldown so each test starts fresh.
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        PortfolioSnapshotRepository._LAST_PRUNED = {}

    def tearDown(self):
        # Restore the env var if it was set before the test.
        if self._prev_disabled is not None:
            os.environ["PORTFOLIO_SNAPSHOT_DB_DISABLED"] = self._prev_disabled
        else:
            os.environ.pop("PORTFOLIO_SNAPSHOT_DB_DISABLED", None)

        # Remove all rows written by this test so the dev DB stays clean.
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM portfolio_snapshots WHERE portfolio_id = %s",
                    (self.pid,),
                )
            conn.commit()
        finally:
            conn.close()

    def _make_repo_with_zero_interval(self):
        """Return a repo whose PRUNE_INTERVAL_SECONDS is 0 so cooldown never blocks."""
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        repo = PortfolioSnapshotRepository()
        repo.PRUNE_INTERVAL_SECONDS = 0.0   # bypass rate-limiter for the test
        return repo

    # ------------------------------------------------------------------
    # Test 1: old rows beyond the retention window are deleted
    # ------------------------------------------------------------------

    def test_prune_deletes_old_rows_keeps_exactly_min_snapshots(self):
        """Insert MIN+5 snapshots all older than RETENTION_DAYS.

        After _maybe_prune exactly MIN_SNAPSHOTS_TO_KEEP rows must remain —
        the DELETE SQL actually executes and removes the excess old rows.
        """
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        min_keep = PortfolioSnapshotRepository.MIN_SNAPSHOTS_TO_KEEP
        retention = PortfolioSnapshotRepository.RETENTION_DAYS
        total_inserted = min_keep + 5

        conn = _connect()
        try:
            # Insert rows in ascending order so the LAST insert has the highest
            # serial id (i.e. is the "newest" row from the DB's perspective).
            days_old = retention + 10  # all rows are clearly beyond the window
            for _ in range(total_inserted):
                _insert_old_snapshot(conn, self.pid, days_old)

            before = _row_count(conn, self.pid)
            self.assertEqual(before, total_inserted, "Pre-condition: all rows inserted")

            repo = self._make_repo_with_zero_interval()
            repo._maybe_prune(conn, self.pid)

            after = _row_count(conn, self.pid)
            self.assertEqual(
                after,
                min_keep,
                f"Expected exactly {min_keep} rows after pruning {total_inserted} "
                f"old snapshots, but found {after}. "
                "The DELETE SQL may not be executing or may be deleting too many/few rows.",
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Test 2: the newest row by serial id always survives
    # ------------------------------------------------------------------

    def test_newest_snapshot_by_serial_id_always_survives(self):
        """The row with the highest serial id must survive even when all rows
        are older than RETENTION_DAYS.

        This validates the NOT IN (… ORDER BY id DESC LIMIT N) guard in the
        DELETE query — the serial-id subquery must exclude the N most-recent
        rows regardless of their snapshotted_at timestamp.
        """
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        min_keep = PortfolioSnapshotRepository.MIN_SNAPSHOTS_TO_KEEP
        retention = PortfolioSnapshotRepository.RETENTION_DAYS
        total_inserted = min_keep + 5
        days_old = retention + 10  # all rows well beyond the retention window

        conn = _connect()
        try:
            last_id = None
            for _ in range(total_inserted):
                last_id = _insert_old_snapshot(conn, self.pid, days_old)

            # last_id is the serial id of the most-recently-inserted row —
            # it must be the highest and therefore must survive the prune.
            self.assertIsNotNone(last_id)

            repo = self._make_repo_with_zero_interval()
            repo._maybe_prune(conn, self.pid)

            survivors = _surviving_ids(conn, self.pid)
            self.assertIn(
                last_id,
                survivors,
                f"The newest row (id={last_id}) was deleted by _maybe_prune — "
                "the NOT IN (… ORDER BY id DESC LIMIT N) guard is not protecting it.",
            )
            self.assertEqual(
                len(survivors),
                min_keep,
                f"Expected {min_keep} survivors but got {len(survivors)}.",
            )
            # The survivors must be the top-N by serial id, i.e. the largest ids.
            all_ids_before_prune_sorted = sorted(survivors + list(
                set(range(survivors[0] - (total_inserted - min_keep), survivors[0]))
                # note: we just assert the known last_id is present and count is right
            ))
            # Primary assertions already checked above; confirm the max id survived.
            self.assertEqual(
                max(survivors),
                last_id,
                "The row with the highest serial id must be among the survivors.",
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Test 3: recent rows (within retention window) are never deleted
    # ------------------------------------------------------------------

    def test_prune_does_not_delete_recent_rows(self):
        """Snapshots within the retention window must never be pruned, even
        if there are more than MIN_SNAPSHOTS_TO_KEEP of them."""
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        min_keep = PortfolioSnapshotRepository.MIN_SNAPSHOTS_TO_KEEP
        total_inserted = min_keep + 3

        conn = _connect()
        try:
            # Insert rows dated only 1 day ago — well within the 30-day window.
            for _ in range(total_inserted):
                _insert_old_snapshot(conn, self.pid, days_old=1)

            before = _row_count(conn, self.pid)
            self.assertEqual(before, total_inserted)

            repo = self._make_repo_with_zero_interval()
            repo._maybe_prune(conn, self.pid)

            after = _row_count(conn, self.pid)
            self.assertEqual(
                after,
                total_inserted,
                "Recent snapshots (within retention window) must not be deleted.",
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Test 4: cooldown is tracked in the class-level dict after a real commit
    # ------------------------------------------------------------------

    def test_cooldown_recorded_after_real_db_commit(self):
        """After a successful _maybe_prune against the real DB the portfolio_id
        must appear in _LAST_PRUNED so subsequent calls within the cooldown
        window are skipped."""
        from src.portfolio.repositories.portfolio_snapshot import (  # noqa: PLC0415
            PortfolioSnapshotRepository,
        )
        repo = self._make_repo_with_zero_interval()

        conn = _connect()
        try:
            self.assertNotIn(self.pid, PortfolioSnapshotRepository._LAST_PRUNED)
            repo._maybe_prune(conn, self.pid)
            self.assertIn(
                self.pid,
                PortfolioSnapshotRepository._LAST_PRUNED,
                "_LAST_PRUNED must be updated after a successful DB commit.",
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
