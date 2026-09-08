# RTV-3C — Clean Task #918 Release Scope Report

**Date:** 2026-08-25 (Asia/Kolkata)  
**Scope verdict:** **PASS — unrelated runtime files isolated**  
**Release verdict:** **BLOCKED by test gate; no release commit created**

## Branch construction

| Field | Value |
| --- | --- |
| Release branch | `release/task918-phase5a-coverage` |
| Exact base | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Current production base | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Mixed source branch | `8317ae3cfad0f907d76cf903d90ee444d7cf9ebe` |
| Task #918 source commit inspected | `fc550ff3b728574fdfbd8f6326955e62312fbff4` |
| Candidate code diff | Contains only the selected Task #918 files; not yet committed |

The release branch was created from the exact production SHA. The Task #918
commit was not cherry-picked wholesale. Its approved runtime/test files were
selectively restored onto the production base so unrelated preceding commits
cannot enter the candidate.

## Candidate file classification

| File | Classification |
| --- | --- |
| `artifacts/api-server/src/python/config.py` | Task #918 runtime / durable universe authority |
| `artifacts/api-server/src/python/preopen_db.py` | Task #918 schema and status model |
| `artifacts/api-server/src/python/preopen_engine.py` | Task #918 runtime / coverage enforcement |
| `artifacts/api-server/src/python/preopen_intelligence_tick.py` | Task #918 runtime |
| `artifacts/api-server/src/python/preopen_provider_manager.py` | Task #918 runtime / cache isolation |
| `artifacts/api-server/src/python/preopen_scheduler.py` | Task #918 runtime / freeze gate |
| `artifacts/api-server/src/python/test_preopen_multi_provider.py` | Task #918 test |
| `artifacts/api-server/src/python/tests/test_preopen_lifecycle_truth.py` | Task #918 test fixture |
| `artifacts/api-server/src/python/tests/test_preopen_universe_coverage.py` | Task #918 test |

No Mission Control, dashboard build identity, deployment script, state file,
generic deployment configuration, strategy, entry, broker, portfolio, or
unrelated runtime file is present in the candidate code diff. The four RTV‑3C
reports are untracked documentation outputs and are not part of the candidate
code scope.

## Root-cause fix presence

The candidate contains all requested Task #918 behavior:

1. durable active-universe resolution before provider selection;
2. exact requested-symbol propagation;
3. provider-cache keys isolated by normalized requested symbol set;
4. no default-watchlist substitution for a readable custom mode or an
   indeterminate durable settings read;
5. `COVERAGE_INCOMPLETE` for partial collections;
6. expected/returned/normalized/missing/duplicate/malformed/unexpected
   coverage evidence;
7. complete expected coverage required for a verified batch; and
8. exact persisted-vs-expected symbol-set validation before freeze.

## Approved commit

No approved commit exists. The candidate was intentionally not committed
because the required test gate failed.

```text
APPROVED_DEPLOY_COMMIT = NOT CREATED
EXPECTED_BUILD_ID = NOT DEFINED
```