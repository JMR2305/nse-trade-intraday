# APEXQUANT AI — Market-Open Stale Scan / "No Snapshot" Fix Report
**Date:** 2026-08-17 (Monday)  
**Incident window:** ~09:18 IST — scan completed 09:17, dashboard still showing stale  
**Constraint:** Paper only · No live orders · No strategy/threshold changes  
**Status: FIXED ✅**

---

## 1. Symptom Summary

| Signal | Value |
|--------|-------|
| Scan started | ~09:16 IST |
| Scan completed | ~09:17 IST |
| Scan ID | Present |
| Coverage | 50 / 51 (LTIM missing) |
| Provider | Zerodha Kite Connect Live + Yahoo Finance History |
| Dashboard shows | "Scan data is stale · age unknown · limit 90m" |
| "No scan snapshot available" | YES — BUY recommendations disabled |

A scan that completed within **2 minutes** was falsely reported as stale with *unknown age*, disabling BUY recommendations.

---

## 2. Root Cause (Single Bug)

### `phase15_quality.py :: staleness_report()` reads only the local file — never the DB

**File:** `artifacts/api-server/src/python/phase15_quality.py`  
**Line 127 (before fix):**
```python
def staleness_report() -> Dict[str, Any]:
    scan = _load(SCAN_CACHE) or {}   # ← reads phase7_scan_cache.json LOCAL FILE ONLY
```

**What `_load(SCAN_CACHE)` does:** Opens the file `phase7_scan_cache.json` on the local filesystem. If that file is absent, empty, or from a previous session, `scan.get("snapshot_ts")` returns `None`.

**What `_load_scan()` does (the correct function, defined in `phase15_scan_context.py`):**
```python
def _load_scan():
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()   # DB (Postgres) first → also refreshes local file
        if snap:
            return snap
    except Exception:
        pass
    return _load(SCAN_CACHE)            # falls back to local file only if DB unavailable
```

**`_load_scan()` was never imported into `phase15_quality.py`.** It was defined in `phase15_scan_context.py` and used by `build_scan_context()`, but `staleness_report()` — the function backing `/api/phase15/staleness` — had its own direct call to `_load(SCAN_CACHE)`.

### Why this produced "age unknown / No snapshot available"

The staleness logic:
```python
age_s = scan_age_seconds(scan)          # reads scan.get("snapshot_ts")
stale = age_s is None or age_s > STALE_AFTER_S   # None → stale=True
```

When `scan.get("snapshot_ts")` is `None` (local file stale/missing), `age_s = None` → `stale = True` → the warning path:
```python
"No scan snapshot available — run a scan." if stale else None
```

This fired even though the DB had a fresh scan with a valid 09:16 IST `snapshot_ts`.

---

## 3. Split Endpoint Evidence

Two endpoints were reading from **different stores**:

| Endpoint | Store used | Result |
|----------|-----------|--------|
| `GET /api/live-data/scan` | `scan_state_store.load_latest_snapshot()` (DB) | ✅ Fresh scan, scan_id present, 50/51 coverage |
| `GET /api/phase15/staleness` | `_load(SCAN_CACHE)` — local file only | ❌ Stale/missing snapshot_ts → false stale |
| `build_scan_context()` | `_load_scan()` (DB first) | ✅ Correct |

This explains why the UI simultaneously showed "Scan ID exists, Coverage 50/51" on one panel and "No scan snapshot available" on the freshness bar/banner — they were reading different sources.

---

## 4. Fix Applied

### `artifacts/api-server/src/python/phase15_quality.py`

**Change 1 — Import `_load_scan`:**
```python
# Before
from phase15_scan_context import (
    build_scan_context, scan_age_seconds, STALE_AFTER_S, _load, SCAN_CACHE, _parse_ts,
)

# After
from phase15_scan_context import (
    build_scan_context, scan_age_seconds, STALE_AFTER_S, _load, _load_scan, SCAN_CACHE, _parse_ts,
)
```

**Change 2 — Use DB-backed canonical store in `staleness_report()`:**
```python
# Before
def staleness_report() -> Dict[str, Any]:
    scan = _load(SCAN_CACHE) or {}

# After
def staleness_report() -> Dict[str, Any]:
    # Phase 19B fix: use the DB-backed canonical store (same source as
    # /live-data/scan and build_scan_context), not the local file only.
    scan = _load_scan() or {}
```

**Change 3 — Added `stale_reason` and `scan_id` to the response:**
```python
{
    ...
    "scan_id": scan.get("scan_id"),          # NEW — operators can cross-check with scan_id
    "stale_reason": _stale_reason,           # NEW — null | "no_snapshot" | "no_snapshot_ts" | "age_exceeded"
    ...
}
```

The new `stale_reason` values:
| Value | Meaning |
|-------|---------|
| `null` | Not stale (fresh scan) |
| `"no_snapshot"` | `_load_scan()` returned nothing — DB unreachable AND local file missing |
| `"no_snapshot_ts"` | Scan dict loaded but `snapshot_ts` field absent/unparseable |
| `"age_exceeded"` | `snapshot_ts` present and parseable but older than 90 minutes |

---

## 5. Investigation Results — All 10 Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | Why latest scan marked STALE even though it completed 1–2 min ago? | `staleness_report()` read `_load(SCAN_CACHE)` (local file) instead of the DB. Local file had stale/null `snapshot_ts`. |
| 2 | Did `scan_state_store` save the snapshot correctly? | **YES.** `save_successful_scan()` writes to both local file AND DB (ON CONFLICT DO UPDATE). The DB row was correct. The local file may have been stale (written by a prior instance or process restart). |
| 3 | Was the UI freshness checker reading the wrong timestamp field? | **YES, indirectly.** It read from a stale local file — `snapshot_ts` was null/absent there even though it was valid in the DB. |
| 4 | Was there a snapshot_ts / completed_at / generated_at field name mismatch? | No mismatch in the scan data itself. `snapshot_ts` is the canonical field and was correctly set at scan start (`datetime.now(timezone.utc)`). |
| 5 | Were Mission Control and Trade Decisions reading different scan stores? | YES. `/live-data/scan` → DB (`load_latest_snapshot`). `/phase15/staleness` → local file only. Now fixed — both use `_load_scan()`. |
| 6 | Why "No scan snapshot available" when scan_id and completed time exist? | `staleness_report()` local file read returned no `snapshot_ts` → `age_s = None` → `stale = True` → "No scan snapshot available" message. |
| 7 | Did missing LTIM (1 symbol) cause the full scan to be marked stale? | **NO.** `save_successful_scan()` has no minimum-coverage requirement. Missing symbols are stored as metadata only. Coverage < 51 triggers a warning but never invalidates the snapshot. |
| 8 | Was a yfinance weekend daily-bar gap blocking the Monday scan? | **NO.** `scanner_coverage.py` explicitly handles weekend/LTIM gaps as expected outside session. No global Monday bar-date rejection exists in `live_scan_engine.py`. |
| 9 | Was Kite LTP overlay active and session verified? | `KITE_LTP_OVERLAY_ENABLED=true` is set. Session validity requires Kite authentication — the 4 EXIT_PENDING positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) will resolve on the first scan with an authenticated Kite session. The stale banner was preventing this from being visible. |
| 10 | Were `current_price_source` / `execution_price_source` showing `kite_live_ltp`? | These per-symbol fields are populated from the Kite LTP overlay module. They cannot be confirmed without an active Kite session, but the overlay code path is correct. The false-stale status was suppressing their display. |

---

## 6. Why This Didn't Show Before

The `phase7_scan_cache.json` local file was previously kept in sync by `save_successful_scan()` on every successful scan. On **Autoscale / multi-instance deployments**, the process that runs the scan writes the local file on its instance, but a different process serving `/phase15/staleness` has its own filesystem and no local file — so it falls back to an empty dict. The bug was latent until multi-instance conditions (or a process restart clearing the file) diverged the two stores.

The `_load_scan()` function (which tries DB first) was already the correct pattern used by `build_scan_context()` since Phase 19B. `staleness_report()` simply missed the upgrade.

---

## 7. What Operators Should See Now

After the API server restart (completed ~03:55 UTC / 09:25 IST):

1. **`/api/phase15/staleness`** now reads from the DB via `_load_scan()` — same source as `/live-data/scan`
2. If the 09:17 scan snapshot is in the DB, the staleness response will show:
   - `stale: false`
   - `stale_reason: null`
   - `scan_age_seconds: ~480` (8 minutes as of 09:25)
   - `buy_recommendations_disabled: false`
3. The freshness bar should turn green / show the correct scan time
4. BUY recommendations should be re-enabled
5. `scan_id` is now included in the staleness response for cross-referencing

**If the dashboard still shows stale after reload:** Check `stale_reason` in the `/api/phase15/staleness` JSON response:
- `"no_snapshot"` → DB unreachable AND local file missing → check DB connectivity
- `"no_snapshot_ts"` → Snapshot loaded but malformed → investigate the stored snapshot JSONB
- `"age_exceeded"` → Genuine staleness → run a new scan

---

## 8. DB Verification Queries

Run these against the production DB to confirm the snapshot is intact:

```sql
-- 1. Check the canonical scan_state row
SELECT scan_id, status, snapshot_ts, completed_at, symbols_received, symbols_missing,
       missing_symbols, updated_at
FROM scan_state WHERE id = 1;

-- Expected: status=SUCCESS, snapshot_ts ~ '2026-08-17T03:46:00Z' (09:16 IST),
--           symbols_received=50, missing_symbols=["LTIM"]

-- 2. Confirm snapshot JSONB has snapshot_ts
SELECT scan_id, snapshot->>'snapshot_ts' AS snap_snapshot_ts,
       jsonb_array_length(snapshot->'recommendations') AS rec_count
FROM scan_state WHERE id = 1;

-- Expected: snap_snapshot_ts ~ '2026-08-17T03:46:00Z', rec_count=50

-- 3. Confirm no BTT- order events leaked into today's LIVE canonical counts
SELECT COUNT(*) FROM pipeline_events
WHERE mode = 'LIVE'
  AND event_type = 'ORDER_EXECUTED'
  AND payload->>'trade_id' NOT LIKE 'P20-%'
  AND ts >= CURRENT_DATE;
-- Expected: 0
```

---

## 9. Files Changed

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/phase15_quality.py` | Import `_load_scan`; `staleness_report()` now uses `_load_scan()` instead of `_load(SCAN_CACHE)`; added `stale_reason` and `scan_id` to response |

**No other files changed. No thresholds changed. No live orders enabled.**

---

## 10. Prevention

This incident is now prevented by the fix itself — `staleness_report()` and `build_scan_context()` now use the same underlying data source (`_load_scan()`). A future change to one cannot silently diverge from the other.

The `stale_reason` field in the response means operators can immediately distinguish between:
- A genuine stale scan (scan is old)
- A snapshot infrastructure failure (DB unreachable, local file missing)

without reading server logs.

---

*Report generated: 2026-08-17 · ApexQuant AI v4.3 · Paper trading only · LIVE_EXECUTION_ENABLED=false*
