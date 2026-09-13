"""Offline Task971 regression checks; no application import or database access."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import task969_ci_report as ci_report
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


class Task978CandidateIdentity(unittest.TestCase):
    """Exercise the identity gate using real reviewed Git history.

    Read-only Git overrides model proposed committed mutations without creating
    commits or changing the checkout. Only the proof output is redirected.
    """

    CANDIDATE = '18b775da0858061f39d62ede89c2984ab6342e58'
    ANCESTOR = 'ce294619cb39fe9fa9a5051aff0933766e21081b'
    TASK976_PATHS = (
        'TASK976_ZB5R4_DIAGNOSTIC_EVIDENCE.md',
        'TASK976_ZB5_2VCPU_CAPACITY_BOUNDARY.md',
        'scripts/task976_zb5_node_probe.mjs',
        'scripts/task976_zb5_runner.py',
        'scripts/task976_zb5_timing_and_evidence_test.py',
        'scripts/task976_zb5_worker.py',
        'scripts/task976_zeabur_benchmark.py',
        'scripts/task976_zeabur_fixture.py',
        'scripts/test_task976_zb5_runner.py',
        'scripts/test_task976_zb5_worker.py',
        'scripts/test_task976_zeabur_benchmark.py',
        'scripts/test_task976_zeabur_fixture.py',
    )

    def run_identity(self, *, extra=(), overrides=None, env=None):
        overrides = overrides or {}
        real_git = ci_report.git
        real_write = Path.write_text

        def read_git(*args):
            if args in overrides:
                return overrides[args]
            if args == ('rev-parse', 'HEAD'):
                return self.CANDIDATE
            if args == ('diff', '--name-only', 'HEAD'):
                # Model the clean CI checkout; separately test dirty rejection.
                return ''
            result = real_git(*args)
            if args == ('diff', '--name-only', self.ANCESTOR, self.CANDIDATE):
                return '\n'.join([result, *extra])
            return result

        with tempfile.TemporaryDirectory(prefix='task978-identity-') as directory:
            proof_path = Path(directory) / 'identity.json'

            def write_proof(path, content, *args, **kwargs):
                target = proof_path if path == ROOT / 'TASK_969_IDENTITY.json' else path
                return real_write(target, content, *args, **kwargs)

            environment = {
                'GITHUB_SHA': self.CANDIDATE,
                'GITHUB_REF': 'refs/heads/task967-migration-guard-hardening',
                **(env or {}),
            }
            with patch.dict(os.environ, environment), \
                    patch.object(ci_report, 'git', side_effect=read_git), \
                    patch.object(Path, 'write_text', write_proof), \
                    contextlib.redirect_stdout(io.StringIO()):
                ci_report.identity()
            return json.loads(proof_path.read_text())

    def test_exact_reviewed_candidate_is_accepted(self):
        proof = self.run_identity()
        self.assertEqual(proof['workflow_head'], self.CANDIDATE)
        self.assertEqual(proof['reviewed_ancestor'], self.ANCESTOR)
        self.assertTrue(set(self.TASK976_PATHS) <= set(proof['allowed_diff']))

    def test_task978e2_fixture_is_exactly_blob_pinned(self):
        path = 'artifacts/api-server/src/python/tests/unit/test_task857_job_classification.py'
        expected = f'100644 blob ee56ecec998cb6a3c033cf67b3ba2f5048bbc17f\t{path}'
        proof = self.run_identity()
        self.assertEqual(proof['task978e2_exact_test_fixture'], {
            'reviewed_commit': '01cb043b484d0233a169724651343713a6ed278d',
            'path': path,
            'blob': 'ee56ecec998cb6a3c033cf67b3ba2f5048bbc17f',
        })
        self.assertEqual(ci_report.git('ls-tree', self.CANDIDATE, '--', path), expected)

    def test_task978e2_fixture_content_change_and_deletion_are_rejected(self):
        path = 'artifacts/api-server/src/python/tests/unit/test_task857_job_classification.py'
        for entry in ['', f'100644 blob {"0" * 40}\t{path}']:
            with self.subTest(entry=entry), self.assertRaisesRegex(RuntimeError, 'Unexpected Task978E2'):
                self.run_identity(overrides={
                    ('ls-tree', self.CANDIDATE, '--', path): entry,
                })

    def test_task978e2_reviewed_commit_must_remain_in_candidate_lineage(self):
        with self.assertRaisesRegex(RuntimeError, 'Task978E2 reviewed commit absent from ancestry'):
            self.run_identity(overrides={('rev-list', 'HEAD'): self.ANCESTOR})

    def test_task978e2_allowance_is_not_a_wildcard(self):
        self.assertEqual(set(ci_report.TASK978E2_REVIEWED_BLOBS), {
            'artifacts/api-server/src/python/tests/unit/test_task857_job_classification.py'
        })
        with self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
            self.run_identity(extra=[
                'artifacts/api-server/src/python/tests/unit/test_task857_unreviewed.py'
            ])

    def test_task978j_fixture_is_exactly_blob_pinned(self):
        path = 'artifacts/api-server/src/python/test_task482_trades.py'
        blob = '70e34d14bcaa419c0ca50e16d7e784207cda69ae'
        expected = f'100644 blob {blob}\t{path}'
        proof = self.run_identity()
        self.assertEqual(proof['task978j_exact_test_fixture'], {
            'reviewed_commit': self.CANDIDATE,
            'path': path,
            'blob': blob,
        })
        self.assertEqual(ci_report.git('ls-tree', self.CANDIDATE, '--', path), expected)

    def test_task978j_fixture_content_mode_and_deletion_are_rejected(self):
        path = 'artifacts/api-server/src/python/test_task482_trades.py'
        blob = '70e34d14bcaa419c0ca50e16d7e784207cda69ae'
        for entry in ['', f'100644 blob {"0" * 40}\t{path}',
                      f'100755 blob {blob}\t{path}', f'120000 blob {blob}\t{path}']:
            with self.subTest(entry=entry), self.assertRaisesRegex(RuntimeError, 'Unexpected Task978J'):
                self.run_identity(overrides={
                    ('ls-tree', self.CANDIDATE, '--', path): entry,
                })

    def test_task978j_reviewed_commit_must_remain_in_candidate_lineage(self):
        with self.assertRaisesRegex(RuntimeError, 'Task978J reviewed commit absent from ancestry'):
            self.run_identity(overrides={
                ('rev-list', 'HEAD'): ci_report.TASK978E2_REVIEWED_COMMIT,
            })

    def test_task978j_allowance_is_not_a_wildcard(self):
        self.assertEqual(set(ci_report.TASK978J_REVIEWED_BLOBS), {
            'artifacts/api-server/src/python/test_task482_trades.py'
        })
        with self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
            self.run_identity(extra=[
                'artifacts/api-server/src/python/test_task482_trades_unreviewed.py'
            ])

    def test_arbitrary_application_addition_or_edit_is_rejected(self):
        for path in ['artifacts/api-server/src/task978_unreviewed.ts',
                     'artifacts/api-server/src/index.ts']:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
                self.run_identity(extra=[path])

    def test_unreviewed_migration_and_schema_files_are_rejected(self):
        for path in ['lib/db/migrations/9999_unreviewed.sql',
                     'lib/db/src/schema/task978_unreviewed.ts']:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
                self.run_identity(extra=[path])

    def test_broker_and_order_path_changes_are_rejected(self):
        for path in ['artifacts/api-server/src/routes/kite.ts',
                     'artifacts/api-server/src/routes/trading.ts']:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
                self.run_identity(extra=[path])

    def test_transfer_patch_is_never_accepted_as_committed_content(self):
        name = 'TASK976_ZB5R4_FREEBUFF_TRANSFER.patch'
        self.assertNotIn(name, self.run_identity()['allowed_diff'])
        with self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
            self.run_identity(extra=[name])

    def test_unknown_future_and_misspelled_files_are_rejected(self):
        for path in ['scripts/task976_future.py', 'TASK976_FUTURE.md',
                     'scripts/test_task976_zb5_timing_and_evidence_test.py']:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected application/source'):
                self.run_identity(extra=[path])

    def test_every_reviewed_task976_file_is_content_pinned(self):
        for path in self.TASK976_PATHS:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected Task976'):
                self.run_identity(overrides={
                    ('rev-parse', f'{self.CANDIDATE}:{path}'): '0' * 40,
                    ('ls-tree', self.CANDIDATE, '--', path): f'100644 blob {"0" * 40}\t{path}',
                })

    def test_task976_mode_type_and_deletion_changes_are_rejected(self):
        path = 'scripts/task976_zb5_runner.py'
        blob = '1f0507ad131816e2e12ca70999b1e2a799a7a704'
        for entry in ['', f'100755 blob {blob}\t{path}',
                      f'120000 blob {blob}\t{path}', f'040000 tree {blob}\t{path}']:
            with self.subTest(entry=entry), self.assertRaisesRegex(RuntimeError, 'Unexpected Task976'):
                self.run_identity(overrides={('ls-tree', self.CANDIDATE, '--', path): entry})

    def test_task976_additions_must_be_absent_from_historical_base(self):
        path = 'scripts/task976_zb5_runner.py'
        with self.assertRaisesRegex(RuntimeError, 'Unexpected Task976 file in reviewed base'):
            self.run_identity(overrides={
                ('ls-tree', self.ANCESTOR, '--', path): f'100644 blob {"0" * 40}\t{path}',
            })

    def test_task971_corrections_reject_additional_source_edits(self):
        for path in SOURCE_CORRECTIONS:
            after = ci_report.git('show', f'{self.CANDIDATE}:{path}')
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'Unexpected Task971'):
                self.run_identity(overrides={
                    ('show', f'{self.CANDIDATE}:{path}'): after + '\nunauthorized edit',
                })

    def test_task972_test_blob_and_task973_order_queue_remain_pinned(self):
        for path, label in [
            ('artifacts/api-server/src/lib/pushNotifier.test.ts', 'Task972'),
            ('artifacts/api-server/src/lib/alertQueue.ts', 'Task973'),
        ]:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, f'Unexpected {label}'):
                self.run_identity(overrides={
                    ('rev-parse', f'{self.CANDIDATE}:{path}'): '0' * 40,
                })

    def test_task974_test_blob_remains_pinned(self):
        path = 'artifacts/api-server/src/python/test_observability_center.py'
        with self.assertRaisesRegex(RuntimeError, 'Unexpected Task974'):
            self.run_identity(overrides={
                ('rev-parse', f'{self.CANDIDATE}:{path}'): '0' * 40,
            })

    def test_wrong_workflow_sha_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unexpected workflow HEAD'):
            self.run_identity(env={'GITHUB_SHA': '0' * 40})

    def test_wrong_branch_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'only on the review branch'):
            self.run_identity(env={'GITHUB_REF': 'refs/heads/main'})

    def test_missing_reviewed_ancestor_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'absent from ancestry'):
            self.run_identity(overrides={('log', '--format=%H %T', 'HEAD'): ''})

    def test_dirty_tracked_worktree_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Tracked worktree differs'):
            self.run_identity(overrides={('diff', '--name-only', 'HEAD'): 'scripts/task969_ci_report.py'})


if __name__ == '__main__':
    unittest.main()
