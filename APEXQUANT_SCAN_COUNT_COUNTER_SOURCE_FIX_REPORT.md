# ApexQuant — Scan Count Counter Source Fix Report

**Date:** 2026-08-18 · **Scope:** Paper trading dashboard metrics only — no live orders enabled, no scheduling/threshold changes.

## Summary

The AI Paper Trader "Intraday Scan Cadence" card under-reported the day's scans
(e.g. 19/75 while the pipeline recorded 77 completions). Two backend bugs and one
UI presentation bug compounded:

1. **Wrong event type** — `completed_scans_today` counted `SCAN_STARTED` rows
   (further filtered to market hours), not `SCAN_COMPLETED`. The authoritative
   daily-report function `count_scans_today_ist()` counts `SCAN_COMPLETED`.
2. **UTC vs IST day boundary** — the cadence endpoint windowed on the UTC
   calendar date. After 18:30 UTC (00:00 IST) the two windows diverge and
   early-IST-day completions fall in the *prior* UTC day, so they were dropped.
3. **Post-market "Review" badge** — the panel derived its badge purely from
   coverage/gap metrics with no market-state awareness, showing an alarming
   "Review" at e.g. 23:26 IST when the market had simply closed.

## True full-day count query (IST boundary)

```sql
-- ist_midnight_utc = (now_utc + interval '5:30') date-truncated, minus '5:30'
SELECT COUNT(*) FROM pipeline_events
WHERE event_type = 'SCAN_COMPLETED'
  AND ts >= :ist_midnight_utc
  AND ts <  :ist_midnight_utc + interval '1 day';
```

This mirrors `count_scans_today_ist()` in `scan_state_store.py`: shift now to
IST (+05:30), take IST midnight, shift back to UTC for the cutoff.

## Why the UI under-reported

- `SCAN_STARTED` rows can be missing for completions recorded after a process
  restart, and starts without completions inflate the count the other way.
- The UTC window silently truncated the IST day whenever queried past
  18:30 UTC, cutting off the earliest scans of the IST session.
- Both errors compounded into a count far below the authoritative 77.

## Changed files

| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` (`phase20_cadence_stats`) | Count `SCAN_COMPLETED` over the IST day window (via `ist_day_bounds_utc`); added `session_scans_today` (completions since the scheduler's recorded `process_start_at`; fallback = IST day start); gaps now from completion timestamps; durations = completion − matching start; `skipped_scans_today` unchanged. Added `phase20_scheduler_started` command that records the scheduler process start time. |
| `artifacts/api-server/src/python/scan_state_store.py` | New pure helper `ist_day_bounds_utc()` (same logic as `count_scans_today_ist`), shared by the cadence command and covered by unit tests. |
| `artifacts/api-server/src/python/phase20_store.py` | `phase20_scheduler_state` gains a durable `process_start_at` column (idempotent ALTER); read/written via `update_scheduler_state` / `get_scheduler_health`. |
| `artifacts/api-server/src/lib/scanScheduler.ts` | On scheduler boot, records `process_start_at` durably (`phase20_scheduler_started`), non-fatal on failure. |
| `artifacts/trading-dashboard/src/pages/AIPaperTraderPage.tsx` (`SCadencePanel`) | Added `session_scans_today` to the type; "Scans Today" card labelled "Full day (IST)" with a muted secondary "Since last restart" row; new exported `cadenceBadgeState()` helper: explicit CLOSED/POST_CLOSE/HOLIDAY states force a neutral "Market closed" badge with a "Last scan at HH:MM IST — BUY recommendations resume after next scan." sub-line; UNKNOWN/missing health data is never presented as a confirmed closure; "Review" reserved for genuinely degraded in-session coverage. |
| `artifacts/api-server/src/python/test_ist_day_bounds.py` | Unit tests for the IST boundary incl. the 18:30 UTC rollover case. |
| `artifacts/trading-dashboard/src/pages/AIPaperTraderPage.cadencebadge.test.tsx` | Badge-state tests: closed states, OPEN good/poor coverage, UNKNOWN/loading never shows "Market closed". |

## New UI labels

- **Full day (IST)** — `completed_scans_today`: all `SCAN_COMPLETED` events since IST midnight. Matches the daily session report.
- **Since last restart** — `session_scans_today`: `SCAN_COMPLETED` events since the scheduler's recorded start (subset of the full-day count; equals it when no restart timestamp is available).
- **Market closed** (neutral/grey badge) — shown whenever market state is not OPEN/PRE_OPEN, regardless of coverage ratio.

## Explicit confirmations

- **The scan scheduler itself did not fail.** `pipeline_events` is authoritative
  and recorded the full day's `SCAN_COMPLETED` events; only the counter's source
  query and day boundary were wrong.
- **No live orders were enabled.** This change touches read-only metrics and UI
  labels only. Paper-only mode, scan scheduling, cadence, thresholds, and all
  trading/risk parameters are unchanged.
