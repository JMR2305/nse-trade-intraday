# Task 940 — fix and test report

## Minimal implementation

The change is deliberately limited to Phase 5A collection observability and
provider scope:

1. Replaced the NSE provider's hard-coded `key=NIFTY` request with a forced
   `key=ALL` for this custom-universe collection path.
2. Made the NSE in-memory response cache query-key-aware.
3. Added provider collection evidence: raw response count, query scope, and a
   concrete symbol outcome for every requested symbol.
4. Added the immutable `preopen_collection_outcomes` storage table, keyed by
   session, collection batch, and symbol.
5. Persisted outcomes transactionally with real snapshot candidates.
6. Added outcome evidence to no-data and provider-unavailable paths.
7. Added a freeze-time exact outcome-set and explicit freshness check. It
   requires all expected symbols to have non-stale `LIVE_PREOPEN_DATA` plus
   durable `is_stale=false` and `source_status=LIVE` row evidence; explicit
   no-data remains observable but cannot certify a partial batch.
8. Corrected NSE `lastUpdateTime` parsing from a false UTC interpretation to
   Asia/Kolkata; an absent/invalid or future timestamp, or `age >= 300`, is
   stale.
9. Preserved exact-batch failure evidence for all post-universe-resolution
   exceptions, including enrichment, serialization, and persistence failures.

No readiness, trade decision, portfolio, broker, scan, universe, provider
fallback, settings, or Task 930 evidence was changed.

## New regression coverage

- Default provider scope is `ALL`.
- Provider evidence distinguishes a normalized row from a requested symbol
  absent from the raw response.
- Partial provider responses retain one outcome for every expected symbol.
- Provider health/fetch unavailability retains one outcome for every expected
  symbol.
- Snapshot and outcome persistence occur in the same collection transaction.
- Freeze rejects a batch whose snapshot counts match but whose outcome matrix
  is incomplete.

## Validation run

All commands passed on 2026-08-26:

| Validation | Result |
|---|---|
| `python -m unittest discover -s tests -p 'test_preopen_universe_coverage.py'` | 21 passed |
| `python -m unittest discover -s tests -p 'test_preopen_lifecycle_truth.py'` | 19 passed |
| `python test_preopen_multi_provider.py` | 52 passed |
| Core pre-open engine safety suite | passed |
| Pre-open intelligence scheduler suite | passed |
| Pre-open accuracy suite | passed |
| Pre-open validation suite | passed |
| Pre-open validation tick suite | passed |
| Phase 20 paper-trading suite | passed |
| Portfolio pre-check event suite | passed |
| Configured workspace TypeScript validation | passed |
| Read-only Pre-Open Intelligence browser smoke test | passed; page rendered with no console or page errors |

The only console note was an existing Python `utcnow()` deprecation warning in
`phase3f_logging.py`; it is unrelated to this scope.

The browser smoke test intentionally did not click a collection, retry, scan,
freeze, or other mutating control. It displayed the historical session's
zero-symbol state without a frontend crash.

## Remaining production evidence

The August 26 session is immutable and remains incomplete. The repaired path
must be observed during the next natural eligible NSE pre-open session. See
`TASK_940_NEXT_NATURAL_SESSION_GATE.md`.