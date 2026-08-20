# After-Hours Scan and Pipeline Audit Summary

**Date:** 2026-08-20  
**Product:** ApexQuant AI paper-only NSE trading platform  
**Scope:** Read-only audit of after-market scanning, Mission Control status, pipeline counts, and execution safety.

## Executive outcome

The scheduler was correctly avoiding full market scans after the NSE session closed, but two full-scan entry paths could bypass that boundary:

1. The operator-triggered `POST /api/live-data/scan/run` route.
2. A cold in-process cache caused by ordinary `GET /api/live-data/recommendations` or `GET /api/live-data/scan` requests after an API restart.

Both paths are now protected. After close, the application serves the last durable canonical snapshot for normal read-only dashboard requests. Explicit refreshes and manual scan requests return `409 MARKET_CLOSED` without starting a scan or replacing canonical state.

## Findings

### Mission Control status

The dashboard previously treated any retained durable `progress.stage` as an active scan. That could display `SCANNING` after the worker had stopped.

The correct source of active-scan status is now:

- progress metadata exists, **and**
- scheduler runtime status is explicitly `SCANNING`.

When the market is closed and the scheduler heartbeat is present, Mission Control now displays:

- `IDLE — MARKET CLOSED`
- `After-hours monitoring only — execution disabled.`

The global desktop market badge was also hardcoded to `NSE OPEN`. It now uses the live authoritative market state and correctly displays `NSE CLOSED`.

### After-hours scheduler behavior

The scheduler may continue lightweight monitoring and maintenance after close, including:

- scheduler heartbeats;
- post-market OHLCV cache refresh;
- reports;
- reconciliation;
- validation;
- learning;
- end-of-day paper-position handling.

The scheduler exits before the full canonical scan path whenever the market state is not `OPEN`.

### Timestamp meanings

- **Stale-scan age:** latest successful canonical snapshot `snapshot_ts`, falling back to completion time.
- **Current scan started:** durable `scan_progress.started_at`.
- **Latest successful scan:** durable `latest_scan` metadata.
- **Latest heartbeat:** `runtime.heartbeat_at`.
- **Latest system job:** classified `latest_system_job` record.

These timestamps intentionally represent different things and should not be compared as if they were one clock.

### Pipeline count meanings

- **Market Scans Today:** classified `MARKET_SCAN` run records.
- **All System Jobs:** market scans plus heartbeats and other non-market jobs.
- **Started / Completed:** append-only scan event counts.
- **Scheduler Ticks:** due scheduled scan-attempt events, not every scheduler heartbeat.
- **Lock-Busy Skips:** attempts rejected because another scan held the lock.
- **Stage and Scanner counts:** per-stage evidence from the latest replay snapshot, not daily totals.

Because these values come from different durable sources, they are not expected to match one another exactly.

## Safety result

After the fix:

- `market_state` is `CLOSED`.
- `entry_execution_allowed` remains `false`.
- Normal recommendations remain readable from the saved snapshot.
- Forced scan requests return `409 MARKET_CLOSED`.
- Manual scan requests return `409 MARKET_CLOSED`.
- The canonical scan ID and snapshot timestamp remain unchanged across those requests.
- No broker API was called.
- No live order or paper order was placed.

The existing `market_open` and `scan_fresh` execution gates remain enabled as defense-in-depth protections.

## Code changes

- `artifacts/trading-dashboard/src/pages/MissionControl.tsx`
  - Requires authoritative runtime `SCANNING` status before presenting an active scan.
  - Adds the explicit closed-market monitoring state.
- `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx`
  - Replaces the hardcoded `NSE OPEN` badge with live market status.
- `artifacts/api-server/src/routes/trading.ts`
  - Adds an `OPEN`-only guard to manual scans.
  - Prevents cold-cache full scans after close.
  - Serves the durable snapshot for ordinary after-hours reads.
  - Rejects explicit refreshes while closed.
- `artifacts/api-server/src/python/main.py`
  - Adds the read-only `scan_snapshot` command used by the cold-cache path.
- Regression tests cover manual scans, forced scans, cold-cache reads, cache invalidation, and closed-market behavior.

## Verification

- API regression tests: **9 passed**
- Mission Control UI tests: **13 passed**
- API TypeScript check: **passed**
- Dashboard TypeScript check: **passed**
- Final browser preview verified:
  - global badge: `NSE CLOSED`;
  - session card: `NSE CLOSED`;
  - Live AI Pipeline: `IDLE — MARKET CLOSED`;
  - Live Scanner: `IDLE — MARKET CLOSED`;
  - stale-scan warning remains visible;
  - no false `SCANNING` state.
