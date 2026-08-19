# ApexQuant AI — Post-Publish Scan Status Freshness Verification

> **Superseded for current-source certification.** This report accurately
> records production observations for the deployment that was live at the time
> of verification. A later completion review found and corrected a
> scheduler-path server-cache invalidation gap. The corrected source has passed
> targeted development regression tests but has not yet been republished, so a
> new production-only verification is required after that publish.

**Verification date:** 2026-08-20 IST  
**Environment checked:** Production only  
**Public URL:** https://nse-trade-intraday.replit.app  
**Deployment:** Public Autoscale, successful production build

## Result

The republished production deployment is serving the new Mission Control scan
freshness contract. The production API, production database, and public
Mission Control page were checked read-only. The final hard-refresh check
showed the same live counts across the API, database, and UI.

## Production API verification

### `GET /api/live-data/scan/status`

Final response: **HTTP 200**

```text
completed_scans_today: 1
started_scans_today: 2
scheduler_ticks_today: 0
lock_busy_skips_today: 0
runtime:
  owner: localhost:3010
  process_start_at: 2026-08-19T19:07:32Z
  status: IDLE
  heartbeat_at: 2026-08-19T19:11:15Z
api_build_id: 1
```

The response also retained the legacy `scan_count_today` and `rotation` fields
for compatibility, but the public UI does not use `rotation` as the completed
scan label.

### `GET /api/live-data/scan/history`

Final response: **HTTP 200**

```text
count: 1
total_completed: 1
ist_date: 2026-08-20
```

## Cache headers

Both production scan endpoints returned the strict headers required for live
status:

```text
Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate
Pragma: no-cache
Expires: 0
Surrogate-Control: no-store
```

The verification requests also included a unique `__aq_verify` query parameter
to bypass any intermediary that might ignore cache directives.

## Production source-of-truth comparison

A read-only query against the production `pipeline_events` store returned:

```text
SCAN_COMPLETED: 1
SCAN_STARTED:   2
SCHEDULER_TICK: 0
SCAN_SKIPPED_BUSY: 0
```

The final public API response matched those production database counts:

- `completed_scans_today = 1`
- `started_scans_today = 2`
- `scheduler_ticks_today = 0`
- `lock_busy_skips_today = 0`
- `history.total_completed = 1`

The values changed during verification because the production scheduler was
active. An earlier read saw zero completed and one started scan; after the
scan completed, the final hard-refresh/API/database snapshot consistently
showed one completed and two started scans.

## Public Mission Control verification

The public page was hard-refreshed in a fresh browser context and allowed to
settle. The final UI showed:

- `1 completed today`
- `2 started`
- `0 scheduler ticks`
- `0 lock-busy skips`
- `History rows shown 1 of 1`

The public page therefore matches the final production API count:

```text
UI completed count: 1
API completed_scans_today: 1
API history total_completed: 1
```

The following freshness requirements were confirmed:

- No operator-facing `Rotation` label is used for completed scans.
- Completed, Started, Scheduler ticks, and Lock-busy skips are separate UI
  metrics.
- History is labeled `History rows shown X of Y`.
- No stale `22`, `26`, or earlier response remained after the hard refresh.
- The page remained usable and read-only.

## Build identity observation

The production API reports:

```text
api_build_id: 1
```

The public browser bundle reports:

```text
UI development · API 1 · Build mismatch
```

This visible mismatch indicator is working as designed and correctly exposes
that the frontend build identifier is using its `development` fallback while
the production API identifies itself as build `1`. It did not prevent the
freshness contract, count parity, or no-store headers from working, but it is
an explicit deployment-identity warning that should be resolved in a future
publish configuration pass.

## Console and safety notes

- One non-blocking browser console error appeared during the public hard
  refresh: `Failed to load resource: the server responded with a status of
  500 ()`.
- It did not block Mission Control rendering or the scan-status/history
  verification. No additional blocking console errors were captured.
- No Start Scan, command, order, or trading mutation control was clicked.
- No live broker order API was called.
- No trading thresholds, paper-entry settings, or execution behavior were
  changed by this verification.

## Final verdict

**HISTORICAL PASS — the then-live production deployment met the checks above.**

The public deployment serves the new API fields and strict no-store headers;
production database counts agree with the API; Mission Control displays the
same completed count, separates the required metrics, labels history rows
correctly, and does not retain the stale 22/26 response after hard refresh.

The only follow-up observation is the visible UI/API build-ID mismatch and the
single non-blocking 500 console response noted above.

## Current-source follow-up required

The corrected scheduler path now invalidates live status and history caches on
scheduled start, completion, lock-busy/no-op, and failure outcomes, with
generation guards preventing stale in-flight reads from restoring prior data.
It also counts `total_completed` directly from durable IST-day completion
events rather than from presentation-history pairing.

Before this report can be restored as a final current-source pass:

1. Publish the corrected API source.
2. Read the public scan-status and scan-history endpoints with a unique query
   parameter before and after a scheduled lifecycle outcome; confirm both
   values refetch rather than serving a prior in-process TTL response.
3. Confirm public API, production database, and Mission Control still agree on
   `completed_scans_today` and `history.total_completed`.

No production reads, scans, orders, or settings changes were performed as part
of this remediation. Development regression coverage passed: 19 scheduler and
route-cache tests; 65 Python scan-status/history tests plus 10 subtests; and
the API TypeScript check.