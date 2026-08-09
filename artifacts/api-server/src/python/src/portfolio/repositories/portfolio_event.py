"""RC-10C1 Portfolio Core — PortfolioEventRepository.

Persistence layer for portfolio events.  Events are persisted to the
``portfolio_events`` Postgres table (when ``DATABASE_URL`` is set) so that
the event history survives API-server restarts and is shared across the
per-request Python processes; an in-memory list is kept as a warm cache
and as the fallback when no database is available.

Durability semantics
--------------------
* Writes are fail-open: a DB error keeps the in-memory copy and never
  breaks the caller (event persistence sits on the fill write path).
* Events are deduplicated at the database by ``(portfolio_id,
  idempotency_key)`` — per-process re-seeding therefore never duplicates
  history, and ledger replay stays idempotent across processes.
* Reads merge DB rows with the process-local list (deduped by
  idempotency key) so events written while the DB was briefly down are
  still visible in this process.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from src.portfolio.contracts import PortfolioEvent, PortfolioEventType

logger = logging.getLogger(__name__)


def _db_available() -> bool:
    """Postgres persistence enabled?

    Requires DATABASE_URL; can be disabled explicitly (e.g. by unit tests)
    via PORTFOLIO_EVENT_DB_DISABLED=1 so hermetic tests never touch the
    development database.
    """
    if os.environ.get("PORTFOLIO_EVENT_DB_DISABLED") == "1":
        return False
    return bool(os.environ.get("DATABASE_URL"))


_SCHEMA_READY = False


def _connect():
    import psycopg2  # lazy — in-memory-only envs don't need it
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    """Idempotent bootstrap of the portfolio_events table."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        # Canonical schema = src/database/models/portfolio_models.py
        # (PortfolioEventModel). Column names/types must match the ORM so
        # both persistence paths share one contract.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_events (
                id SERIAL PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                sequence INTEGER,
                version INTEGER NOT NULL DEFAULT 1,
                instrument_token INTEGER,
                internal_order_id TEXT,
                broker_order_id TEXT,
                strategy_id TEXT,
                correlation_id TEXT,
                payload JSONB NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (portfolio_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_events_pid_time
                ON portfolio_events (portfolio_id, occurred_at);
            """
        )
        # Migration for tables provisioned by earlier revisions or by the
        # ORM: converge on the canonical column set. All statements are
        # idempotent.
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'portfolio_events'
                      AND column_name = 'event_payload'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'portfolio_events'
                      AND column_name = 'payload'
                ) THEN
                    ALTER TABLE portfolio_events
                        RENAME COLUMN event_payload TO payload;
                END IF;
            END $$;
            ALTER TABLE portfolio_events
                ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
                ADD COLUMN IF NOT EXISTS instrument_token INTEGER,
                ADD COLUMN IF NOT EXISTS internal_order_id TEXT,
                ADD COLUMN IF NOT EXISTS broker_order_id TEXT,
                ADD COLUMN IF NOT EXISTS strategy_id TEXT,
                ADD COLUMN IF NOT EXISTS correlation_id TEXT,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW();
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _event_to_payload(event: PortfolioEvent):
    from psycopg2.extras import Json
    return Json(json.loads(event.model_dump_json()))


def _event_from_payload(payload: Any) -> PortfolioEvent:
    if isinstance(payload, str):
        return PortfolioEvent.model_validate_json(payload)
    return PortfolioEvent.model_validate(payload)


class PortfolioEventRepository:
    """Stores and retrieves PortfolioEvent records.

    Postgres-backed (``portfolio_events`` table) when ``DATABASE_URL`` is
    configured; otherwise falls back to a process-local in-memory list.
    DB failures degrade to the previous in-memory semantics, never raise.
    """

    def __init__(self) -> None:
        self._events: list[PortfolioEvent] = []
        # Contiguous incorporated floor per pid: every durable id <= baseline
        # is reflected in this instance's state.
        self._baseline: dict[str, int] = {}
        # Durable ids > baseline that this instance has incorporated
        # (own writes + replayed events).
        self._above: dict[str, set[int]] = {}

    # ── persistence helpers ────────────────────────────────────────────

    def _db_save_many(self, events: list[PortfolioEvent]) -> None:
        conn = _connect()
        try:
            _ensure_schema(conn)
            self._maybe_prune(conn, events[0].portfolio_id if events else None)
            with conn.cursor() as cur:
                for event in events:
                    cur.execute(
                        """
                        INSERT INTO portfolio_events (
                            event_id, idempotency_key, event_type,
                            portfolio_id, sequence, version,
                            instrument_token, internal_order_id,
                            broker_order_id, strategy_id, correlation_id,
                            payload, occurred_at
                        ) VALUES (
                            %s,%s,%s,%s,
                            COALESCE(%s, (SELECT COALESCE(MAX(sequence),0)+1
                                          FROM portfolio_events
                                          WHERE portfolio_id = %s)),
                            %s,%s,%s,%s,%s,%s,%s,%s
                        )
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            str(event.event_id),
                            event.idempotency_key,
                            event.event_type.value,
                            event.portfolio_id,
                            event.sequence,
                            event.portfolio_id,
                            event.version,
                            event.instrument_token,
                            event.internal_order_id,
                            event.broker_order_id,
                            event.strategy_id,
                            event.correlation_id,
                            _event_to_payload(event),
                            event.occurred_at,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

    _PRUNED_PIDS: set[str] = set()  # class-level: prune once per process/pid
    RETENTION_DAYS = 30

    def _note_durable_ids(self, events: list[PortfolioEvent]) -> None:
        """Record the serial ids of events THIS instance durably wrote.

        Ids are added to the incorporated SET — never used directly as a
        cursor. The snapshot cursor is the largest CONTIGUOUS durable
        prefix (see :meth:`incorporated_cursor`): a max-of-own-writes
        cursor would leap past a concurrent writer's interleaved event and
        skip it forever on recovery."""
        try:
            conn = _connect()
            try:
                with conn.cursor() as cur:
                    for event in events:
                        cur.execute(
                            "SELECT id FROM portfolio_events "
                            "WHERE portfolio_id = %s AND idempotency_key = %s",
                            (event.portfolio_id, event.idempotency_key),
                        )
                        row = cur.fetchone()
                        if row and row[0] is not None:
                            pid = event.portfolio_id
                            self._above.setdefault(pid, set()).add(
                                int(row[0]))
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("incorporated-cursor lookup skipped: %s", exc)

    def incorporated_cursor(self, portfolio_id: str = "default") -> int | None:
        """Largest durable serial id C such that EVERY durable event of this
        portfolio with id <= C is incorporated in this instance's state.

        Computed by walking this portfolio's durable ids above the baseline
        in order and advancing only while each id is in the incorporated
        set. A concurrent writer's un-replayed event creates a gap and
        pins the cursor below it, so recovery will replay it. Conservative
        on DB failure (returns the last proven baseline)."""
        baseline = self._baseline.get(portfolio_id, 0)
        above = self._above.get(portfolio_id, set())
        if baseline == 0 and not above:
            return None  # nothing durable known (e.g. DB disabled)
        if not _db_available():
            return baseline or None
        try:
            conn = _connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM portfolio_events "
                        "WHERE portfolio_id = %s AND id > %s ORDER BY id",
                        (portfolio_id, baseline),
                    )
                    rows = [int(r[0]) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("cursor prefix scan skipped: %s", exc)
            return baseline or None
        for rid in rows:
            if rid in above:
                baseline = rid
            else:
                break  # gap: an event we have not incorporated
        # Persist the proven prefix and drop covered set entries.
        self._baseline[portfolio_id] = baseline
        self._above[portfolio_id] = {i for i in above if i > baseline}
        return baseline or None

    def note_baseline(self, portfolio_id: str, sequence: int | None) -> None:
        """Set the contiguous incorporated floor (from a recovered
        snapshot's cursor): every durable id <= sequence is incorporated."""
        if sequence is None:
            return
        cur = self._baseline.get(portfolio_id, 0)
        self._baseline[portfolio_id] = max(cur, int(sequence))
        above = self._above.get(portfolio_id)
        if above:
            self._above[portfolio_id] = {
                i for i in above if i > self._baseline[portfolio_id]}

    def note_incorporated(self, portfolio_id: str, sequence: int | None) -> None:
        """Record one durable event id as incorporated (recovery replay)."""
        if sequence is None:
            return
        if int(sequence) > self._baseline.get(portfolio_id, 0):
            self._above.setdefault(portfolio_id, set()).add(int(sequence))

    def _maybe_prune(self, conn, portfolio_id: str | None) -> None:
        """Bounded retention (best-effort, once per process per portfolio).

        Cursor-based, never wall-clock: a row is prunable only when its
        serial id is at or below the replay baseline — the MINIMUM
        event_cursor across the most recent snapshots (any of which could
        be the recovery target) — AND it is older than the audit window.
        Backdated occurrence times can never cause a replay-required event
        to be deleted, because the id comparison ignores occurred_at."""
        if not portfolio_id or portfolio_id in self._PRUNED_PIDS:
            return
        self._PRUNED_PIDS.add(portfolio_id)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM portfolio_events
                    WHERE portfolio_id = %s
                      AND occurred_at < NOW() - make_interval(days => %s)
                      AND id <= COALESCE(
                          (SELECT MIN(event_cursor) FROM (
                              SELECT event_cursor FROM portfolio_snapshots
                              WHERE portfolio_id = %s
                                AND event_cursor IS NOT NULL
                              ORDER BY id DESC LIMIT 5
                          ) recent), 0)
                    """,
                    (portfolio_id, self.RETENTION_DAYS, portfolio_id),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.debug("event prune skipped: %s", exc)

    def _db_fetch(
        self, portfolio_id: str, after: datetime | None = None
    ) -> list[PortfolioEvent]:
        """Insert-ordered fetch of decodable events from Postgres.

        The returned events carry the durable table id as their
        ``sequence`` — per-process ledger sequences restart at 1 in every
        process and would collide across processes, so the serial id is
        the only cross-process replay cursor.

        Undecodable rows are logged and skipped — events are an audit
        trail, and one bad row must not block recovery of the rest."""
        conn = _connect()
        try:
            _ensure_schema(conn)
            sql = (
                "SELECT id, payload FROM portfolio_events "
                "WHERE portfolio_id = %s"
            )
            params: list[Any] = [portfolio_id]
            if after is not None:
                sql += " AND occurred_at > %s"
                params.append(after)
            # Serial id reflects durable write order (occurred_at can tie).
            sql += " ORDER BY id ASC"
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        out: list[PortfolioEvent] = []
        for (row_id, payload) in rows:
            try:
                event = _event_from_payload(payload)
                # Durable cross-process ordering: override the process-local
                # sequence with the table's serial id.
                out.append(event.model_copy(update={"sequence": int(row_id)}))
            except Exception as exc:
                logger.warning(
                    "Unparseable persisted portfolio event — skipped",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return out

    def _merged(
        self, portfolio_id: str, after: datetime | None = None
    ) -> list[PortfolioEvent]:
        """DB rows merged with the in-memory list, deduped by idempotency
        key (DB copy wins), preserving durable write order first."""
        local = [
            e for e in self._events
            if e.portfolio_id == portfolio_id
            and (after is None or e.occurred_at > after)
        ]
        if not _db_available():
            return local
        try:
            db_rows = self._db_fetch(portfolio_id, after=after)
        except Exception as exc:
            logger.warning(
                "Event DB read failed — using in-memory fallback",
                extra={"portfolio_id": portfolio_id, "error": str(exc)},
            )
            return local
        seen = {e.idempotency_key for e in db_rows}
        # Durable rows first (globally ordered by serial id); local-only
        # leftovers (events whose DB persist failed) after, in this
        # process's append order — they are this process's newest writes
        # and carry NO durable id, so they must never be interleaved with
        # (or compared against) serial-id cursor semantics. Their per-
        # process ledger sequence is stripped so callers can never mistake
        # it for a durable id (e.g. when advancing a snapshot cursor).
        return db_rows + [
            e.model_copy(update={"sequence": None})
            for e in local if e.idempotency_key not in seen
        ]

    def _split_after_cursor(
        self, portfolio_id: str, sequence: int
    ) -> list[PortfolioEvent]:
        """Durable rows with serial id > *sequence*, followed by local-only
        events (never durably persisted).  Local per-process sequences are
        NOT comparable to DB serial ids, so local-only events are included
        unconditionally — idempotency-key dedupe at replay makes an
        already-applied event a safe no-op."""
        local = [e for e in self._events if e.portfolio_id == portfolio_id]
        if not _db_available():
            return [e for e in local if (e.sequence or 0) > sequence]
        try:
            db_rows = self._db_fetch(portfolio_id)
        except Exception as exc:
            logger.warning(
                "Event DB read failed — using in-memory fallback",
                extra={"portfolio_id": portfolio_id, "error": str(exc)},
            )
            return [e for e in local if (e.sequence or 0) > sequence]
        durable_keys = {e.idempotency_key for e in db_rows}
        after = [e for e in db_rows if (e.sequence or 0) > sequence]
        # Local-only events carry per-process ledger sequences that are NOT
        # durable serial ids — strip them so a caller advancing a snapshot
        # cursor from replayed events can never leap past durable rows it
        # has not seen (note_incorporated ignores None).
        local_only = [
            e.model_copy(update={"sequence": None})
            for e in local if e.idempotency_key not in durable_keys
        ]
        return after + local_only

    # ── public API ─────────────────────────────────────────────────────

    async def append(self, event: PortfolioEvent) -> None:
        """Persist *event* (in-memory always; Postgres when available)."""
        self._events.append(event)
        if _db_available():
            try:
                self._db_save_many([event])
                self._note_durable_ids([event])
            except Exception as exc:
                logger.warning(
                    "Event DB persist failed — kept in-memory copy only",
                    extra={
                        "event_id": str(event.event_id),
                        "error": str(exc),
                    },
                )
        logger.debug(
            "Portfolio event persisted",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type.value,
                "idempotency_key": event.idempotency_key,
            },
        )

    async def append_many(self, events: list[PortfolioEvent]) -> None:
        """Persist multiple events."""
        for event in events:
            await self.append(event)

    async def get_events_after_sequence(
        self, portfolio_id: str, sequence: int
    ) -> list[PortfolioEvent]:
        """Return events after the durable serial-id cursor *sequence*.

        Durable rows are filtered by serial id; local-only events (DB
        persist failed) are appended unconditionally since their
        per-process sequences are not cursor-comparable."""
        return self._split_after_cursor(portfolio_id, sequence)

    async def get_events_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioEvent]:
        """Return events occurred after *after* for *portfolio_id*."""
        return self._merged(portfolio_id, after=after)

    async def list_all(self, portfolio_id: str = "default") -> list[PortfolioEvent]:
        """Return all events for *portfolio_id*."""
        return self._merged(portfolio_id)
