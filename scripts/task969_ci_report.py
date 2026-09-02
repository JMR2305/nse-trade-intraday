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
    'scripts/task973_prepare_python_db.py',
    'scripts/task974_collection_diagnostics.py',
    'TASK_974_ORIGINAL_COLLECTION_FAILURES.md',
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


# Task974 permits only these complete test-infrastructure blobs. A new test
# must be absent from the reviewed tree; existing tests pin both versions.
TASK974_TEST_BLOBS = {
    "artifacts/api-server/src/python/test_consecutive_blocks.py": [
        "cc4dda43dfa32c7fee79585db1f8e23bfc8305aa",
        "e0f21d56109778839d51927bb1a20e9251aea384"
    ],
    "artifacts/api-server/src/python/test_analytics_30plus_integration.py": [
        "a95fa4696921d4715e08b97d392f258ddb0d449e",
        "b83482ed4e93c852e900402a7d630b38caace820"
    ],
    "artifacts/api-server/src/python/ai_performance/test_ai_performance.py": [
        "d6ab9b98f20e9e9a10b24f8383af9fc054fd2d6f",
        "58b3ba0d155cf7c69ca6c528371c9007b88e454b"
    ],
    "artifacts/api-server/src/python/strategy_intelligence/test_strategy_intelligence.py": [
        "29e5ee13df4286652cb104a6d272f9e76e9a0ce9",
        "a7f163d06ceba5b920b4f5f5d0e5119009e024b6"
    ],
    "artifacts/api-server/src/python/test_phase9.py": [
        "d2e9e345a553c4e288e7fadac55340eb8093a402",
        "c817872bcb9351db3bcdb8cf68426f44592a623c"
    ],
    "artifacts/api-server/src/python/test_phase22_final.py": [
        "3dfc85b6502018382981a8df0a242c328ddde044",
        "ca83c6f3e5a62d84581488f4edc0ab381c472757"
    ],
    "artifacts/api-server/src/python/test_task974_import_isolation.py": [
        None,
        "763289ecddca51f169bd5da2168d4b20e706d060"
    ],
    "artifacts/api-server/src/python/test_event_intelligence.py": [
        "6fade4c4962c5de7c80a62b18d76814197609466",
        "364c04c9f158abd963230ddfd9a0152eff8dc14e"
    ],
    "artifacts/api-server/src/python/test_macro_intelligence.py": [
        "6162ee5823b98570a3ee289c6ca9add8cd83ff05",
        "de89883f856927658f390a43f953667e74aeed53"
    ],
    "artifacts/api-server/src/python/test_explainable_ai.py": [
        "632dd0050b55644161c74458bc5390b8fc8bed87",
        "1671c0af6e8074f66d2171a4fd464e9514385db6"
    ],
    "artifacts/api-server/src/python/test_research_lab.py": [
        "ab9d05fe923f288fa49ac4249185150f935263d9",
        "94995bc5006cf55b7028a4e8153d4d30ec66f5b9"
    ],
    "artifacts/api-server/src/python/test_phase18.py": [
        "ba75a7e2e160b0444e10f4108ff92fa1915358e9",
        "7018fafd6e4a7a7cf30657b8c0d9ca4ac2626b13"
    ],
    "artifacts/api-server/src/python/portfolio_performance/test_portfolio_performance.py": [
        "a24cb1bb417d89490fa5f5f6d50707f9c30c0771",
        "df6ceae721f0ba02927a9d1ae629f725cff845bf"
    ],
    "artifacts/api-server/src/python/tests/buy_audit_test.py": [
        "53d17107c62a587c512629d8efcd84cef46305ca",
        "d9d32bc5ab5b55253ab370bc89090242807da64f"
    ],
    "artifacts/api-server/src/python/tests/test_eod_reconciliation.py": [
        "30ac433adf337d7f9264833399df4167041265b2",
        "5eef663c3d175293b39c5611f900b48b8b860455"
    ],
    "artifacts/api-server/src/python/tests/test_phase20_startup_overnight_check.py": [
        "b82ccd74d19556091428d72a894b981f49359363",
        "8fe4758bcaaf25986b3eb5f9ce663eb6211a2d1c"
    ],
    "artifacts/api-server/src/python/tests/unit/test_size_reduced_to_cap.py": [
        "346684a657a352dedc054d85262306cad59a0d51",
        "de683b798236e0c7a3b4cdb6ac3515098f7d08a2"
    ],
    "artifacts/api-server/src/python/task974_test_isolation.py": [
        None,
        "08982b401da29d5e5e91a2281071ae96855591b0"
    ],
    "artifacts/api-server/src/python/task974_runtime_leak_diagnostics.py": [
        None,
        "2bb60b6d8f57b52ebf6d4e51643f06017e7a79e9"
    ],
    "artifacts/api-server/src/python/tests/test_ohlcv_cold_start_check.py": [
        "25bbb412e42b05125706f4434273db0b5e4a5c2c",
        "90abb892a2952eee02812bad497a5fe7fa3053d7"
    ],
    "artifacts/api-server/src/python/tests/unit/test_bootstrap_paper_trade.py": [
        "812c06d01e87ef32d4b74f1112f7e2f1c260e49b",
        "565595ed746e1c7d27465f8d95ad98a8a0b3fe03"
    ],
    "artifacts/api-server/src/python/tests/test_journey_execution_labels.py": [
        "ce45f9fa77d477d9f98a3f21b4501a419636045b",
        "1aaca25606bf181e8c7df09ee359d741149c1999"
    ],
    "artifacts/api-server/src/python/market_intelligence_hub/test_market_intelligence_hub.py": [
        "e66f393adbb186b27c00bd5764283ae1cd2bb0fb",
        "e167717c70b661f7af4f6f3ba8544d151d3a258c"
    ],
    "artifacts/api-server/src/python/research_lab/test_research_lab.py": [
        "bc60544b3950ea1c0cbc60a452f9ab842e43636f",
        "51235e8df74e9c3317801643f7eeea6e700a0c64"
    ],
    "artifacts/api-server/src/python/conftest.py": [
        None,
        "d5988b0e9a648fdbe9e5c8771102ddf335162c54"
    ],
    "artifacts/api-server/src/python/tests/test_balanced_decision.py": [
        "18fecde4d15d78c58905e7986d5b930aa2989b15",
        "9947f530ea6763c765a8950bbca9f3536d200fa8"
    ],
    "artifacts/api-server/src/python/tests/test_strategy_intelligence.py": [
        "e3dd80ddf645a22dffbef9e5cb7136c1e6ddd2fd",
        "75974caefb5c4b1224d194380a7f46541de487a8"
    ]
}


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
    unexpected = set(changed) - ALLOWED - SOURCE_CORRECTIONS.keys() - {TASK972_TEST_PATH, TASK973_QUEUE_PATH} - TASK974_TEST_BLOBS.keys()
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
    for path, (expected_before, expected_after) in TASK974_TEST_BLOBS.items():
        exists = subprocess.run(['git', 'cat-file', '-e', f'{ancestor}:{path}'], cwd=ROOT,
                                capture_output=True).returncode == 0
        before = git('rev-parse', f'{ancestor}:{path}') if exists else None
        after = git('rev-parse', f'{head}:{path}')
        if (before, after) != (expected_before, expected_after):
            raise RuntimeError(f'Unexpected Task974 test content: {path}')
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
    gates = ['identity', 'schema_order', 'pnpm', 'install', 'validator_deps', 'guard', 'offline', 'native', 'api_focused', 'api', 'python_deps', 'python_fixture', 'python_native', 'python', 'dashboard', 'typecheck', 'compile', 'api_build', 'dashboard_build']
    gates.append('python_isolation')
    if outcome('schema_order') == 'failure' or unique.get('match') is False or evidence.get('status') == 'CATALOG_FAILURE':
        verdict = 'B. FAIL — CATALOG/SCHEMA INCOMPATIBILITY'
    elif outcome('guard') == 'failure' or outcome('offline') == 'failure':
        verdict = 'C. FAIL — MIGRATION GUARD'
    elif any(outcome(x) == 'failure' for x in ['native', 'api_focused', 'api', 'python_native', 'python_isolation', 'python', 'dashboard', 'typecheck', 'compile', 'api_build', 'dashboard_build']):
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
