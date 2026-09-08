# Task 947 — Proposed Fix and Test Report

## Implemented minimal correction

1. The automatic pre-open intelligence tick now collects from 09:00 up to,
   but not including, 09:12 IST. It no longer collects at 09:12–09:14 during
   matching/transition.
2. Scheduler-origin collections explicitly persist as `SCHEDULED`; direct and
   refresh collections persist as `MANUAL`.
3. Freeze now requires the scheduled final-proof window (09:08–09:12 IST),
   a durable same-day completion time, and exact batch-ID identity in addition
   to the existing full-coverage, live-row, and immutable-outcome gates.
4. The normal 300-second NSE timestamp boundary is unchanged.

No deployment, production write, manual refresh, manual freeze, or revision of
Task 930 evidence occurred.

## New deterministic regression coverage

- automatic collection ends at 09:12 and marks its origin `SCHEDULED`;
- a 09:07:00 NSE timestamp is fresh at 09:11:59 (299 seconds) and stale at
  09:12:00 (300 seconds);
- a complete 23-symbol scheduled final batch freezes successfully;
- manual, invalid, future, cross-day, pre-window, and post-window batches do
  not freeze; and
- rows returned from a different batch ID do not freeze.

Existing tests also cover missing timestamps, future timestamps, stale rows,
partial/duplicate/malformed coverage, exact outcome accounting, and no
downstream freeze after a failed collection.

## Validation

| Check | Result |
| --- | --- |
| Pre-open lifecycle and custom-universe coverage | 47 passed |
| Pre-open intelligence tick and multi-provider/provider timestamp tests | 88 passed |
| Core pre-open tests and Python compile | 59 passed; compile passed |
| Phase 20 paper-trading safety | 62 passed |
| Market-data authority and portfolio/ledger pytest group | 48 passed (one unrelated deprecation warning) |
| Readiness group | 91 passed |
| TypeScript API/dashboard typecheck | Passed |
| Dashboard unit suite | 53 files, 1,007 tests passed |
| Dashboard production build | Passed |
| API service restart | Passed; API Server workflow running |

The first broad commands used dotted module imports for directories that are
not Python packages, and the first dashboard build omitted required `PORT`.
Those invocations were retried with discovery/pytest and
`PORT=5173 BASE_PATH=/trading-dashboard/`; all corrected checks passed.

The dashboard emitted pre-existing React `act(...)`, sourcemap, dynamic-import,
and large-chunk warnings. None were test or build failures, and this
server-only change did not alter the dashboard.