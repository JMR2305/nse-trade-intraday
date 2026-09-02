#!/usr/bin/env python3
"""Task969-only identity proof and always-run report; standard library only."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TREE = 'c0653b1d0f26a9869bc86d70240cd96a2e54128c'
ALLOWED = {
    '.github/workflows/task969-postgres16-validation.yml',
    'scripts/task969_postgres_validation.py',
    'scripts/task969_ci_report.py',
    'scripts/test_task971_schema_order.py',
    'TASK_971_SCHEMA_ORDER_CORRECTION.md',
    'TASK_973_QUEUE_DIAGNOSTICS.json',
    'TASK_973_ROOT_CAUSE.md',
}
# Task971 explicitly authorizes only these byte-for-byte source corrections.
# The reviewed Task967 tree remains the historical anchor, not a moving target.
SOURCE_CORRECTIONS = {
    'lib/db/migrations/0002_universe_authority_schema_parity.sql': (
        'UNIQUE ("action", "correlation_id")', 'UNIQUE ("correlation_id", "action")'),
    'artifacts/api-server/src/python/universe_version_store.py': (
        'UNIQUE (action, correlation_id)', 'UNIQUE (correlation_id, action)'),
    'lib/db/scripts/reviewed-additive-sql.json': (
        '200fae443c28f58cae39e754795adc1eb48c194002a79a59c6c964207215f8a8',
        'b5cdba323db2ebbd425ed525142276a8f4ae6f6ec172d28e1a127680ae5bd6b9'),
}
# Task972/973 change only this integration-test setup and observation. Pin both complete blobs;
# do not permit arbitrary edits to the test or any additional source files.
TASK972_TEST_PATH = 'artifacts/api-server/src/lib/pushNotifier.test.ts'
TASK972_TEST_BLOBS = (
    '86b3bed734c1da10ea64ceb1cc209db9b324c304',
    'a0382b7ec1603306fb7ce7154d207299a963b4cd',
)
# Task973 permits the demonstrated queue-clock defect correction, not other
# runtime edits. Pin the entire before/after source blobs independently.
TASK973_QUEUE_PATH = 'artifacts/api-server/src/lib/alertQueue.ts'
TASK973_QUEUE_BLOBS = (
    'a04689aaeb6a3345a3e25d032725c0e4dfe7499d',
    'ecf2556ed072537590128d64bafd0f9a7e009530',
)


def verify_source_correction(path, before, after):
    old, new = SOURCE_CORRECTIONS[path]
    if before.count(old) != 1 or after != before.replace(old, new, 1):
        raise RuntimeError(f'Unexpected Task971 source edit: {path}')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def identity():
    head = git('rev-parse', 'HEAD')
    if os.environ.get('GITHUB_SHA') and head != os.environ['GITHUB_SHA']:
        raise RuntimeError('Unexpected workflow HEAD')
    if os.environ.get('GITHUB_REF', 'refs/heads/task967-migration-guard-hardening') != 'refs/heads/task967-migration-guard-hardening':
        raise RuntimeError('Validation may run only on the review branch')
    ancestor = next((line.split()[0] for line in git('log', '--format=%H %T', 'HEAD').splitlines()
                     if line.split()[1] == TREE), None)
    if not ancestor:
        raise RuntimeError('Reviewed Task967 tree absent from ancestry')
    changed = git('diff', '--name-only', ancestor, head).splitlines()
    unexpected = set(changed) - ALLOWED - SOURCE_CORRECTIONS.keys() - {TASK972_TEST_PATH, TASK973_QUEUE_PATH}
    if unexpected:
        raise RuntimeError(f'Unexpected application/source changes: {unexpected}')
    test_blobs = (git('rev-parse', f'{ancestor}:{TASK972_TEST_PATH}'),
                  git('rev-parse', f'{head}:{TASK972_TEST_PATH}'))
    if test_blobs != TASK972_TEST_BLOBS:
        raise RuntimeError('Unexpected Task972 pushNotifier test content')
    queue_blobs = (git('rev-parse', f'{ancestor}:{TASK973_QUEUE_PATH}'),
                   git('rev-parse', f'{head}:{TASK973_QUEUE_PATH}'))
    if queue_blobs != TASK973_QUEUE_BLOBS:
        raise RuntimeError('Unexpected Task973 queue source content')
    corrections = {}
    for path in SOURCE_CORRECTIONS:
        before = git('show', f'{ancestor}:{path}')
        after = git('show', f'{head}:{path}')
        verify_source_correction(path, before, after)
        # Check raw git blobs as well; strip() must not mask trailing edits.
        raw_before = subprocess.check_output(['git', 'show', f'{ancestor}:{path}'], cwd=ROOT)
        raw_after = subprocess.check_output(['git', 'show', f'{head}:{path}'], cwd=ROOT)
        old, new = SOURCE_CORRECTIONS[path]
        if raw_after != raw_before.replace(old.encode(), new.encode(), 1):
            raise RuntimeError(f'Unexpected Task971 raw source edit: {path}')
        corrections[path] = {'before_blob': git('rev-parse', f'{ancestor}:{path}'),
                             'after_blob': git('rev-parse', f'{head}:{path}'),
                             'sha256': hashlib.sha256(raw_after).hexdigest()}
    if git('diff', '--name-only', 'HEAD'):
        raise RuntimeError('Tracked worktree differs from workflow HEAD')
    proof = {'workflow_head': head, 'reviewed_ancestor': ancestor,
             'reviewed_tree': git('rev-parse', f'{ancestor}^{{tree}}'), 'allowed_diff': changed,
             'task971_exact_source_corrections': corrections,
             'task972_exact_test_correction': {'path': TASK972_TEST_PATH,
                 'before_blob': test_blobs[0], 'after_blob': test_blobs[1]},
             'task973_exact_queue_correction': {'path': TASK973_QUEUE_PATH,
                 'before_blob': queue_blobs[0], 'after_blob': queue_blobs[1]}}
    (ROOT / 'TASK_969_IDENTITY.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))


def report():
    steps = json.loads(os.environ.get('TASK969_STEPS', '{}'))
    def outcome(name):
        return steps.get(name, {}).get('outcome', 'not executed')
    def load(name):
        p = ROOT / name
        return json.loads(p.read_text()) if p.exists() else {}
    proof = load('TASK_969_IDENTITY.json')
    evidence = load('TASK_969_POSTGRES_BEFORE_AFTER_EVIDENCE.json')
    unique = evidence.get('audit_unique_key', {})
    gates = ['identity', 'schema_order', 'pnpm', 'install', 'validator_deps', 'guard', 'offline', 'native', 'api_focused', 'api', 'python_deps', 'python_native', 'python', 'dashboard', 'typecheck', 'compile', 'api_build', 'dashboard_build']
    if outcome('schema_order') == 'failure' or unique.get('match') is False or evidence.get('status') == 'CATALOG_FAILURE':
        verdict = 'B. FAIL — CATALOG/SCHEMA INCOMPATIBILITY'
    elif outcome('guard') == 'failure' or outcome('offline') == 'failure':
        verdict = 'C. FAIL — MIGRATION GUARD'
    elif any(outcome(x) == 'failure' for x in ['native', 'api_focused', 'api', 'python_native', 'python', 'dashboard', 'typecheck', 'compile', 'api_build', 'dashboard_build']):
        verdict = 'D. FAIL — APPLICATION/DB TESTS'
    elif all(outcome(x) == 'success' for x in gates):
        verdict = 'A. PASS — READY FOR REVIEW, NO MERGE/DEPLOY PERFORMED'
    else:
        verdict = 'E. ENVIRONMENT/CI BLOCKER'
    guard = ROOT / 'task969-guard.log'
    totals = re.findall(r'# (?:tests|pass|fail) \d+', guard.read_text()) if guard.exists() else []
    lines = ['# TASK #969 — Final Report', '', f'**{verdict}**', '',
             f'- Workflow HEAD: `{proof.get("workflow_head", os.environ.get("GITHUB_SHA", "unknown"))}`',
             f'- Reviewed ancestor: `{proof.get("reviewed_ancestor", "not proven")}`',
             f'- Reviewed tree: `{proof.get("reviewed_tree", "not proven")}`',
             f'- Task971 exact source corrections: `{proof.get("task971_exact_source_corrections", "not proven")}`',
             f'- Task972 exact test correction: `{proof.get("task972_exact_test_correction", "not proven")}`',
             f'- PostgreSQL: `{evidence.get("server", {}).get("version", "not measured")}`',
             f'- Guard totals: `{totals}`',
             f'- Offline classification: `{outcome("offline")}` (see task969-offline.log)',
             f'- pg_catalog audit order: `{unique.get("pre_task964_catalog_order", "not measured")}`',
             f'- Migration-declared order: `{unique.get("candidate_migration_declared_order", "not measured")}`',
             f'- First migration: `{evidence.get("first_migration", "not executed")}`',
             f'- Second migration: `{evidence.get("second_migration", "not executed")}`', '',
             '| Gate | Outcome |', '| --- | --- |']
    lines.extend(f'| {name} | {outcome(name)} |' for name in gates)
    lines += ['', '## Row evidence', '', '| Table | Before count/hash | After first | After second |', '| --- | --- | --- | --- |']
    for table, before in (evidence.get('before') or {}).items():
        def snapshot(key):
            row = (evidence.get(key) or {}).get(table)
            return f'{row["row_count"]} / {row["sha256"]}' if row else 'not executed'
        lines.append(f'| {table} | {before["row_count"]} / {before["sha256"]} | {snapshot("after_first_migration")} | {snapshot("after_second_migration")} |')
    lines += ['', 'Only the disposable service was configured. No merge, deployment or production action.',
              'A catalog mismatch stops before migration and all downstream application gates.',
              'The native validator covers authority rows/catalogs; tests/integration provides additional DB integration. Mocked unit tests are not relabeled native tests.']
    (ROOT / 'TASK_969_FINAL_REPORT.md').write_text('\n'.join(lines) + '\n')
    for name, title in [('TASK_969_POSTGRES_CATALOG_PARITY.md', 'Catalog parity'), ('TASK_969_IDEMPOTENCY_REPORT.md', 'Idempotency')]:
        p = ROOT / name
        if not p.exists():
            p.write_text(f'# Task969 — {title}\n\nNOT EXECUTED / BLOCKED. See TASK_969_FINAL_REPORT.md.\n')
    if not (ROOT / 'TASK_969_POSTGRES_BEFORE_AFTER_EVIDENCE.json').exists():
        (ROOT / 'TASK_969_POSTGRES_BEFORE_AFTER_EVIDENCE.json').write_text(json.dumps({'status': 'NOT_EXECUTED', 'before': None, 'after_first_migration': None, 'after_second_migration': None}) + '\n')
    print(verdict)


if __name__ == '__main__':
    {'identity': identity, 'report': report}[sys.argv[1]]()
