"""RC-10C1 Portfolio Core — ReconciliationRepository.

Persistence layer for reconciliation reports.  Reports are persisted to
the canonical ``reconciliation_runs`` Postgres table (when ``DATABASE_URL``
is set) so the audit trail survives API-server restarts; an in-memory
list is kept as a warm cache and as the fallback when no database is
available.  DB failures degrade to in-memory semantics, never raise.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from src.portfolio.contracts import PortfolioReconciliationReport

logger = logging.getLogger(__name__)


def _db_available() -> bool:
    """Postgres persistence enabled?

    Requires DATABASE_URL; can be disabled explicitly (e.g. by unit tests)
    via PORTFOLIO_RECON_DB_DISABLED=1 so hermetic tests never touch the
    development database.
    """
    if os.environ.get("PORTFOLIO_RECON_DB_DISABLED") == "1":
        return False
    return bool(os.environ.get("DATABASE_URL"))


_SCHEMA_READY = False


def _connect():
    import psycopg2  # lazy — in-memory-only envs don't need it
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    """Idempotent bootstrap/migration of the canonical reconciliation_runs
    table (schema owner: src/database/models/portfolio_models.py
    ReconciliationRunModel; report_payload is a repository extension also
    declared on the ORM model)."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id SERIAL PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                portfolio_id TEXT NOT NULL,
                dry_run BOOLEAN NOT NULL,
                critical_count INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                portfolio_ready BOOLEAN NOT NULL,
                notes TEXT,
                state_version INTEGER NOT NULL DEFAULT 0,
                broker_snapshot_age_s NUMERIC(20,6),
                report_payload JSONB,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ
            );
            ALTER TABLE reconciliation_runs
                ADD COLUMN IF NOT EXISTS report_payload JSONB;
            CREATE INDEX IF NOT EXISTS idx_recon_runs_pid_time
                ON reconciliation_runs (portfolio_id, started_at DESC);
            """
        )
        # One-time migration from the legacy repository-owned table.
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'portfolio_reconciliations'
                ) THEN
                    INSERT INTO reconciliation_runs (
                        run_id, portfolio_id, dry_run, critical_count,
                        warning_count, portfolio_ready, report_payload,
                        started_at, completed_at
                    )
                    SELECT run_id, portfolio_id, dry_run, critical_count,
                           warning_count, portfolio_ready, report_payload,
                           started_at, completed_at
                    FROM reconciliation_runs
                    ORDER BY id
                    ON CONFLICT (run_id) DO NOTHING;
                    DROP TABLE portfolio_reconciliations;
                END IF;
            END $$;
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _report_to_payload(report: PortfolioReconciliationReport):
    from psycopg2.extras import Json
    return Json(json.loads(report.model_dump_json()))


def _report_from_payload(payload: Any) -> PortfolioReconciliationReport:
    if isinstance(payload, str):
        return PortfolioReconciliationReport.model_validate_json(payload)
    return PortfolioReconciliationReport.model_validate(payload)


class ReconciliationRepository:
    """Stores and retrieves PortfolioReconciliationReport objects.

    Postgres-backed (``reconciliation_runs`` table) when
    ``DATABASE_URL`` is configured; otherwise process-local in-memory.
    """

    def __init__(self) -> None:
        self._reports: list[PortfolioReconciliationReport] = []

    # ── persistence helpers ────────────────────────────────────────────

    _PRUNED_PIDS: set[str] = set()  # class-level: prune once per process/pid
    RETENTION_DAYS = 30

    def _maybe_prune(self, conn, portfolio_id: str) -> None:
        """Bounded retention (best-effort): drop reports older than the
        audit window, always keeping the newest report per portfolio."""
        if portfolio_id in self._PRUNED_PIDS:
            return
        self._PRUNED_PIDS.add(portfolio_id)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM reconciliation_runs
                    WHERE portfolio_id = %s
                      AND started_at < NOW() - make_interval(days => %s)
                      AND id <> (SELECT MAX(id) FROM reconciliation_runs
                                 WHERE portfolio_id = %s)
                    """,
                    (portfolio_id, self.RETENTION_DAYS, portfolio_id),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.debug("reconciliation prune skipped: %s", exc)

    def _db_save(self, report: PortfolioReconciliationReport) -> None:
        conn = _connect()
        try:
            _ensure_schema(conn)
            self._maybe_prune(conn, report.portfolio_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reconciliation_runs (
                        run_id, portfolio_id, dry_run, critical_count,
                        warning_count, portfolio_ready, report_payload,
                        started_at, completed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    (
                        str(report.run_id),
                        report.portfolio_id,
                        report.dry_run,
                        report.critical_count,
                        report.warning_count,
                        report.portfolio_ready,
                        _report_to_payload(report),
                        report.started_at,
                        report.completed_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _db_fetch(
        self, portfolio_id: str, after: datetime | None = None,
        limit: int | None = None,
    ) -> list[PortfolioReconciliationReport]:
        """Newest-first fetch of decodable reports from Postgres."""
        conn = _connect()
        try:
            _ensure_schema(conn)
            sql = (
                "SELECT report_payload FROM reconciliation_runs "
                "WHERE portfolio_id = %s"
            )
            params: list[Any] = [portfolio_id]
            if after is not None:
                sql += " AND started_at > %s"
                params.append(after)
            sql += " ORDER BY id DESC"
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        out: list[PortfolioReconciliationReport] = []
        for (payload,) in rows:
            try:
                out.append(_report_from_payload(payload))
            except Exception as exc:
                logger.warning(
                    "Unparseable persisted reconciliation report — skipped",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return out

    def _candidates(
        self, portfolio_id: str, after: datetime | None = None
    ) -> list[PortfolioReconciliationReport]:
        """Newest-first reports; DB merged with in-memory (dedup by run_id)."""
        local = [
            r for r in self._reports
            if r.portfolio_id == portfolio_id
            and (after is None or r.started_at > after)
        ]
        if _db_available():
            try:
                db_rows = self._db_fetch(portfolio_id, after=after)
                seen = {r.run_id for r in db_rows}
                merged = db_rows + [r for r in local if r.run_id not in seen]
                return sorted(
                    merged,
                    key=lambda r: r.completed_at or r.started_at,
                    reverse=True,
                )
            except Exception as exc:
                logger.warning(
                    "Reconciliation DB read failed — using in-memory fallback",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
        return sorted(
            local, key=lambda r: r.completed_at or r.started_at, reverse=True
        )

    # ── public API ─────────────────────────────────────────────────────

    async def save(self, report: PortfolioReconciliationReport) -> None:
        """Persist *report* (in-memory always; Postgres when available)."""
        self._reports.append(report)
        if _db_available():
            try:
                self._db_save(report)
            except Exception as exc:
                logger.warning(
                    "Reconciliation DB persist failed — kept in-memory copy only",
                    extra={"run_id": str(report.run_id), "error": str(exc)},
                )
        logger.debug(
            "Reconciliation report saved",
            extra={
                "run_id": str(report.run_id),
                "portfolio_id": report.portfolio_id,
                "critical_count": report.critical_count,
                "portfolio_ready": report.portfolio_ready,
            },
        )

    async def get_latest(
        self, portfolio_id: str = "default"
    ) -> PortfolioReconciliationReport | None:
        """Return the most recent reconciliation report for *portfolio_id*.

        Bounded: the DB read is LIMIT 1 — it never loads full history."""
        if _db_available():
            try:
                rows = self._db_fetch(portfolio_id, limit=1)
                db_latest = rows[0] if rows else None
            except Exception as exc:
                logger.warning(
                    "Reconciliation DB read failed — using in-memory fallback",
                    extra={"portfolio_id": portfolio_id, "error": str(exc)},
                )
                db_latest = None
            local = [r for r in self._reports if r.portfolio_id == portfolio_id]
            candidates = ([db_latest] if db_latest else []) + local
            if not candidates:
                return None
            return max(candidates, key=lambda r: r.completed_at or r.started_at)
        candidates = self._candidates(portfolio_id)
        return candidates[0] if candidates else None

    async def list_after(
        self, portfolio_id: str, after: datetime
    ) -> list[PortfolioReconciliationReport]:
        """Return reports started after *after* for *portfolio_id*."""
        return [
            r for r in self._candidates(portfolio_id, after=after)
            if r.started_at > after
        ]

    async def count_unresolved(self, portfolio_id: str = "default") -> int:
        """Return the total unresolved critical discrepancy count from the latest report."""
        latest = await self.get_latest(portfolio_id)
        if latest is None:
            return 0
        return latest.critical_count
