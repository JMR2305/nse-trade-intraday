# Observability Hardening Final Release Report

**Date:** August 25, 2026  
**Release scope:** Current-price provenance and future manual-scan audit observability  
**Instructed release base:** `cafc2c18a99fc6e0affe61afb9fac29c3c3251ee`  
**Current workspace head:** `b87312cb3ca5e5e991cc987cf6d9c49abe211c77`  
**Approved deploy commit:** Not created  
**Final verdict:** **B. FRONTEND TEST FAILURE — DEPLOYMENT BLOCKED**

## Decision

The observability-hardening batch is not approved for deployment. The corrected
provenance code and all task-scoped validation gates pass, but the required full
dashboard suite still has 71 unrelated failures. A zero-failure suite is the
release requirement, so neither an approved deployment commit nor a publish
action was created.

## Delivered observability safeguards

- Current quote provider, actual recorded quote timestamp, freshness, historical
  OHLCV provider, fallback/synthetic/unavailable counts, and scan origin remain
  distinct on Mission Control.
- A closed market displays `MARKET CLOSED / LAST KNOWN` only when there is a
  recorded quote timestamp. A scan completion timestamp is never presented as
  a quote timestamp.
- Historical OHLCV provenance is derived only from fields recorded in the
  canonical scan; the spot-quote service is not treated as OHLCV evidence.
- Future manual scans persist only allowlisted, server-shaped audit identifiers
  and explicit actor/source/approval context. Recovery and backfill activity is
  classified as internal diagnostic work, not as a manual scan.
- Legacy manual rows remain immutable and are shown as provenance unavailable
  when their original evidence is incomplete.

## Validation record

| Gate | Result | Evidence |
| --- | --- | --- |
| Focused market-data, scheduler, and Kite regressions | PASS | `68 passed` |
| Custom-universe regression | PASS | `14 passed` |
| Focused Mission Control provenance tests | PASS | `20 passed` |
| API scan-cache invalidation regression | PASS | `13 passed` |
| Python compilation | PASS | Modified provenance modules compiled successfully |
| Dashboard/API/workspace TypeScript | PASS | Configured workspace typecheck completed successfully |
| Dashboard production build | PASS | Completed with existing sourcemap, dynamic-import, and bundle-size warnings only |
| Browser smoke check | PASS | After the API restart, Mission Control rendered the visible provenance block without console or backend errors. Missing current-quote evidence visibly rendered as `UNAVAILABLE / NOT PROVEN`; no mutating controls were used |
| Independent architecture/security review | PASS after correction | Review confirmed the timestamp and OHLCV provenance defects were corrected, including the closed-market no-timestamp case, and found no scope breach |
| Diff and schema safety | PASS | No schema or migration files changed; no destructive SQL or historical-row rewrite found |
| Full dashboard Vitest suite | BLOCKED / FAILING RELEASE GATE | `49` files passed, `2` failed; `925` tests passed, `71` failed in unrelated freshness-coverage and AI Validation heading contracts |
| Deployment identity verification | Not applicable | No approved deployment commit or publish action exists |

## Changed runtime and validation files

- `artifacts/api-server/src/routes/trading.ts`
- `artifacts/api-server/src/python/main.py`
- `artifacts/api-server/src/python/market_data_health.py`
- `artifacts/api-server/src/python/phase20_scheduler.py`
- `artifacts/api-server/src/python/phase20_store.py`
- `artifacts/api-server/src/python/scan_state_store.py`
- `artifacts/api-server/src/python/tests/unit/test_market_data_health.py`
- `artifacts/api-server/src/python/tests/unit/test_task857_job_classification.py`
- `artifacts/trading-dashboard/src/pages/MissionControl.tsx`
- `artifacts/trading-dashboard/src/pages/MissionControl.custom-universe.test.tsx`
- `artifacts/trading-dashboard/package.json`

The remaining workspace changes are task documentation, durable provenance
notes, and an incidental artifact-metadata entry; they do not affect runtime
behavior.

## Safety and post-deployment checklist

No deployment occurred, so the post-deployment checklist is intentionally not
asserted. Before any future controlled deployment, verify read-only that:

- UI and API build identities match;
- the visible provenance block reports only recorded provider/timestamp evidence;
- future manual scan audit fields appear while legacy scan `e1ded4dfba2e`
  remains unchanged and unavailable where evidence is absent;
- the active custom universe has 23 symbols with 23/23 mappings when that mode
  is selected;
- automatic entries and bootstrap are false, controlled execution is disabled,
  and live broker orders remain disabled;
- portfolio and ledger values are unchanged; and
- Task #930 evidence has not been created, changed, or backfilled by this work.

## Required next step

Task #936 owns the unrelated dashboard failures. It must restore a zero-failure
dashboard suite before a new deployment decision can be considered.