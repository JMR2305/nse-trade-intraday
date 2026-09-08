# ApexQuant Off-Market Scan Reduction and Job Classification Report

**Prepared:** 2026-08-20  
**Scope:** Task 857 — scheduler job classification, off-market containment, and
paper-entry safety.  
**Mode:** Paper trading / research only. No live execution was enabled, called,
or configured by this work.

## 1. Read-only audit evidence

The audit read the durable `phase20_scan_runs`, `pipeline_events`,
`daily_ohlcv_refresh_state`, and `phase20_scheduler_state` records. It did not
trigger a scan, a scheduler command, cache refresh, settings change, paper
entry, or broker call.

### Observed off-market records

`phase20_scan_runs` contained manually triggered canonical diagnostics outside
the NSE session. Examples include 19 August 2026 at 15:40–19:31 IST and 20
August 2026 at 00:40–03:36 IST. They were recorded with
`trigger_source=MANUAL`, with durations between 5.29 and 99.13 seconds. These
are manual diagnostics, not scheduler market scans.

Recent `SCHEDULED` rows were instead inside the open session: on 20 August,
03:45–04:15 UTC (09:15–09:45 IST). They are actual in-session market scans,
not cache maintenance or readiness work.

The durable refresh ledger separately showed:

| Refresh date | Type | Result | Duration | Evidence |
| --- | --- | --- | ---: | --- |
| 2026-08-19 | postmarket | SUCCESS | 3.28s | 50 requested, 50 updated |
| 2026-08-18 | postmarket | FAILED | 9.49s | 51 requested, 0 updated; cache preserved |

The first successful row was stored at 00:01 IST on the following calendar day.
That was a classification/time-window defect: `CLOSED` previously included
overnight time. The new gate permits a post-market refresh only after the
configured NSE close on an IST trading day.

### 2,304-second partial-refresh investigation

No durable `daily_ohlcv_refresh_state` or `phase20_scan_runs` row with a
duration in the 2,303–2,305 second range was found. The available refresh
records above therefore do not support attributing a 2,304-second operation to
the post-market refresh job. The prior implementation also did not attach a
shared job identifier or classification to that work, so this cannot be
reconstructed from a UI count. Future runs record explicit job metadata,
unfinished symbols, attempts, duration, and status.

### AI, execution, bootstrap, and entry-path evidence

For the audited manual off-market scan IDs, the durable pipeline-event query
returned no `BUY_GENERATED`, `ORDER_SUBMITTED`, `ORDER_EXECUTED`, or
`BOOTSTRAP_PAPER_TRADE_APPROVED` events. Across the sampled seven-day event
window, the durable event store contained `SCAN_STARTED`, `SCAN_COMPLETED`, and
`BUY_GENERATED` events, but no `ORDER_SUBMITTED`, `ORDER_EXECUTED`, or
`BOOTSTRAP_PAPER_TRADE_APPROVED` events.

This proves the inspected manual records did not reach paper-order submission,
execution, or BOOTSTRAP_AUTO. It does **not** infer a decision from a UI
counter: it is based on the durable event and run records. AI-decision event
types were not present in the queried durable event vocabulary, so the audit
does not claim an AI-decision stage was reached or not reached beyond the
absence of an execution/entry event.

## 2. Classification rules implemented

All displayed scheduler and scan jobs use one durable record contract in
`phase20_scan_runs`:

- `job_type`: `MARKET_SCAN`, `POSTMARKET_CACHE_REFRESH`,
  `PREMARKET_READINESS_CHECK`, `SYSTEM_HEARTBEAT`, or `MANUAL_SCAN`
- `scan_type`, source/trigger, job status, provider and symbol counts
- UTC and operator-facing IST start/completion timestamps, duration, and gap
- market state plus separate entry and execution eligibility flags
- job details, including cache failures/unfinished symbols or readiness checks

Only `MARKET_SCAN` with `market_state=OPEN` receives entry/execution
eligibility. Manual diagnostics are always displayed as `MANUAL_SCAN` and do
not grant it.

## 3. Scheduler containment and cache recovery

- Canonical scheduled scans run only on the existing `OPEN` branch.
- The scheduler records bounded non-market heartbeats outside the session.
- A readiness check runs once in the 08:45–09:05 IST window on a trading day.
- A cache refresh is post-close only, cache-only, and cannot be invoked through
  the old ungated command path.
- A successful cache refresh consumes the IST day. Failed/partial work releases
  its lease, retains prior cache rows, persists unfinished symbols, and allows
  at most three retries that fetch only those unfinished symbols.
- EOD and post-close force-exit behavior was not changed.

Readiness evidence now also includes active universe, paper capital, circuit
breaker, open positions, build identity, and IST-correct refresh-age checks.

## 4. Final paper-entry safety

Decision-time gates remain in place. A second fail-closed NSE `OPEN` check now
runs at the ledger-admission boundary immediately before a paper BUY is
committed. It covers normal automatic entries and `BOOTSTRAP_AUTO`, and treats
unknown/unavailable market state as blocked. This does not enable or call a
live broker API.

## 5. API and Mission Control contract

The scan-status response retains legacy counters and adds:

- `market_scans_today`
- `all_system_jobs_today`
- `latest_market_job`, `latest_system_job`, and `next_jobs`
- `market_state` and `entry_execution_allowed`

History now uses classified durable jobs when available and labels non-market
rows with job type, IST time, market state, source, duration, gap, symbols, and
execution allowance. Existing route `no-store` behavior remains unchanged.

Mission Control renders the new market/system counts and labels without
presenting cache, readiness, heartbeat, or manual work as a completed trading
scan.

## 6. Verification

Completed locally:

- Python compile checks for all modified modules
- Focused Task 857 backend suite plus existing status/history/scheduler suites:
  **96 passed**
- Scheduler regression suite: **21 passed**
- Mission Control Task 857 UI plus related scanner suites: **17 passed**
- API server TypeScript check: passed
- `git diff --check`: passed
- Read-only live API verification: scan status and history both returned strict
  `no-store`; a newly persisted `MARKET_SCAN` row showed `OPEN`, IST timestamps,
  and entry/execution eligibility.

A broader legacy test command reported two unrelated failures in
`test_task657_execution_fix.py`: it patches a missing
`pipeline_events._emit_unsafe` helper before executing the tested code. This
predates the Task 857 paths and is recorded here rather than masked.

## 7. Publish and next-session readiness

**Production publish status:** not published by this task. Development changes
are verified only; a production deployment must use the normal publish flow.

For the next trading session, verify the pre-market readiness record appears
between 08:45 and 09:05 IST, confirm `Market Scans Today` remains zero before
09:15 IST, and confirm the first successful post-close refresh has exactly one
`SUCCESS` job for that IST trading day. Any partial refresh should show its
unfinished symbols and bounded retry attempt, not a market scan.

The retry lease is owner-token fenced, renewed while bounded provider work is
active, and checked immediately before refresh-state publication. A slow active
worker therefore cannot be taken over mid-operation or overwrite a new owner's
durable result after its lease has changed hands.