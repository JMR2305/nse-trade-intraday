#!/usr/bin/env python3
"""Prepare or clean up the Task976 disposable Zeabur benchmark fixture.

This is benchmark tooling only.  It never runs the Task976 benchmark and it
does not import application or broker modules.  All database-changing paths
require the exact Zeabur identity and an explicit disposable acknowledgement.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import os
import re
import sys
import textwrap
import types
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import psycopg2

# Task969's CI-only module imports psycopg v3, while this application declares
# psycopg2-binary.  Its reviewed fixture helpers use only the common DB-API
# surface.  Supply a narrow import shim rather than copying their constants or
# fixture SQL into this wrapper.
_psycopg_shim = types.ModuleType("psycopg")
_psycopg_shim.connect = psycopg2.connect
_psycopg_rows_shim = types.ModuleType("psycopg.rows")
_psycopg_rows_shim.dict_row = object()
_psycopg_shim.rows = _psycopg_rows_shim
sys.modules.setdefault("psycopg", _psycopg_shim)
sys.modules.setdefault("psycopg.rows", _psycopg_rows_shim)
import task969_postgres_validation as task969


AUTHORIZED_HOST = "postgres16-benchmark.zeabur.internal"
AUTHORIZED_PORT = 5432
AUTHORIZED_DATABASE = "apexquant_disposable"
AUTHORIZED_USER = "apexquant_benchmark"
AUTHORIZED_PG_MAJOR = 16
REQUIRED_ACK = AUTHORIZED_DATABASE

LIVE_ORDER_FLAGS = ("AUTO_EXECUTION_ENABLED", "LIVE_ORDERS_ENABLED")
TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})

AUTHORITY_TABLES = tuple(task969.EXPECTED_TABLES)
AUTHORITY_TABLE_SET = frozenset(AUTHORITY_TABLES)
EXPECTED_FIXTURE_COUNTS = {
    "trading_universe_sources": 1,
    "trading_universes": 1,
    "trading_universe_members": 23,
    "trading_universe_audit_events": 1,
    "runtime_universe_session_pins": 1,
    "trading_universe_member_details": 23,
    "trading_universe_validations": 1,
    "trading_universe_baseline_migrations": 1,
}


class SafetyError(RuntimeError):
    """A fail-closed Task976 safety-gate rejection."""


@dataclass(frozen=True)
class AuthorizedUrl:
    host: str
    port: int
    database: str
    user: str


def redact(text: Any, database_url: str = "") -> str:
    """Remove the URL and any parsed password from operator-visible errors."""
    safe = str(text)
    if database_url:
        safe = safe.replace(database_url, "[REDACTED_DATABASE_URL]")
        try:
            password = urlsplit(database_url).password
        except ValueError:
            password = None
        if password:
            safe = safe.replace(password, "[REDACTED]")
            safe = safe.replace(unquote(password), "[REDACTED]")
    return safe


def require_ack(env: Mapping[str, str]) -> None:
    if env.get("TASK976_DISPOSABLE_ACK", "") != REQUIRED_ACK:
        raise SafetyError(
            "TASK976_DISPOSABLE_ACK must exactly acknowledge apexquant_disposable"
        )


def validate_database_url(database_url: str) -> AuthorizedUrl:
    """Validate without returning or displaying credentials."""
    if not database_url:
        raise SafetyError("DATABASE_URL is missing")
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
    except ValueError as exc:
        raise SafetyError("DATABASE_URL is malformed") from exc

    identity = AuthorizedUrl(
        host=(parsed.hostname or "").lower(),
        port=port or 0,
        database=unquote(parsed.path.removeprefix("/")),
        user=unquote(parsed.username or ""),
    )
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or identity.host != AUTHORIZED_HOST
        or identity.port != AUTHORIZED_PORT
        or identity.database != AUTHORIZED_DATABASE
        or identity.user != AUTHORIZED_USER
        or parsed.query
        or parsed.fragment
    ):
        raise SafetyError("DATABASE_URL does not match the exact authorized Zeabur identity")
    return identity


def exact_set_hash(symbols: list[str] | tuple[str, ...]) -> str:
    canonical = "\n".join(sorted({str(symbol).strip().upper() for symbol in symbols}))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_fixture_contract() -> None:
    if (
        len(task969.SYMBOLS) != task969.EXPECTED_MEMBER_COUNT
        or task969.EXPECTED_MEMBER_COUNT != 23
        or exact_set_hash(task969.SYMBOLS) != task969.APPROVED_SET_HASH
    ):
        raise SafetyError("Reviewed Task969 23-symbol fixture contract is inconsistent")


def require_paper_only(env: Mapping[str, str]) -> None:
    enabled = [
        name for name in LIVE_ORDER_FLAGS
        if env.get(name, "").strip().lower() in TRUTHY
    ]
    if enabled:
        raise SafetyError("Live-order environment flags must be disabled: " + ", ".join(enabled))


def read_live_identity(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT current_database() AS database,
                   current_user AS db_user,
                   current_setting('server_version_num')::int AS version_num
            """
        )
        database, db_user, version_num = cur.fetchone()
        return {
            "database": database,
            "db_user": db_user,
            "version_num": version_num,
        }


def require_live_identity(live: Mapping[str, Any]) -> None:
    if live.get("database") != AUTHORIZED_DATABASE:
        raise SafetyError("Live current_database() is not the authorized disposable database")
    if live.get("db_user") != AUTHORIZED_USER:
        raise SafetyError("Live current_user is not the authorized benchmark user")
    try:
        major = int(live.get("version_num", 0)) // 10000
    except (TypeError, ValueError) as exc:
        raise SafetyError("Live PostgreSQL version is unavailable") from exc
    if major != AUTHORIZED_PG_MAJOR:
        raise SafetyError("Live server is not PostgreSQL major 16")


def fixture_evidence(conn: Any) -> tuple[dict[str, int], list[str], str]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in task969.EXPECTED_TABLES:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            counts[table] = int(cur.fetchone()[0])
        cur.execute(
            """SELECT symbol FROM trading_universe_members
               WHERE universe_id = 3 AND enabled
               ORDER BY symbol"""
        )
        symbols = [row[0] for row in cur.fetchall()]
    return counts, symbols, exact_set_hash(symbols)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def public_table_counts(conn: Any) -> dict[str, int]:
    """Capture counts only; never read or print application row contents."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
               ORDER BY table_name"""
        )
        tables = [row[0] for row in cur.fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            cur.execute(f"SELECT count(*) FROM {_quote_identifier(table)}")
            counts[table] = int(cur.fetchone()[0])
    return counts


def require_unrelated_tables_preserved(
    before: Mapping[str, int], after: Mapping[str, int]
) -> int:
    before_unrelated = {
        table: count for table, count in before.items()
        if table not in AUTHORITY_TABLE_SET
    }
    after_unrelated = {
        table: count for table, count in after.items()
        if table not in AUTHORITY_TABLE_SET
    }
    if before_unrelated != after_unrelated:
        raise SafetyError("An unrelated public table changed during fixture tooling")
    return len(before_unrelated)


def classify_authority_state(
    existing_counts: Mapping[str, int], exact_fixture: bool
) -> str:
    authority_counts = {
        table: int(existing_counts[table])
        for table in AUTHORITY_TABLES if table in existing_counts
    }
    if any(count != 0 for count in authority_counts.values()):
        if (
            exact_fixture
            and set(authority_counts) == AUTHORITY_TABLE_SET
            and authority_counts == EXPECTED_FIXTURE_COUNTS
        ):
            return "EXACT"
        raise SafetyError("Non-empty universe-authority state is not the exact Task976 fixture")
    return "EMPTY"


def _reviewed_schema_sql() -> str:
    source = textwrap.dedent(inspect.getsource(task969.create_pre_task964_schema))
    tree = ast.parse(source)
    candidates = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "CREATE TABLE trading_universe_sources" in node.value
    ]
    if len(candidates) != 1:
        raise SafetyError("Could not resolve the reviewed Task969 authority schema")
    return candidates[0]


def reviewed_additive_statements(missing_tables: set[str]) -> list[str]:
    if not missing_tables <= AUTHORITY_TABLE_SET:
        raise SafetyError("Unreviewed authority table requested")
    selected: list[str] = []
    created: set[str] = set()
    for raw in _reviewed_schema_sql().split(";"):
        statement = raw.strip()
        if not statement:
            continue
        table_match = re.match(r"CREATE TABLE\s+([a-z0-9_]+)", statement, re.I)
        index_match = re.match(
            r"CREATE(?: UNIQUE)? INDEX\s+[a-z0-9_]+\s+ON\s+([a-z0-9_]+)",
            statement,
            re.I,
        )
        target = (table_match or index_match)
        if target and target.group(1) in missing_tables:
            if re.search(r"\b(DROP|TRUNCATE|DELETE|ALTER)\b", statement, re.I):
                raise SafetyError("Reviewed additive schema unexpectedly became destructive")
            selected.append(statement)
            if table_match:
                created.add(table_match.group(1))
    if created != missing_tables:
        raise SafetyError("Reviewed schema does not define every missing authority table")
    return selected


def create_missing_authority_tables(conn: Any, missing_tables: set[str]) -> None:
    statements = reviewed_additive_statements(missing_tables)
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def _fetchall(conn: Any, sql: str) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def _matching_count(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.fetchone()[0])


def expected_member_rows() -> list[tuple[Any, ...]]:
    symbols = sorted(task969.SYMBOLS)
    sectors = {symbol: "INFRA" for symbol in symbols}
    sectors.update({
        "BANKBARODA": "BANK", "BANKINDIA": "BANK", "CANBK": "BANK",
        "FEDERALBNK": "BANK", "IDFCFIRSTB": "BANK", "KTKBANK": "BANK",
        "MAHABANK": "BANK", "PNB": "BANK", "UNIONBANK": "BANK",
        "WIPRO": "IT",
    })
    return sorted(
        (symbol, sectors[symbol], 900000 + task969.SYMBOLS.index(symbol) + 1,
         "MAPPED", True, "task969", "representative mapping")
        for symbol in symbols
    )


def fixture_state_is_exact(conn: Any, counts: Mapping[str, int]) -> bool:
    if set(counts).intersection(AUTHORITY_TABLE_SET) != AUTHORITY_TABLE_SET:
        return False
    authority_counts = {table: int(counts[table]) for table in AUTHORITY_TABLES}
    if authority_counts != EXPECTED_FIXTURE_COUNTS:
        return False

    symbols = sorted(task969.SYMBOLS)
    expected_members = expected_member_rows()
    full_match_counts = [
        _matching_count(conn, """SELECT count(*) FROM trading_universe_sources
            WHERE id=1 AND source_type='BASELINE' AND source_reference='task969-seed'
              AND source_table='custom_universe_master'
              AND source_snapshot_at='2026-08-28T04:00:00Z'::timestamptz
              AND source_set_hash=%s AND imported_at IS NOT NULL
              AND imported_by='task969'
              AND metadata='{"purpose":"native-postgres-validation"}'::jsonb""",
                        (task969.APPROVED_SET_HASH,)),
        _matching_count(conn, """SELECT count(*) FROM trading_universes
            WHERE id=3 AND universe_key='CUSTOM_LOW_PRICE_SECTOR'
              AND display_name='Custom Low Price Sector' AND version=1
              AND status='ACTIVE' AND effective_from='2026-08-31T03:30:00Z'::timestamptz
              AND effective_until IS NULL AND created_at='2026-08-28T04:00:00Z'::timestamptz
              AND created_by='task969' AND approved_at='2026-08-28T04:01:00Z'::timestamptz
              AND approved_by='task969'
              AND notes='Task969 representative pre-Task964 authority state'
              AND exact_set_hash=%s AND enabled_symbol_count=23 AND source_id=1""",
                        (task969.APPROVED_SET_HASH,)),
        _matching_count(conn, """SELECT count(*) FROM trading_universe_members
            WHERE universe_id=3 AND exchange='NSE' AND mapping_status='MAPPED'
              AND enabled IS TRUE AND added_at='2026-08-28T04:02:00Z'::timestamptz
              AND added_by='task969' AND removed_at IS NULL AND removed_by IS NULL
              AND notes='representative mapping'"""),
        _matching_count(conn, """SELECT count(*) FROM trading_universe_audit_events
            WHERE id=1 AND occurred_at='2026-08-28T04:05:00Z'::timestamptz
              AND actor='task969' AND action='BASELINE_IMPORTED'
              AND universe_key='CUSTOM_LOW_PRICE_SECTOR' AND old_version IS NULL
              AND new_version=1 AND symbol IS NULL AND change_type IS NULL
              AND old_value IS NULL AND new_value IS NULL
              AND notes='Representative audit event'
              AND correlation_id='task969-audit-1' AND approval_state='APPROVED'"""),
        _matching_count(conn, """SELECT count(*) FROM runtime_universe_session_pins
            WHERE natural_session='preopen-2026-08-31-task969'
              AND universe_key='CUSTOM_LOW_PRICE_SECTOR' AND universe_id=3
              AND universe_version=1 AND universe_symbols=%s::jsonb
              AND universe_symbol_count=23 AND universe_set_hash=%s
              AND effective_from='2026-08-31T03:30:00Z'::timestamptz
              AND pinned_at='2026-08-31T03:30:01Z'::timestamptz""",
                        (task969.canonical_json(task969.SYMBOLS), task969.APPROVED_SET_HASH)),
        _matching_count(conn, """SELECT count(*) FROM trading_universe_member_details
            WHERE universe_id=3 AND created_at='2026-08-28T04:02:00Z'::timestamptz
              AND created_by='task969'
              AND metadata->>'exchange'='NSE' AND metadata->>'instrument_type'='EQ'
              AND metadata->>'segment'='NSE' AND metadata->>'mapping_status'='MAPPED'
              AND (metadata - 'instrument_token') =
                  '{"exchange":"NSE","instrument_type":"EQ","segment":"NSE","mapping_status":"MAPPED"}'::jsonb"""),
        _matching_count(conn, """SELECT count(*) FROM trading_universe_validations
            WHERE id=1 AND universe_id=3 AND result='VALIDATION_PASS'
              AND checked_at='2026-08-28T04:03:00Z'::timestamptz
              AND checked_by='task969' AND correlation_id='task969-validation-1'
              AND evidence='{"mapping_count":23,"expected_count":23}'::jsonb"""),
        _matching_count(conn, """SELECT count(*) FROM trading_universe_baseline_migrations
            WHERE id=1 AND occurred_at='2026-08-28T04:04:00Z'::timestamptz
              AND actor='task969' AND action='BASELINE_MIGRATION'
              AND universe_key='CUSTOM_LOW_PRICE_SECTOR' AND destination_universe_id=3
              AND destination_version=1 AND source_authority='custom_universe_master'
              AND exact_symbol_count=23 AND exact_set_hash=%s AND mapping_count=23
              AND previous_configured_universe_key='CUSTOM_LOW_PRICE_SECTOR'
              AND reason='MIGRATE_EXISTING_PRODUCTION_BASELINE_TO_VERSIONED_AUTHORITY'
              AND correlation_id='task969-baseline-migration-1'
              AND evidence='{"mapping_complete":true}'::jsonb""",
                        (task969.APPROVED_SET_HASH,)),
    ]
    if full_match_counts != [1, 1, 23, 1, 1, 23, 1, 1]:
        return False
    checks = [
        (_fetchall(conn, """SELECT id, source_type, source_reference, source_table,
                         source_set_hash, imported_by FROM trading_universe_sources"""),
         [(1, "BASELINE", "task969-seed", "custom_universe_master",
           task969.APPROVED_SET_HASH, "task969")]),
        (_fetchall(conn, """SELECT id, universe_key, version, status, exact_set_hash,
                         enabled_symbol_count, source_id, created_by, approved_by
                         FROM trading_universes"""),
         [(3, "CUSTOM_LOW_PRICE_SECTOR", 1, "ACTIVE", task969.APPROVED_SET_HASH,
           23, 1, "task969", "task969")]),
        (_fetchall(conn, """SELECT symbol, sector, instrument_token, mapping_status,
                         enabled, added_by, notes FROM trading_universe_members
                         ORDER BY symbol"""), expected_members),
        (_fetchall(conn, """SELECT id, actor, action, universe_key, old_version,
                         new_version, correlation_id, approval_state
                         FROM trading_universe_audit_events"""),
         [(1, "task969", "BASELINE_IMPORTED", "CUSTOM_LOW_PRICE_SECTOR", None,
           1, "task969-audit-1", "APPROVED")]),
        (_fetchall(conn, """SELECT natural_session, universe_key, universe_id,
                         universe_version, universe_symbol_count, universe_set_hash
                         FROM runtime_universe_session_pins"""),
         [("preopen-2026-08-31-task969", "CUSTOM_LOW_PRICE_SECTOR", 3, 1, 23,
           task969.APPROVED_SET_HASH)]),
        (_fetchall(conn, """SELECT id, universe_id, result, checked_by, correlation_id
                         FROM trading_universe_validations"""),
         [(1, 3, "VALIDATION_PASS", "task969", "task969-validation-1")]),
        (_fetchall(conn, """SELECT id, actor, action, universe_key,
                         destination_universe_id, destination_version,
                         exact_symbol_count, exact_set_hash, mapping_count,
                         correlation_id FROM trading_universe_baseline_migrations"""),
         [(1, "task969", "BASELINE_MIGRATION", "CUSTOM_LOW_PRICE_SECTOR", 3, 1,
           23, task969.APPROVED_SET_HASH, 23, "task969-baseline-migration-1")]),
    ]
    if not all(actual == expected for actual, expected in checks):
        return False
    detail_rows = _fetchall(
        conn,
        """SELECT symbol, metadata->>'instrument_token', metadata->>'mapping_status',
                  created_by FROM trading_universe_member_details ORDER BY symbol""",
    )
    expected_details = [
        (symbol, str(900000 + task969.SYMBOLS.index(symbol) + 1), "MAPPED", "task969")
        for symbol in symbols
    ]
    return detail_rows == expected_details


def require_fixture_evidence(
    counts: Mapping[str, int], symbols: list[str], symbol_hash: str
) -> None:
    if dict(counts) != EXPECTED_FIXTURE_COUNTS:
        raise SafetyError("Prepared fixture row counts do not match the reviewed fixture")
    if symbols != sorted(task969.SYMBOLS):
        raise SafetyError("Prepared fixture does not contain the exact authorized symbol set")
    if symbol_hash != task969.APPROVED_SET_HASH:
        raise SafetyError("Prepared fixture exact-set hash mismatch")


def prepare(conn: Any) -> None:
    print("TASK976 action: PREPARE_DISPOSABLE_FIXTURE_ONLY")
    before = public_table_counts(conn)
    exact_before = fixture_state_is_exact(conn, before)
    state = classify_authority_state(before, exact_before)
    if state == "EXACT":
        counts, symbols, symbol_hash = fixture_evidence(conn)
        require_fixture_evidence(counts, symbols, symbol_hash)
        after = public_table_counts(conn)
        unrelated_count = require_unrelated_tables_preserved(before, after)
        print("TASK976 fixture_state: EXACT_EXISTING_IDEMPOTENT")
    else:
        missing = AUTHORITY_TABLE_SET - set(before)
        print(f"TASK976 authority_tables_missing: {len(missing)}")
        print("TASK976 authority_existing_rows: 0")
        create_missing_authority_tables(conn, set(missing))
        task969.seed_authority_state(_NoCommitConnection(conn))
        after = public_table_counts(conn)
        if not fixture_state_is_exact(conn, after):
            raise SafetyError("Prepared authority state is not the exact Task976 fixture")
        unrelated_count = require_unrelated_tables_preserved(before, after)
        counts, symbols, symbol_hash = fixture_evidence(conn)
        require_fixture_evidence(counts, symbols, symbol_hash)
        conn.commit()
        print("TASK976 fixture_state: PREPARED")

    for table in task969.EXPECTED_TABLES:
        print(f"TASK976 row_count.{table}: {counts[table]}")
    print(f"TASK976 enabled_symbol_count: {len(symbols)}")
    print("TASK976 exact_symbol_set: PASS")
    print(f"TASK976 exact_set_hash: {symbol_hash}")
    print("TASK976 mapping_tokens_scope: BENCHMARK_ONLY_NON_BROKER")
    print("TASK976 unrelated_tables_preserved: PASS")
    print(f"TASK976 unrelated_table_count: {unrelated_count}")
    print("TASK976 fixture_preparation: PASS")


class _NoCommitConnection:
    """Expose DB-API operations while deferring a reviewed helper's commit."""

    def __init__(self, connection: Any):
        self._connection = connection

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._connection.cursor(*args, **kwargs)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self._connection.rollback()


def delete_fixture_rows(conn: Any) -> None:
    statements = [
        ("""DELETE FROM runtime_universe_session_pins
            WHERE natural_session=%s AND universe_key=%s AND universe_id=%s
              AND universe_version=%s AND universe_symbols=%s::jsonb
              AND universe_symbol_count=23 AND universe_set_hash=%s""",
         ("preopen-2026-08-31-task969", "CUSTOM_LOW_PRICE_SECTOR", 3, 1,
          task969.canonical_json(task969.SYMBOLS), task969.APPROVED_SET_HASH)),
        ("""DELETE FROM trading_universe_member_details
            WHERE universe_id=%s AND created_by=%s AND metadata->>'mapping_status'='MAPPED'""",
         (3, "task969")),
        ("""DELETE FROM trading_universe_validations
            WHERE id=%s AND universe_id=3 AND checked_by=%s AND correlation_id=%s
              AND evidence=%s::jsonb""",
         (1, "task969", "task969-validation-1",
          '{"mapping_count":23,"expected_count":23}')),
        ("""DELETE FROM trading_universe_baseline_migrations
            WHERE id=%s AND actor=%s AND correlation_id=%s AND exact_set_hash=%s
              AND reason='MIGRATE_EXISTING_PRODUCTION_BASELINE_TO_VERSIONED_AUTHORITY'
              AND evidence=%s::jsonb""",
         (1, "task969", "task969-baseline-migration-1", task969.APPROVED_SET_HASH,
          '{"mapping_complete":true}')),
        ("""DELETE FROM trading_universe_members
            WHERE universe_id=%s AND added_by=%s AND exchange='NSE'
              AND mapping_status='MAPPED' AND instrument_token BETWEEN 900001 AND 900023""",
         (3, "task969")),
        ("""DELETE FROM trading_universe_audit_events
            WHERE id=%s AND actor=%s AND correlation_id=%s
              AND universe_key='CUSTOM_LOW_PRICE_SECTOR'""",
         (1, "task969", "task969-audit-1")),
        ("""DELETE FROM trading_universes
            WHERE id=%s AND created_by=%s AND universe_key='CUSTOM_LOW_PRICE_SECTOR'
              AND version=1 AND exact_set_hash=%s""",
         (3, "task969", task969.APPROVED_SET_HASH)),
        ("""DELETE FROM trading_universe_sources
            WHERE id=%s AND imported_by=%s AND source_reference='task969-seed'
              AND metadata=%s::jsonb""",
         (1, "task969", '{"purpose":"native-postgres-validation"}')),
    ]
    with conn.cursor() as cur:
        for sql, params in statements:
            cur.execute(sql, params)


def cleanup(conn: Any) -> None:
    """Remove exact fixture-owned rows; never drop any application table."""
    before = public_table_counts(conn)
    if not fixture_state_is_exact(conn, before):
        raise SafetyError("Cleanup refused: exact Task976 fixture ownership is not proven")
    with conn.cursor() as cur:
        for table in AUTHORITY_TABLES:
            cur.execute(f"LOCK TABLE {_quote_identifier(table)} IN SHARE ROW EXCLUSIVE MODE")
    if not fixture_state_is_exact(conn, before):
        raise SafetyError("Cleanup refused: fixture state changed before ownership lock")
    delete_fixture_rows(conn)
    after = public_table_counts(conn)
    if any(after.get(table, 0) for table in AUTHORITY_TABLES):
        raise SafetyError("Cleanup did not remove the complete Task976 fixture state")
    unrelated_count = require_unrelated_tables_preserved(before, after)
    conn.commit()
    print("TASK976 action: CLEANUP_DISPOSABLE_FIXTURE_ONLY")
    print("TASK976 unrelated_tables_preserved: PASS")
    print(f"TASK976 unrelated_table_count: {unrelated_count}")
    print("TASK976 cleanup: PASS")


def print_identity(url_identity: AuthorizedUrl, live: Mapping[str, Any]) -> None:
    print(f"TASK976 host: {url_identity.host}")
    print(f"TASK976 port: {url_identity.port}")
    print(f"TASK976 database: {live['database']}")
    print(f"TASK976 user: {live['db_user']}")
    print(f"TASK976 PostgreSQL_major: {int(live['version_num']) // 10000}")
    print("TASK976 identity_gate: PASS")


def print_safety_assertions() -> None:
    print("TASK976 safety.fixture_scope: DISPOSABLE_DATABASE_ONLY")
    print("TASK976 safety.paper_only: PASS")
    print("TASK976 safety.broker_modules_imported: false")
    print("TASK976 safety.broker_credentials_read: false")
    print("TASK976 safety.orders_submitted: false")
    print("TASK976 safety.heavy_benchmark_run: false")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cleanup", action="store_true",
        help="remove only recognized fixture tables after the same safety gates",
    )
    args = parser.parse_args(argv)
    active_env = os.environ if env is None else env
    database_url = active_env.get("DATABASE_URL", "").strip()

    try:
        require_ack(active_env)
        url_identity = validate_database_url(database_url)
        require_fixture_contract()
        require_paper_only(active_env)
        print("TASK976: connecting for live identity gate (credentials redacted)")
        with psycopg2.connect(database_url) as conn:
            live = read_live_identity(conn)
            require_live_identity(live)
            print_identity(url_identity, live)
            print_safety_assertions()
            if args.cleanup:
                cleanup(conn)
            else:
                prepare(conn)
        return 0
    except SystemExit:
        print("TASK976 FIXTURE FAILURE: reviewed Task969 helper rejected the operation", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"TASK976 FIXTURE FAILURE: {redact(exc, database_url)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
