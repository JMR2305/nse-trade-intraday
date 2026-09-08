# RTV-3D — Test Reconciliation and Clean Release Scope

**Date:** 2026-08-25 (Asia/Kolkata)  
**Final result:** **PASS**

## Clean candidate

The approved release was built from the production base:

```text
BASE = 2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832
BRANCH = release/task918-phase5a-coverage-clean
APPROVED_DEPLOY_COMMIT = 9f83f6764e3861e351e6334070d4031a85818876
EXPECTED_BUILD_ID = apexquant-9f83f6764e38
```

The candidate contains exactly 10 files:

### Task #918 runtime/schema/status model

- `artifacts/api-server/src/python/config.py`
- `artifacts/api-server/src/python/preopen_db.py`
- `artifacts/api-server/src/python/preopen_engine.py`
- `artifacts/api-server/src/python/preopen_intelligence_tick.py`
- `artifacts/api-server/src/python/preopen_provider_manager.py`
- `artifacts/api-server/src/python/preopen_scheduler.py`

### Task #918 tests

- `artifacts/api-server/src/python/test_preopen_multi_provider.py`
- `artifacts/api-server/src/python/tests/test_preopen_lifecycle_truth.py`
- `artifacts/api-server/src/python/tests/test_preopen_universe_coverage.py`

### Approved RTV‑2E test reconciliation

- `artifacts/api-server/src/python/test_daily_session_and_pipeline_e2e.py`

The RTV‑2E change is assertion-only. It replaces an exact total-call assertion
with checks for the date-specific `session_init_open_alert:` key and the
coexisting `system_heartbeat:` key. No runtime file was changed by that
reconciliation.

There are zero unrelated runtime files and zero unrelated tests in the
approved release commit. It contains no Mission Control, dashboard identity,
deployment-script, state, strategy, entry, broker, portfolio, ledger, or
universe-membership changes.

## Task #918 fix presence

The release implements and tests:

1. durable active-universe resolution before provider selection;
2. exact requested-symbol propagation;
3. provider-cache isolation by normalized requested symbol set;
4. fail-closed behavior instead of default-watchlist substitution for an
   unreadable or explicitly custom durable setting;
5. `COVERAGE_INCOMPLETE` for partial or malformed collections;
6. expected, returned, normalized, missing, duplicate, malformed, and
   unexpected coverage evidence;
7. complete expected coverage as a prerequisite for a verified batch; and
8. exact persisted-vs-expected symbol identity before freeze.

## Test gate

| Suite | Result |
|---|---:|
| Phase 5A engine/lifecycle/provider/scheduler/persistence/coverage | **169 passed** |
| Phase 20 safety | **62 passed** |
| Daily session and pipeline | **27 passed** |
| Canonical portfolio/pre-check | **32 passed** |
| Readiness/overnight-entry safety | **67 passed** |
| Scan history/status/custom universe | **89 passed + 10 subtests** |
| API build | **Passed** |
| API and workspace TypeScript | **Passed** |
| Python compilation | **Passed** |

One deprecation warning for `datetime.utcnow()` was observed; there were no
test failures.

## Schema check

The production schema diff is additive-only:

```sql
ALTER TABLE "preopen_sessions" ADD COLUMN "expected_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "provider_returned_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "normalized_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "missing_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "duplicate_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "malformed_count" integer;
ALTER TABLE "preopen_sessions" ADD COLUMN "collection_coverage" jsonb;
```

No `DROP`, `TRUNCATE`, table recreation, column removal, schema removal, or
historical evidence rewrite was proposed. Structural data loss and
backwards-compatibility warnings were both false.

## Verdict

**RTV‑3D clean scope and test reconciliation: PASS.**