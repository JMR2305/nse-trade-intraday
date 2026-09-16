#!/usr/bin/env python3
"""Deterministic, non-runtime PostgreSQL authority bootstrap.

This module deliberately does not import application code.  PostgreSQL is
loaded only after the static target contract has passed.  The checked-in SQL
and JSON manifests are the review boundary; source extraction is performed by
offline review tests, never while mutating a database.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit


ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "scripts" / "task978r_application_authority_schema.sql"
MANIFEST_PATH = ROOT / "scripts" / "task978r_clean_authority_manifest.json"

CANONICAL_SYMBOLS = (
    "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
    "KTKBANK", "MAHABANK", "PNB", "UNIONBANK", "COALINDIA", "GAIL",
    "HUDCO", "IRCON", "IRFC", "MRPL", "NBCC", "NMDC", "NTPC", "PFC",
    "RECLTD", "RVNL", "SAIL", "WIPRO",
)
CANONICAL_SET_HASH = hashlib.sha256(
    "\n".join(sorted(CANONICAL_SYMBOLS)).encode("utf-8")
).hexdigest()
CANONICAL_MEMBER_SECTORS = {
    **{symbol: "BANK" for symbol in CANONICAL_SYMBOLS[:9]},
    **{symbol: "INFRA" for symbol in CANONICAL_SYMBOLS[9:-1]},
    "WIPRO": "IT",
}

SAFETY_SETTINGS = {
    "PAPER_TRADING_MODE": True,
    "AUTO_EXECUTION_ENABLED": False,
    "LIVE_EXECUTION_ENABLED": False,
    "LIVE_ORDERS_ENABLED": False,
    "CONTROLLED_PAPER_ENTRY_ENABLED": False,
    "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED": False,
    "BOOTSTRAP_PAPER_ENABLED": False,
    "AUTO_PAPER_ENTRIES": False,
}
CLEAN_PHASE20_SETTINGS = {
    "auto_paper_entries": False,
    "auto_paper_entries_confirmed_at": None,
    "bootstrap_paper_enabled": False,
    "auto_paper_exits": True,
    "initial_capital": 100000.0,
    "authority_class": "CLEAN_RECONSTRUCTED_AUTHORITY",
    "historically_equivalent_to_replit_db": False,
}

PROHIBITED_HOSTS = frozenset({"postgres16-benchmark.zeabur.internal"})
PROHIBITED_DATABASES = frozenset({
    "apexquant_disposable", "task967_disposable_task968",
})


class IdentityRefused(RuntimeError):
    """The target is not the exact reviewed authority identity."""


class BootstrapFailure(RuntimeError):
    """The bootstrap could not be proven complete and atomic."""


@dataclasses.dataclass(frozen=True)
class TargetIdentity:
    scheme: str
    host: str
    port: int
    database: str
    user: str
    purpose: str
    acknowledgement: str


def parse_target_identity(
    database_url: str,
    *,
    purpose: str,
    acknowledgement: str,
) -> TargetIdentity:
    if not database_url:
        raise IdentityRefused("database URL is missing")
    try:
        parsed = urlsplit(database_url)
        port = parsed.port or 5432
    except ValueError as exc:
        raise IdentityRefused("database URL is malformed") from exc
    if parsed.query or parsed.fragment:
        raise IdentityRefused("database URL query and fragment are forbidden")
    return TargetIdentity(
        scheme=parsed.scheme,
        host=(parsed.hostname or "").lower(),
        port=port,
        database=unquote(parsed.path.removeprefix("/")),
        user=unquote(parsed.username or ""),
        purpose=purpose,
        acknowledgement=acknowledgement,
    )


def authorize_target(target: TargetIdentity, *, expected_user: str = "") -> None:
    if target.scheme not in {"postgres", "postgresql"}:
        raise IdentityRefused("PostgreSQL URL required")
    if target.host in PROHIBITED_HOSTS or target.database in PROHIBITED_DATABASES:
        raise IdentityRefused("prohibited database identity")
    if target.purpose == "TASK978ZA_NATIVE_PG16":
        expected = (
            target.host in {"127.0.0.1", "localhost", "::1"}
            and target.port == 5432
            and target.database == "task978za_disposable_authority"
            and target.user == "task967"
            and target.acknowledgement == "TASK978ZA_DISPOSABLE_AUTHORITY"
        )
    elif target.purpose == "TASK978ZA_ZEABUR_APPLICATION":
        expected = (
            target.host == "postgres16-apexquant-app.zeabur.internal"
            and target.port == 5432
            and target.database == "apexquant_app"
            and bool(expected_user)
            and target.user == expected_user
            and target.acknowledgement == "apexquant_app"
        )
    else:
        expected = False
    if not expected:
        raise IdentityRefused("target does not match an exact reviewed contract")


def preflight_authorize(
    database_url: str,
    *,
    purpose: str,
    acknowledgement: str,
    expected_user: str = "",
) -> TargetIdentity:
    target = parse_target_identity(
        database_url,
        purpose=purpose,
        acknowledgement=acknowledgement,
    )
    authorize_target(target, expected_user=expected_user)
    return target


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def seed_statements() -> tuple[str, ...]:
    """Return only clean current-state seed SQL; never historical evidence."""
    settings_json = _canonical_json(CLEAN_PHASE20_SETTINGS).replace("'", "''")
    safety_json = _canonical_json(SAFETY_SETTINGS).replace("'", "''")
    symbol_json = _canonical_json(list(CANONICAL_SYMBOLS)).replace("'", "''")
    member_values = ",\n".join(
        "(%s, '%s', 'NSE', '%s', 'UNVERIFIED', true, "
        "'task978za_clean_authority')" % (index, symbol, CANONICAL_MEMBER_SECTORS[symbol])
        for index, symbol in enumerate(CANONICAL_SYMBOLS, start=1)
    )
    return (
        """
        INSERT INTO phase20_settings (id, data, updated_at)
        VALUES (1, '%s'::jsonb, NOW())
        ON CONFLICT (id) DO NOTHING
        """ % settings_json,
        """
        INSERT INTO phase20_kv (key, value, updated_at)
        VALUES ('task978za_deployment_safety_v1', '%s'::jsonb, NOW())
        ON CONFLICT (key) DO NOTHING
        """ % safety_json,
        """
        INSERT INTO phase20_kv (key, value, updated_at)
        VALUES ('task978za_clean_authority_v1',
                jsonb_build_object(
                    'authority_class', 'CLEAN_RECONSTRUCTED_AUTHORITY',
                    'historically_equivalent_to_replit_db', false,
                    'universe_key', 'CUSTOM_LOW_PRICE_SECTOR',
                    'universe_id', 3,
                    'version', 1,
                    'symbols', '%s'::jsonb,
                    'exact_set_hash', '%s'), NOW())
        ON CONFLICT (key) DO NOTHING
        """ % (symbol_json, CANONICAL_SET_HASH),
        """
        INSERT INTO trading_universe_sources (
            source_type, source_reference, source_set_hash, imported_by, metadata
        ) VALUES (
            'CLEAN_RECONSTRUCTION', 'TASK978ZA_CLEAN_RECONSTRUCTION', '%s',
            'task978za_clean_authority',
            '{"authority_class":"CLEAN_RECONSTRUCTED_AUTHORITY",'
            '"historical_equivalence":"NOT_HISTORICALLY_EQUIVALENT_TO_REPLIT_DB"}'::jsonb
        )
        ON CONFLICT (source_type, source_reference, source_set_hash) DO NOTHING
        """ % CANONICAL_SET_HASH,
        """
        INSERT INTO trading_universes (
            id, universe_key, display_name, version, status, effective_from,
            created_by, approved_at, approved_by, notes, exact_set_hash,
            enabled_symbol_count, source_id
        )
        SELECT 3, 'CUSTOM_LOW_PRICE_SECTOR', 'Custom Low Price Sector', 1,
               'DRAFT', '2026-08-31T03:30:00Z'::timestamptz,
               'task978za_clean_authority', NOW(), 'task978za_clean_authority',
               'CLEAN_RECONSTRUCTED_AUTHORITY; NOT_HISTORICALLY_EQUIVALENT_TO_REPLIT_DB',
               '%s', 23, id
        FROM trading_universe_sources
        WHERE source_type = 'CLEAN_RECONSTRUCTION'
          AND source_reference = 'TASK978ZA_CLEAN_RECONSTRUCTION'
          AND source_set_hash = '%s'
        ON CONFLICT (universe_key, version) DO NOTHING
        """ % (CANONICAL_SET_HASH, CANONICAL_SET_HASH),
        "SELECT setval(pg_get_serial_sequence('trading_universes', 'id'), "
        "GREATEST((SELECT MAX(id) FROM trading_universes), 1), true)",
        """
        WITH expected(ordinal, symbol, exchange, sector, mapping_status, enabled, added_by) AS (
            VALUES
            %s
        )
        INSERT INTO trading_universe_members (
            universe_id, symbol, exchange, sector, mapping_status, enabled,
            added_by, notes
        )
        SELECT 3, expected.symbol, expected.exchange, expected.sector,
               expected.mapping_status, expected.enabled, expected.added_by,
               'CLEAN_RECONSTRUCTED_AUTHORITY ordinal=' || expected.ordinal
        FROM expected
        JOIN trading_universes universe
          ON universe.id = 3
         AND universe.universe_key = 'CUSTOM_LOW_PRICE_SECTOR'
         AND universe.version = 1
         AND universe.status = 'DRAFT'
        WHERE NOT EXISTS (
            SELECT 1 FROM trading_universe_members existing
            WHERE existing.universe_id = 3
              AND existing.symbol = expected.symbol
        )
        ORDER BY expected.ordinal
        """ % member_values,
        """
        UPDATE trading_universes
        SET status = 'ACTIVE'
        WHERE id = 3
          AND universe_key = 'CUSTOM_LOW_PRICE_SECTOR'
          AND version = 1
          AND status = 'DRAFT'
          AND exact_set_hash = '%s'
          AND enabled_symbol_count = 23
        """ % CANONICAL_SET_HASH,
    )


def _read_sql() -> str:
    sql = SQL_PATH.read_text(encoding="utf-8")
    upper = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.M | re.S).upper()
    for forbidden in ("DROP ", "TRUNCATE ", "DELETE FROM", "CREATE DATABASE"):
        if forbidden in upper:
            raise BootstrapFailure(f"prohibited SQL token: {forbidden.strip()}")
    if not re.search(
        r'UNIQUE\s*\(\s*"?CORRELATION_ID"?\s*,\s*"?ACTION"?\s*\)', upper
    ):
        raise BootstrapFailure("canonical audit uniqueness is missing")
    if re.search(
        r'UNIQUE\s*\(\s*"?ACTION"?\s*,\s*"?CORRELATION_ID"?\s*\)', upper
    ):
        raise BootstrapFailure("reordered audit uniqueness is forbidden")
    return sql


def _split_statements(sql: str) -> list[str]:
    """Split the generated manifest at explicit bootstrap breakpoints."""
    return [part.strip() for part in re.split(
        r"^\s*-->\s*(?:statement|bootstrap)-breakpoint\s*$", sql, flags=re.M
    ) if part.strip()]


def _verify_live_identity(conn: Any, target: TargetIdentity) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(), current_user, "
            "current_setting('server_version_num')::int"
        )
        database, user, version_num = cur.fetchone()
    if database != target.database or user != target.user:
        raise IdentityRefused("live database identity mismatch")
    if int(version_num) // 10000 != 16:
        raise IdentityRefused("PostgreSQL major 16 required")


def _verify_authority(cur: Any) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required_tables = sorted(
        item["name"] for item in manifest["objects"] if item["kind"] == "table"
    )
    cur.execute(
        """
        SELECT expected.name
        FROM unnest(%s::text[]) AS expected(name)
        WHERE to_regclass('public.' || quote_ident(expected.name)) IS NULL
        ORDER BY expected.name
        """,
        (required_tables,),
    )
    missing = [row[0] for row in cur.fetchall()]
    if missing:
        raise BootstrapFailure(f"schema coverage incomplete: {missing}")

    cur.execute("SELECT data FROM phase20_settings WHERE id = 1")
    row = cur.fetchone()
    if not row or row[0] != CLEAN_PHASE20_SETTINGS:
        raise BootstrapFailure("Phase20 clean settings differ from the reviewed manifest")

    cur.execute(
        "SELECT key, value FROM phase20_kv "
        "WHERE key IN ('task978za_deployment_safety_v1', "
        "'task978za_clean_authority_v1', 'kite_token_v1')"
    )
    kv = {key: value for key, value in cur.fetchall()}
    if kv.get("task978za_deployment_safety_v1") != SAFETY_SETTINGS:
        raise BootstrapFailure("deployment safety settings differ from the reviewed manifest")
    authority = kv.get("task978za_clean_authority_v1", {})
    if (
        authority.get("authority_class") != "CLEAN_RECONSTRUCTED_AUTHORITY"
        or authority.get("historically_equivalent_to_replit_db") is not False
        or authority.get("symbols") != list(CANONICAL_SYMBOLS)
        or authority.get("exact_set_hash") != CANONICAL_SET_HASH
        or "kite_token_v1" in kv
    ):
        raise BootstrapFailure("clean-authority KV state is not exact")

    cur.execute(
        """
        SELECT id, universe_key, version, status, effective_from::text,
               effective_until, exact_set_hash, enabled_symbol_count
        FROM trading_universes
        ORDER BY id
        """
    )
    universes = cur.fetchall()
    if len(universes) != 1:
        raise BootstrapFailure("exactly one clean reconstructed universe is required")
    universe = universes[0]
    if (
        universe[0:4] != (3, "CUSTOM_LOW_PRICE_SECTOR", 1, "ACTIVE")
        or not str(universe[4]).startswith("2026-08-31 03:30:00")
        or universe[5] is not None
        or universe[6] != CANONICAL_SET_HASH
        or universe[7] != 23
    ):
        raise BootstrapFailure("canonical universe authority differs")

    cur.execute(
        """
        SELECT symbol, exchange, sector, mapping_status, enabled
        FROM trading_universe_members
        WHERE universe_id = 3
        ORDER BY symbol
        """
    )
    members = cur.fetchall()
    expected_members = sorted(
        (symbol, "NSE", CANONICAL_MEMBER_SECTORS[symbol], "UNVERIFIED", True)
        for symbol in CANONICAL_SYMBOLS
    )
    if members != expected_members:
        raise BootstrapFailure("canonical universe membership differs")

    historical_tables = (
        "phase20_paper_trades",
        "trading_universe_audit_events",
        "runtime_universe_session_pins",
        "trading_universe_validations",
        "trading_universe_baseline_migrations",
    )
    for table in historical_tables:
        cur.execute(f"SELECT count(*) FROM {table}")
        if cur.fetchone()[0] != 0:
            raise BootstrapFailure(f"historical rows are forbidden in {table}")

    cur.execute(
        """
        SELECT array_agg(attribute.attname ORDER BY ordinal.ordinality)
        FROM pg_constraint constraint_row
        JOIN LATERAL unnest(constraint_row.conkey)
          WITH ORDINALITY ordinal(attnum, ordinality) ON true
        JOIN pg_attribute attribute
          ON attribute.attrelid = constraint_row.conrelid
         AND attribute.attnum = ordinal.attnum
        WHERE constraint_row.conrelid = 'trading_universe_audit_events'::regclass
          AND constraint_row.contype = 'u'
        GROUP BY constraint_row.oid
        HAVING array_agg(attribute.attname ORDER BY ordinal.ordinality)
               = ARRAY['correlation_id', 'action']::name[]
        """
    )
    audit_row = cur.fetchone()
    if not audit_row or list(audit_row[0]) != ["correlation_id", "action"]:
        raise BootstrapFailure("canonical audit uniqueness order differs")
    return {
        "required_table_count": len(required_tables),
        "canonical_member_count": len(members),
        "historical_fabrication": 0,
        "kite_token_rows": 0,
        "audit_unique_order": ["correlation_id", "action"],
    }


def bootstrap(
    database_url: str,
    *,
    purpose: str,
    acknowledgement: str,
    expected_user: str = "",
) -> dict[str, Any]:
    target = preflight_authorize(
        database_url,
        purpose=purpose,
        acknowledgement=acknowledgement,
        expected_user=expected_user,
    )
    sql = _read_sql()
    import psycopg  # loaded only after the static identity gate

    conn = psycopg.connect(database_url)
    try:
        _verify_live_identity(conn, target)
        with conn.transaction():
            with conn.cursor() as cur:
                for statement in _split_statements(sql):
                    cur.execute(statement)
                for statement in seed_statements():
                    cur.execute(statement)
                verification = _verify_authority(cur)
        return {
            "status": "PASS",
            "database": target.database,
            "user": target.user,
            "postgresql_major": 16,
            "authority_class": "CLEAN_RECONSTRUCTED_AUTHORITY",
            "historically_equivalent_to_replit_db": False,
            "verification": verification,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="TASK978ZA_DATABASE_URL")
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--expected-user", default="")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get(args.database_url_env, "")
    try:
        result = bootstrap(
            database_url,
            purpose=args.purpose,
            acknowledgement=args.acknowledgement,
            expected_user=args.expected_user,
        )
    except Exception as exc:
        print(f"TASK978R_BOOTSTRAP=FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("TASK978R_BOOTSTRAP=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
