#!/usr/bin/env python3
"""Native PostgreSQL 16 validation for the Task978ZA clean bootstrap.

The validator accepts only the established Task969 local CI service and creates
a separate, unmistakably disposable database.  It never connects to Zeabur.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import sys
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
EVIDENCE_PATH = ROOT / "TASK_978ZA_NATIVE_BOOTSTRAP_EVIDENCE.json"
VALIDATION_DATABASE = "task978za_disposable_authority"

PROTECTED_TABLES = {
    "trading_universe_sources",
    "trading_universes",
    "trading_universe_members",
    "trading_universe_audit_events",
    "runtime_universe_session_pins",
    "trading_universe_member_details",
    "trading_universe_validations",
    "trading_universe_baseline_migrations",
}
PROHIBITED_HISTORY_TABLES = {
    "phase20_paper_trades",
    "trading_universe_audit_events",
    "trading_universe_validations",
    "runtime_universe_session_pins",
    "trading_universe_baseline_migrations",
}


def _manifest() -> dict[str, Any]:
    return json.loads(
        (SCRIPT_DIR / "task978r_clean_authority_manifest.json").read_text(encoding="utf-8")
    )


REQUIRED_TABLES = frozenset(
    obj["name"] for obj in _manifest()["objects"] if obj["kind"] == "table"
)


@dataclasses.dataclass(frozen=True)
class ValidationIdentity:
    maintenance_url: str
    validation_url: str
    maintenance_database: str
    validation_database: str
    user: str


def _with_database(parsed: SplitResult, database: str) -> str:
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", "", ""))


def derive_validation_identity(source_url: str) -> ValidationIdentity:
    parsed = urlsplit(source_url)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
        or (parsed.port or 5432) != 5432
        or parsed.path != "/task967_disposable_task968"
        or parsed.username != "task967"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("only the exact Task969 local disposable service is permitted")
    return ValidationIdentity(
        maintenance_url=_with_database(parsed, "postgres"),
        validation_url=_with_database(parsed, VALIDATION_DATABASE),
        maintenance_database="postgres",
        validation_database=VALIDATION_DATABASE,
        user="task967",
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _query_one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def _catalog_snapshot(conn: Any) -> dict[str, Any]:
    tables = _query_one(
        conn,
        """
        SELECT COALESCE(jsonb_agg(table_name ORDER BY table_name), '[]'::jsonb)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """,
    )
    columns = _query_one(
        conn,
        """
        SELECT COALESCE(jsonb_agg(to_jsonb(c) ORDER BY c.table_name, c.ordinal_position), '[]'::jsonb)
        FROM (
          SELECT table_name, column_name, ordinal_position, data_type, is_nullable,
                 column_default
          FROM information_schema.columns
          WHERE table_schema = 'public'
        ) c
        """,
    )
    indexes = _query_one(
        conn,
        """
        SELECT COALESCE(jsonb_agg(to_jsonb(i) ORDER BY i.tablename, i.indexname), '[]'::jsonb)
        FROM (
          SELECT tablename, indexname, indexdef
          FROM pg_indexes WHERE schemaname = 'public'
        ) i
        """,
    )
    constraints = _query_one(
        conn,
        """
        SELECT COALESCE(jsonb_agg(to_jsonb(c) ORDER BY c.table_name, c.constraint_name), '[]'::jsonb)
        FROM (
          SELECT tc.table_name, tc.constraint_name, tc.constraint_type,
                 pg_get_constraintdef(pc.oid) AS definition
          FROM information_schema.table_constraints tc
          JOIN pg_constraint pc ON pc.conname = tc.constraint_name
          JOIN pg_namespace pn ON pn.oid = pc.connamespace AND pn.nspname = 'public'
          WHERE tc.table_schema = 'public'
        ) c
        """,
    )
    return {
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "constraints": constraints,
    }


def _table_rows(conn: Any, table: str) -> Any:
    if table not in REQUIRED_TABLES:
        raise AssertionError(f"unreviewed snapshot table: {table}")
    return _query_one(
        conn,
        f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM {table} t",
    )


def _content_snapshot(conn: Any) -> dict[str, Any]:
    tables = (
        "phase20_settings",
        "phase20_kv",
        "trading_universe_sources",
        "trading_universes",
        "trading_universe_members",
        *sorted(PROHIBITED_HISTORY_TABLES),
    )
    return {table: _table_rows(conn, table) for table in dict.fromkeys(tables)}


def _audit_unique_order(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(att.attname ORDER BY ord.ordinality)
            FROM pg_constraint con
            JOIN LATERAL unnest(con.conkey) WITH ORDINALITY ord(attnum, ordinality) ON true
            JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ord.attnum
            WHERE con.conrelid = 'trading_universe_audit_events'::regclass
              AND con.contype = 'u'
            GROUP BY con.oid
            HAVING array_agg(att.attname ORDER BY ord.ordinality)
                   = ARRAY['correlation_id', 'action']::name[]
            """
        )
        row = cur.fetchone()
    if not row:
        raise AssertionError("canonical UNIQUE(correlation_id, action) is absent")
    return list(row[0])


def _assert_clean_authority(conn: Any, snapshot: dict[str, Any]) -> None:
    actual_tables = set(_catalog_snapshot(conn)["tables"])
    missing = REQUIRED_TABLES - actual_tables
    if missing:
        raise AssertionError(f"bootstrap schema missing tables: {sorted(missing)}")
    if not PROTECTED_TABLES.issubset(actual_tables):
        raise AssertionError("protected table chain is incomplete")
    if _audit_unique_order(conn) != ["correlation_id", "action"]:
        raise AssertionError("canonical audit uniqueness order changed")

    for table in PROHIBITED_HISTORY_TABLES:
        if snapshot[table]:
            raise AssertionError(f"historical rows were fabricated in {table}")
    universes = snapshot["trading_universes"]
    if len(universes) != 1:
        raise AssertionError("exactly one reconstructed current universe is required")
    universe = universes[0]
    expected = {
        "id": 3,
        "universe_key": "CUSTOM_LOW_PRICE_SECTOR",
        "version": 1,
        "status": "ACTIVE",
        "enabled_symbol_count": 23,
        "exact_set_hash": "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016",
    }
    for key, value in expected.items():
        if universe.get(key) != value:
            raise AssertionError(f"universe {key} differs: {universe.get(key)!r}")
    members = snapshot["trading_universe_members"]
    symbols = sorted(row["symbol"] for row in members if row["enabled"])
    if len(symbols) != 23:
        raise AssertionError(f"expected 23 enabled members, got {len(symbols)}")
    digest = hashlib.sha256("\n".join(symbols).encode("utf-8")).hexdigest()
    if digest != expected["exact_set_hash"]:
        raise AssertionError("canonical member set hash differs")
    sectors = {"BANK": 0, "INFRA": 0, "IT": 0}
    for row in members:
        sectors[row["sector"]] = sectors.get(row["sector"], 0) + 1
    if sectors != {"BANK": 9, "INFRA": 13, "IT": 1}:
        raise AssertionError(f"canonical sector counts differ: {sectors}")

    settings = snapshot["phase20_settings"]
    if len(settings) != 1 or settings[0]["data"].get("auto_paper_entries") is not False:
        raise AssertionError("fail-closed Phase20 settings are absent")
    kv = {row["key"]: row["value"] for row in snapshot["phase20_kv"]}
    if "kite_token_v1" in kv:
        raise AssertionError("real or synthetic Kite token row is forbidden")
    if kv.get("task978za_clean_authority_v1", {}).get("authority_class") != "CLEAN_RECONSTRUCTED_AUTHORITY":
        raise AssertionError("clean-authority provenance is absent")


def run(source_url: str) -> dict[str, Any]:
    identity = derive_validation_identity(source_url)
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import psycopg
        import task978r_clean_authority as bootstrap_module
    finally:
        if sys.path[0] == str(SCRIPT_DIR):
            sys.path.pop(0)

    created = False
    evidence: dict[str, Any] = {
        "status": "STARTED",
        "validation_database": identity.validation_database,
        "task976_access": 0,
        "zeabur_application_db_apply": "NOT_PERFORMED",
    }
    maintenance = psycopg.connect(identity.maintenance_url, autocommit=True)
    try:
        with maintenance.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, current_setting('server_version_num')::int")
            database, user, version_num = cur.fetchone()
            if database != "postgres" or user != identity.user or version_num // 10000 != 16:
                raise AssertionError("maintenance service is not the exact PostgreSQL 16 CI identity")
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (identity.validation_database,))
            if cur.fetchone():
                raise AssertionError("disposable validation database already exists; refusing to overwrite")
            cur.execute(f'CREATE DATABASE "{identity.validation_database}"')
            created = True

        bootstrap_module.bootstrap(
            identity.validation_url,
            purpose="TASK978ZA_NATIVE_PG16",
            acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
        )
        with psycopg.connect(identity.validation_url) as conn:
            catalog_first = _catalog_snapshot(conn)
            content_first = _content_snapshot(conn)
            _assert_clean_authority(conn, content_first)

        bootstrap_module.bootstrap(
            identity.validation_url,
            purpose="TASK978ZA_NATIVE_PG16",
            acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
        )
        with psycopg.connect(identity.validation_url) as conn:
            catalog_second = _catalog_snapshot(conn)
            content_second = _content_snapshot(conn)
            _assert_clean_authority(conn, content_second)

        if catalog_first != catalog_second:
            raise AssertionError("second bootstrap changed the PostgreSQL catalog")
        if content_first != content_second:
            raise AssertionError("second bootstrap changed clean-authority content")
        evidence.update({
            "status": "PASS",
            "postgresql_major": 16,
            "required_table_count": len(REQUIRED_TABLES),
            "protected_tables": "PASS",
            "audit_unique_order": ["correlation_id", "action"],
            "first_bootstrap": "PASS",
            "second_bootstrap_idempotency": "PASS",
            "catalog_fingerprint": _sha256(catalog_first),
            "content_fingerprint": _sha256(content_first),
            "historical_fabrication": 0,
            "runtime_side_effects": 0,
        })
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return evidence
    finally:
        if created:
            with maintenance.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (identity.validation_database,),
                )
                cur.execute(f'DROP DATABASE "{identity.validation_database}"')
        maintenance.close()


def main() -> int:
    source_url = os.environ.get("TASK967_TEST_DATABASE_URL", "")
    try:
        evidence = run(source_url)
    except Exception as exc:
        print(f"TASK978ZA NATIVE BOOTSTRAP: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    print("TASK978ZA NATIVE BOOTSTRAP: PASS")
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
