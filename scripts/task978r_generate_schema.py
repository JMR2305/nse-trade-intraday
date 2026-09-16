#!/usr/bin/env python3
"""Generate the reviewable Task978R schema/provenance manifests statically.

No application module is imported.  The extractor symbolically evaluates only
literal assignments, loops and SQL execute-call arguments in source ASTs.
Unresolved DDL is a hard failure.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "artifacts" / "api-server" / "src" / "python"
SQL_OUT = ROOT / "scripts" / "task978r_application_authority_schema.sql"
MANIFEST_OUT = ROOT / "scripts" / "task978r_clean_authority_manifest.json"
MIGRATIONS = (
    ROOT / "lib/db/migrations/0000_initial_baseline.sql",
    ROOT / "lib/db/migrations/0001_alert_deliveries.sql",
    ROOT / "lib/db/migrations/0002_universe_authority_schema_parity.sql",
)
CANONICAL_SYMBOLS = (
    "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
    "KTKBANK", "MAHABANK", "PNB", "UNIONBANK", "COALINDIA", "GAIL",
    "HUDCO", "IRCON", "IRFC", "MRPL", "NBCC", "NMDC", "NTPC", "PFC",
    "RECLTD", "RVNL", "SAIL", "WIPRO",
)
CANONICAL_SET_HASH = "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"

DDL_MARKERS = (
    "CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX",
    "CREATE OR REPLACE FUNCTION", "CREATE TRIGGER", "ALTER TABLE", "DO $$",
)


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DDL:
    sql: str
    source: str
    line: int


UNKNOWN = object()


def _literal(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, UNKNOWN)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values = [_literal(item, env) for item in node.elts]
        if UNKNOWN in values:
            return UNKNOWN
        return tuple(values)
    if isinstance(node, ast.Dict):
        keys = [_literal(item, env) for item in node.keys]
        values = [_literal(item, env) for item in node.values]
        if UNKNOWN in keys or UNKNOWN in values:
            return UNKNOWN
        return dict(zip(keys, values))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left, env), _literal(node.right, env)
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                resolved = _literal(value.value, env)
                if resolved is UNKNOWN:
                    return UNKNOWN
                parts.append(str(resolved))
            else:
                return UNKNOWN
        return "".join(parts)
    return UNKNOWN


def _bind(target: ast.AST, value: Any, env: dict[str, Any]) -> None:
    if isinstance(target, ast.Name):
        env[target.id] = value
    elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
        if len(target.elts) != len(value):
            raise ExtractionError("loop unpacking length mismatch")
        for child, child_value in zip(target.elts, value):
            _bind(child, child_value, env)


def _is_execute(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr in {
        "execute", "executescript"
    }


def _walk_statements(
    statements: Iterable[ast.stmt],
    env: dict[str, Any],
    *,
    source: pathlib.Path,
    out: list[DDL],
    unresolved: list[str],
) -> None:
    for statement in statements:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value_node = statement.value
            value = _literal(value_node, env) if value_node is not None else UNKNOWN
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if value is not UNKNOWN:
                for target in targets:
                    _bind(target, value, env)
        if isinstance(statement, ast.For):
            values = _literal(statement.iter, env)
            if values is not UNKNOWN:
                for value in values:
                    child = dict(env)
                    _bind(statement.target, value, child)
                    _walk_statements(statement.body, child, source=source, out=out, unresolved=unresolved)
            else:
                _walk_statements(statement.body, dict(env), source=source, out=out, unresolved=unresolved)
            _walk_statements(statement.orelse, dict(env), source=source, out=out, unresolved=unresolved)
            continue
        # Process only the call owned by this statement.  Compound statements
        # are walked below with their correctly bound loop environment; using
        # ast.walk() here would inspect their children too early and report
        # resolvable f-strings as unresolved.
        calls = []
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            if _is_execute(statement.value):
                calls.append(statement.value)
        for call in calls:
            if not call.args:
                continue
            value = _literal(call.args[0], env)
            segment = ast.get_source_segment(source.read_text(encoding="utf-8"), call.args[0]) or ""
            might_be_ddl = any(marker in segment.upper() for marker in DDL_MARKERS)
            if value is UNKNOWN:
                if might_be_ddl:
                    unresolved.append(f"{source.relative_to(ROOT)}:{call.lineno}: {segment[:160]}")
                continue
            if isinstance(value, str) and any(marker in value.upper() for marker in DDL_MARKERS):
                out.append(DDL(textwrap.dedent(value).strip(), str(source.relative_to(ROOT)), call.lineno))
        nested: list[list[ast.stmt]] = []
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nested.append(statement.body)
        elif isinstance(statement, ast.If):
            nested.extend((statement.body, statement.orelse))
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            nested.append(statement.body)
        elif isinstance(statement, ast.Try):
            nested.extend([statement.body, statement.orelse, statement.finalbody])
            nested.extend(handler.body for handler in statement.handlers)
        for body in nested:
            _walk_statements(body, dict(env), source=source, out=out, unresolved=unresolved)


def extract_runtime_ddl() -> list[DDL]:
    records: list[DDL] = []
    unresolved: list[str] = []
    for path in sorted(PYTHON_ROOT.rglob("*.py")):
        relative_parts = path.relative_to(PYTHON_ROOT).parts
        if path.name.startswith("test_") or "tests" in relative_parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "CREATE TABLE" not in text.upper():
            continue
        # PostgreSQL modules either connect directly or reuse a shared
        # PostgreSQL connection helper.  Pure sqlite modules are local-only
        # authorities and are intentionally outside this bootstrap.
        pure_sqlite = (
            ("import sqlite3" in text or "from sqlite3" in text)
            and "psycopg" not in text
            and "DATABASE_URL" not in text
        )
        if pure_sqlite:
            continue
        tree = ast.parse(text, filename=str(path))
        env: dict[str, Any] = {}
        literal_ddl: list[DDL] = []
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value_node = node.value
                value = _literal(value_node, env) if value_node is not None else UNKNOWN
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value is not UNKNOWN:
                    for target in targets:
                        _bind(target, value, env)
                    if isinstance(value, str) and any(
                        marker in value.upper() for marker in DDL_MARKERS
                    ):
                        literal_ddl.append(DDL(
                            textwrap.dedent(value).strip(),
                            str(path.relative_to(ROOT)),
                            node.lineno,
                        ))
        records.extend(literal_ddl)
        _walk_statements(tree.body, env, source=path, out=records, unresolved=unresolved)
    if unresolved:
        raise ExtractionError("unresolved PostgreSQL DDL:\n" + "\n".join(sorted(set(unresolved))))
    unique: dict[tuple[str, str], DDL] = {}
    for record in records:
        canonical = re.sub(r"\s+", " ", record.sql).strip().lower()
        unique.setdefault((canonical, record.source), record)
    return sorted(unique.values(), key=lambda item: (item.source, item.line, item.sql))


def _split_migration(sql: str) -> list[str]:
    return [part.strip() for part in re.split(
        r"^\s*-->\s*statement-breakpoint\s*$", sql, flags=re.M
    ) if part.strip()]


def _normalize_additive(sql: str) -> str:
    sql = textwrap.dedent(sql)
    sql = re.sub(r"--.*?$", "", sql, flags=re.M).strip().rstrip(";")
    sql = "\n".join(line.rstrip() for line in sql.splitlines())
    sql = re.sub(
        r"(?i)^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE TABLE IF NOT EXISTS ", sql,
    )
    sql = re.sub(
        r"(?i)^CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)",
        lambda m: "CREATE " + (m.group(1) or "") + "INDEX IF NOT EXISTS ", sql,
    )
    constraint = re.fullmatch(
        r"(?is)ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ADD\s+CONSTRAINT\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)",
        sql,
    )
    if constraint:
        table, name, definition = constraint.groups()
        sql = (
            "DO $$\nBEGIN\n"
            "    IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN\n"
            f"        ALTER TABLE {table} ADD CONSTRAINT {name} {definition};\n"
            "    END IF;\nEND $$"
        )
    return sql + ";"


def _created_table(sql: str) -> str | None:
    match = re.search(
        r'(?i)CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        sql,
    )
    return match.group(1).lower() if match else None


def _created_tables(sql: str) -> set[str]:
    return {name.lower() for name in re.findall(
        r'(?i)CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        sql,
    )}


def _dependencies(sql: str) -> list[str]:
    return sorted(set(match.lower() for match in re.findall(
        r'(?i)REFERENCES\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', sql
    )))


def build() -> tuple[str, dict[str, Any]]:
    statements: list[DDL] = []
    for migration in MIGRATIONS:
        for index, chunk in enumerate(_split_migration(migration.read_text(encoding="utf-8")), 1):
            statements.append(DDL(_normalize_additive(chunk), str(migration.relative_to(ROOT)), index))
    migration_tables = {table for item in statements if (table := _created_table(item.sql))}
    runtime = extract_runtime_ddl()
    excluded_compatibility: list[dict[str, Any]] = []
    for item in runtime:
        normalized = _normalize_additive(item.sql)
        plain = re.sub(r"--.*?$|/\*.*?\*/", "", normalized, flags=re.M | re.S).upper()
        destructive = next((token for token in (
            "DROP ", "TRUNCATE ", "DELETE FROM", "RENAME COLUMN",
        ) if token in plain), None)
        if destructive:
            excluded_compatibility.append({
                "source": f"{item.source}:{item.line}",
                "reason": f"prohibited compatibility operation: {destructive.strip()}",
            })
            continue
        table = _created_table(normalized)
        if table and table in migration_tables:
            continue
        statements.append(DDL(normalized, item.source, item.line))

    deduped: list[DDL] = []
    seen: set[str] = set()
    for item in statements:
        canonical = re.sub(r"\s+", " ", item.sql).strip().lower()
        if canonical not in seen:
            deduped.append(item)
            seen.add(canonical)

    table_items = [item for item in deduped if _created_table(item.sql)]
    other_items = [item for item in deduped if not _created_table(item.sql)]
    ordered: list[DDL] = []
    available: set[str] = set()
    pending = list(table_items)
    while pending:
        progress = False
        for item in list(pending):
            table_name = _created_table(item.sql) or ""
            item_tables = _created_tables(item.sql)
            dependencies = set(_dependencies(item.sql)) - item_tables
            if dependencies.issubset(available | {t for t in migration_tables}):
                ordered.append(item)
                available.update(item_tables)
                pending.remove(item)
                progress = True
        if not progress:
            details = ", ".join(
                f"{_created_table(item.sql)}->{_dependencies(item.sql)}" for item in pending
            )
            raise ExtractionError("unresolved table dependency order: " + details)
    ordered.extend(other_items)

    blocks = [
        "-- Task978R deterministic application-authority schema.",
        "-- Generated statically; application modules are never imported.",
    ]
    objects: dict[tuple[str, str], dict[str, Any]] = {}
    for item in ordered:
        blocks.extend((
            "",
            f"-- source: {item.source}:{item.line}",
            item.sql,
            "--> bootstrap-breakpoint",
        ))
        patterns = (
            ("table", r'(?i)CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?'),
            ("index", r'(?i)CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?'),
            ("function", r'(?i)CREATE\s+OR\s+REPLACE\s+FUNCTION\s+"?([A-Za-z_][A-Za-z0-9_]*)"?'),
            ("trigger", r'(?i)CREATE\s+TRIGGER\s+"?([A-Za-z_][A-Za-z0-9_]*)"?'),
        )
        for kind, pattern in patterns:
            for name in re.findall(pattern, item.sql):
                key = (kind, name.lower())
                objects.setdefault(key, {
                    "kind": kind,
                    "name": name.lower(),
                    "owner": item.source,
                    "source": f"{item.source}:{item.line}",
                    "dependencies": _dependencies(item.sql),
                    "constraints": sorted(set(re.findall(
                        r"(?i)(PRIMARY\s+KEY|UNIQUE\s*\([^)]*\)|CHECK\s*\([^;]*?\)|REFERENCES\s+\"?[A-Za-z_][A-Za-z0-9_]*\"?)",
                        item.sql,
                    ))),
                    "indexes": [],
                })
    for obj in objects.values():
        if obj["kind"] == "index":
            match = re.search(
                rf'(?is)CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+"?{re.escape(obj["name"])}"?\s+ON\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
                "\n".join(blocks),
            )
            if match and ("table", match.group(1).lower()) in objects:
                objects[("table", match.group(1).lower())]["indexes"].append(obj["name"])

    manifest = {
        "authority_class": "CLEAN_RECONSTRUCTED_AUTHORITY",
        "historically_equivalent_to_replit_db": False,
        "generator": "scripts/task978r_generate_schema.py",
        "kite_token_authority": {"table": "phase20_kv", "key": "kite_token_v1"},
        "clean_seed_manifest": {
            "phase20_settings": {
                "auto_paper_entries": False,
                "auto_paper_entries_confirmed_at": None,
                "bootstrap_paper_enabled": False,
                "auto_paper_exits": True,
                "initial_capital": 100000.0,
            },
            "universe": {
                "universe_key": "CUSTOM_LOW_PRICE_SECTOR",
                "universe_id": 3,
                "version": 1,
                "status": "ACTIVE",
                "effective_from": "2026-08-31T03:30:00Z",
                "symbol_count": len(CANONICAL_SYMBOLS),
                "symbols": list(CANONICAL_SYMBOLS),
                "exact_set_hash": CANONICAL_SET_HASH,
                "sector_counts": {"BANK": 9, "INFRA": 13, "IT": 1},
            },
            "history_rows": 0,
            "kite_token_rows": 0,
        },
        "prohibited_historical_domains": [
            "phase20_paper_trades", "historical_ledger_rows",
            "historical_audit_events", "historical_scheduler_rows",
            "historical_certification_rows", "runtime_universe_session_pins",
            "historical_token_rows", "historical_validation_rows",
        ],
        "excluded_destructive_compatibility": excluded_compatibility,
        "objects": sorted(objects.values(), key=lambda obj: (obj["kind"], obj["name"])),
    }
    return "\n".join(blocks).rstrip() + "\n", manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    sql, manifest = build()
    if args.write:
        SQL_OUT.write_text(sql, encoding="utf-8")
        MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps({
            "sql_sha256": __import__("hashlib").sha256(sql.encode()).hexdigest(),
            "object_count": len(manifest["objects"]),
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
