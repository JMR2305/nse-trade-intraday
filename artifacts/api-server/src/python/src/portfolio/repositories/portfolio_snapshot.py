"""RC-10C1 Portfolio Core — PortfolioSnapshotRepository.

Persistence layer for portfolio snapshots.  Snapshots are persisted to the
``portfolio_snapshots`` Postgres table (when ``DATABASE_URL`` is set) so
that portfolio state survives API-server restarts; an in-memory list is
kept as a warm cache and as the fallback when no database is available.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from src.portfolio.contracts import PortfolioSnapshot
from src.portfolio.exceptions import CorruptSnapshotError

logger = logging.getLogger(__name__)


def compute_snapshot_checksum(snapshot: PortfolioSnapshot) -> str:
    """Return the canonical SHA-256 checksum for *snapshot*.

    The checksum covers every field *except* ``checksum`` itself so that
    it can be stored alongside the payload without creating a circular
    dependency.  The JSON serialisation uses sorted keys for determinism.
    """
    data = snapshot.model_dump(exclude={"checksum"})

    def _default(obj: Any) -> Any:
        from decimal import Decimal
        from uuid import UUID
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")

    serialised = json.dumps(data, sort_keys=True, default=_default)
    return hashlib.sha256(serialised.encode()).hexdigest()


def validate_snapshot(snapshot: PortfolioSnapshot) -> None:
    """Raise :class:`CorruptSnapshotError` if *snapshot* fails integrity checks.

    Rules
    -----
    * If ``snapshot.checksum`` is **present**, it must match the recomputed
      checksum.  A mismatch means the stored bytes were modified after the
      checksum was written.
    * A ``None`` checksum is accepted (snapshots created before checksumming
      was introduced are treated as valid — this is a forward-compatible
      policy that can be tightened later).
    """
    if snapshot.checksum is None:
        return  # legacy snapshot — no checksum to validate
    expected = compute_snapshot_checksum(snapshot)
    if snapshot.checksum != expected:
        raise CorruptSnapshotError(
            f"Snapshot {snapshot.snapshot_id} for portfolio "
            f"'{snapshot.portfolio_id}' failed checksum validation "
            f"(stored={snapshot.checksum!r}, computed={expected!r})"
        )


def _db_available() -> bool:
    """Postgres persistence enabled?

    Requires DATABASE_URL; can be disabled explicitly (e.g. by unit tests)
    via PORTFOLIO_SNAPSHOT_DB_DISABLED=1 so hermetic tests never touch the
    development database.
    """
    if os.environ.get("PORTFOLIO_SNAPSHOT_DB_DISABLED") == "1":
        return False
    return bool(os.environ.get("DATABASE_URL"))


_SCHEMA_READY = False


def _connect():
    import psycopg2  # lazy — in-memory-only envs don't need it
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    """Idempotent bootstrap of the portfolio_snapshots table.

    Mirrors src/database/models/portfolio_models.PortfolioSnapshotModel so a
    later SQLAlchemy migration finds a compatible table already in place.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id SERIAL PRIMARY KEY,
                snapshot_id TEXT NOT NULL UNIQUE,
                portfolio_id TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                paper_mode BOOLEAN NOT NULL DEFAULT TRUE,
                cash_available NUMERIC(20,6) NOT NULL,
                cash_blocked NUMERIC(20,6) NOT NULL,
                cash_total NUMERIC(20,6) NOT NULL,
                buying_power_net NUMERIC(20,6) NOT NULL,
                equity NUMERIC(20,6) NOT NULL,
                open_position_count INTEGER NOT NULL DEFAULT 0,
                pending_order_count INTEGER NOT NULL DEFAULT 0,
                realised_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
                unrealised_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
                daily_pnl NUMERIC(20,6) NOT NULL DEFAULT 0,
                drawdown NUMERIC(20,6) NOT NULL DEFAULT 0,
                snapshot_payload JSONB,
                checksum TEXT,
                snapshotted_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_pid
                ON portfolio_snapshots (portfolio_id, snapshotted_at DESC);
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _snapshot_to_payload(snapshot: PortfolioSnapshot):
    """Explicit JSONB adaptation — psycopg2 adapts plain strings as text,
    so wrap the dict payload in extras.Json for an unambiguous jsonb write."""
    from psycopg2.extras import Json
    return Json(json.loads(snapshot.model_dump_json()))


def _snapshot_from_payload(payload: Any) -> PortfolioSnapshot:
    if isinstance(payload, str):
        return PortfolioSnapshot.model_validate_json(payload)
    return PortfolioSnapshot.model_validate(payload)


class PortfolioSnapshotRepository:
    """Stores and retrieves PortfolioSnapshot objects.

    Postgres-backed (``portfolio_snapshots`` table) when ``DATABASE_URL``
    is configured; otherwise falls back to a process-local in-memory list.
    DB write failures are logged and never break the caller — the in-memory
    copy is always kept, so behaviour degrades to the previous in-memory
    semantics rather than raising.
    """

    def __init__(self) -> None:
        self._snapshots: list[PortfolioSnapshot] = []

    # ── persistence helpers ────────────────────────────────────────────

    def _db_save(self, snapshot: PortfolioSnapshot) -> None:
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO portfolio_snapshots (
                        snapshot_id, portfolio_id, status, version, paper_mode,
                        cash_available, cash_blocked, cash_total,
                        buying_power_net, equity,
                        open_position_count, pending_order_count,
                        realised_pnl, unrealised_pnl, daily_pnl, drawdown,
                        snapshot_payload, checksum, snapshotted_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    (
                        str(snapshot.snapshot_id),
                        snapshot.portfolio_id,
                        snapshot.status.value,
                        snapshot.version,
                        snapshot.paper_mode,
                        str(snapshot.cash.available),
                        str(snapshot.cash.blocked),
                        str(snapshot.cash.total),
                        str(snapshot.buying_power.net),
                        str(snapshot.pnl.current_equity),
                        len(snapshot.open_positions),
                        snapshot.pending_order_count,
                        str(snapshot.pnl.realised),
                        str(snapshot.pnl.unrealised),
                        str(snapshot.pnl.daily_pnl),
                        str(snapshot.pnl.drawdown),
                        _snapshot_to_payload(snapshot),
                        snapshot.checksum,
                        snapshot.snapshotted_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _db_fetch(
        self, portfolio_id: str, after: datetime | None = None, limit: int | None = None
    ) -> tuple[list[PortfolioSnapshot], int]:
        """Newest-first fetch of snapshots with payloads from Postgres.

        Returns ``(snapshots, corrupt_count)`` where *corrupt_count* is the
        number of persisted rows whose payload could not be decoded — such
        rows are corruption evidence, not silently discardable noise."""
        conn = _connect()
        try:
            _ensure_schema(conn)
            sql = (
                "SELECT snapshot_payload FROM portfolio_snapshots "
                "WHERE portfolio_id = %s AND snapshot_payload IS NOT NULL"
            )
            params: list[Any] = [portfolio_id]
            if after is not None:
                sql += " AND snapshotted_at > %s"
                params.append(after)
            # Durable ordering invariant: the serial `id` reflects write
            # order and is monotonic per table, whereas snapshotted_at can
            # regress (create_snapshot() reuses the state's last-update
            # timestamp, so a startup seed snapshot written AFTER a fill
            # snapshot may carry an OLDER timestamp). Latest write wins.
            sql += " ORDER BY id DESC"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        out: list[PortfolioSnapshot] = []
        corrupt = 0
        for (payload,) in rows:
            try:
                out.append(_snapshot_from_payload(payload))
            except Exception as exc:
                corrupt += 1
                logger.warning(
                    "Unparseable persisted snapshot (corruption candidate)",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return out, corrupt

    def _candidates(self, portfolio_id: str) -> tuple[list[PortfolioSnapshot], int]:
        """Newest-first candidates plus a count of corrupt (undecodable)
        persisted rows.  DB when available, else in-memory."""
        if _db_available():
            try:
                rows, corrupt = self._db_fetch(portfolio_id)
                if rows or corrupt:
                    return rows, corrupt
            except Exception as exc:
                logger.warning(
                    "Snapshot DB read failed — using in-memory fallback",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return sorted(
            [s for s in self._snapshots if s.portfolio_id == portfolio_id],
            key=lambda s: s.snapshotted_at,
            reverse=True,
        ), 0

    # ── public API ─────────────────────────────────────────────────────

    async def save(self, snapshot: PortfolioSnapshot) -> None:
        """Persist *snapshot* (in-memory always; Postgres when available)."""
        self._snapshots.append(snapshot)
        if _db_available():
            try:
                self._db_save(snapshot)
            except Exception as exc:
                logger.warning(
                    "Snapshot DB persist failed — kept in-memory copy only",
                    extra={
                        "snapshot_id": str(snapshot.snapshot_id),
                        "error": str(exc),
                    },
                )
        logger.debug(
            "Snapshot saved",
            extra={
                "snapshot_id": str(snapshot.snapshot_id),
                "portfolio_id": snapshot.portfolio_id,
                "version": snapshot.version,
            },
        )

    async def get_latest(self, portfolio_id: str = "default") -> PortfolioSnapshot | None:
        """Return the most recent snapshot for *portfolio_id*, or None."""
        candidates, _corrupt = self._candidates(portfolio_id)
        return candidates[0] if candidates else None

    async def get_latest_valid(self, portfolio_id: str = "default") -> PortfolioSnapshot | None:
        """Return the most recent *valid* snapshot for *portfolio_id*.

        "Valid" means the snapshot passes :func:`validate_snapshot`.  Candidates
        are tested newest-first; the first one that passes is returned.

        Raises
        ------
        CorruptSnapshotError
            If **all** candidates for *portfolio_id* exist but none pass
            checksum validation.  This signals that the snapshot store is
            in a corrupt state and a fill-history rebuild is required.
        """
        candidates, corrupt = self._candidates(portfolio_id)
        if not candidates:
            if corrupt:
                # Rows exist but none could even be decoded — that is the
                # all-candidates-corrupt case and must raise, not return None,
                # so recovery emits its critical alert and rebuilds from fills.
                raise CorruptSnapshotError(
                    f"All {corrupt} persisted snapshot(s) for portfolio "
                    f"'{portfolio_id}' are undecodable"
                )
            return None

        last_err: CorruptSnapshotError | None = None
        for candidate in candidates:
            try:
                validate_snapshot(candidate)
                return candidate
            except CorruptSnapshotError as exc:
                logger.warning(
                    "Snapshot failed checksum — trying older candidate",
                    extra={
                        "snapshot_id": str(candidate.snapshot_id),
                        "portfolio_id": portfolio_id,
                        "error": str(exc),
                    },
                )
                last_err = exc

        # Every candidate failed — propagate the most recent error.
        assert last_err is not None
        raise last_err

    async def list_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioSnapshot]:
        """Return snapshots taken after *after* for *portfolio_id*."""
        if _db_available():
            try:
                rows, _corrupt = self._db_fetch(portfolio_id, after=after)
                return list(reversed(rows))
            except Exception as exc:
                logger.warning(
                    "Snapshot DB read failed in list_after — using in-memory fallback",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return [
            s for s in self._snapshots
            if s.portfolio_id == portfolio_id and s.snapshotted_at > after
        ]
