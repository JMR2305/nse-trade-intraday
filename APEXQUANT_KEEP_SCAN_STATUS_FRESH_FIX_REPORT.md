# ApexQuant AI — Keep Scan Status Fresh Fix Report

**Completed:** 2026-08-19  
**Scope:** Mission Control scan observability and stale-display prevention  
**Safety boundary:** Paper trading and read-only operational visibility only. No
trading thresholds, broker-order paths, or live-execution settings were changed.

## Outcome

Mission Control now has an explicit, durable scan-observability contract instead
of overloading one completion count as “Rotation.” Browser/proxy caches are
forbidden from retaining live status responses, the UI asks for no-store
responses, appends a unique per-request cache-busting timestamp, and prevents
an older scan-status response from overwriting a newer value already displayed
in the browser.

## API freshness protections

The following read endpoints return all of these headers:

```text
Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate
Pragma: no-cache
Expires: 0
Surrogate-Control: no-store
```

Endpoints covered:

- `GET /api/live-data/scan/status`
- `GET /api/live-data/scan/history`
- `GET /api/phase20/bootstrap-status`
- `GET /api/phase20/eod-status`
- `GET /api/ohlcv-cache/status`
- `GET /api/ohlcv-cache/readiness`

The small server-side coalescing cache for scan status remains in place to avoid
duplicate Python work. It is invalidated when a scan starts and when it
completes; browser/CDN/proxy reuse is not permitted.

For status polling, Mission Control also appends
`__aq_refresh=<milliseconds>` to the request URL. This is a defense in depth
measure for intermediaries that ignore request cache mode or response headers.

## Explicit scan metrics

`GET /api/live-data/scan/status` now returns:

| Field | Durable source | Meaning |
|---|---|---|
| `completed_scans_today` | `SCAN_COMPLETED` events since IST midnight | Completed scans today |
| `started_scans_today` | `SCAN_STARTED` events since IST midnight | Actual scanner starts today |
| `scheduler_ticks_today` | `SCHEDULER_TICK` events since IST midnight | Due scheduled scan attempts; not one-minute heartbeats |
| `lock_busy_skips_today` | `SCAN_SKIPPED_BUSY` events since IST midnight | Attempts skipped because another scan holds the lock |
| `runtime` | durable scheduler health | Scheduler owner/process identity and heartbeat, not a scan count |

`scan_count_today` and `rotation` remain as compatibility aliases for existing
clients, but Mission Control no longer presents either as the operator-facing
rotation metric.

`GET /api/live-data/scan/history` now returns both:

- `count`: history rows actually sent to the current view
- `total_completed`: all completed scans for the current IST day

The scanner therefore displays `History rows shown 10 of 54`, rather than
mistakenly implying that the ten displayed rows are the day’s total scans.

## Freshness and ordering behavior

- Mission Control requests scan status, scan history, bootstrap status, EOD
  status, and OHLCV cache status with `fetch` cache mode `no-store` and a
  unique cache-busting timestamp.
- A monotonic display guard compares each incoming scan response with the
  latest rendered response by snapshot time, then by completion count when
  timestamps are equal or absent.
- A response that regresses is not rendered; the screen keeps the newer value,
  shows a stale-display warning, and forces a refetch.
- A newer timestamp is accepted even when the completed count resets at the
  next IST day boundary.
- Mission Control displays both `UI <build id>` and `API <build id>`. Local
  development correctly shows `development` for each. It also displays
  **Builds match** for equal IDs and a visible **Build mismatch** warning when
  they differ.
- The accepted response time is rendered as `Last refreshed HH:MM:SS IST`.

## Development verification

Direct development endpoint check on 2026-08-19:

```text
scan status:
  completed_scans_today: 55
  started_scans_today: 55
  scheduler_ticks_today: 0
  lock_busy_skips_today: 0
  api_build_id: development

scan history:
  count: 10
  total_completed: 55
  ist_date: 2026-08-19
```

The zero scheduler-tick count is honest: that event is newly instrumented and
will begin counting only scheduled due attempts that occur after this release
is running.

Browser verification confirmed:

- Completed, Started, Scheduler ticks, and Lock-busy skips are visible.
- No `Rotation` label is used for the completion count.
- Build IDs render in the Mission Control header.
- Build-ID match/mismatch state and the accepted refresh time render in the
  header.
- History explicitly says `History rows shown`.
- The duplicate React chip-key warning found during the first browser check was
  fixed by using the chip label-and-value pair as the list key.
- A fresh browser context then showed no duplicate-key or blocking console
  errors.

## Production comparison before republish

Read-only production database evidence for 2026-08-19:

```text
SCAN_COMPLETED:    26
SCAN_STARTED:      28
SCAN_SKIPPED_BUSY: 17
SCHEDULER_TICK:     0  (not emitted by the older deployment)
latest completed: 2026-08-19T12:46:16Z, scan_id d10d61b2b9ef
```

Current public API at `https://nse-trade-intraday.replit.app` matches the older
production database’s 26 completed scans and latest scan ID. It still exposes
only the old `scan_count_today`/`rotation` payload and the older
`Cache-Control: no-store, max-age=0` header. This is a deployment-version
difference, not a mismatch between the public API and its production database.

Development and production intentionally have different scan histories:
development showed 54 completed scans while production showed 26.

## Validation completed

- Python scan-status and scan-history unit suite: **64 passed, 10 subtests
  passed**
- Focused Mission Control frontend freshness suite: **6 passed**, including a
  real asynchronous late-response sequence that proves an older response cannot
  replace a newer rendered scan
- Focused API scan cache-invalidation suite: **5 passed**
- Workspace typecheck: **passed**
- Direct development endpoint verification: strict no-store headers confirmed
  on all six covered endpoints
- Browser verification: passed in a fresh context with no duplicate-key or
  blocking console errors
- Current direct development status check after API restart: succeeded with
  `__aq_refresh` cache busting, strict no-store headers, API build ID
  `development`, and the explicit scan counters

## Required production step

The code is ready to publish. Publishing will deploy the new API payload,
strict cache headers, build identifiers, and Mission Control UI to the public
site. It will **not** copy development scan counts into production or alter
paper-trading safety behavior. After publish, recheck the public scan-status
and scan-history endpoints to confirm the new fields/build IDs are present.

## Completion-review remediation

The completion review identified a remaining stale-data path: scheduled scans
ran through `scheduled_scan_tick` without invalidating the API process's
short-lived scan-status and scan-history caches. That meant a cache-busted,
no-store browser request could still receive a server-side TTL entry after a
scheduled start, completion, lock-busy outcome, or failure.

This is now corrected:

- The scheduler publishes lifecycle events for start, completed, lock-busy,
  no-op, and failed outcomes.
- The route layer invalidates both live caches for each of those events.
- Both caches now use generation guards, so a Python read that began before an
  invalidation cannot repopulate the cache with stale data after it finishes.
- `history.total_completed` is independently counted from all IST-day durable
  `SCAN_COMPLETED` events; history pairing is retained only for duration and
  gap enrichment.

Regression validation after this remediation:

- Scheduler lifecycle and route-cache tests: **19 passed**.
- Python scan-status/history tests: **65 passed, 10 subtests passed**.
- API TypeScript check: **passed**.
- Restarted development API: clean startup; both scan endpoints returned
  strict no-store headers and their required payload fields.

Final post-publish verification is now complete. Production API, production
database, and the fresh public Mission Control browser check agree at
4 completed scans and 6 started scans today; both live endpoints returned
strict no-store headers. No scheduled scan was manually triggered during this
read-only verification, so the scheduler lifecycle itself remains validated by
the focused development tests rather than by a production mutation. The
remaining visible `UI development · API 1 · Build mismatch` state is recorded
as a deployment-identity warning only.