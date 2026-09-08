# Task #941 — Account for Every Pre-Open Universe Symbol

## Executive summary

Task #941 completed the observability and provenance work required to account
for every symbol in a Phase 5A pre-open collection attempt.

The collection pipeline now creates immutable, symbol-level outcome evidence
for the entire resolved active universe. Provider responses are never silently
treated as complete, and incomplete or unreliable data cannot be promoted to a
certified `MATCH` or frozen batch.

The implementation was independently reviewed and the completion validation
passed. Task #941 is complete and merged.

## Original problem

The historical natural-session result for `preopen-2026-08-26-ccb21a` showed
only 3 collected and persisted symbols out of 23 expected:

- `COALINDIA`
- `GAIL`
- `NTPC`

The active universe was `CUSTOM_LOW_PRICE_SECTOR` with 23 symbols. The primary
root cause was a provider-scope defect: the NSE adapter used the hard-coded
query key `NIFTY` while collecting a custom universe. That restricted provider
scope could not prove coverage for the requested 23-symbol universe.

The old behavior also lacked complete durable evidence for symbols that were
missing, omitted, malformed, duplicated, unavailable, or rejected during
normalization. As a result, a partial response could be difficult to audit and
could not safely distinguish “not returned” from “not requested.”

## Scope and safety boundaries

This work was intentionally limited to observability, provenance, and
certification evidence.

### Explicitly included

- Provider query scope and cache isolation.
- Per-symbol collection outcomes.
- Coverage accounting.
- Timestamp and liveness provenance.
- Persistence and freeze certification gates.
- Failure-path auditability.
- Regression tests and audit documentation.

### Explicitly excluded

- Readiness authority changes.
- Trading or execution logic changes.
- Portfolio or capital changes.
- Universe membership changes.
- Provider fallback policy changes beyond the required NSE scope fix.
- Settings changes.
- Production data repair.
- Retrying, replaying, backfilling, or rewriting the August 26 session.

Automatic paper entries, bootstrap mode, controlled execution, and live broker
orders remain disabled.

## Implemented changes

### 1. NSE provider scope is forced to `ALL`

The custom-universe NSE collection path now explicitly uses provider scope
`ALL`. A restricted key such as `NIFTY` cannot override the requested custom
universe path.

The provider cache is also isolated by query scope so that a response obtained
for one scope cannot be reused as if it represented another scope.

### 2. Every expected symbol receives an outcome

After resolving the active universe, the collector creates one immutable
outcome for every expected symbol in the collection batch.

Examples of observable outcomes include:

- `LIVE_PREOPEN_DATA`
- `NO_PREOPEN_DATA`
- `PROVIDER_UNAVAILABLE`
- `COLLECTION_PROCESSING_FAILED`
- Normalization, omission, duplicate, malformed-row, or unexpected-symbol
  outcomes

These outcomes are evidence only. A complete outcome matrix is necessary for
auditability but is not, by itself, sufficient to certify a collection.

### 3. Missing data never becomes a fabricated snapshot

The system does not synthesize price rows for symbols that are absent from the
provider response or fail normalization.

Instead:

- The missing symbol remains represented in the outcome matrix.
- No fabricated `PreOpenSnapshot` row is created.
- Coverage is marked incomplete.
- Certification remains blocked.

### 4. Provider failures retain the original collection batch

Provider initialization, provider selection, and health-check failures now use
the same collection batch that was created for the attempt.

Once the active universe is resolved, a provider failure persists:

- The original `collection_batch_id`.
- The exact expected symbol set.
- One `PROVIDER_UNAVAILABLE` outcome per expected symbol.
- Coverage metadata showing that no usable provider rows were collected.

This prevents a generic error handler from silently creating a replacement
batch with no symbol-level evidence.

### 5. Post-resolution failures retain exact-batch evidence

Failures after provider collection are also accounted for. This includes
exceptions during:

- Analytics enrichment.
- Snapshot serialization.
- Collection processing.
- Persistence.

These failures produce `COLLECTION_PROCESSING_FAILED` outcomes for all expected
symbols under the original collection batch ID. The system no longer falls
back to an error-only record that loses the expected universe and batch
context.

### 6. NSE timestamps are interpreted as Asia/Kolkata time

NSE `lastUpdateTime` values are wall-clock timestamps in IST/Asia/Kolkata, for
example:

```text
29-Jul-2026 09:07:00
```

They were previously interpreted as UTC, which could make a genuinely stale
pre-open row appear to be from the future and therefore appear fresh.

The current behavior is fail-closed:

- A timestamp is parsed as Asia/Kolkata.
- `age >= 300` seconds is stale.
- A missing timestamp is stale.
- A malformed timestamp is stale.
- A future-dated timestamp is stale.

Regression examples:

- `09:07 IST` observed at `09:15 IST` is 480 seconds old and stale.
- `09:10 IST` observed at `09:15 IST` is exactly 300 seconds old and stale.
- `09:16 IST` observed at `09:15 IST` is future-dated and stale.

### 7. `MATCH` and freeze require explicit live evidence

Certification now requires all of the following:

1. Exact expected/live/persisted symbol parity.
2. Complete durable outcome coverage.
3. Explicit `is_stale = false`.
4. Explicit `source_status = LIVE`.
5. No missing or unknown liveness metadata.
6. A matching collection batch ID.
7. Outcomes that support the same exact batch.

Missing liveness fields are not treated as healthy by default. Stale,
future-dated, non-live, or incomplete rows block certification.

The freeze path independently rechecks the evidence rather than relying only
on the earlier persistence result.

## Files changed

### Provider and collection engine

- `artifacts/api-server/src/python/nse_preopen_provider.py`
  - Forces custom-universe scope to `ALL`.
  - Isolates cache behavior by provider query scope.
  - Adds collection evidence and outcome reporting.
  - Parses NSE timestamps as Asia/Kolkata.
  - Fails closed for missing, malformed, stale, or future timestamps.

- `artifacts/api-server/src/python/preopen_engine.py`
  - Resolves the expected universe before provider work.
  - Produces complete outcomes for provider and processing failures.
  - Preserves the original collection batch ID through all failure paths.
  - Passes coverage and outcomes into persistence and failure recording.

- `artifacts/api-server/src/python/preopen_db.py`
  - Adds durable `preopen_collection_outcomes` storage.
  - Canonicalizes and inserts immutable per-symbol outcomes.
  - Requires complete outcome evidence and explicit live-row evidence for
    `MATCH`.
  - Reads collection outcomes for audit and freeze validation.

- `artifacts/api-server/src/python/preopen_scheduler.py`
  - Requires exact outcome coverage for freeze.
  - Rejects stale, non-live, missing, or unknown liveness evidence.
  - Prevents incomplete batches from being treated as certified.

### Tests

- `artifacts/api-server/src/python/tests/test_preopen_universe_coverage.py`
  - Restricted-scope coverage.
  - Partial provider responses.
  - Unavailable providers.
  - Missing outcome evidence.
  - Provider health and initialization exceptions.
  - Enrichment/post-resolution exception accounting.

- `artifacts/api-server/src/python/tests/test_preopen_lifecycle_truth.py`
  - Durable lifecycle and persistence invariants.
  - Exact batch and outcome evidence.
  - Stale and missing-liveness rejection behavior.

- `artifacts/api-server/src/python/test_preopen_multi_provider.py`
  - Multi-provider behavior.
  - NSE scope and normalization behavior.
  - IST timestamp parsing and stale-boundary regressions.

### Audit artifacts

- `TASK_940_PHASE5A_3_OF_23_ROOT_CAUSE.md`
- `TASK_940_SYMBOL_OUTCOME_MATRIX.csv`
- `TASK_940_PROVIDER_ELIGIBILITY_CONTRACT.md`
- `TASK_940_FIX_AND_TEST_REPORT.md`
- `TASK_940_NEXT_NATURAL_SESSION_GATE.md`
- `TASK_941_DETAILED_SUMMARY.md` — this report

## Validation evidence

### Focused Python suites

| Suite | Result |
|---|---:|
| Universe coverage | 21 passed |
| Lifecycle and persistence truth | 19 passed |
| Multi-provider behavior | 52 passed |
| Combined focused total | 92 passed |

The final completion review also reported that the broader pre-open validation
covered 268 passing tests.

### Static and runtime checks

- Python modules compiled successfully.
- Configured TypeScript validation had passed.
- `git diff --check` passed.
- The API workflow rebuilt and restarted successfully.
- API startup logs showed the server listening on port 8080.
- The API live-health endpoint returned HTTP 200.
- The read-only `/api/preopen/status` check returned `ENABLED`.
- The dashboard browser smoke test completed without console or page errors.
- No collection, retry, freeze, replay, or production repair was invoked while
  performing the final checks.

## Production-session handling

The August 26 session remains immutable:

```text
preopen-2026-08-26-ccb21a
```

The historical 3-of-23 result was not retried, replayed, backfilled, repaired,
or rewritten. It remains incomplete evidence and does not become certified as a
result of this implementation.

The latest successful scheduled market scan identifier was preserved as:

```text
4354dd7cf3d3
```

The approved production build context before this task was:

```text
Commit: fa612a219c2ca2aa682e5af58b051e2da4425c16
Build:  apexquant-fa612a219c2c
```

## Operational gate for the next natural session

The next eligible NSE pre-open session should be used for operational evidence.
The expected validation sequence is:

1. Resolve the configured active universe.
2. Confirm the provider request uses scope `ALL`.
3. Confirm every expected symbol receives exactly one durable outcome.
4. Confirm normalized rows contain real provider evidence only.
5. Confirm current rows include explicit liveness metadata.
6. Confirm expected, live, and persisted symbol sets match exactly.
7. Confirm the collection batch reaches `MATCH` only when all gates pass.
8. Confirm freeze is withheld for any missing, stale, future-dated, non-live, or
   incomplete evidence.

No operational retry or repair should be performed against the immutable
August 26 session.

## Related task status

- **Task #941:** merged and complete.
- **Task #942:** merged. It clarifies the Pre-Open UI so a session-level
  “Frozen” state cannot imply that an empty or incomplete collection batch was
  certified.
- **Task #943:** cancelled as redundant after the Task #942 UI correction.

Task #942 was reported as merged at commit:

```text
ba3727403d45c8bdec6a25eebaf3236da859727c
```

## Final verdict

**Task #941 is complete and ready for the next natural eligible NSE-session
validation.**

The implementation now provides complete, immutable, fail-closed accounting
for every expected pre-open universe symbol without changing the historical
session or enabling trading behavior.