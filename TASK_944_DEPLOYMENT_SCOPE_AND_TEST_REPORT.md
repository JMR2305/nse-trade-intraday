# Task #944 — Deployment Scope and Test Report

## Scope

This report verifies the source and test gates for the merged Task #941
pre-open outcome-accounting work and Task #942 collection-certification UI
clarification.

It does **not** trigger a pre-open collection, Phase 5B/5C lifecycle action,
manual market scan, retry, replay, backfill, settings change, universe change,
portfolio mutation, or broker order.

## Source and merge state

| Item | Result |
|---|---|
| Current branch | `release/task918-phase5a-coverage-clean` |
| Current HEAD / deployment candidate | `356da659ea636a1c39dc8a379bbb5947ce492ac7` |
| Task #942 merge commit | `ba3727403d45c8bdec6a25eebaf3236da859727c` |
| Task #942 ancestry | Present as an ancestor of `HEAD` |
| Final Task #941/#942 runtime-change commit | `ba3727403d45c8bdec6a25eebaf3236da859727c` |
| Uncommitted runtime changes | None |

There are no uncommitted runtime-source changes. Validation temporarily
refreshed timestamps and fixture IDs in three static historical report outputs;
those generated differences were restored before the deployment gate. The
user-supplied Task #944 brief and these Task #944 reports are documentation
only and are not runtime source changes or part of the deployment candidate.

`HEAD` is a documentation-only descendant of Task #942. There are no runtime
file changes between `ba372740…` and `356da659…`, so the approved source
candidate is:

```text
APPROVED_DEPLOY_COMMIT = 356da659ea636a1c39dc8a379bbb5947ce492ac7
EXPECTED_BUILD_ID      = apexquant-356da659ea63
```

## Runtime source scope

### Task #941 runtime files

- `artifacts/api-server/src/python/nse_preopen_provider.py`
- `artifacts/api-server/src/python/preopen_db.py`
- `artifacts/api-server/src/python/preopen_engine.py`
- `artifacts/api-server/src/python/preopen_scheduler.py`

### Task #942 runtime/UI files

- `artifacts/trading-dashboard/src/pages/PreOpenIntelligence.tsx`
- `artifacts/trading-dashboard/src/pages/PreOpenIntelligence.test.tsx`

### Supporting tests and static audit artifacts

- `artifacts/api-server/src/python/test_preopen_multi_provider.py`
- `artifacts/api-server/src/python/tests/test_preopen_lifecycle_truth.py`
- `artifacts/api-server/src/python/tests/test_preopen_universe_coverage.py`
- Static historical reports under
  `artifacts/api-server/src/python/reports/`

No trading execution, broker-order, portfolio, ledger, universe-membership, or
operator-settings runtime file is part of the Task #941/#942 merge range.

## Source proof of the root-cause fix

| Required invariant | Source result |
|---|---|
| Active custom universe resolves 23 symbols | PASS — production readiness payload and resolved expected-set contract identify `CUSTOM_LOW_PRICE_SECTOR`, count 23. |
| NSE collection scope is `ALL` | PASS — `_preopen_key()` returns `ALL`. |
| Hard-coded `NIFTY` cannot override custom collection | PASS — custom-universe scope helper has no external restricted-key override. |
| Provider cache includes query scope | PASS — `_data_cache_key` is compared against the requested key before a cached response is reused. |
| Each expected symbol gets one durable outcome | PASS — canonical outcome set is persisted per session/batch/symbol. |
| Missing provider rows never become price snapshots | PASS — the provider emits metadata outcomes and only normalizes real rows. |
| Incomplete coverage cannot return `MATCH` | PASS — persistence requires exact outcome and live-snapshot parity. |
| Freeze independently rechecks evidence | PASS — scheduler reads the exact verified batch, outcome matrix, liveness, and `LIVE` evidence before freeze. |
| NSE timestamps use Asia/Kolkata | PASS — timestamp parser is explicit and fails stale for missing, malformed, future, or `age >= 300` values. |
| Failure paths preserve the original batch | PASS — provider initialization, health, fetch, enrichment, serialization, and processing exceptions write exact-batch failure outcomes. |

## Test gate

| Gate | Command/result |
|---|---|
| Broader pre-open suite | **312 passed** |
| Readiness + Phase 20 suite | **221 passed**, one pre-existing deprecation warning only |
| Portfolio/ledger regressions | **139 passed**, one pre-existing deprecation warning only |
| Python compilation | PASS — `python -m compileall -q .` |
| Dashboard test suite | **52 files / 1,002 tests passed** |
| Task #942 page tests | PASS — included in dashboard suite |
| Dashboard production build | PASS with `PORT=24210 BASE_PATH=/trading-dashboard/` |
| API and workspace TypeScript | PASS |
| Git whitespace check | PASS in the preceding Task #941 completion validation |

The first dashboard build attempt omitted the artifact-required `PORT`
environment variable. The same build passed when run with the production
artifact values above. This was a command-environment issue, not a source
failure.

## Read-only UI verification

The current-source Pre-Open Intelligence page was opened without any
collection action. Its visible state distinguishes:

- **Session Phase** (for example, `NO_SESSION` / `FROZEN`), from
- **Collection Batch** (`Not certified` unless the API provides complete,
  matching durable proof).

For an empty/no-session display, the page explicitly says:

> Collection batch is not certified. No durable pre-open session exists for
> the displayed trading date.

This satisfies Task #942's requirement that an empty or incomplete collection
cannot visually imply a successful certified freeze.

## Schema safety

The development-to-production schema diff contains one additive table:

```sql
CREATE TABLE "preopen_collection_outcomes" (
  "session_id" text NOT NULL,
  "collection_batch_id" text NOT NULL,
  "symbol" text NOT NULL,
  "outcome_status" text NOT NULL,
  "reason_code" text NOT NULL,
  "provider_symbol" text,
  "provider_response_present" boolean DEFAULT false NOT NULL,
  "normalization_result" text,
  "eligibility_status" text,
  "snapshot_id" text,
  "provider_scope" text,
  "provider_raw_count" integer,
  "created_at" timestamp with time zone DEFAULT now(),
  CONSTRAINT "preopen_collection_outcomes_pkey"
    PRIMARY KEY("session_id","collection_batch_id","symbol")
);

ALTER TABLE "preopen_collection_outcomes"
  ADD CONSTRAINT "preopen_collection_outcomes_session_id_fkey"
  FOREIGN KEY ("session_id")
  REFERENCES "public"."preopen_sessions"("session_id")
  ON DELETE no action ON UPDATE no action;

CREATE INDEX "idx_preopen_outcomes_session_batch"
  ON "preopen_collection_outcomes"
  USING btree ("session_id","collection_batch_id");
```

The schema tool reported:

- no tables to remove;
- no columns to remove;
- no truncations;
- no materialized views or schemas to remove;
- no structural data loss; and
- no backwards-compatibility warning.

This SQL must be applied only by Replit's Publish flow. No direct production
DDL, custom migration script, startup migration, or historical-row rewrite is
approved.

## Pre-publish verdict

**PRE-PUBLISH SOURCE/TEST/SCHEMA GATE: PASS**

The source candidate is ready for controlled publication. The current
production runtime remains on the earlier `fa612a21…` build and must not be
called deployed-compliant until it reports the approved commit and build ID.