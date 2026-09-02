"""Offline Task971 regression checks; no application import or database access."""
import ast
import json
from pathlib import Path
import re
import subprocess
import unittest

from task969_ci_report import SOURCE_CORRECTIONS, verify_source_correction

ROOT = Path(__file__).resolve().parents[1]
PARENT = '865210ebc282a997ed1157515682faca21839912'
REVIEWED = 'c0653b1d0f26a9869bc86d70240cd96a2e54128c'
PYTHON_SCHEMA = 'artifacts/api-server/src/python/universe_version_store.py'
SQL = 'lib/db/migrations/0002_universe_authority_schema_parity.sql'
REGISTRY = 'lib/db/scripts/reviewed-additive-sql.json'


def audit_order(sql):
    table = re.search(r'CREATE TABLE(?: IF NOT EXISTS)?\s+"?trading_universe_audit_events"?\s*\(', sql)
    if not table:
        raise AssertionError('audit table declaration missing')
    unique = re.search(r'\bUNIQUE\s*\(([^)]+)\)', sql[table.end():])
    if not unique:
        raise AssertionError('audit unique constraint missing')
    return [x.strip().strip('"') for x in unique.group(1).split(',')]


class Task971SchemaOrder(unittest.TestCase):
    def test_historical_and_candidate_declarations_match(self):
        historical = subprocess.check_output(['git', 'show', f'{PARENT}:{PYTHON_SCHEMA}'], cwd=ROOT, text=True)
        self.assertEqual(audit_order(historical), ['correlation_id', 'action'])
        for path in [PYTHON_SCHEMA, SQL, 'scripts/task969_postgres_validation.py']:
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                if path.endswith('.py'):
                    declarations = [n.value for n in ast.walk(ast.parse(text))
                                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                                    and re.search(r'CREATE TABLE(?: IF NOT EXISTS)?\s+"?trading_universe_audit_events', n.value)]
                    self.assertEqual(len(declarations), 1)
                    text = declarations[0]
                self.assertEqual(audit_order(text), audit_order(historical))

    def test_only_exact_authorized_source_edits(self):
        for path in SOURCE_CORRECTIONS:
            with self.subTest(path=path):
                before = subprocess.check_output(['git', 'show', f'{REVIEWED}:{path}'], cwd=ROOT).decode()
                after = (ROOT / path).read_text()
                verify_source_correction(path, before, after)
                for invalid in [before, after + '\n', after + 'unrelated change']:
                    with self.assertRaises(RuntimeError):
                        verify_source_correction(path, before, invalid)

    def test_exactly_one_reviewed_fingerprint_replaced(self):
        before = json.loads(subprocess.check_output(['git', 'show', f'{REVIEWED}:{REGISTRY}'], cwd=ROOT))
        after = json.loads((ROOT / REGISTRY).read_text())
        self.assertEqual(len(before['statements']), len(after['statements']))
        changed = [(a, b) for a, b in zip(before['statements'], after['statements']) if a != b]
        self.assertEqual(len(changed), 1)
        old, new = changed[0]
        self.assertEqual(old['source'], Path(SQL).name)
        self.assertEqual(old['statement'], new['statement'])
        self.assertEqual((old['sha256'], new['sha256']), SOURCE_CORRECTIONS[REGISTRY])

    def test_guard_allows_correction_but_rejects_altered_declaration(self):
        js = '''
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {assertSafeMigration} from './lib/db/scripts/sql-classifier.mjs';
const sql=fs.readFileSync('lib/db/migrations/0002_universe_authority_schema_parity.sql','utf8');
assertSafeMigration(sql);
for (const replacement of ['UNIQUE ("action", "correlation_id")', 'UNIQUE ("correlation_id")', 'UNIQUE ("correlation_id", "action", "actor")']) {
  assert.throws(()=>assertSafeMigration(sql.replace('UNIQUE ("correlation_id", "action")', replacement)), /BLOCKED/);
}
assert.throws(()=>assertSafeMigration(sql+'; DROP TABLE trading_universe_audit_events CASCADE;'), /BLOCKED/);
'''
        subprocess.run(['node', '--input-type=module', '-e', js], cwd=ROOT, check=True)


if __name__ == '__main__':
    unittest.main()
