"""
preopen_db.py — Phase 5A Pre-Open Intelligence database layer.

Creates and manages six isolated tables:
  preopen_sessions, preopen_snapshots, preopen_rankings,
  preopen_watchlists, preopen_provider_health, preopen_reconciliation

Additive only — never modifies existing tables.
Falls back gracefully when DB is unavailable.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from scan_state_store import db_available, _connect
except ImportError:
    def db_available() -> bool:
        return False
    def _connect():
        raise RuntimeError("DB not available")

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        # preopen_sessions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_sessions (
                session_id     TEXT PRIMARY KEY,
                trading_date   TEXT NOT NULL,
                started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status         TEXT NOT NULL DEFAULT 'INITIALISING',
                symbol_count   INTEGER DEFAULT 0,
                valid_count    INTEGER DEFAULT 0,
                stale_count    INTEGER DEFAULT 0,
                provider_status TEXT DEFAULT 'UNAVAILABLE',
                provider_collected_count INTEGER,
                persisted_count INTEGER,
                failed_count INTEGER,
                collection_started_at TIMESTAMPTZ,
                collection_completed_at TIMESTAMPTZ,
                collection_source TEXT,
                persistence_status TEXT,
                verified_collection_batch_id TEXT,
                frozen_collection_batch_id TEXT,
                retry_state TEXT,
                phase_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                frozen_at      TIMESTAMPTZ,
                reconciled_at  TIMESTAMPTZ,
                error          TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                updated_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # `CREATE TABLE IF NOT EXISTS` does not upgrade a pre-existing
        # production table. Keep the canonical columns above and make this
        # additive migration explicit so collection truth is durable everywhere.
        cur.execute("""
            ALTER TABLE preopen_sessions
                ADD COLUMN IF NOT EXISTS provider_collected_count INTEGER,
                ADD COLUMN IF NOT EXISTS persisted_count INTEGER,
                ADD COLUMN IF NOT EXISTS failed_count INTEGER,
                ADD COLUMN IF NOT EXISTS collection_started_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS collection_completed_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS collection_source TEXT,
                ADD COLUMN IF NOT EXISTS persistence_status TEXT,
                ADD COLUMN IF NOT EXISTS verified_collection_batch_id TEXT,
                ADD COLUMN IF NOT EXISTS frozen_collection_batch_id TEXT,
                ADD COLUMN IF NOT EXISTS retry_state TEXT,
                ADD COLUMN IF NOT EXISTS phase_state JSONB NOT NULL DEFAULT '{}'::jsonb
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_sessions_date
            ON preopen_sessions (trading_date DESC)
        """)

        # preopen_snapshots
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_snapshots (
                snapshot_id              TEXT PRIMARY KEY,
                session_id               TEXT REFERENCES preopen_sessions(session_id),
                collection_batch_id      TEXT,
                trading_date             TEXT NOT NULL,
                timestamp_ist            TIMESTAMPTZ NOT NULL,
                symbol                   TEXT NOT NULL,
                company_name             TEXT,
                sector                   TEXT,
                previous_close           DOUBLE PRECISION,
                indicative_equilibrium_price DOUBLE PRECISION,
                indicative_open_price    DOUBLE PRECISION,
                final_open_price         DOUBLE PRECISION,
                price_change             DOUBLE PRECISION,
                gap_percent              DOUBLE PRECISION,
                total_buy_quantity       BIGINT DEFAULT 0,
                total_sell_quantity      BIGINT DEFAULT 0,
                matched_quantity         BIGINT DEFAULT 0,
                final_executed_quantity  BIGINT DEFAULT 0,
                total_traded_value       DOUBLE PRECISION DEFAULT 0,
                buy_sell_imbalance       BIGINT DEFAULT 0,
                imbalance_percent        DOUBLE PRECISION DEFAULT 0,
                volume_rank              INTEGER,
                gap_rank                 INTEGER,
                liquidity_score          DOUBLE PRECISION DEFAULT 0,
                classification           TEXT,
                opportunity_score        DOUBLE PRECISION DEFAULT 0,
                factor_scores            JSONB,
                data_source              TEXT,
                data_freshness_seconds   INTEGER DEFAULT 0,
                source_status            TEXT,
                is_stale                 BOOLEAN DEFAULT TRUE,
                validation_status        TEXT DEFAULT 'UNVALIDATED',
                raw_payload_reference    TEXT,
                created_at               TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_snaps_date_sym
            ON preopen_snapshots (trading_date, symbol)
        """)
        # Production already has this table. Upgrade it before creating the
        # batch index so existing deployments retain durable Phase 5A access.
        cur.execute("""
            ALTER TABLE preopen_snapshots
                ADD COLUMN IF NOT EXISTS collection_batch_id TEXT
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session
            ON preopen_snapshots (session_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session_batch
            ON preopen_snapshots (session_id, collection_batch_id)
        """)

        # preopen_rankings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_rankings (
                id             BIGSERIAL PRIMARY KEY,
                session_id     TEXT REFERENCES preopen_sessions(session_id),
                trading_date   TEXT NOT NULL,
                frozen_at      TIMESTAMPTZ,
                rankings_json  JSONB NOT NULL,
                summary        JSONB,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_rankings_date
            ON preopen_rankings (trading_date DESC)
        """)

        # preopen_watchlists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_watchlists (
                id             BIGSERIAL PRIMARY KEY,
                session_id     TEXT REFERENCES preopen_sessions(session_id),
                trading_date   TEXT NOT NULL,
                list_type      TEXT NOT NULL,
                items_json     JSONB NOT NULL,
                generated_at   TIMESTAMPTZ DEFAULT NOW(),
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_watchlists_date_type
            ON preopen_watchlists (trading_date, list_type)
        """)

        # preopen_provider_health
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_provider_health (
                id             BIGSERIAL PRIMARY KEY,
                session_id     TEXT,
                trading_date   TEXT NOT NULL,
                checked_at     TIMESTAMPTZ DEFAULT NOW(),
                provider_name  TEXT NOT NULL,
                status         TEXT NOT NULL,
                latency_ms     INTEGER,
                message        TEXT,
                raw_response   JSONB,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_health_date
            ON preopen_provider_health (trading_date DESC, checked_at DESC)
        """)

        # preopen_reconciliation
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preopen_reconciliation (
                id                            BIGSERIAL PRIMARY KEY,
                session_id                    TEXT REFERENCES preopen_sessions(session_id),
                symbol                        TEXT NOT NULL,
                trading_date                  TEXT NOT NULL,
                indicative_equilibrium_price  DOUBLE PRECISION,
                final_pre_open_price          DOUBLE PRECISION,
                actual_open_price             DOUBLE PRECISION,
                price_at_0920                 DOUBLE PRECISION,
                price_at_0930                 DOUBLE PRECISION,
                indicative_to_open_error      DOUBLE PRECISION,
                opening_continuation          BOOLEAN,
                opening_reversal              BOOLEAN,
                watchlist_confirmed           BOOLEAN,
                was_in_watchlist              BOOLEAN DEFAULT FALSE,
                reconciled_at                 TIMESTAMPTZ DEFAULT NOW(),
                created_at                    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_recon_date_sym
            ON preopen_reconciliation (trading_date, symbol)
        """)

    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback=None):
    if not db_available():
        return fallback() if fallback else None
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            return fn(conn)
        finally:
            conn.close()
    except Exception:
        return fallback() if fallback else None


# ── Session CRUD ──────────────────────────────────────────────────────────────

def _forward_session_status(existing: str, incoming: Optional[str]) -> str:
    """Mirror the SQL upsert lifecycle guard for focused policy tests."""
    incoming = incoming or "INITIALISING"
    if existing in ("RECONCILED_0930", "COMPLETE", "NO_CANDIDATES"):
        return existing
    if existing == "RECONCILED" and incoming != "RECONCILED_0930":
        return existing
    if existing == "FROZEN" and incoming not in ("RECONCILED", "RECONCILED_0930"):
        return existing
    if incoming == "INITIALISING" and existing != "INITIALISING":
        return existing
    return incoming


def upsert_session(session: dict) -> bool:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_sessions
                    (session_id, trading_date, status, symbol_count, valid_count,
                     stale_count, provider_status, verified_collection_batch_id,
                     frozen_collection_batch_id, frozen_at, reconciled_at, error, updated_at)
                VALUES (%s,%s,COALESCE(%s, 'INITIALISING'),%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    -- Lifecycle is forward-only.  A late collection/init
                    -- write may still refresh counts, but can never reopen a
                    -- frozen or reconciled historical session.
                    status=CASE
                        WHEN preopen_sessions.status IN ('RECONCILED_0930', 'COMPLETE', 'NO_CANDIDATES')
                            THEN preopen_sessions.status
                        WHEN preopen_sessions.status = 'RECONCILED'
                             AND EXCLUDED.status <> 'RECONCILED_0930'
                            THEN preopen_sessions.status
                        WHEN preopen_sessions.status = 'FROZEN'
                             AND EXCLUDED.status NOT IN ('RECONCILED', 'RECONCILED_0930')
                            THEN preopen_sessions.status
                        WHEN EXCLUDED.status = 'INITIALISING'
                             AND preopen_sessions.status <> 'INITIALISING'
                            THEN preopen_sessions.status
                        ELSE EXCLUDED.status
                    END,
                    symbol_count=COALESCE(EXCLUDED.symbol_count, preopen_sessions.symbol_count),
                    valid_count=COALESCE(EXCLUDED.valid_count, preopen_sessions.valid_count),
                    stale_count=COALESCE(EXCLUDED.stale_count, preopen_sessions.stale_count),
                    provider_status=COALESCE(EXCLUDED.provider_status, preopen_sessions.provider_status),
                    verified_collection_batch_id=COALESCE(
                        EXCLUDED.verified_collection_batch_id,
                        preopen_sessions.verified_collection_batch_id
                    ),
                    frozen_collection_batch_id=COALESCE(
                        preopen_sessions.frozen_collection_batch_id,
                        EXCLUDED.frozen_collection_batch_id
                    ),
                    frozen_at=COALESCE(EXCLUDED.frozen_at, preopen_sessions.frozen_at),
                    reconciled_at=COALESCE(EXCLUDED.reconciled_at, preopen_sessions.reconciled_at),
                    error=COALESCE(EXCLUDED.error, preopen_sessions.error),
                    updated_at=NOW()
            """, [
                session.get("session_id"), session.get("trading_date"),
                session.get("status"),
                session.get("symbol_count"), session.get("valid_count"),
                session.get("stale_count"),
                session.get("provider_status"),
                session.get("verified_collection_batch_id"),
                session.get("frozen_collection_batch_id"),
                session.get("frozen_at"), session.get("reconciled_at"),
                session.get("error"),
            ])
        conn.commit()
        return True
    return bool(_with_db(to_db, fallback=lambda: False))


def get_session(session_id: str) -> Optional[dict]:
    """Return one session by id, for collection persistence verification."""
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session_id, trading_date, status, symbol_count, valid_count,
                       stale_count, provider_status, provider_collected_count,
                       persisted_count, failed_count, collection_started_at,
                       collection_completed_at, collection_source, persistence_status,
                        retry_state, phase_state, verified_collection_batch_id,
                        frozen_collection_batch_id, frozen_at, reconciled_at, error,
                       created_at, updated_at
                FROM preopen_sessions WHERE session_id = %s
            """, [session_id])
            row = cur.fetchone()
            if not row:
                return None
            cols = ["session_id","trading_date","status","symbol_count","valid_count",
                    "stale_count","provider_status","provider_collected_count",
                    "persisted_count","failed_count","collection_started_at",
                    "collection_completed_at","collection_source","persistence_status",
                    "retry_state","phase_state","verified_collection_batch_id",
                    "frozen_collection_batch_id","frozen_at","reconciled_at","error",
                    "created_at","updated_at"]
            return {k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in zip(cols, row)}
    return _with_db(from_db)


def get_latest_session() -> Optional[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session_id, trading_date, status, symbol_count, valid_count,
                       stale_count, provider_status, provider_collected_count,
                       persisted_count, failed_count, collection_started_at,
                       collection_completed_at, collection_source, persistence_status,
                        retry_state, phase_state, verified_collection_batch_id,
                        frozen_collection_batch_id, frozen_at, reconciled_at, error,
                       created_at, updated_at
                FROM preopen_sessions ORDER BY created_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return None
            cols = ["session_id","trading_date","status","symbol_count","valid_count",
                    "stale_count","provider_status","provider_collected_count",
                    "persisted_count","failed_count","collection_started_at",
                    "collection_completed_at","collection_source","persistence_status",
                    "retry_state","phase_state","verified_collection_batch_id",
                    "frozen_collection_batch_id","frozen_at","reconciled_at","error",
                    "created_at","updated_at"]
            return {k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in zip(cols, row)}
    return _with_db(from_db)


def get_session_for_trading_date(trading_date: str) -> Optional[dict]:
    """Return the most recent durable Phase 5A session for one IST date."""
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session_id FROM preopen_sessions
                WHERE trading_date = %s
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
            """, [trading_date])
            row = cur.fetchone()
        return get_session(row[0]) if row else None
    return _with_db(from_db)


def update_phase_state(session_id: str, phase: str, detail: dict,
                       completed: bool) -> bool:
    """Persist phase outcome so a restarted scheduler resumes truthfully."""
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE preopen_sessions
                SET phase_state = COALESCE(phase_state, '{}'::jsonb)
                    || jsonb_build_object(%s, %s::jsonb),
                    retry_state = CASE WHEN %s THEN NULL ELSE 'RETRY_REQUIRED' END,
                    updated_at = NOW()
                WHERE session_id = %s
            """, [phase, json.dumps({**detail, "completed": completed}),
                  completed, session_id])
            if cur.rowcount != 1:
                raise RuntimeError(f"Unknown pre-open session {session_id}")
        conn.commit()
        return True
    return bool(_with_db(to_db, fallback=lambda: False))


# ── Snapshot storage ──────────────────────────────────────────────────────────

def _insert_snapshot(cur, session_id: str, s: dict,
                     collection_batch_id: Optional[str] = None) -> None:
    cur.execute("""
        INSERT INTO preopen_snapshots
            (snapshot_id, session_id, collection_batch_id, trading_date, timestamp_ist, symbol,
             company_name, sector, previous_close, indicative_equilibrium_price,
             indicative_open_price, final_open_price, price_change, gap_percent,
             total_buy_quantity, total_sell_quantity, matched_quantity,
             final_executed_quantity, total_traded_value, buy_sell_imbalance,
             imbalance_percent, volume_rank, gap_rank, liquidity_score,
             classification, opportunity_score, factor_scores,
             data_source, data_freshness_seconds, source_status,
             is_stale, validation_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (snapshot_id) DO NOTHING
    """, [
        s.get("snapshot_id"), session_id, collection_batch_id, s.get("trading_date"),
        s.get("timestamp_ist"), s.get("symbol"), s.get("company_name"),
        s.get("sector"), s.get("previous_close"),
        s.get("indicative_equilibrium_price"), s.get("indicative_open_price"),
        s.get("final_open_price"), s.get("price_change"), s.get("gap_percent"),
        s.get("total_buy_quantity"), s.get("total_sell_quantity"),
        s.get("matched_quantity"), s.get("final_executed_quantity"),
        s.get("total_traded_value"), s.get("buy_sell_imbalance"),
        s.get("imbalance_percent"), s.get("volume_rank"), s.get("gap_rank"),
        s.get("liquidity_score"), s.get("classification"),
        s.get("opportunity_score"), json.dumps(s.get("factor_scores") or {}),
        s.get("data_source"), s.get("data_freshness_seconds"),
        s.get("source_status"), s.get("is_stale"), s.get("validation_status"),
    ])


def save_snapshots(session_id: str, snapshots: List[dict]) -> bool:
    def to_db(conn):
        with conn.cursor() as cur:
            for s in snapshots:
                _insert_snapshot(cur, session_id, s)
        conn.commit()
        return True
    return bool(_with_db(to_db, fallback=lambda: False))


def persist_collection(session_id: str, trading_date: str, snapshots: List[dict],
                       provider_status: str, valid_count: int,
                       stale_count: int, source: str = "SCHEDULED",
                       collection_batch_id: Optional[str] = None) -> dict:
    """Atomically persist a provider batch and prove every supplied row exists.

    The returned counts describe *this exact provider batch*, not a previous
    in-memory or database aggregate. A successful collection is therefore
    impossible unless provider_collected_count == persisted_count.
    """
    collection_batch_id = collection_batch_id or f"collection-{uuid.uuid4().hex}"
    provider_count = len(snapshots)
    snapshot_ids = [str(s.get("snapshot_id") or "") for s in snapshots]
    started_at = _now()

    def to_db(conn):
        with conn.cursor() as cur:
            for snapshot in snapshots:
                _insert_snapshot(cur, session_id, snapshot, collection_batch_id)
            if snapshot_ids:
                cur.execute("""
                    SELECT COUNT(*) FROM preopen_snapshots
                    WHERE session_id = %s AND collection_batch_id = %s
                      AND snapshot_id = ANY(%s)
                """, [session_id, collection_batch_id, snapshot_ids])
                persisted_count = int(cur.fetchone()[0] or 0)
            else:
                persisted_count = 0
            failed_count = max(0, provider_count - persisted_count)
            persistence_status = "MATCH" if persisted_count == provider_count else "MISMATCH"
            status = "COLLECTED" if persistence_status == "MATCH" else "PERSISTENCE_FAILED"
            cur.execute("""
                UPDATE preopen_sessions
                SET status = CASE
                        WHEN status IN ('FROZEN', 'RECONCILED', 'RECONCILED_0930', 'COMPLETE')
                            THEN status
                        ELSE %s
                    END,
                    symbol_count = %s, valid_count = %s, stale_count = %s,
                    provider_status = %s, provider_collected_count = %s,
                    persisted_count = %s, failed_count = %s,
                    collection_started_at = %s, collection_completed_at = NOW(),
                    collection_source = %s, persistence_status = %s,
                    verified_collection_batch_id = CASE
                        WHEN %s = 'MATCH'
                             AND status NOT IN ('FROZEN', 'RECONCILED', 'RECONCILED_0930', 'COMPLETE')
                            THEN %s
                        ELSE verified_collection_batch_id
                    END,
                    retry_state = CASE WHEN %s = 'MATCH' THEN NULL ELSE 'RETRY_REQUIRED' END,
                    error = CASE WHEN %s = 'MATCH' THEN NULL
                                 ELSE 'Provider collection did not persist completely' END,
                    updated_at = NOW()
                WHERE session_id = %s
            """, [status, provider_count, valid_count, stale_count, provider_status,
                  provider_count, persisted_count, failed_count, started_at, source,
                  persistence_status, persistence_status, collection_batch_id,
                  persistence_status, persistence_status, session_id])
            if cur.rowcount != 1:
                raise RuntimeError(f"Unknown pre-open session {session_id}")
        conn.commit()
        return {
            "success": persistence_status == "MATCH",
            "provider_collected_count": provider_count,
            "persisted_count": persisted_count,
            "failed_count": failed_count,
            "persistence_status": persistence_status,
            "collection_batch_id": collection_batch_id,
            "source": source,
        }

    return _with_db(to_db, fallback=lambda: {
        "success": False,
        "provider_collected_count": provider_count,
        "persisted_count": None,
        "failed_count": provider_count,
        "persistence_status": "PERSISTENCE_UNAVAILABLE",
        "collection_batch_id": collection_batch_id,
        "source": source,
        "error": "Durable pre-open collection persistence is unavailable",
    })


def record_collection_failure(session_id: str, status: str, error: str,
                              source: str = "SCHEDULED") -> bool:
    """Persist a retryable, explicit collection failure when the DB is reachable."""
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE preopen_sessions
                SET status = %s, collection_completed_at = NOW(), collection_source = %s,
                    persistence_status = 'NOT_COMPLETE', retry_state = 'RETRY_REQUIRED',
                    error = %s, updated_at = NOW()
                WHERE session_id = %s
            """, [status, source, str(error)[:500], session_id])
            if cur.rowcount != 1:
                raise RuntimeError(f"Unknown pre-open session {session_id}")
        conn.commit()
        return True
    return bool(_with_db(to_db, fallback=lambda: False))


def get_latest_snapshots(trading_date: Optional[str] = None) -> List[dict]:
    """Return one (most recent) snapshot per symbol for the given trading date.

    Uses DISTINCT ON (symbol) ordered by created_at DESC so that repeated
    collect_snapshot() calls within the same session never produce duplicate
    symbols in downstream analytics.  A Python-level dedup runs as a
    belt-and-suspenders safety net after the DB fetch.
    """
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT DISTINCT ON (symbol) *
                    FROM preopen_snapshots
                    WHERE trading_date = %s
                    ORDER BY symbol, created_at DESC
                """, [trading_date])
            else:
                cur.execute("""
                    SELECT DISTINCT ON (symbol) *
                    FROM preopen_snapshots
                    WHERE trading_date = (
                        SELECT MAX(trading_date) FROM preopen_snapshots
                    )
                    ORDER BY symbol, created_at DESC
                """)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
                result.append(d)

        # Belt-and-suspenders: deduplicate by symbol in Python, keeping the
        # row that was already picked as most-recent by the SQL above.
        seen: Dict[str, dict] = {}
        for snap in result:
            sym = snap.get("symbol")
            if sym and sym not in seen:
                seen[sym] = snap
        return list(seen.values())

    return _with_db(from_db) or []


def get_session_snapshots(session_id: str, collection_batch_id: str) -> List[dict]:
    """Return only the exact persisted collection batch for one session.

    There is deliberately no newest-per-symbol fallback across batches: freeze
    must consume the immutable batch whose counts were parity-verified.
    """
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM preopen_snapshots
                WHERE session_id = %s AND collection_batch_id = %s
                ORDER BY created_at ASC
            """, [session_id, collection_batch_id])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        result = []
        for row in rows:
            record = dict(zip(cols, row))
            for key, value in record.items():
                if isinstance(value, datetime):
                    record[key] = value.isoformat()
            result.append(record)
        return result

    return _with_db(from_db) or []


# ── Rankings + watchlists ─────────────────────────────────────────────────────

def save_rankings(session_id: str, trading_date: str, rankings: list, summary: dict) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_rankings (session_id, trading_date, frozen_at, rankings_json, summary)
                VALUES (%s, %s, NOW(), %s, %s)
            """, [session_id, trading_date, json.dumps(rankings), json.dumps(summary)])
        conn.commit()
    _with_db(to_db)


def save_watchlist(session_id: str, trading_date: str, list_type: str, items: list) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_watchlists (session_id, trading_date, list_type, items_json)
                VALUES (%s, %s, %s, %s)
            """, [session_id, trading_date, list_type, json.dumps(items)])
        conn.commit()
    _with_db(to_db)


def get_latest_watchlists(trading_date: Optional[str] = None) -> Dict[str, list]:
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT list_type, items_json FROM preopen_watchlists
                    WHERE trading_date = %s
                    ORDER BY created_at DESC
                """, [trading_date])
            else:
                cur.execute("""
                    SELECT list_type, items_json FROM preopen_watchlists
                    WHERE trading_date = (
                        SELECT MAX(trading_date) FROM preopen_watchlists
                    )
                    ORDER BY created_at DESC
                """)
            rows = cur.fetchall()
            result: Dict[str, list] = {}
            for list_type, items_json in rows:
                if list_type not in result:
                    result[list_type] = items_json if isinstance(items_json, list) else []
            return result
    return _with_db(from_db) or {}


def get_session_watchlists(session_id: str) -> Dict[str, list]:
    """Return the frozen watchlists created by one durable session."""
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT list_type, items_json FROM preopen_watchlists
                WHERE session_id = %s
                ORDER BY created_at DESC
            """, [session_id])
            rows = cur.fetchall()
        result: Dict[str, list] = {}
        for list_type, items_json in rows:
            if list_type not in result:
                result[list_type] = items_json if isinstance(items_json, list) else []
        return result
    return _with_db(from_db) or {}


# ── Provider health ───────────────────────────────────────────────────────────

def save_provider_health(session_id: Optional[str], trading_date: str,
                          provider_name: str, health: dict) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_provider_health
                    (session_id, trading_date, provider_name, status, latency_ms, message, raw_response)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, [session_id, trading_date, provider_name,
                  health.get("status", "UNKNOWN"),
                  health.get("latency_ms"),
                  health.get("message", ""),
                  json.dumps(health)])
        conn.commit()
    _with_db(to_db)


# ── Reconciliation ────────────────────────────────────────────────────────────

def save_reconciliation(records: List[dict]) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO preopen_reconciliation
                        (session_id, symbol, trading_date, indicative_equilibrium_price,
                         final_pre_open_price, actual_open_price, price_at_0920, price_at_0930,
                         indicative_to_open_error, opening_continuation, opening_reversal,
                         watchlist_confirmed, was_in_watchlist)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, [
                    r.get("session_id"), r.get("symbol"), r.get("trading_date"),
                    r.get("indicative_equilibrium_price"), r.get("final_pre_open_price"),
                    r.get("actual_open_price"), r.get("price_at_0920"), r.get("price_at_0930"),
                    r.get("indicative_to_open_error"), r.get("opening_continuation"),
                    r.get("opening_reversal"), r.get("watchlist_confirmed"),
                    r.get("was_in_watchlist", False),
                ])
        conn.commit()
    _with_db(to_db)


def get_reconciliation(trading_date: Optional[str] = None) -> List[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            if trading_date:
                cur.execute("""
                    SELECT * FROM preopen_reconciliation WHERE trading_date = %s
                    ORDER BY symbol
                """, [trading_date])
            else:
                cur.execute("""
                    SELECT * FROM preopen_reconciliation
                    WHERE trading_date = (SELECT MAX(trading_date) FROM preopen_reconciliation)
                    ORDER BY symbol
                """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    return _with_db(from_db) or []


def get_reconciliation_dates(n: int = 5) -> List[str]:
    """Return the last N distinct trading dates that have reconciliation records."""
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT trading_date
                FROM preopen_reconciliation
                ORDER BY trading_date DESC
                LIMIT %s
            """, [n])
            return [row[0] for row in cur.fetchall()]
    return _with_db(from_db) or []


def update_reconciliation_0930(session_id: str, prices_0930: Dict[str, float]) -> None:
    """Patch price_at_0930 only for reconciliation rows in one session."""
    def to_db(conn):
        with conn.cursor() as cur:
            for symbol, price in prices_0930.items():
                cur.execute("""
                    UPDATE preopen_reconciliation
                    SET price_at_0930 = %s
                    WHERE session_id = %s AND symbol = %s
                      AND price_at_0930 IS NULL
                """, [price, session_id, symbol])
        conn.commit()
    _with_db(to_db)
