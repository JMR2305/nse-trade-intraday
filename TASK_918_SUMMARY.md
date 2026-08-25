# Task #918 — Restore Phase 5A Universe Coverage

**Status:** Merged and complete  
**Objective:** Restore safe, exact Phase 5A collection for the 23-symbol
`CUSTOM_LOW_PRICE_SECTOR` universe while preserving paper-trading safeguards.

## Root cause

The scheduled Phase 5A collector selected a provider without passing the active
symbol list. The provider manager consequently used the legacy ten-symbol
`DEFAULT_WATCHLIST` instead of the durable 23-symbol custom universe.

The provider cache also was not isolated by requested symbol set, so a cached
ten-symbol provider could be reused by a later custom-universe request.

The original production evidence recorded 10 provider rows and 10 persisted
rows, which proved only 10/10 persistence parity—not complete 23-symbol
coverage. The headline shortfall was 13 symbols. Exact identity comparison
showed 22 custom symbols missing and 9 unexpected legacy-watchlist symbols,
with only WIPRO shared between the two sets.

## Implemented repair

- Resolve the durable active universe before provider selection.
- Pass the resolved symbol set through health, status, and collection paths.
- Fail closed when durable settings or custom membership are empty, malformed,
  or unavailable. Environment defaults cannot override an indeterminate durable
  setting.
- Preserve the legacy default-watchlist path when a readable durable setting
  explicitly selects a non-custom mode.
- Key provider caching by the normalized requested symbol set.
- Persist expected, returned, normalized, missing, duplicate, malformed,
  unexpected, and per-symbol coverage evidence.
- Validate the exact serialized rows that will be stored, including canonical
  symbols and unique snapshot IDs.
- Mark partial collections as `COVERAGE_INCOMPLETE`; they remain retryable and
  cannot create a verified batch or pass freeze.
- Require freeze to compare the persisted symbol set exactly with the durable
  expected symbol set, not just compare row counts.
- Expose the durable coverage fields through the latest-session status model.

## Validation

- Phase 5A engine, lifecycle, provider, scheduler, persistence, and coverage
  suite: **169 passed**
- Phase 20 safety suite: **62 passed**
- Daily session and pipeline suite: **27 passed**
- Portfolio pre-check and canonical portfolio suite: **32 passed**
- Live-readiness and overnight-entry-safety suite: **67 passed**
- Scan history/status and custom-universe suite: **89 passed, 10 subtests**
- API build, API TypeScript check, workspace TypeScript check, and Python
  compilation: **passed**
- Read-only browser/API smoke test: `/api/preopen/health` and
  `/api/preopen/status` returned HTTP 200 with `PAPER / ADVISORY ONLY`
- Final independent safety review: **passed**

## Safety preserved

- Automatic paper entries remain disabled and unconfirmed.
- Bootstrap remains disabled.
- Automatic exits remain enabled.
- Execution remains paper-only.
- Live broker order placement remains disabled.
- Capital, portfolio, ledger, universe membership, and preserved RTV-3
  production evidence were not modified.
- No manual scan, retry, lifecycle trigger, simulated data, portfolio reset,
  or production deployment was performed.

## Evidence files

- `RTV3A_PHASE5A_10_OF_23_ROOT_CAUSE.md`
- `RTV3A_SYMBOL_COVERAGE_MATRIX.csv`
- `RTV3A_PROVIDER_CONTRACT.md`
- `RTV3A_FIX_AND_TEST_REPORT.md`
- `RTV3A_NEXT_NATURAL_SESSION_GATE.md`

## Next step

Task #920 tracks validation during the next naturally scheduled NSE session.
That validation must use the exact gate in
`RTV3A_NEXT_NATURAL_SESSION_GATE.md`; the failed production batch must not be
manually replayed or mutated.