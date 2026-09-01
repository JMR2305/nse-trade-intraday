"""Additive, durable versioning foundation for scanner universes.

This module intentionally does not participate in runtime universe selection.
The existing ``custom_universe_master`` remains the authority until a later
task explicitly migrates consumers.  This store provides an immutable
revision-shaped record of that authority, safe read primitives, and a
transactional baseline import.

All writes are narrowly scoped:
* revisions and members are inserted, never edited in place;
* audit events are append-only;
* a baseline import refuses malformed, incomplete, duplicate, or conflicting
  source data before it can commit anything.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

CUSTOM_UNIVERSE_KEY = "CUSTOM_LOW_PRICE_SECTOR"
NIFTY_UNIVERSE_KEY = "NIFTY_50"
DISPLAY_NAME = "Custom Low-Price IT / Infra / Bank"
REVISION_STATUSES = (
    "DRAFT",
    "PENDING_ACTIVATION",
    "ACTIVE",
    "SUPERSEDED",
    "CANCELLED",
)
AUDIT_ACTIONS = (
    "DRAFT_CREATED",
    "SYMBOL_ADDED",
    "SYMBOL_REMOVED",
    "SYMBOL_RESTORED",
    "VALIDATION_RUN",
    "ACTIVATION_REQUESTED",
    "ACTIVATION_APPROVED",
    "ACTIVATED",
    "CANCELLED",
    "BASELINE_IMPORTED",
)
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&-]{0,31}$")


def _db_available() -> bool:
    try:
        import psycopg2  # noqa: F401
        return bool(os.environ.get("DATABASE_URL"))
    except Exception:
        return False


@contextmanager
def _connect() -> Generator:
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn: Any) -> None:
    """Create only new tables/indexes; never alter existing trading tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_universe_sources (
                id BIGSERIAL PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_reference TEXT NOT NULL,
                source_table TEXT,
                source_snapshot_at TIMESTAMPTZ,
                source_set_hash TEXT NOT NULL,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                imported_by TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                UNIQUE (source_type, source_reference, source_set_hash)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_universes (
                id BIGSERIAL PRIMARY KEY,
                universe_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'DRAFT', 'PENDING_ACTIVATION', 'ACTIVE',
                        'SUPERSEDED', 'CANCELLED'
                    )
                ),
                effective_from TIMESTAMPTZ,
                effective_until TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by TEXT NOT NULL,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                notes TEXT,
                exact_set_hash TEXT NOT NULL,
                enabled_symbol_count INTEGER NOT NULL DEFAULT 0
                    CHECK (enabled_symbol_count >= 0),
                source_id BIGINT REFERENCES trading_universe_sources(id),
                UNIQUE (universe_key, version)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trading_universes_lookup
            ON trading_universes (universe_key, status, effective_from)
            """
        )
        # One editable draft is the authoritative workflow invariant. Edits
        # create an immutable successor only after cancelling their predecessor,
        # so concurrent UI/API callers cannot leave ambiguous open drafts.
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_trading_universes_one_draft
            ON trading_universes (universe_key)
            WHERE status = 'DRAFT'
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_universe_members (
                id BIGSERIAL PRIMARY KEY,
                universe_id BIGINT NOT NULL REFERENCES trading_universes(id),
                symbol TEXT NOT NULL,
                exchange TEXT,
                sector TEXT,
                instrument_token BIGINT,
                mapping_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                added_by TEXT NOT NULL,
                removed_at TIMESTAMPTZ,
                removed_by TEXT,
                notes TEXT,
                UNIQUE (universe_id, symbol),
                CHECK (NOT enabled OR removed_at IS NULL),
                CHECK (enabled OR removed_at IS NOT NULL OR removed_by IS NOT NULL)
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_trading_universe_enabled_token
            ON trading_universe_members (universe_id, instrument_token)
            WHERE enabled AND instrument_token IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trading_universe_members_symbol
            ON trading_universe_members (symbol, enabled)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_universe_audit_events (
                id BIGSERIAL PRIMARY KEY,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                actor TEXT NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN (
                        'DRAFT_CREATED', 'SYMBOL_ADDED', 'SYMBOL_REMOVED',
                        'SYMBOL_RESTORED', 'VALIDATION_RUN',
                        'ACTIVATION_REQUESTED', 'ACTIVATION_APPROVED',
                        'ACTIVATED', 'CANCELLED', 'BASELINE_IMPORTED'
                    )
                ),
                universe_key TEXT NOT NULL,
                old_version INTEGER,
                new_version INTEGER,
                symbol TEXT,
                change_type TEXT,
                old_value JSONB,
                new_value JSONB,
                notes TEXT,
                correlation_id TEXT,
                approval_state TEXT,
                UNIQUE (action, correlation_id)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trading_universe_audit_lookup
            ON trading_universe_audit_events (universe_key, occurred_at DESC)
            """
        )
        # Session pins are runtime provenance records over immutable revisions;
        # keep their bootstrap beside the revision authority rather than an
        # unrelated Phase 20 feature schema.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_universe_session_pins (
                natural_session TEXT PRIMARY KEY,
                universe_key TEXT NOT NULL,
                universe_id BIGINT NOT NULL,
                universe_version INTEGER NOT NULL,
                universe_symbols JSONB NOT NULL,
                universe_symbol_count INTEGER NOT NULL,
                universe_set_hash TEXT NOT NULL,
                effective_from TIMESTAMPTZ,
                pinned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # Preserve the original append-only guard setup for callers that only
        # bootstrap the version store (without resolving a runtime universe).
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION task946_reject_history_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Task 946 history is append-only: % on % is forbidden',
                    TG_OP, TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_audit_immutable'
                ) THEN
                    CREATE TRIGGER trg_task946_audit_immutable
                    BEFORE UPDATE OR DELETE ON trading_universe_audit_events
                    FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_member_history_guard'
                ) THEN
                    -- The draft-only INSERT/UPDATE/DELETE member guard is
                    -- installed below under trg_task946_member_guard.
                    CREATE TRIGGER trg_task946_member_history_guard
                    BEFORE UPDATE OR DELETE ON trading_universe_members
                    FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
                END IF;
            END
            $$
            """
        )
    conn.commit()


def ensure_builtin_nifty_baseline(conn: Any) -> None:
    """Create the immutable NIFTY baseline once for the supported default.

    This is a schema-era baseline migration, not a runtime list fallback:
    after it is written every reader resolves the exact durable revision and
    its persisted member rows. Custom mode continues to require its approved
    imported baseline and therefore remains fail-closed when unavailable.
    """
    from config import NIFTY_50, SECTOR_MAP

    symbols = normalize_symbols(NIFTY_50)
    symbol_hash = exact_set_hash(symbols)
    sector_by_symbol = {
        symbol: sector
        for sector, members in SECTOR_MAP.items()
        for symbol in members
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, exact_set_hash, enabled_symbol_count
            FROM trading_universes
            WHERE universe_key = %s AND status = 'ACTIVE'
            ORDER BY version DESC
            """,
            (NIFTY_UNIVERSE_KEY,),
        )
        active = cur.fetchall()
        if active:
            # Existing authority, including a human-approved later version, is
            # never changed by the baseline bootstrap.
            return
        cur.execute(
            "SELECT version FROM trading_universes WHERE universe_key = %s",
            (NIFTY_UNIVERSE_KEY,),
        )
        if cur.fetchone():
            raise RuntimeError(
                "NIFTY_50 has revisions but no active immutable authority"
            )
        cur.execute(
            """
            INSERT INTO trading_universe_sources (
                source_type, source_reference, source_set_hash, imported_by,
                metadata
            ) VALUES (
                'BUILTIN_BASELINE', 'config:NIFTY_50', %s,
                'TASK_948_NIFTY_BASELINE',
                %s::jsonb
            )
            ON CONFLICT (source_type, source_reference, source_set_hash)
            DO UPDATE SET source_set_hash = EXCLUDED.source_set_hash
            RETURNING id
            """,
            (symbol_hash, json.dumps({"symbol_count": len(symbols)})),
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO trading_universes (
                universe_key, display_name, version, status, effective_from,
                created_by, approved_at, approved_by, notes, exact_set_hash,
                enabled_symbol_count, source_id
            ) VALUES (
                %s, 'NIFTY 50 baseline', 1, 'DRAFT',
                NULL, 'TASK_948_NIFTY_BASELINE',
                NULL, NULL,
                'Immutable built-in NIFTY baseline imported for runtime authority.',
                %s, %s, %s
            )
            RETURNING id
            """,
            (NIFTY_UNIVERSE_KEY, symbol_hash, len(symbols), source_id),
        )
        universe_id = cur.fetchone()[0]
        cur.executemany(
            """
            INSERT INTO trading_universe_members (
                universe_id, symbol, exchange, sector, mapping_status, enabled,
                added_by, notes
            ) VALUES (%s, %s, 'NSE', %s, 'UNVERIFIED', TRUE,
                      'TASK_948_NIFTY_BASELINE', 'Built-in NIFTY baseline member')
            """,
            [
                (universe_id, symbol, sector_by_symbol.get(symbol, "OTHER"))
                for symbol in symbols
            ],
        )
        # Existing Task 946 DB protection permits members only on DRAFT
        # revisions. Verify the persisted exact set before atomically
        # promoting this baseline to the active authority.
        cur.execute(
            """
            SELECT symbol FROM trading_universe_members
            WHERE universe_id = %s AND enabled = TRUE
            ORDER BY symbol
            """,
            (universe_id,),
        )
        persisted_symbols = [row[0] for row in cur.fetchall()]
        if (
            persisted_symbols != symbols
            or exact_set_hash(persisted_symbols) != symbol_hash
        ):
            raise RuntimeError(
                "NIFTY_50 baseline exact-set verification failed before activation"
            )
        cur.execute(
            """
            UPDATE trading_universes
            SET status = 'ACTIVE',
                effective_from = '1970-01-01T00:00:00Z',
                approved_at = NOW(),
                approved_by = 'TASK_948_NIFTY_BASELINE'
            WHERE id = %s AND status = 'DRAFT'
            """,
            (universe_id,),
        )
        if cur.rowcount != 1:
            raise RuntimeError("NIFTY_50 baseline activation transition failed")
        cur.execute(
            """
            INSERT INTO trading_universe_audit_events (
                actor, action, universe_key, new_version, notes, correlation_id,
                approval_state
            ) VALUES (
                'TASK_948_NIFTY_BASELINE', 'BASELINE_IMPORTED', %s, 1,
                'Built-in NIFTY baseline established for durable runtime authority.',
                %s, 'APPROVED'
            )
            """,
            (NIFTY_UNIVERSE_KEY, f"task-948-nifty-{symbol_hash[:16]}"),
        )
        # Database-level immutability is required because omitting a Python
        # update helper does not protect history from another SQL client.
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION task946_reject_history_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Task 946 history is append-only: % on % is forbidden',
                    TG_OP, TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION task946_guard_revision_snapshot()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Universe revisions cannot be deleted';
                END IF;
                IF OLD.universe_key IS DISTINCT FROM NEW.universe_key
                   OR OLD.display_name IS DISTINCT FROM NEW.display_name
                   OR OLD.version IS DISTINCT FROM NEW.version
                   OR OLD.created_at IS DISTINCT FROM NEW.created_at
                   OR OLD.created_by IS DISTINCT FROM NEW.created_by
                   OR OLD.notes IS DISTINCT FROM NEW.notes
                   OR OLD.exact_set_hash IS DISTINCT FROM NEW.exact_set_hash
                   OR OLD.enabled_symbol_count IS DISTINCT FROM NEW.enabled_symbol_count
                   OR OLD.source_id IS DISTINCT FROM NEW.source_id THEN
                    RAISE EXCEPTION 'Universe revision snapshot fields are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION task946_guard_member_write()
            RETURNS trigger AS $$
            DECLARE revision_status TEXT;
            BEGIN
                IF TG_OP IN ('UPDATE', 'DELETE') THEN
                    RAISE EXCEPTION 'Universe members are immutable once recorded';
                END IF;
                SELECT status INTO revision_status
                FROM trading_universes WHERE id = NEW.universe_id;
                IF revision_status IS DISTINCT FROM 'DRAFT' THEN
                    RAISE EXCEPTION 'Members may only be added to DRAFT revisions';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_source_immutable'
                ) THEN
                    CREATE TRIGGER trg_task946_source_immutable
                    BEFORE UPDATE OR DELETE ON trading_universe_sources
                    FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_audit_immutable'
                ) THEN
                    CREATE TRIGGER trg_task946_audit_immutable
                    BEFORE UPDATE OR DELETE ON trading_universe_audit_events
                    FOR EACH ROW EXECUTE FUNCTION task946_reject_history_mutation();
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_member_guard'
                ) THEN
                    CREATE TRIGGER trg_task946_member_guard
                    BEFORE INSERT OR UPDATE OR DELETE ON trading_universe_members
                    FOR EACH ROW EXECUTE FUNCTION task946_guard_member_write();
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task946_revision_guard'
                ) THEN
                    CREATE TRIGGER trg_task946_revision_guard
                    BEFORE UPDATE OR DELETE ON trading_universes
                    FOR EACH ROW EXECUTE FUNCTION task946_guard_revision_snapshot();
                END IF;
            END
            $$
            """
        )
    conn.commit()


def ensure_schema() -> bool:
    """Idempotently create the additive versioning schema."""
    if not _db_available():
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
        return True
    except Exception as exc:
        logger.warning("universe_version_store.ensure_schema: %s", exc)
        return False


def normalize_symbol(value: Any) -> str:
    """Normalize one NSE symbol or raise a useful validation error."""
    symbol = " ".join(str(value or "").upper().split())
    if not symbol:
        raise ValueError("symbol is required")
    if " " in symbol or not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"invalid normalized symbol: {value!r}")
    return symbol


def normalize_symbols(symbols: Iterable[Any]) -> List[str]:
    normalized = [normalize_symbol(value) for value in symbols]
    if len(set(normalized)) != len(normalized):
        duplicates = sorted(
            symbol for symbol in set(normalized) if normalized.count(symbol) > 1
        )
        raise ValueError(f"duplicate normalized symbols: {', '.join(duplicates)}")
    return sorted(normalized)


def exact_set_hash(symbols: Iterable[Any]) -> str:
    """Hash the canonical, sorted enabled symbol set."""
    canonical = "\n".join(normalize_symbols(symbols))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_dict(columns: Sequence[str], row: Sequence[Any]) -> Dict[str, Any]:
    return {key: _json_value(value) for key, value in zip(columns, row)}


def _source_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and project a current custom-master row for baseline import."""
    symbol = normalize_symbol(row.get("symbol"))
    if row.get("is_active") is not True:
        raise ValueError(f"baseline row {symbol} is not active")
    # A company name is descriptive source metadata, not a membership identity
    # or provider mapping key. Older approved master rows legitimately lack it;
    # rejecting them would force a membership rewrite just to preserve the
    # exact approved set. The resolver-critical fields remain mandatory.
    required = ("sector", "yahoo_symbol", "kite_symbol")
    missing = [key for key in required if not str(row.get(key) or "").strip()]
    if missing:
        raise ValueError(f"baseline row {symbol} missing: {', '.join(missing)}")
    instrument_token = row.get("instrument_token")
    if instrument_token is not None:
        try:
            if int(instrument_token) <= 0:
                raise ValueError
            instrument_token = int(instrument_token)
        except (TypeError, ValueError):
            raise ValueError(f"baseline row {symbol} has invalid instrument_token")
    exchange = str(
        row.get("instrument_exchange") or "NSE"
    ).strip().upper()
    mapping_status = "MAPPED" if instrument_token and exchange == "NSE" else "UNVERIFIED"
    return {
        "symbol": symbol,
        "exchange": exchange,
        "sector": str(row.get("sector")).strip().upper(),
        "instrument_token": instrument_token,
        "mapping_status": mapping_status,
        "enabled": True,
        "added_by": "TASK_946_BASELINE_MIGRATION",
        "notes": "Imported from custom_universe_master; mapping preserved as observed.",
    }


def _validate_baseline_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        raise ValueError("current custom universe has no active rows")
    projected = [_source_row(row) for row in rows]
    symbols = [row["symbol"] for row in projected]
    normalize_symbols(symbols)
    tokens = [
        row["instrument_token"] for row in projected
        if row["instrument_token"] is not None
    ]
    if len(tokens) != len(set(tokens)):
        raise ValueError("baseline contains duplicate enabled instrument_token values")
    return sorted(projected, key=lambda row: row["symbol"])


def _fetch_current_active_rows(cur: Any) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT symbol, company_name, sector, yahoo_symbol, kite_symbol,
               instrument_token, is_active, instrument_exchange,
               instrument_tradingsymbol, instrument_cache_date,
               instrument_mapping_at, last_verified_at
        FROM custom_universe_master
        WHERE allowed_universe = %s AND is_active = TRUE
        ORDER BY symbol
        """,
        (CUSTOM_UNIVERSE_KEY,),
    )
    columns = (
        "symbol", "company_name", "sector", "yahoo_symbol", "kite_symbol",
        "instrument_token", "is_active", "instrument_exchange",
        "instrument_tradingsymbol", "instrument_cache_date",
        "instrument_mapping_at", "last_verified_at",
    )
    return [_row_dict(columns, row) for row in cur.fetchall()]


def seed_baseline(
    *,
    created_by: str = "TASK_946_BASELINE_MIGRATION",
    source_reference: str = "custom_universe_master:CUSTOM_LOW_PRICE_SECTOR",
) -> Dict[str, Any]:
    """Import the current active custom master exactly once, atomically."""
    if not _db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                # Serialize all import attempts. A second caller waits, then
                # sees and verifies the first complete revision as idempotent.
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("task946:baseline:CUSTOM_LOW_PRICE_SECTOR",),
                )
                # Keep the source membership stable from read through exact-set
                # verification. This blocks concurrent current-master refreshes
                # instead of importing a moving source snapshot.
                cur.execute("LOCK TABLE custom_universe_master IN SHARE MODE")
                rows = _fetch_current_active_rows(cur)
                projected = _validate_baseline_rows(rows)
                symbols = [row["symbol"] for row in projected]
                source_hash = exact_set_hash(symbols)
                cur.execute(
                    """
                    SELECT id, version, status, exact_set_hash
                    FROM trading_universes
                    WHERE universe_key = %s
                    ORDER BY version
                    """,
                    (CUSTOM_UNIVERSE_KEY,),
                )
                existing = cur.fetchall()
                if existing:
                    matching = [
                        row for row in existing if row[3] == source_hash
                    ]
                    if len(matching) == 1:
                        cur.execute(
                            """
                            SELECT symbol FROM trading_universe_members
                            WHERE universe_id = %s AND enabled = TRUE
                            ORDER BY symbol
                            """,
                            (matching[0][0],),
                        )
                        existing_symbols = [row[0] for row in cur.fetchall()]
                        if existing_symbols != symbols:
                            raise ValueError(
                                "existing revision hash/member mismatch; "
                                "refusing duplicate or partial baseline import"
                            )
                        return {
                            "success": True,
                            "already_seeded": True,
                            "revision_id": matching[0][0],
                            "version": matching[0][1],
                            "status": matching[0][2],
                            "symbol_count": len(symbols),
                            "exact_set_hash": source_hash,
                        }
                    raise ValueError(
                        "universe already has a conflicting revision; "
                        "refusing duplicate or partial baseline import"
                    )

                cur.execute(
                    """
                    INSERT INTO trading_universe_sources (
                        source_type, source_reference, source_table,
                        source_snapshot_at, source_set_hash, imported_by,
                        metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        "CURRENT_MASTER",
                        source_reference,
                        "custom_universe_master",
                        datetime.now(timezone.utc),
                        source_hash,
                        created_by,
                        json.dumps({
                            "allowed_universe": CUSTOM_UNIVERSE_KEY,
                            "active_row_count": len(symbols),
                            "mapping_statuses": sorted({
                                row["mapping_status"] for row in projected
                            }),
                        }),
                    ),
                )
                source_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO trading_universes (
                        universe_key, display_name, version, status,
                        effective_from, created_by, notes, exact_set_hash,
                        enabled_symbol_count, source_id
                    ) VALUES (%s, %s, 1, 'DRAFT', NULL, %s, %s, %s, %s, %s)
                    RETURNING id, version, status
                    """,
                    (
                        CUSTOM_UNIVERSE_KEY,
                        DISPLAY_NAME,
                        created_by,
                        "Immutable baseline imported without changing runtime authority.",
                        source_hash,
                        len(symbols),
                        source_id,
                    ),
                )
                revision_id, version, status = cur.fetchone()
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    INSERT INTO trading_universe_members (
                        universe_id, symbol, exchange, sector,
                        instrument_token, mapping_status, enabled,
                        added_by, notes
                    ) VALUES %s
                    """,
                    [
                        (
                            revision_id, row["symbol"], row["exchange"],
                            row["sector"], row["instrument_token"],
                            row["mapping_status"], True, created_by,
                            row["notes"],
                        )
                        for row in projected
                    ],
                )
                cur.execute(
                    """
                    SELECT symbol FROM trading_universe_members
                    WHERE universe_id = %s AND enabled = TRUE
                    ORDER BY symbol
                    """,
                    (revision_id,),
                )
                persisted_symbols = [row[0] for row in cur.fetchall()]
                if persisted_symbols != symbols:
                    raise ValueError(
                        "baseline exact-set verification failed; transaction rolled back"
                    )
                cur.execute(
                    """
                    UPDATE trading_universes
                    SET status = 'ACTIVE', effective_from = %s
                    WHERE id = %s AND status = 'DRAFT'
                    """,
                    (datetime.now(timezone.utc), revision_id),
                )
                if cur.rowcount != 1:
                    raise ValueError(
                        "baseline activation transition failed; transaction rolled back"
                    )
                status = "ACTIVE"
                cur.execute(
                    """
                    INSERT INTO trading_universe_audit_events (
                        actor, action, universe_key, new_version,
                        change_type, new_value, notes, correlation_id,
                        approval_state
                    ) VALUES (%s, 'BASELINE_IMPORTED', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        created_by, CUSTOM_UNIVERSE_KEY, version,
                        "BASELINE_IMPORT",
                        json.dumps({
                            "symbol_count": len(symbols),
                            "exact_set_hash": source_hash,
                        }),
                        "Imported from current custom master after exact-set verification.",
                        f"task-946-baseline-{source_hash[:16]}",
                        "RECORDED",
                    ),
                )
                return {
                    "success": True,
                    "already_seeded": False,
                    "revision_id": revision_id,
                    "version": version,
                    "status": status,
                    "symbol_count": len(symbols),
                    "exact_set_hash": source_hash,
                    "mapping_coverage": sum(
                        1 for row in projected if row["mapping_status"] == "MAPPED"
                    ),
                }
    except Exception as exc:
        logger.warning("universe_version_store.seed_baseline: %s", exc)
        return {"success": False, "error": str(exc)[:300]}


_REVISION_COLUMNS = (
    "id", "universe_key", "display_name", "version", "status",
    "effective_from", "effective_until", "created_at", "created_by",
    "approved_at", "approved_by", "notes", "exact_set_hash",
    "enabled_symbol_count", "source_id",
)


def _revision_dict(row: Sequence[Any]) -> Dict[str, Any]:
    return _row_dict(_REVISION_COLUMNS, row)


def get_revision(
    *,
    universe_key: str = CUSTOM_UNIVERSE_KEY,
    version: Optional[int] = None,
    revision_id: Optional[int] = None,
    effective_at: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Read a revision by id/version or resolve the revision effective at a time."""
    # Resolver calls must remain usable by a read-only DB role. Schema
    # bootstrap is explicit (ensure_schema / universe_version_schema) and
    # never occurs on this path.
    if not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                if revision_id is not None:
                    cur.execute(
                        f"SELECT {', '.join(_REVISION_COLUMNS)} "
                        "FROM trading_universes WHERE id = %s",
                        (revision_id,),
                    )
                elif version is not None:
                    cur.execute(
                        f"SELECT {', '.join(_REVISION_COLUMNS)} "
                        "FROM trading_universes WHERE universe_key = %s AND version = %s",
                        (universe_key, int(version)),
                    )
                elif effective_at is not None:
                    cur.execute(
                        f"""
                        SELECT {', '.join(_REVISION_COLUMNS)}
                        FROM trading_universes
                        WHERE universe_key = %s
                          AND status = 'ACTIVE'
                          AND effective_from IS NOT NULL
                          AND effective_from <= %s
                          AND (effective_until IS NULL OR effective_until > %s)
                        ORDER BY effective_from DESC, version DESC
                        LIMIT 2
                        """,
                        (universe_key, effective_at, effective_at),
                    )
                    rows = cur.fetchall()
                    # Two effective rows at one server time are ambiguous
                    # authority.  Returning either would silently rewrite
                    # history, so all runtime consumers must fail closed.
                    if len(rows) != 1:
                        return None
                    return _revision_dict(rows[0])
                else:
                    cur.execute(
                        f"""
                        SELECT {', '.join(_REVISION_COLUMNS)}
                        FROM trading_universes
                        WHERE universe_key = %s AND status = 'ACTIVE'
                        ORDER BY version DESC LIMIT 1
                        """,
                        (universe_key,),
                    )
                row = cur.fetchone()
                return _revision_dict(row) if row else None
    except Exception as exc:
        logger.warning("universe_version_store.get_revision: %s", exc)
        return None


_MEMBER_COLUMNS = (
    "id", "universe_id", "symbol", "exchange", "sector",
    "instrument_token", "mapping_status", "enabled", "added_at", "added_by",
    "removed_at", "removed_by", "notes",
)


def get_members(
    *,
    universe_key: str = CUSTOM_UNIVERSE_KEY,
    version: Optional[int] = None,
    revision_id: Optional[int] = None,
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    revision = get_revision(
        universe_key=universe_key, version=version, revision_id=revision_id
    )
    if not revision or not _db_available():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                sql = (
                    f"SELECT {', '.join(_MEMBER_COLUMNS)} "
                    "FROM trading_universe_members WHERE universe_id = %s"
                )
                params: List[Any] = [revision["id"]]
                if enabled_only:
                    sql += " AND enabled = TRUE"
                sql += " ORDER BY symbol"
                cur.execute(sql, params)
                return [_row_dict(_MEMBER_COLUMNS, row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("universe_version_store.get_members: %s", exc)
        return []


def resolve_enabled_symbols(
    *,
    universe_key: str = CUSTOM_UNIVERSE_KEY,
    version: Optional[int] = None,
    revision_id: Optional[int] = None,
    effective_at: Optional[Any] = None,
) -> Dict[str, Any]:
    revision = get_revision(
        universe_key=universe_key,
        version=version,
        revision_id=revision_id,
        effective_at=effective_at,
    )
    if not revision:
        return {
            "success": False,
            "error": "revision_not_found",
            "universe_key": universe_key,
            "symbols": [],
        }
    members = get_members(revision_id=revision["id"], enabled_only=True)
    symbols = [member["symbol"] for member in members]
    try:
        normalized_symbols = normalize_symbols(symbols)
    except ValueError as exc:
        return {
            "success": False,
            "error": f"invalid_persisted_membership: {exc}",
            "universe_key": revision["universe_key"],
            "universe_id": revision["id"],
            "version": revision["version"],
            "symbols": [],
        }
    persisted_hash = exact_set_hash(normalized_symbols)
    if (
        symbols != normalized_symbols
        or len(normalized_symbols) != revision["enabled_symbol_count"]
        or persisted_hash != revision["exact_set_hash"]
    ):
        return {
            "success": False,
            "error": "revision_integrity_mismatch",
            "universe_key": revision["universe_key"],
            "universe_id": revision["id"],
            "version": revision["version"],
            "expected_symbol_count": revision["enabled_symbol_count"],
            "actual_symbol_count": len(normalized_symbols),
            "expected_exact_set_hash": revision["exact_set_hash"],
            "actual_exact_set_hash": persisted_hash,
            "symbols": [],
        }
    return {
        "success": True,
        "universe_key": revision["universe_key"],
        "universe_id": revision["id"],
        "version": revision["version"],
        "status": revision["status"],
        "effective_from": revision["effective_from"],
        "symbol_count": len(symbols),
        "symbols": normalized_symbols,
        "mapping_coverage": {
            "mapped": sum(
                1 for member in members
                if member.get("mapping_status") == "MAPPED"
                and member.get("instrument_token")
            ),
            "total": len(members),
        },
        "exact_set_hash": persisted_hash,
    }


def compare_revisions(
    left_version: int,
    right_version: int,
    *,
    universe_key: str = CUSTOM_UNIVERSE_KEY,
) -> Dict[str, Any]:
    left = resolve_enabled_symbols(universe_key=universe_key, version=left_version)
    right = resolve_enabled_symbols(universe_key=universe_key, version=right_version)
    if not left.get("success") or not right.get("success"):
        return {
            "success": False,
            "error": "revision_not_found",
            "left": left,
            "right": right,
        }
    left_set, right_set = set(left["symbols"]), set(right["symbols"])
    return {
        "success": True,
        "universe_key": universe_key,
        "left_version": left_version,
        "right_version": right_version,
        "added": sorted(right_set - left_set),
        "removed": sorted(left_set - right_set),
        "unchanged": sorted(left_set & right_set),
    }


def append_audit_event(
    *,
    actor: str,
    action: str,
    universe_key: str = CUSTOM_UNIVERSE_KEY,
    old_version: Optional[int] = None,
    new_version: Optional[int] = None,
    symbol: Optional[str] = None,
    change_type: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    notes: Optional[str] = None,
    correlation_id: Optional[str] = None,
    approval_state: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one audit event; there is deliberately no update/delete API."""
    if action not in AUDIT_ACTIONS:
        return {"success": False, "error": f"unsupported audit action: {action}"}
    if symbol is not None:
        try:
            symbol = normalize_symbol(symbol)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
    if not _db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trading_universe_audit_events (
                        actor, action, universe_key, old_version, new_version,
                        symbol, change_type, old_value, new_value, notes,
                        correlation_id, approval_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, occurred_at
                    """,
                    (
                        actor, action, universe_key, old_version, new_version,
                        symbol, change_type,
                        json.dumps(old_value) if old_value is not None else None,
                        json.dumps(new_value) if new_value is not None else None,
                        notes, correlation_id, approval_state,
                    ),
                )
                event_id, occurred_at = cur.fetchone()
                return {
                    "success": True,
                    "event_id": event_id,
                    "occurred_at": _iso(occurred_at),
                }
    except Exception as exc:
        logger.warning("universe_version_store.append_audit_event: %s", exc)
        return {"success": False, "error": str(exc)[:300]}