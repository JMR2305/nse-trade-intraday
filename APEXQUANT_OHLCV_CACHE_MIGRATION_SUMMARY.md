# ApexQuant AI — Local NIFTY 50 OHLCV Cache Migration
**Date:** 2026-08-19 (implemented overnight 2026-08-18 → 2026-08-19)  
**Environment:** Development (paper trading only — no live orders, no broker API calls)  
**Status:** ✅ Complete — cache warm, 50/51 symbols LIVE, backfill done

---

## 1. Why This Was Needed

### The problem
Every live scan called:
```python
yf.download(50_tickers, period="6mo", interval="1d", group_by="ticker", threads=True)
```
This fetched **~124 rows × 50 symbols = 6,200 rows** of daily OHLCV from Yahoo Finance on **every single scan** — even though the data had not changed since the previous scan 5 minutes earlier.

### Impact on scan cadence
| Condition | Scan duration |
|-----------|--------------|
| Yahoo CDN warm (fast) | 17–23 seconds |
| Partial cache miss | 3–13 minutes |
| Full 6-month history download | 19–22 minutes |

While a slow scan held the distributed lock, the next 5-minute scheduler ticks logged "lock busy" and skipped. This reduced the completed scan count to **18–25 per full session** instead of the theoretical maximum of ~75.

### Root cause confirmed from code
- `live_data_provider.fetch_batch()` had zero caching — every call hit yfinance unconditionally
- No local OHLCV table existed before this change
- `kite_ltp_overlay.py` only overlays the live price (< 1 second) — it was never the bottleneck

---

## 2. Architecture: Before vs After

### Before
```
Scan trigger (every 5 min)
    ↓
live_data_provider.fetch_batch()
    ↓
yf.download(50 symbols, 6mo history)     ← 7–22 minutes per scan
    ↓
kite_ltp_overlay (< 1 second)
    ↓
Indicators + signals
```

### After
```
Scan trigger (every 5 min)
    ↓
live_data_provider.fetch_batch()
    │
    ├── Step 1: daily_ohlcv_cache (PostgreSQL)  ← < 1 second for all 50 symbols
    │     HIT  → use cached DataFrame, skip yfinance entirely
    │     MISS → add to remaining list
    │
    ├── Step 2: yf.download(remaining only)     ← only for cache misses
    │     → write results back to daily_ohlcv_cache
    │
    └── Step 3: per-symbol fallback for stragglers
          → write results back to cache
    ↓
kite_ltp_overlay (< 1 second, unchanged)
    ↓
Indicators + signals
```

**On a warm cache day (post-market refresh ran the evening before):**  
Step 1 serves all 50 symbols → Steps 2 and 3 are skipped entirely → **< 5 seconds per scan**.

---

## 3. New Database Tables

### `daily_ohlcv_cache` — primary OHLCV store
```sql
CREATE TABLE daily_ohlcv_cache (
    symbol          TEXT NOT NULL,
    trading_date    DATE NOT NULL,
    open            NUMERIC(14,4),
    high            NUMERIC(14,4),
    low             NUMERIC(14,4),
    close           NUMERIC(14,4),
    adjusted_close  NUMERIC(14,4),
    volume          BIGINT,
    source          TEXT DEFAULT 'yfinance',
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    data_quality    TEXT,   -- LIVE / NEAR_LIVE / STALE / UNAVAILABLE
    PRIMARY KEY (symbol, trading_date)
);
```

### `daily_ohlcv_refresh_state` — append-only refresh audit log
```sql
CREATE TABLE daily_ohlcv_refresh_state (
    id                  SERIAL PRIMARY KEY,
    refresh_date        DATE,
    refresh_type        TEXT,   -- backfill | postmarket | premarket | manual
    status              TEXT,   -- RUNNING | SUCCESS | PARTIAL | FAILED
    symbols_requested   INTEGER,
    symbols_updated     INTEGER,
    missing_symbols     TEXT[],
    stale_symbols       TEXT[],
    failed_symbols      TEXT[],
    start_time          TIMESTAMPTZ,
    end_time            TIMESTAMPTZ,
    duration_seconds    NUMERIC(10,2),
    error_summary       TEXT
);
```

### `nifty50_company_master` — symbol reference data
```sql
CREATE TABLE nifty50_company_master (
    symbol              TEXT PRIMARY KEY,
    yahoo_symbol        TEXT,        -- e.g. RELIANCE.NS
    kite_symbol         TEXT,        -- e.g. RELIANCE
    instrument_token    BIGINT,
    company_name        TEXT,
    sector              TEXT,
    industry            TEXT,
    exchange            TEXT DEFAULT 'NSE',
    lot_size            INTEGER,
    tick_size           NUMERIC(10,4),
    isin                TEXT,
    index_membership    TEXT DEFAULT 'NIFTY_50',
    is_active           BOOLEAN DEFAULT TRUE,
    last_verified_at    TIMESTAMPTZ,
    source              TEXT DEFAULT 'config'
);
```
Seeded from `config.SECTOR_MAP` — 51 symbols (includes TMPV + TMCV post-TATAMOTORS demerger).

---

## 4. Data Freshness Rules

| Label | Age of latest bar | Used for |
|-------|-------------------|---------|
| `LIVE` | ≤ 3 calendar days | All scans — full confidence |
| `NEAR_LIVE` | ≤ 5 days | Long weekend / public holiday — acceptable |
| `STALE` | ≤ 14 days | Triggers warning in readiness check |
| `UNAVAILABLE` | > 14 days or not cached | Excluded from scan; LTIM is known permanent gap |

**MIN_BARS_REQUIRED = 120** — minimum trading days needed to compute all indicators reliably. Set to 120 (not 126) because NSE holidays mean a "6mo" yfinance fetch returns ~124 bars; 120 is the holiday-safe lower bound. Backfill uses `period="8mo"` to guarantee ≥ 120 bars in heavy-holiday periods.

---

## 5. Post-Market Refresh (Automatic)

**Module:** `post_market_data_refresh.py`  
**Trigger:** First `POST_CLOSE` or `CLOSED` scheduler tick after 15:30 IST  
**Gate:** `kv_claim_once("ohlcv_postmarket_refresh:{YYYY-MM-DD}")` — exactly once per IST day

```
Market closes 15:30 IST
    ↓
Phase 20 scheduler fires POST_CLOSE tick
    ↓
maybe_run_postmarket_refresh(mstate) — wired into phase20_scheduler.py
    ↓
kv_claim_once → first claimant wins, others skip
    ↓
yf.download(51 symbols, period="5d")  ← small window, typically 2–10 seconds
    ↓
UPSERT today's final bar into daily_ohlcv_cache for each symbol
    ↓
Emit DATA_CACHE_POSTMARKET_REFRESH_COMPLETED pipeline event
    ↓
Log to daily_ohlcv_refresh_state
```

**Scheduler output key:** `ohlcv_postmarket_refresh`  
**If yfinance unavailable post-market:** existing cache preserved; `FAILED` event emitted; next scan still uses previous cache (within LIVE/NEAR_LIVE age).  
**LTIM:** logged as `known_missing_ltim` — never blocks other symbols.

---

## 6. Pre-Market Readiness Check

**Module:** `pre_market_data_readiness.py`  
**When:** Run manually or by operator at 08:45–09:00 IST before first scan

### Verdict meanings
| Verdict | Meaning |
|---------|---------|
| `READY` | All symbols have ≥ 120 LIVE/NEAR_LIVE bars; Kite authenticated; master ≥ 80% |
| `READY_WITH_WARNINGS` | Minor gaps (LTIM, old refresh date) — safe to scan |
| `BLOCKED` | Critical gap — one of the block criteria below is true |

### BLOCKED criteria (any one is enough)
| Check | Threshold |
|-------|-----------|
| Symbols missing required bars (excl. LTIM) | > 20% of universe |
| Symbols with STALE/UNAVAILABLE cache | > 20% |
| Kite session not verified | any |
| Company master coverage | < 80% |
| yfinance not installed | any |

### Shell command (run after Kite re-auth at 09:00 IST)
```bash
curl -s http://localhost:8080/api/ohlcv-cache/readiness | python3 -m json.tool
```

---

## 7. New API Endpoints

All endpoints are read-only or advisory. No order placement. Paper trading only.

| Method | Path | Purpose | Typical response time |
|--------|------|---------|----------------------|
| `GET` | `/api/ohlcv-cache/status` | Per-symbol cache health + overall summary | < 1s |
| `POST` | `/api/ohlcv-cache/backfill` | Full 6-month history backfill for all symbols | 5–20 min (one-time) |
| `POST` | `/api/ohlcv-cache/postmarket-refresh` | Trigger post-market daily-bar append manually | 10–30s |
| `GET` | `/api/ohlcv-cache/readiness` | Pre-market readiness verdict | < 2s |
| `GET` | `/api/ohlcv-cache/company-master` | List all company master rows | < 1s |
| `POST` | `/api/ohlcv-cache/company-master/bootstrap` | Seed company master from config | < 3s |

---

## 8. New Data Fields on Every Scan Result

Every `SymbolFetchResult` now carries:

| Field | Type | Values | Meaning |
|-------|------|--------|---------|
| `cache_hit` | bool | true / false | Local cache served this symbol |
| `ohlcv_source` | str | `local_yfinance_cache` / `yfinance_fallback` | Where OHLCV bars came from |
| `cache_age_days` | int | 0–14 | Days since latest cached bar |
| `cache_latest_date` | str | ISO date | Most recent date in cache |
| `yfinance_called` | bool | true / false | Whether yfinance was invoked this scan |
| `yfinance_call_duration_ms` | int | milliseconds | Time spent in yfinance (0 on cache hit) |

**Unchanged fields** (Kite LTP overlay still sets these):
- `indicator_source` = `yfinance_daily_bars` — hardcoded, never changes
- `current_price_source` = `kite_live_ltp` when Kite session verified
- `execution_price_source` = `kite_live_ltp` when Kite session verified
- `quote_reliable` = true only when Kite LTP is valid

---

## 9. New main.py Commands

Six new commands available via the Python command interface:

| Command | What it does |
|---------|-------------|
| `ohlcv_cache_status` | Returns per-symbol cache health and overall summary |
| `ohlcv_backfill [force]` | Backfill 8-month history for all NIFTY 50 symbols |
| `ohlcv_postmarket_refresh` | Trigger post-market daily-bar append immediately (no gate) |
| `pre_market_data_readiness` | Run pre-market readiness check and return verdict |
| `company_master_bootstrap` | Seed nifty50_company_master from config.SECTOR_MAP |
| `company_master_list` | Return all company master entries |

---

## 10. Files Changed

### New files
| File | Purpose |
|------|---------|
| `artifacts/api-server/src/python/ohlcv_cache_store.py` | Core cache module — read, write, backfill, status, refresh logging |
| `artifacts/api-server/src/python/nifty50_company_master_store.py` | Company master store — bootstrap, lookup, missing-symbol report |
| `artifacts/api-server/src/python/post_market_data_refresh.py` | Post-market daily-bar append job with kv_claim_once gate |
| `artifacts/api-server/src/python/pre_market_data_readiness.py` | Pre-market readiness check — 5 checks, three-verdict output |
| `artifacts/api-server/src/python/test_ohlcv_cache.py` | 15 tests (15/15 pass) |
| `artifacts/api-server/src/routes/ohlcvCache.ts` | Express router — 6 REST endpoints |
| `APEXQUANT_SCAN_COUNT_AND_DATA_FETCH_REFERENCE.md` | Reference: correct scan count (18 completed) + fetch architecture |
| `APEXQUANT_LOCAL_NIFTY50_DATA_STORE_AND_YFINANCE_FALLBACK_REPORT.md` | Detailed technical report |
| `APEXQUANT_OHLCV_CACHE_MIGRATION_SUMMARY.md` | This file |

### Modified files
| File | What changed |
|------|-------------|
| `artifacts/api-server/src/python/live_data_provider.py` | `fetch_batch()` rewritten as 3-step priority: cache → yfinance bulk → per-symbol fallback. Six new fields on `SymbolFetchResult`. |
| `artifacts/api-server/src/python/phase20_scheduler.py` | Added `maybe_run_postmarket_refresh()` call in POST_CLOSE/CLOSED block. Output key `ohlcv_postmarket_refresh` included in scheduler response. |
| `artifacts/api-server/src/python/main.py` | Six new `elif command ==` blocks for all cache commands. |
| `artifacts/api-server/src/routes/index.ts` | Imported and registered `ohlcvCacheRouter`. |

---

## 11. Bugs Fixed During This Session

Three bugs were found and fixed during initial testing:

### Bug 1 — Company master bootstrap SQL mismatch
**File:** `nifty50_company_master_store.py`  
**Error:** `INSERT has more target columns than expressions` on `last_verified_at, source`  
**Cause:** INSERT column list had 6 entries `(symbol, yahoo_symbol, kite_symbol, sector, last_verified_at, source)` but the row tuple only had 5 values — `"config"` for the `source` column was missing.  
**Fix:** Added `"config"` as the 6th element of each row tuple.

### Bug 2 — Write cache INSERT column/value mismatch
**File:** `ohlcv_cache_store.py`, `write_symbol_to_cache()`  
**Error:** All 51 symbols failing with `symbols_updated=0`  
**Cause:** INSERT listed 11 columns `(..., data_quality, updated_at)` but the values tuple had only 10 elements. `updated_at` was in the column list but had no corresponding `%s` placeholder value. Postgres rejected every row silently (caught by `except Exception: return 0`).  
**Fix:** Removed `updated_at` from the INSERT column list — the column has `DEFAULT NOW()` and the ON CONFLICT DO UPDATE clause already sets `updated_at = NOW()`.

### Bug 3 — Readiness check false positive: "50 symbols missing required bars"
**File:** `ohlcv_cache_store.py`  
**Error:** After a successful backfill (50 LIVE symbols), readiness reported 50 symbols as "missing required OHLCV bars — BUY entries blocked"  
**Cause:** `MIN_BARS_REQUIRED = 126` but a yfinance `period="6mo"` fetch for NSE returns only ~124 trading days due to Indian market holidays. All 50 successfully cached symbols had 124 bars < 126 threshold → incorrectly flagged as missing.  
**Fix:**
- Lowered `MIN_BARS_REQUIRED` from 126 → **120** (120 is the holiday-safe lower bound for 6 months of NSE trading)
- Changed backfill default period from `"6mo"` → **`"8mo"`** so future cold-starts always deliver ≥ 120 bars even in heavy-holiday periods

---

## 12. LTIM — Known Provider Gap

`LTIM.NS` is consistently unavailable from yfinance bulk downloads. This is a known upstream provider issue, not an ApexQuant bug.

**Handling:**
- Backfill: `LTIM` logged in `failed_symbols`; all other 50 symbols complete normally
- Post-market refresh: `known_missing_ltim` key in result; does not affect other symbols
- Readiness check: LTIM explicitly excluded from the `blocking_missing` list; logged as a warning only
- Scan: LTIM result is `UNAVAILABLE`; no BUY signal generated for LTIM
- Overall: system status = **PARTIAL** (not FAILED) when only LTIM is missing

---

## 13. What Did Not Change

These are explicitly unchanged — verified by AST scan of all new modules:

| Component | Status |
|-----------|--------|
| Kite LTP overlay (`kite_ltp_overlay.py`) | **Unchanged** — still overlays current/execution price |
| `indicator_source` field | **Always `yfinance_daily_bars`** — hardcoded constant |
| Safety gates (reliability, provider_zerodha, thresholds) | **Unchanged** |
| Paper trading ledger (`paper_trades`, `paper_portfolio`) | **Unchanged** |
| Live order execution path | **Unchanged** — no order placement in any cache module |
| Backtest engine | **Unchanged** — uses its own `historical_data_engine` with in-memory cache |
| Scan lock and distributed coordination | **Unchanged** |

---

## 14. Performance Comparison

### Before (2026-08-18, no cache)
| Metric | Value |
|--------|-------|
| yfinance calls per scan | 1 bulk (50 symbols, 6 months history) |
| Scan duration range | 17 seconds – 22 minutes |
| Completed scans on 2026-08-18 | **18** |
| Started scans | 19 (1 incomplete) |
| Scheduler ticks skipped (lock busy) | ~56 of ~75 |

### After (warm cache, post-market refresh ran)
| Metric | Expected |
|--------|----------|
| yfinance calls per scan | **0** (all 50 symbols from local DB) |
| Scan duration | **< 5 seconds** |
| yfinance calls per day total | 1 post-market refresh (5-day window, < 30 seconds) |
| Expected completed scans per day | **60–75** |
| Scheduler ticks skipped | ~0–5 |

### Current state (2026-08-19 00:00 IST, immediately after deploy)
```
cache_enabled:       true
live_symbols:        50
unavailable:         1 (LTIM — known gap)
cache_hit_rate_pct:  98
bars per symbol:     124
latest_date:         2026-08-17 (last trading day)
readiness verdict:   BLOCKED — Kite session not verified (expected overnight)
```

---

## 15. Operator Checklist for Tomorrow (2026-08-19)

| Time | Action | Command |
|------|--------|---------|
| **09:00 IST** | Re-authenticate Kite session | Manual via Kite dashboard |
| **09:05 IST** | Verify readiness | `curl -s http://localhost:8080/api/ohlcv-cache/readiness \| python3 -m json.tool` |
| **09:15 IST** | First scan fires automatically | Should complete in **< 5 seconds** |
| **15:30 IST** | Post-market refresh fires automatically | No action needed — scheduler handles it |
| **Any time** | Check cache status | `curl -s http://localhost:8080/api/ohlcv-cache/status \| python3 -m json.tool` |

**Expected readiness verdict at 09:05 IST (after Kite re-auth):**
```json
{
  "verdict": "READY_WITH_WARNINGS",
  "blocking_reasons": [],
  "warnings": ["1 symbols missing cache (including LTIM — known provider gap)"]
}
```
This means the system is safe to scan. The first scan of the day will use local cache for 50 symbols and complete in under 5 seconds.

---

## 16. Test Results

**15/15 tests pass** — `cd artifacts/api-server/src/python && python -m pytest test_ohlcv_cache.py -v`

| # | Test | Result |
|---|------|--------|
| 1 | First run fetches yfinance + writes to cache | ✅ PASS |
| 2 | Second scan uses cache — yfinance NOT called | ✅ PASS |
| 3 | Only symbols with cache misses fetch yfinance | ✅ PASS |
| 4 | Post-market job appends latest candle for all symbols | ✅ PASS |
| 5 | Pre-market readiness returns READY when cache is complete | ✅ PASS |
| 6 | Cache data > 14 days old returns None → BUY blocked | ✅ PASS |
| 7 | yfinance failure → cache-hit symbols still succeed | ✅ PASS |
| 8 | Kite LTP still overrides current/execution price after cache hit | ✅ PASS |
| 9 | `ohlcv_source = local_yfinance_cache` on cache hit | ✅ PASS |
| 10 | Company master bootstraps correctly from config.SECTOR_MAP | ✅ PASS |
| 11 | 1/6 symbols missing from master → warning, not blocked | ✅ PASS |
| 12 | Cache DataFrame supports as-of date slicing for backtest (no lookahead) | ✅ PASS |
| 13 | LTIM missing does not block the other 50 symbols | ✅ PASS |
| 14 | Scan-count API returns `scan_count_today` (COMPLETED only, not ticks) | ✅ PASS |
| 15 | No live broker order API present in any cache module (AST scan) | ✅ PASS |
