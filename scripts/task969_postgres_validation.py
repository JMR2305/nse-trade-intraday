#!/usr/bin/env python3
"""
Task #969 — Native PostgreSQL 16 validation for Task #967 / Task #964.

SAFETY:
- Disposable PostgreSQL only.
- Refuses obvious production-like database names/hosts.
- Does not read production credentials.
- Does not merge/deploy anything.
- Preserves seeded authority rows byte-for-byte/canonically across migration runs.

Expected environment:
    TASK967_TEST_DATABASE_URL
or:
    DATABASE_URL

Outputs:
    TASK_969_POSTGRES_BEFORE_AFTER_EVIDENCE.json
    TASK_969_POSTGRES_CATALOG_PARITY.md
    TASK_969_IDEMPOTENCY_REPORT.md
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "lib/db/migrations/0002_universe_authority_schema_parity.sql"

EVIDENCE_JSON = ROOT / "TASK_969_POSTGRES_BEFORE_AFTER_EVIDENCE.json"
CATALOG_MD = ROOT / "TASK_969_POSTGRES_CATALOG_PARITY.md"
IDEMPOTENCY_MD = ROOT / "TASK_969_IDEMPOTENCY_REPORT.md"

EXPECTED_TABLES = [
    "trading_universe_sources",
    "trading_universes",
    "trading_universe_members",
    "trading_universe_audit_events",
    "runtime_universe_session_pins",
    "trading_universe_member_details",
    "trading_universe_validations",
    "trading_universe_baseline_migrations",
]

PRESERVATION_TABLES = [
    "trading_universes",
    "trading_universe_members",
    "trading_universe_audit_events",
    "runtime_universe_session_pins",
    "trading_universe_member_details",
    "trading_universe_validations",
    "trading_universe_baseline_migrations",
]

EXPECTED_MEMBER_COUNT = 23

SYMBOLS = [
    "BANKBARODA",
    "BANKINDIA",
    "CANBK",
    "FEDERALBNK",
    "IDFCFIRSTB",
    "KTKBANK",
    "MAHABANK",
    "PNB",
    "UNIONBANK",
    "COALINDIA",
    "GAIL",
    "HUDCO",
    "IRCON",
    "IRFC",
    "MRPL",
    "NBCC",
    "NMDC",
    "NTPC",
    "PFC",
    "RECLTD",
    "RVNL",
    "SAIL",
    "WIPRO",
]

APPROVED_SET_HASH = (
    "22e5751f25686718f5572041834ce998"
    "b7c5ce9844d3b573bc3841749fe77016"
)


def fail(message: str) -> None:
    print(f"\nTASK969 FAILURE: {message}", file=sys.stderr)
    raise SystemExit(1)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_database_url() -> str:
    url = (
        os.environ.get("TASK967_TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()

    if not url:
        fail("TASK967_TEST_DATABASE_URL / DATABASE_URL is missing")

    lower = url.lower()

    # Task #969 must never be pointed at a production database.
    forbidden_markers = [
        "production",
        "prod-db",
        "neon.tech",
        "supabase.co",
        "replit",
    ]
    for marker in forbidden_markers:
        if marker in lower:
            fail(
                f"Refusing database URL containing production-risk marker: {marker}"
            )

    if "task967_disposable_task968" not in lower:
        fail(
            "Database name must contain task967_disposable_task968 "
            "for this validation"
        )

    return url


def execute_script(conn: psycopg.Connection, sql: str) -> None:
    """
    Execute Drizzle migration chunks safely.

    Drizzle uses:
        --> statement-breakpoint

    Each resulting chunk can itself contain a PostgreSQL DO block,
    trigger/function body, etc., so we execute by breakpoint rather than
    naive semicolon splitting.
    """
    chunks = re.split(r"^\s*-->\s*statement-breakpoint\s*$", sql, flags=re.M)

    with conn.cursor() as cur:
        for index, chunk in enumerate(chunks, start=1):
            statement = chunk.strip()
            if not statement:
                continue
            try:
                cur.execute(statement)
            except Exception as exc:
                conn.rollback()
                fail(
                    f"Migration chunk {index} failed:\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    f"Chunk:\n{statement[:3000]}"
                )
    conn.commit()


def reset_public_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO public")
    conn.commit()


def create_pre_task964_schema(conn: psycopg.Connection) -> None:
    """
    Representative pre-Task964 PostgreSQL authority schema.

    CRITICAL:
    trading_universe_audit_events deliberately uses the historical
    pre-Task964 ordering:

        UNIQUE (correlation_id, action)

    Task #969 must inspect PostgreSQL's actual ordered constraint columns
    and compare this with the Task #967 candidate declaration.
    """
    sql = r"""
    CREATE TABLE trading_universe_sources (
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
    );

    CREATE TABLE trading_universes (
        id BIGSERIAL PRIMARY KEY,
        universe_key TEXT NOT NULL,
        display_name TEXT NOT NULL,
        version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN (
                'DRAFT',
                'PENDING_ACTIVATION',
                'ACTIVE',
                'SUPERSEDED',
                'CANCELLED'
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
    );

    CREATE INDEX idx_trading_universes_lookup
        ON trading_universes (
            universe_key,
            status,
            effective_from
        );

    CREATE UNIQUE INDEX uq_trading_universes_one_draft
        ON trading_universes (universe_key)
        WHERE status = 'DRAFT';

    CREATE TABLE trading_universe_members (
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
        CHECK (
            enabled
            OR removed_at IS NOT NULL
            OR removed_by IS NOT NULL
        )
    );

    CREATE UNIQUE INDEX uq_trading_universe_enabled_token
        ON trading_universe_members (
            universe_id,
            instrument_token
        )
        WHERE enabled AND instrument_token IS NOT NULL;

    CREATE INDEX idx_trading_universe_members_symbol
        ON trading_universe_members (symbol, enabled);

    CREATE TABLE trading_universe_audit_events (
        id BIGSERIAL PRIMARY KEY,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        actor TEXT NOT NULL,
        action TEXT NOT NULL CHECK (
            action IN (
                'DRAFT_CREATED',
                'SYMBOL_ADDED',
                'SYMBOL_REMOVED',
                'SYMBOL_RESTORED',
                'VALIDATION_RUN',
                'ACTIVATION_REQUESTED',
                'ACTIVATION_APPROVED',
                'ACTIVATED',
                'CANCELLED',
                'BASELINE_IMPORTED'
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
        CONSTRAINT trading_universe_audit_events_correlation_id_action_key
            UNIQUE (correlation_id, action)
    );

    CREATE INDEX idx_trading_universe_audit_lookup
        ON trading_universe_audit_events (
            universe_key,
            occurred_at DESC
        );

    CREATE TABLE runtime_universe_session_pins (
        natural_session TEXT PRIMARY KEY,
        universe_key TEXT NOT NULL,
        universe_id BIGINT NOT NULL,
        universe_version INTEGER NOT NULL,
        universe_symbols JSONB NOT NULL,
        universe_symbol_count INTEGER NOT NULL,
        universe_set_hash TEXT NOT NULL,
        effective_from TIMESTAMPTZ,
        pinned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE trading_universe_member_details (
        universe_id BIGINT NOT NULL
            REFERENCES trading_universes(id),
        symbol TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by TEXT NOT NULL,
        PRIMARY KEY (universe_id, symbol)
    );

    CREATE TABLE trading_universe_validations (
        id BIGSERIAL PRIMARY KEY,
        universe_id BIGINT NOT NULL
            REFERENCES trading_universes(id),
        result TEXT NOT NULL CHECK (
            result IN (
                'VALIDATION_PASS',
                'VALIDATION_FAIL'
            )
        ),
        checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        checked_by TEXT NOT NULL,
        correlation_id TEXT,
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb
    );

    CREATE INDEX idx_trading_universe_validations_revision
        ON trading_universe_validations (
            universe_id,
            checked_at DESC
        );

    CREATE TABLE trading_universe_baseline_migrations (
        id BIGSERIAL PRIMARY KEY,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        actor TEXT NOT NULL,
        action TEXT NOT NULL
            CHECK (action = 'BASELINE_MIGRATION'),
        universe_key TEXT NOT NULL,
        destination_universe_id BIGINT NOT NULL
            REFERENCES trading_universes(id),
        destination_version INTEGER NOT NULL,
        source_authority TEXT NOT NULL,
        exact_symbol_count INTEGER NOT NULL
            CHECK (exact_symbol_count > 0),
        exact_set_hash TEXT NOT NULL,
        mapping_count INTEGER NOT NULL,
        previous_configured_universe_key TEXT NOT NULL,
        reason TEXT NOT NULL,
        correlation_id TEXT NOT NULL UNIQUE,
        evidence JSONB NOT NULL,
        UNIQUE (universe_key, destination_version)
    );
    """

    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def seed_authority_state(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading_universe_sources (
                id,
                source_type,
                source_reference,
                source_table,
                source_snapshot_at,
                source_set_hash,
                imported_by,
                metadata
            )
            VALUES (
                1,
                'BASELINE',
                'task969-seed',
                'custom_universe_master',
                '2026-08-28T04:00:00Z',
                %s,
                'task969',
                '{"purpose":"native-postgres-validation"}'::jsonb
            )
            """,
            (APPROVED_SET_HASH,),
        )

        cur.execute(
            """
            INSERT INTO trading_universes (
                id,
                universe_key,
                display_name,
                version,
                status,
                effective_from,
                effective_until,
                created_at,
                created_by,
                approved_at,
                approved_by,
                notes,
                exact_set_hash,
                enabled_symbol_count,
                source_id
            )
            VALUES (
                3,
                'CUSTOM_LOW_PRICE_SECTOR',
                'Custom Low Price Sector',
                1,
                'ACTIVE',
                '2026-08-31T03:30:00Z',
                NULL,
                '2026-08-28T04:00:00Z',
                'task969',
                '2026-08-28T04:01:00Z',
                'task969',
                'Task969 representative pre-Task964 authority state',
                %s,
                23,
                1
            )
            """,
            (APPROVED_SET_HASH,),
        )

        sectors = {
            "BANKBARODA": "BANK",
            "BANKINDIA": "BANK",
            "CANBK": "BANK",
            "FEDERALBNK": "BANK",
            "IDFCFIRSTB": "BANK",
            "KTKBANK": "BANK",
            "MAHABANK": "BANK",
            "PNB": "BANK",
            "UNIONBANK": "BANK",
            "WIPRO": "IT",
        }

        for index, symbol in enumerate(SYMBOLS, start=1):
            sector = sectors.get(symbol, "INFRA")
            token = 900000 + index

            cur.execute(
                """
                INSERT INTO trading_universe_members (
                    universe_id,
                    symbol,
                    exchange,
                    sector,
                    instrument_token,
                    mapping_status,
                    enabled,
                    added_at,
                    added_by,
                    notes
                )
                VALUES (
                    3,
                    %s,
                    'NSE',
                    %s,
                    %s,
                    'MAPPED',
                    TRUE,
                    '2026-08-28T04:02:00Z',
                    'task969',
                    'representative mapping'
                )
                """,
                (symbol, sector, token),
            )

            cur.execute(
                """
                INSERT INTO trading_universe_member_details (
                    universe_id,
                    symbol,
                    metadata,
                    created_at,
                    created_by
                )
                VALUES (
                    3,
                    %s,
                    %s::jsonb,
                    '2026-08-28T04:02:00Z',
                    'task969'
                )
                """,
                (
                    symbol,
                    json.dumps(
                        {
                            "exchange": "NSE",
                            "instrument_type": "EQ",
                            "segment": "NSE",
                            "instrument_token": token,
                            "mapping_status": "MAPPED",
                        }
                    ),
                ),
            )

        cur.execute(
            """
            INSERT INTO trading_universe_validations (
                id,
                universe_id,
                result,
                checked_at,
                checked_by,
                correlation_id,
                evidence
            )
            VALUES (
                1,
                3,
                'VALIDATION_PASS',
                '2026-08-28T04:03:00Z',
                'task969',
                'task969-validation-1',
                '{"mapping_count":23,"expected_count":23}'::jsonb
            )
            """
        )

        cur.execute(
            """
            INSERT INTO trading_universe_baseline_migrations (
                id,
                occurred_at,
                actor,
                action,
                universe_key,
                destination_universe_id,
                destination_version,
                source_authority,
                exact_symbol_count,
                exact_set_hash,
                mapping_count,
                previous_configured_universe_key,
                reason,
                correlation_id,
                evidence
            )
            VALUES (
                1,
                '2026-08-28T04:04:00Z',
                'task969',
                'BASELINE_MIGRATION',
                'CUSTOM_LOW_PRICE_SECTOR',
                3,
                1,
                'custom_universe_master',
                23,
                %s,
                23,
                'CUSTOM_LOW_PRICE_SECTOR',
                'MIGRATE_EXISTING_PRODUCTION_BASELINE_TO_VERSIONED_AUTHORITY',
                'task969-baseline-migration-1',
                '{"mapping_complete":true}'::jsonb
            )
            """,
            (APPROVED_SET_HASH,),
        )

        cur.execute(
            """
            INSERT INTO runtime_universe_session_pins (
                natural_session,
                universe_key,
                universe_id,
                universe_version,
                universe_symbols,
                universe_symbol_count,
                universe_set_hash,
                effective_from,
                pinned_at
            )
            VALUES (
                'preopen-2026-08-31-task969',
                'CUSTOM_LOW_PRICE_SECTOR',
                3,
                1,
                %s::jsonb,
                23,
                %s,
                '2026-08-31T03:30:00Z',
                '2026-08-31T03:30:01Z'
            )
            """,
            (json.dumps(SYMBOLS), APPROVED_SET_HASH),
        )

        cur.execute(
            """
            INSERT INTO trading_universe_audit_events (
                id,
                occurred_at,
                actor,
                action,
                universe_key,
                old_version,
                new_version,
                notes,
                correlation_id,
                approval_state
            )
            VALUES (
                1,
                '2026-08-28T04:05:00Z',
                'task969',
                'BASELINE_IMPORTED',
                'CUSTOM_LOW_PRICE_SECTOR',
                NULL,
                1,
                'Representative audit event',
                'task969-audit-1',
                'APPROVED'
            )
            """
        )

    conn.commit()


def ordered_rows(conn: psycopg.Connection, table: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
              AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
            """,
            (table,),
        )
        pk_cols = [row["attname"] for row in cur.fetchall()]

        if pk_cols:
            order_sql = ", ".join(
                '"' + col.replace('"', '""') + '"' for col in pk_cols
            )
        else:
            order_sql = "ctid"

        cur.execute(f'SELECT * FROM "{table}" ORDER BY {order_sql}')
        return list(cur.fetchall())


def table_snapshot(conn: psycopg.Connection, table: str) -> dict[str, Any]:
    rows = ordered_rows(conn, table)
    canonical = canonical_json(rows)

    return {
        "row_count": len(rows),
        "sha256": sha256_text(canonical),
        "rows": rows,
    }


def preservation_snapshot(conn: psycopg.Connection) -> dict[str, Any]:
    return {
        table: table_snapshot(conn, table)
        for table in PRESERVATION_TABLES
    }


def get_unique_constraints(
    conn: psycopg.Connection,
    table: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        c.conname,
        ARRAY(
            SELECT a.attname
            FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid
             AND a.attnum = k.attnum
            ORDER BY k.ord
        ) AS columns
    FROM pg_constraint c
    WHERE c.conrelid = %s::regclass
      AND c.contype = 'u'
    ORDER BY c.conname
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (table,))
        return list(cur.fetchall())


def get_columns(conn: psycopg.Connection, table: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        a.attnum,
        a.attname AS name,
        pg_catalog.format_type(a.atttypid, a.atttypmod) AS type,
        a.attnotnull AS not_null,
        pg_get_expr(d.adbin, d.adrelid) AS default_expr
    FROM pg_attribute a
    LEFT JOIN pg_attrdef d
      ON d.adrelid = a.attrelid
     AND d.adnum = a.attnum
    WHERE a.attrelid = %s::regclass
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY a.attnum
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (table,))
        return list(cur.fetchall())


def get_indexes(conn: psycopg.Connection, table: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        indexname,
        indexdef
    FROM pg_indexes
    WHERE schemaname = current_schema()
      AND tablename = %s
    ORDER BY indexname
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (table,))
        return list(cur.fetchall())


def get_triggers(conn: psycopg.Connection, table: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        t.tgname AS trigger_name,
        p.proname AS function_name,
        pg_get_triggerdef(t.oid, true) AS definition
    FROM pg_trigger t
    JOIN pg_proc p
      ON p.oid = t.tgfoid
    WHERE t.tgrelid = %s::regclass
      AND NOT t.tgisinternal
    ORDER BY t.tgname
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (table,))
        return list(cur.fetchall())


def catalog_snapshot(conn: psycopg.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for table in EXPECTED_TABLES:
        result[table] = {
            "columns": get_columns(conn, table),
            "unique_constraints": get_unique_constraints(conn, table),
            "indexes": get_indexes(conn, table),
            "triggers": get_triggers(conn, table),
        }

    return result


def assert_preserved(
    before: dict[str, Any],
    after: dict[str, Any],
    phase: str,
) -> None:
    failures = []

    for table in PRESERVATION_TABLES:
        b = before[table]
        a = after[table]

        if b["row_count"] != a["row_count"]:
            failures.append(
                f"{table}: row count {b['row_count']} -> {a['row_count']}"
            )

        if b["sha256"] != a["sha256"]:
            failures.append(
                f"{table}: row hash {b['sha256']} -> {a['sha256']}"
            )

    if failures:
        fail(
            f"Authority data changed during {phase}:\n- "
            + "\n- ".join(failures)
        )


def inspect_audit_unique_order(
    conn: psycopg.Connection,
) -> tuple[list[str], list[dict[str, Any]]]:
    constraints = get_unique_constraints(
        conn,
        "trading_universe_audit_events",
    )

    relevant = [
        row
        for row in constraints
        if set(row["columns"]) == {"correlation_id", "action"}
    ]

    if len(relevant) != 1:
        fail(
            "Expected exactly one audit unique constraint involving "
            "correlation_id + action; found "
            f"{len(relevant)}: {constraints}"
        )

    return list(relevant[0]["columns"]), constraints


def migration_declared_unique_order() -> list[str]:
    text = MIGRATION.read_text(encoding="utf-8")

    patterns = [
        r'UNIQUE\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
        r"UNIQUE\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\)",
    ]

    pairs: list[list[str]] = []

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            pair = [match.group(1), match.group(2)]
            if set(pair) == {"correlation_id", "action"}:
                pairs.append(pair)

    unique_pairs = []
    for pair in pairs:
        if pair not in unique_pairs:
            unique_pairs.append(pair)

    if not unique_pairs:
        fail(
            "Could not locate migration declaration for audit "
            "correlation_id/action unique constraint"
        )

    if len(unique_pairs) > 1:
        fail(
            "Migration contains conflicting audit unique-key orderings: "
            f"{unique_pairs}"
        )

    return unique_pairs[0]


def write_json_evidence(
    *,
    before: dict[str, Any],
    after_first: dict[str, Any],
    after_second: dict[str, Any],
    catalog_before: dict[str, Any],
    catalog_after_first: dict[str, Any],
    catalog_after_second: dict[str, Any],
    pre_order: list[str],
    migration_order: list[str],
) -> None:
    evidence = {
        "task": 969,
        "database": "task967_disposable_task968",
        "migration": str(MIGRATION.relative_to(ROOT)),
        "migration_sha256": sha256_text(
            MIGRATION.read_text(encoding="utf-8")
        ),
        "expected_symbol_count": EXPECTED_MEMBER_COUNT,
        "approved_set_hash": APPROVED_SET_HASH,
        "audit_unique_key": {
            "pre_task964_catalog_order": pre_order,
            "candidate_migration_declared_order": migration_order,
            "match": pre_order == migration_order,
        },
        "before": before,
        "after_first_migration": after_first,
        "after_second_migration": after_second,
        "catalog_before": catalog_before,
        "catalog_after_first": catalog_after_first,
        "catalog_after_second": catalog_after_second,
    }

    EVIDENCE_JSON.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_catalog_report(
    *,
    pre_order: list[str],
    migration_order: list[str],
    catalog_after_first: dict[str, Any],
) -> None:
    status = "PASS" if pre_order == migration_order else "FAIL"

    lines = [
        "# TASK #969 — PostgreSQL Catalog Parity",
        "",
        f"**Unique-key ordering result: {status}**",
        "",
        "## Audit unique constraint",
        "",
        f"- Pre-Task964 PostgreSQL catalog order: `{tuple(pre_order)}`",
        f"- Candidate migration declaration: `{tuple(migration_order)}`",
        f"- Exact ordered match: `{pre_order == migration_order}`",
        "",
        "## Tables inspected",
        "",
    ]

    for table in EXPECTED_TABLES:
        data = catalog_after_first[table]
        lines.extend(
            [
                f"### `{table}`",
                "",
                f"- Columns: {len(data['columns'])}",
                f"- Unique constraints: {len(data['unique_constraints'])}",
                f"- Indexes: {len(data['indexes'])}",
                f"- Non-internal triggers: {len(data['triggers'])}",
                "",
            ]
        )

    CATALOG_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_idempotency_report(
    *,
    after_first: dict[str, Any],
    after_second: dict[str, Any],
    catalog_after_first: dict[str, Any],
    catalog_after_second: dict[str, Any],
) -> None:
    data_equal = canonical_json(after_first) == canonical_json(after_second)
    catalog_equal = (
        canonical_json(catalog_after_first)
        == canonical_json(catalog_after_second)
    )

    lines = [
        "# TASK #969 — Migration Idempotency",
        "",
        f"- Authority data identical after second application: `{data_equal}`",
        f"- PostgreSQL catalog identical after second application: `{catalog_equal}`",
        "",
    ]

    if data_equal and catalog_equal:
        lines.append("**PASS — second migration application produced no drift.**")
    else:
        lines.append("**FAIL — second migration application produced drift.**")

    IDEMPOTENCY_MD.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    if not data_equal:
        fail("Second migration application changed seeded authority data")

    if not catalog_equal:
        fail("Second migration application changed PostgreSQL catalog")


def main() -> None:
    if not MIGRATION.exists():
        fail(f"Migration file not found: {MIGRATION}")

    database_url = get_database_url()

    print("TASK969: connecting to disposable PostgreSQL")
    print("TASK969: production access is prohibited")

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    current_database() AS database,
                    current_user AS db_user,
                    version() AS version
                """
            )
            env = cur.fetchone()

        print(f"TASK969 database: {env['database']}")
        print(f"TASK969 PostgreSQL: {env['version']}")

        if env["database"] != "task967_disposable_task968":
            fail(
                "Connected database is not the required disposable DB: "
                f"{env['database']}"
            )

        if "PostgreSQL 16" not in env["version"]:
            fail(
                "Task969 requires PostgreSQL 16; got: "
                f"{env['version']}"
            )

        print("TASK969: resetting disposable public schema")
        reset_public_schema(conn)

        print("TASK969: creating representative pre-Task964 schema")
        create_pre_task964_schema(conn)

        print("TASK969: seeding representative authority state")
        seed_authority_state(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM trading_universe_members
                WHERE universe_id = 3
                  AND enabled
                """
            )
            count = cur.fetchone()[0]

        if count != 23:
            fail(f"Expected 23 enabled members, found {count}")

        print("TASK969: capturing BEFORE evidence")
        before = preservation_snapshot(conn)
        catalog_before = catalog_snapshot(conn)

        pre_order, all_constraints = inspect_audit_unique_order(conn)
        migration_order = migration_declared_unique_order()

        print(
            "TASK969 pre-Task964 audit unique order:",
            tuple(pre_order),
        )
        print(
            "TASK969 candidate migration audit unique order:",
            tuple(migration_order),
        )

        # This is the explicit Task #969 catalog gate.
        if pre_order != migration_order:
            write_json_evidence(
                before=before,
                after_first=before,
                after_second=before,
                catalog_before=catalog_before,
                catalog_after_first=catalog_before,
                catalog_after_second=catalog_before,
                pre_order=pre_order,
                migration_order=migration_order,
            )

            write_catalog_report(
                pre_order=pre_order,
                migration_order=migration_order,
                catalog_after_first=catalog_before,
            )

            fail(
                "CATALOG PARITY FAILURE: pre-Task964 audit unique-key "
                f"order is {tuple(pre_order)}, but candidate migration "
                f"declares {tuple(migration_order)}. "
                f"Constraints: {all_constraints}"
            )

        migration_sql = MIGRATION.read_text(encoding="utf-8")

        print("TASK969: applying migration — first application")
        execute_script(conn, migration_sql)

        after_first = preservation_snapshot(conn)
        catalog_after_first = catalog_snapshot(conn)

        assert_preserved(
            before,
            after_first,
            "first migration application",
        )

        print("TASK969: first application preserved all seeded authority rows")

        print("TASK969: applying migration — second application")
        execute_script(conn, migration_sql)

        after_second = preservation_snapshot(conn)
        catalog_after_second = catalog_snapshot(conn)

        assert_preserved(
            before,
            after_second,
            "second migration application",
        )

        write_json_evidence(
            before=before,
            after_first=after_first,
            after_second=after_second,
            catalog_before=catalog_before,
            catalog_after_first=catalog_after_first,
            catalog_after_second=catalog_after_second,
            pre_order=pre_order,
            migration_order=migration_order,
        )

        write_catalog_report(
            pre_order=pre_order,
            migration_order=migration_order,
            catalog_after_first=catalog_after_first,
        )

        write_idempotency_report(
            after_first=after_first,
            after_second=after_second,
            catalog_after_first=catalog_after_first,
            catalog_after_second=catalog_after_second,
        )

    print()
    print("TASK969 NATIVE POSTGRESQL VALIDATION: PASS")
    print(f"Evidence: {EVIDENCE_JSON.name}")
    print(f"Catalog:  {CATALOG_MD.name}")
    print(f"Idempotency: {IDEMPOTENCY_MD.name}")


if __name__ == "__main__":
    main()