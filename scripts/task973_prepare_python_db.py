"""Initialize the fresh disposable fixture required by integration teardown.

Extract only the existing additive CREATE/ADD/INDEX declaration, without
importing application code or executing its legacy migration/pruning paths.
"""
import ast
from pathlib import Path

import psycopg

from task969_postgres_validation import get_database_url

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/api-server/src/python/src/portfolio/repositories/reconciliation.py'


def main():
    module = ast.parse(SOURCE.read_text())
    bootstrap = next(node for node in module.body
                     if isinstance(node, ast.FunctionDef) and node.name == '_ensure_schema')
    declarations = [node.value for node in ast.walk(bootstrap)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.strip().startswith('CREATE TABLE IF NOT EXISTS reconciliation_runs')]
    if len(declarations) != 1:
        raise RuntimeError('Expected exactly one canonical reconciliation declaration')
    declaration = declarations[0]
    # Fail closed if this fixture's known three additive statements change.
    statements = [part.strip() for part in declaration.split(';') if part.strip()]
    expected = ['CREATE TABLE IF NOT EXISTS reconciliation_runs (',
                'ALTER TABLE reconciliation_runs\n                ADD COLUMN IF NOT EXISTS report_payload JSONB',
                'CREATE INDEX IF NOT EXISTS idx_recon_runs_pid_time']
    if len(statements) != 3 or any(not sql.startswith(prefix)
                                 for sql, prefix in zip(statements, expected)):
        raise RuntimeError('Unexpected non-additive fixture declaration')
    import re
    if re.search(r'\b(DROP|TRUNCATE|DELETE|CASCADE)\b', declaration, re.I):
        raise RuntimeError('Destructive SQL forbidden in fixture setup')
    with psycopg.connect(get_database_url()) as conn:
        database, version = conn.execute(
            "SELECT current_database(), current_setting('server_version_num')::int").fetchone()
        if database != 'task967_disposable_task968' or version // 10000 != 16:
            raise RuntimeError('Only the named disposable PostgreSQL 16 service is accepted')
        conn.execute(declaration)
        print(f'Canonical reconciliation fixture schema ready in {database}; no data seeded or modified')


if __name__ == '__main__':
    main()
