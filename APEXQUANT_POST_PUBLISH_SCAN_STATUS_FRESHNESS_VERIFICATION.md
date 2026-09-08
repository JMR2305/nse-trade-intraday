# ApexQuant AI — Post-Publish Scan Status Freshness Verification

> **Final current-source verification.** This report records the read-only
> production snapshot after the corrected scheduler cache-invalidation source
> was published. No scan, order, command, or settings mutation was triggered.

**Verification date:** 2026-08-20 IST  
**Environment checked:** Production only  
**Public URL:** https://nse-trade-intraday.replit.app  
**Deployment:** Public Autoscale, successful production build

## Result

The published production deployment is serving the corrected Mission Control
scan-freshness contract. The production API, production database, and public
Mission Control page were checked read-only. The final fresh-browser check
showed the same live counts across the API, database, and UI.

## Production API verification

### `GET /api/live-data/scan/status`

Final response: **HTTP 200**

```text
completed_scans_today: 4
started_scans_today: 6
scheduler_ticks_today: 0
lock_busy_skips_today: 0
runtime:
  owner: localhost:205
  process_start_at: 2026-08-19T20:04:26Z
  status: IDLE
  heartbeat_at: 2026-08-19T20:10:56Z
api_build_id: 1
```

The response also retained the legacy `scan_count_today` and `rotation` fields
for compatibility, but the public UI does not use `rotation` as the completed
scan label.

### `GET /api/live-data/scan/history`

Final response: **HTTP 200**

```text
count: 4
total_completed: 4
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
SCAN_COMPLETED: 4
SCAN_STARTED:   6
SCHEDULER_TICK: 0
SCAN_SKIPPED_BUSY: 0
```

The final public API response matched those production database counts:

- `completed_scans_today = 4`
- `started_scans_today = 6`
- `scheduler_ticks_today = 0`
- `lock_busy_skips_today = 0`
- `history.total_completed = 4`

The values changed during verification because the production scheduler was
active. An earlier read saw zero completed and one started scan; after the
scan completed, the final hard-refresh/API/database snapshot consistently
showed one completed and two started scans.

## Public Mission Control verification

The public page was hard-refreshed in a fresh browser context and allowed to
settle. The final UI showed:

- `4 completed today`
- `6 started`
- `0 scheduler ticks`
- `0 lock-busy skips`
- `History rows shown 4 of 4`

The public page therefore matches the final production API count:

```text
UI completed count: 4
API completed_scans_today: 4
API history total_completed: 4
```

The following freshness requirements were confirmed:

- No operator-facing `Rotation` label is used for completed scans.
- Completed, Started, Scheduler ticks, and Lock-busy skips are separate UI
  metrics.
- History is labeled `History rows shown X of Y`.
- No stale `22`, `26`, `1`, or `2` response remained after the fresh
  production-browser load.
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

- No visible browser console errors were observed during the final fresh
  production-browser verification.
- No Start Scan, command, order, or trading mutation control was clicked.
- No live broker order API was called.
- No trading thresholds, paper-entry settings, or execution behavior were
  changed by this verification.

## Final verdict

**PASS — final current-source production verification completed.**

The public deployment serves the corrected API fields and strict no-store
headers; production database counts agree with the API; Mission Control
displays the same completed count, separates the required metrics, labels
history rows correctly, and remains read-only and usable.

The only remaining deployment warning is the visible build-ID mismatch:
`UI development · API 1 · Build mismatch`. The indicator is correctly exposing
that the frontend bundle still uses its `development` fallback while the API
reports build `1`; it did not affect freshness, count parity, or cache headers.

The live production log search did not find a post-publish
`Scheduled market scan` record. No scheduled scan was manually triggered,
because this verification was required to remain read-only. Scheduled-path
behavior is covered by the development regression tests documented in the
implementation report.