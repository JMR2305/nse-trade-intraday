---
name: Kite session verification & scan locking
description: Rules for Zerodha session proof, durable tokens on Autoscale, and scan-lock lease safety in the paper-trading system.
---

## Session proof, not credential presence
Rule: paper-entry provider gates must key off `kite_session_verified()` (an authenticated `kite.profile()` probe, TTL-cached), never `kite_available()` (which only checks that a key + token exist).
**Why:** an expired daily token still "exists", so presence checks let Yahoo-fallback scans look Zerodha-connected and could unblock auto entries on fallback data. Architect review flagged this as a blocking safety gap.
**How to apply:** any new gate or safety flag about provider identity should read the structured `safety.kite_connected` written by the scan (which uses the verified probe), matched by `scan_id` — string label matching is only a defensive second check.

## Durable tokens on Autoscale
Rule: anything that must survive a redeploy (e.g. the Kite access token) goes in Postgres (phase20 kv) with the local file only as a warm cache.
**Why:** Autoscale instances have ephemeral disks; file-only tokens silently vanish on deploy, downgrading the provider without any error.

## Scan lock lease safety
Rules that keep scheduled scans overlap-free:
- Scheduler ticks use `wait_for_lock=False` — on busy lock, record `SKIPPED_ACTIVE_SCAN` + bump a kv counter, never poll (polling inflated tick durations by up to 120s and was counted in scan time).
- Long scans renew the lease via a heartbeat callback (~25s in the fetch loop plus stage transitions); only the holder can renew; expired leases are reclaimed automatically.
**Why:** a fixed 180s lease with 400–980s scans lost the lock mid-run and allowed overlapping scans.

## Perf classification
Scheduled scan duration classes: NORMAL ≤120s < WARNING ≤300s < DEGRADED (stored per run as `perf`, with a `timings` JSONB breakdown: fetch_s / analysis_s / db_write_s / lock_wait_s / retry_events).
