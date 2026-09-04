#!/usr/bin/env python3
"""Prepare or clean up the Task976 disposable Zeabur benchmark fixture.

This is benchmark tooling only.  It never runs the Task976 benchmark and it
does not import application or broker modules.  All database-changing paths
require the exact Zeabur identity and an explicit disposable acknowledgement.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
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


def prepare(conn: Any) -> None:
    print("TASK976 action: PREPARE_DISPOSABLE_FIXTURE_ONLY")
    print("TASK976 fixture: requiring empty public schema; no overwrite/reset")
    task969.require_empty_public_schema(conn)
    task969.create_pre_task964_schema(conn)
    task969.seed_authority_state(conn)

    counts, symbols, symbol_hash = fixture_evidence(conn)
    if symbols != sorted(task969.SYMBOLS):
        raise SafetyError("Prepared fixture does not contain the exact authorized symbol set")
    if symbol_hash != task969.APPROVED_SET_HASH:
        raise SafetyError("Prepared fixture exact-set hash mismatch")

    for table in task969.EXPECTED_TABLES:
        print(f"TASK976 row_count.{table}: {counts[table]}")
    print(f"TASK976 enabled_symbol_count: {len(symbols)}")
    print("TASK976 exact_symbol_set: PASS")
    print(f"TASK976 exact_set_hash: {symbol_hash}")
    print("TASK976 fixture_preparation: PASS")


def cleanup(conn: Any) -> None:
    """Remove only reviewed Task969 fixture tables from the authorized DB."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.relname
               FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'public'
                 AND c.relkind IN ('r', 'p')
               ORDER BY c.relname"""
        )
        present = {row[0] for row in cur.fetchall()}
        unexpected = present - set(task969.EXPECTED_TABLES)
        if unexpected:
            raise SafetyError(
                "Cleanup refused because public contains non-fixture tables: "
                + ", ".join(sorted(unexpected))
            )
        for table in reversed(task969.EXPECTED_TABLES):
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    conn.commit()
    print("TASK976 action: CLEANUP_DISPOSABLE_FIXTURE_ONLY")
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
