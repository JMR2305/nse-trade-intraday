# RTV-3A — Fix and Test Report

**Date:** 2026-08-25 (Asia/Kolkata)  
**Result:** Source repair complete; next-session validation remains required.  
**Deployment:** Not performed.

## Delivered repair

- Phase 5A now resolves and passes the active custom-universe symbol set into
  provider construction for health, status, and scheduled collection.
- Any unreadable durable universe setting, or empty/unavailable custom
  membership, fails closed instead of reverting to the ten-symbol default
  watchlist. The legacy default path applies only after a readable durable
  non-custom decision.
- Provider cache reuse is isolated by normalized requested-symbol set.
- Durable collection proof now records expected/returned/normalized/missing/
  duplicate/malformed coverage facts and accepts `MATCH` only for exact,
  one-to-one full-universe coverage.
- Coverage is derived from the canonical serialized rows that will be stored;
  blank/duplicate snapshot IDs and serialized-symbol mismatches are rejected.
  Freeze independently compares the immutable batch's canonical symbol set to
  the durable expected set.
- Partial responses are `COVERAGE_INCOMPLETE`, retryable, and unable to create
  a verified-batch pointer or pass freeze/reconciliation gates.
- The latest-session read model exposes the durable coverage fields to status
  consumers. Historical rows are not rewritten; their new fields remain null.
- Focused regression tests cover the full 23-symbol request, empty custom
  universe, partial 10-of-23 response, malformed/duplicate/unexpected rows,
  provider-cache isolation, immutable collection evidence, and freeze blocking.

## Validation results

| Check | Result |
| --- | --- |
| Phase 5A engine, scheduler, lifecycle, provider, and new coverage suite | 169 passed |
| API Python syntax compilation for changed modules | Passed |
| Durable SQL parameter/placeholder coverage check | Passed |
| Phase 20 settings and safety suite | 62 passed |
| Daily session/pipeline lifecycle suite | 27 passed |
| Portfolio pre-check and canonical portfolio suite | 32 passed |
| Live-readiness and overnight-entry-safety suite | 67 passed |
| Scan history/status and custom-universe suite | 89 passed, 10 subtests passed |
| API build | Passed |
| API TypeScript check | Passed |
| Workspace TypeScript check | Passed |
| API workflow restart | Passed; listening on port 8080 |
| Read-only browser/API smoke | Passed; `/api/preopen/health` and `/api/preopen/status` returned HTTP 200 and advisory status without action calls |
| Independent safety review | Passed after fail-closed authority and serialized-row/freeze-set hardening |

## Known unrelated validation observation

`tests/test_v43_entry_gates.py` has 19 pre-existing expectation failures when
run in an isolated process (for example, it expects several operator overrides
that the current entry-gate defaults do not honor). It was not edited because
this task changes neither entry-gate behavior nor safety settings.

Running that suite after other legacy tests in one shared pytest process adds
further failures because an earlier test replaces `phase20_store` in
`sys.modules`. This is a test-harness isolation issue, not a Phase 5A runtime
failure. The Phase 20 and live-readiness entry-safety suites listed above pass
in isolated processes.

## Safety preservation

- Active universe membership remains the same 23-symbol custom set.
- All 23 production mappings remained valid during read-only diagnosis.
- Automatic entries remain disabled and unconfirmed.
- Bootstrap remains disabled.
- Automatic exits remain enabled.
- Execution mode remains paper trading and live broker placement remains
  disabled.
- Capital, canonical portfolio, six closed ledger rows, and the failed
  production session/batch were not modified.
- No manual scan, manual pre-open collection, lifecycle trigger, retry,
  portfolio reset, or deployment was performed.