---
name: Phase 19B durable scan state
description: Canonical scan snapshot/lock live in Postgres via scan_state_store; rules for keeping stale-data protection intact on Autoscale.
---

# Durable scan state (Phase 19B)

Rule: the canonical scan snapshot, its metadata, and the scan lock must be
read/written through `scan_state_store.py` (Postgres `scan_state` + `scan_lock`
tables, file fallback when DATABASE_URL absent). Never treat
`phase7_scan_cache.json` or Express in-memory caches as the source of truth —
they are per-instance warm caches only.

**Why:** production runs on Replit Autoscale; local files/memory are ephemeral
and per-instance, which caused the "Rescan does nothing / 14h stale banner" bug.
Also: writing a test snapshot via `save_successful_scan` overwrites BOTH the DB
row and the local phase7_scan_cache.json — restore a real snapshot afterwards
or other test suites (phase9/phase15) fail.

**How to apply:**
- New scan consumers: load via `live_scan_engine.load_cached_scan()` or
  `phase15_scan_context._load_scan()`, not raw file reads.
- Failed scans must never overwrite the last successful snapshot
  (`record_failed_scan` only sets the error column).
- Frontend Rescan = POST /api/live-data/scan/run (canonical), then
  GET /market-scan?refresh=true for the page view; 429 = "ran recently", not failure.
- All persisted timestamps: tz-aware UTC "...Z"; display converts with
  timeZone "Asia/Kolkata". Stale limit stays 90 min — never widen it.
- Scheduler: Node `scanScheduler.ts` → python `scheduled_scan_tick` (market
  hours + freshness + DB lease). In-process timer only runs while an instance
  is warm (Autoscale scale-to-zero limitation, documented deliberately).
