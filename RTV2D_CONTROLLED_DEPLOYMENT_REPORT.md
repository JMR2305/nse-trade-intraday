# RTV-2D — Controlled Deployment Report

**Date:** 2026-08-25 (IST)  
**Verdict:** **E. TEST FAILURE — natural-session certification remains locked**

## Deployment identity

The source safety repair is already running in production. No additional publish
was performed during this gate.

| Field | Verified value |
| --- | --- |
| Environment | `production` |
| Deploy commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Expected build ID | `apexquant-2e54e5e2f23f` |
| Reported build ID | `apexquant-2e54e5e2f23f` |
| Deployment ID | Present |
| Runtime identity | Exact match |

The later workspace commit labelled “Published your App” contains no runtime
source changes after the deployed safety-repair commit.

## Source scope

Compared with the prior production commit
`393747a8102ee3fc8adaa36d60b6ed8db18bc4b8`, the runtime change set is limited
to:

- the daily-session manager;
- the Phase 20 command delegation;
- scheduler wording describing preserved entry state;
- the Phase 20 release-default settings;
- the durable Phase 20 settings store; and
- targeted Phase 20/bootstrap regression tests.

The change set confirms:

1. automatic paper entries default to `false`;
2. automatic-entry confirmation defaults to `null`;
3. daily initialization preserves state and cannot activate entries;
4. unavailable, unreadable, or malformed durable settings fail closed;
5. legacy daily activation delegates to the typed-confirmation Phase 22 flow.

The retained production base also contains the RTV-2A durable Phase 5A,
scan-origin, and observation-GET controls. No unrelated runtime trading change
was identified. No source diff contains `DROP`, `TRUNCATE`, a historical-ledger
rewrite, or a destructive schema operation.

## Schema safety

The development-to-production schema comparison returned:

- `hasDiff: false`
- zero statements to execute;
- no tables, columns, schemas, or materialized views to remove;
- no truncation;
- no structural data-loss or backward-compatibility warning.

## Required validation

Passing current checks include:

- Phase 20 settings/exits: **62 passed**
- execution-fix regression: **9 passed**
- entry cutoff/admission: **8 passed**
- bootstrap paper trade: **53 passed**
- bootstrap eligibility: **33 passed**
- bootstrap status: **40 passed**
- session restore: **17 passed**
- Phase 22 integration: **8 passed**
- Phase 5A pre-open validation: **55 passed**
- Phase 5A durability/read-safety: **15 passed**
- scan history/origin: **37 passed, 6 subtests**
- enriched scan status: **28 passed, 4 subtests**
- portfolio endpoint contract: **3 passed**
- canonical portfolio truth: **5 passed**
- ledger integrity: **15 passed**
- custom-universe store: **24 passed**
- portfolio restart/source/history/retention checks: **24 passed**
- API build and workspace TypeScript checks: **passed**

Two unchanged, pre-existing test expectations remain red:

1. `test_daily_session_and_pipeline_e2e.py::TestOpenAlert::test_run_tick_alerts_even_when_auto_scan_disabled` expects the mocked `kv_claim_once` helper to have one call, but the pre-existing production heartbeat also claims its own key. The heartbeat was introduced before the production baseline.
2. `test_phase22_session.py::EnvTokenExpiryTests::test_env_token_without_timestamp_trusted` expects a token supplied only through environment variables to be returned, while the unchanged current credential resolver fails closed.

The tests were not weakened and runtime safety was not changed to satisfy these
expectations. Accordingly, the full RTV-2D test gate is not green.

## Controlled-operation record

No production scan, pre-open lifecycle trigger, paper entry, bootstrap action,
broker order, portfolio reset, ledger rewrite, universe change, strategy change,
or threshold change was performed for RTV-2D.
