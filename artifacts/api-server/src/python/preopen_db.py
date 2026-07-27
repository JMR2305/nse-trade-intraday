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
                frozen_at      TIMESTAMPTZ,
                reconciled_at  TIMESTAMPTZ,
                error          TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                updated_at     TIMESTAMPTZ DEFAULT NOW()
            )
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session
            ON preopen_snapshots (session_id)
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

def upsert_session(session: dict) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO preopen_sessions
                    (session_id, trading_date, status, symbol_count, valid_count,
                     stale_count, provider_status, frozen_at, reconciled_at, error, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    status=EXCLUDED.status,
                    symbol_count=EXCLUDED.symbol_count,
                    valid_count=EXCLUDED.valid_count,
                    stale_count=EXCLUDED.stale_count,
                    provider_status=EXCLUDED.provider_status,
                    frozen_at=EXCLUDED.frozen_at,
                    reconciled_at=EXCLUDED.reconciled_at,
                    error=EXCLUDED.error,
                    updated_at=NOW()
            """, [
                session.get("session_id"), session.get("trading_date"),
                session.get("status", "INITIALISING"),
                session.get("symbol_count", 0), session.get("valid_count", 0),
                session.get("stale_count", 0),
                session.get("provider_status", "UNAVAILABLE"),
                session.get("frozen_at"), session.get("reconciled_at"),
                session.get("error"),
            ])
        conn.commit()
    _with_db(to_db)


def get_latest_session() -> Optional[dict]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session_id, trading_date, status, symbol_count, valid_count,
                       stale_count, provider_status, frozen_at, reconciled_at, error,
                       created_at, updated_at
                FROM preopen_sessions ORDER BY created_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return None
            cols = ["session_id","trading_date","status","symbol_count","valid_count",
                    "stale_count","provider_status","frozen_at","reconciled_at","error",
                    "created_at","updated_at"]
            return {k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in zip(cols, row)}
    return _with_db(from_db)


# ── Snapshot storage ──────────────────────────────────────────────────────────

def save_snapshots(session_id: str, snapshots: List[dict]) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            for s in snapshots:
                cur.execute("""
                    INSERT INTO preopen_snapshots
                        (snapshot_id, session_id, trading_date, timestamp_ist, symbol,
                         company_name, sector, previous_close, indicative_equilibrium_price,
                         indicative_open_price, final_open_price, price_change, gap_percent,
                         total_buy_quantity, total_sell_quantity, matched_quantity,
                         final_executed_quantity, total_traded_value, buy_sell_imbalance,
                         imbalance_percent, volume_rank, gap_rank, liquidity_score,
                         classification, opportunity_score, factor_scores,
                         data_source, data_freshness_seconds, source_status,
                         is_stale, validation_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (snapshot_id) DO NOTHING
                """, [
                    s.get("snapshot_id"), session_id, s.get("trading_date"),
                    s.get("timestamp_ist"), s.get("symbol"), s.get("company_name"),
                    s.get("sector"), s.get("previous_close"),
                    s.get("indicative_equilibrium_price"), s.get("indicative_open_price"),
                    s.get("final_open_price"), s.get("price_change"), s.get("gap_percent"),
                    s.get("total_buy_quantity"), s.get("total_sell_quantity"),
                    s.get("matched_quantity"), s.get("final_executed_quantity"),
                    s.get("total_traded_value"), s.get("buy_sell_imbalance"),
                    s.get("imbalance_percent"), s.get("volume_rank"), s.get("gap_rank"),
                    s.get("liquidity_score"), s.get("classification"),
                    s.get("opportunity_score"),
                    json.dumps(s.get("factor_scores") or {}),
                    s.get("data_source"), s.get("data_freshness_seconds"),
                    s.get("source_status"), s.get("is_stale"), s.get("validation_status"),
                ])
        conn.commit()
    _with_db(to_db)


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
