# ApexQuant AI — Local NIFTY 50 Data Store & yfinance Fallback Report
**Date:** 2026-08-18 (post-session)  
**System:** https://nse-trade-intraday.replit.app  
**Status:** PAPER TRADING ONLY — no live orders, no broker API calls  

---

## 1. Current Scan-Count Truth

**Confirmed from production `pipeline_events` DB (2026-08-18):**

| Metric | Count | Source |
|--------|-------|--------|
| Scheduler ticks fired | ~75 | Every 5-min clock pulse (including skipped) |
| SCAN_STARTED events | **19** | Scans that acquired the lock and began |
| SCAN_COMPLETED events | **18** | Scans that fully finished ← **authoritative** |
| Incomplete scans | 1 | `bf004caf48b5` started 09:36 IST, never completed |
| Yesterday (2026-08-17) | 23 completed / 25 started | Same pattern |

Full per-scan log: see `APEXQUANT_SCAN_COUNT_AND_DATA_FETCH_REFERENCE.md`.

---

## 2. Why Scan Count Is Low — Root Cause

The bottleneck is **`live_data_provider.fetch_batch()`**, which calls `yf.download(50 tickers, period="6mo")` on every single scan — no caching.

| Scan speed | Examples | Why |
|------------|---------|-----|
| 17–23 seconds (fast) | Scans 1–3, 5, 12–13, 16–17, 19 | yfinance data in Yahoo CDN cache |
| 3–13 minutes (medium) | Scans 6, 7, 8, 14, 15, 18 | Partial cache miss |
| 19–22 minutes (slow) | Scans 9, 10, 11 | Full 6-month history download for 50 .NS symbols |

While a slow scan runs, its lock is held. The next 5-minute scheduler ticks fire and log "lock busy" — they skip. Only after the slow scan releases the lock can a new one start.

**The "77 scans"** figure in the FINAL_PUBLISH doc was the scheduler's internal tick counter. The DB has never had 77 `SCAN_COMPLETED` events in a session.

---

## 3. Current yfinance Fetch Bottleneck

Every scan calls:
```python
# live_data_provider.py — fetch_batch()
yf.download(50_tickers, period="6mo", interval="1d", group_by="ticker", threads=True)
```

- **1 bulk call per scan** for all 50 NIFTY 50 symbols
- Fetches **~126 rows × 50 symbols = 6,300 rows** of daily OHLCV per scan
- The same 6,300 rows are fetched again 5 minutes later, unchanged
- None of the data is cached between scans
- yfinance has no timeout configured — a slow Yahoo response holds the lock for 22+ minutes

---

## 4. New Local OHLCV Cache Schema

### `daily_ohlcv_cache` (primary store)
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
    data_quality    TEXT,
    PRIMARY KEY (symbol, trading_date)
);
```

### `daily_ohlcv_refresh_state` (audit log)
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

---

## 5. New Company Master Schema

### `nifty50_company_master`
```sql
CREATE TABLE nifty50_company_master (
    symbol              TEXT PRIMARY KEY,
    yahoo_symbol        TEXT,      -- e.g. RELIANCE.NS
    kite_symbol         TEXT,      -- e.g. RELIANCE
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

**Seeded from** `config.SECTOR_MAP` (51 symbols including TMPV + TMCV post-demerger).  
**LTIM** included but flagged as known provider gap.  
**Refresh policy:** weekly or on manual trigger via `POST /ohlcv-cache/company-master/bootstrap`.

---

## 6. Post-Market Refresh Design

**Module:** `post_market_data_refresh.py`  
**Trigger:** First `POST_CLOSE` or `CLOSED` scheduler tick after 15:30 IST  
**Gate:** `kv_claim_once("ohlcv_postmarket_refresh:{YYYY-MM-DD}")` — exactly once per IST day  

```
POST_CLOSE tick fires (15:30 IST)
    ↓
kv_claim_once → first claimant wins
    ↓
yf.download(50 symbols, period="5d", interval="1d")  ← small window, fast
    ↓
UPSERT into daily_ohlcv_cache (latest 5 days per symbol)
    ↓
Emit DATA_CACHE_POSTMARKET_REFRESH_COMPLETED pipeline event
    ↓
Log to daily_ohlcv_refresh_state
```

**If yfinance is unavailable post-market:**  
- Existing cache is preserved  
- `DATA_CACHE_POSTMARKET_REFRESH_FAILED` event emitted  
- Next scan still uses previous cache (within safe age)  
- LTIM missing is logged separately as known provider gap, not a failure

---

## 7. Pre-Market Readiness Design

**Module:** `pre_market_data_readiness.py`  
**When:** Callable at any time; intended 08:45–09:00 IST via operator or scheduler  
**Output:** `READY` / `READY_WITH_WARNINGS` / `BLOCKED`

### BLOCKED criteria (any one triggers block):
| Condition | Threshold |
|-----------|-----------|
| Symbols missing required bars | > 20% of universe |
| Symbols with STALE/UNAVAILABLE cache | > 20% |
| Kite session not verified | any |
| Company master coverage | < 80% |
| yfinance not installed | any |

### Checks performed:
1. Per-symbol cache completeness (≥126 bars, ≤3 days old)
2. Kite session verification status
3. Company master coverage
4. yfinance fallback availability
5. Date of last post-market refresh

---

## 8. Fetch Policy: Local First, yfinance Fallback

### Modified `live_data_provider.fetch_batch()` — three-step priority:

```
STEP 1: Check local daily_ohlcv_cache (< 1 second for all 50 symbols)
  ├── Cache HIT + fresh (≤3 days) → use cached DataFrame
  │     result.cache_hit = True
  │     result.ohlcv_source = "local_yfinance_cache"
  │     result.yfinance_called = False
  └── Cache MISS or stale → add to `remaining` list

STEP 2: yfinance bulk download for `remaining` only
  yf.download(remaining_tickers, period="6mo", ...)
  → Write results back to daily_ohlcv_cache
  → result.ohlcv_source = "yfinance_fallback"
  → result.yfinance_called = True

STEP 3: Per-symbol fallback for bulk stragglers
  fetch_symbol(sym) → write to cache
```

**On a warm cache day** (post-market refresh ran the evening before):  
Step 1 serves all 50 symbols. Steps 2 and 3 are skipped entirely.  
**Expected scan duration: < 5 seconds** (vs 7–22 minutes today).

---

## 9. Data-Source Labels

Every scan record now carries:

| Field | Values | Meaning |
|-------|--------|---------|
| `ohlcv_source` | `local_yfinance_cache` / `yfinance_fallback` | Where OHLCV bars came from |
| `indicator_source` | Always `yfinance_daily_bars` | Indicators always from yfinance-origin data |
| `current_price_source` | `kite_live_ltp` / `yfinance_daily_bars` | Live vs close price |
| `execution_price_source` | `kite_live_ltp` / `yfinance_daily_bars` | Entry/exit price source |
| `cache_hit` | `true` / `false` | Local cache served this symbol |
| `cache_age_days` | integer | Days since latest cached bar |
| `cache_latest_date` | ISO date | Most recent date in cache |
| `yfinance_called` | `true` / `false` | Whether yfinance was invoked |
| `yfinance_call_duration_ms` | integer | Time spent in yfinance for this symbol |

---

## 10. Backtesting Compatibility

- `backtesting_engine.py` uses `market_data_engine._fetch_yfinance()` (separate path)
- `backtest_runner.py` and `backtest_replay.py` use `historical_data_engine` with in-memory `daily_cache` — unaffected by this change
- `daily_ohlcv_cache` can optionally supply backtest as-of slices:
  - Caller slices the DataFrame to the as-of date: `df[df.index.date <= cutoff]`
  - No lookahead possible — cache only stores past confirmed closes
  - Cache source and date range must be written into backtest report (existing behaviour)
- Backtest replay does not pollute live paper analytics — replay ledger is isolated

---

## 11. Performance Before / After

### Before (today's baseline)
| Metric | Value |
|--------|-------|
| yfinance calls per scan | 1 bulk (up to 151 on fallback) |
| Scan duration P50 | ~20 seconds (fast) to 22 minutes (slow) |
| Scan duration P95 | >20 minutes |
| Completed scans per day | **18–25** |
| Scheduler ticks skipped | ~56 of 75 (lock busy during slow scans) |
| Cache hit rate | 0% (no cache) |

### After (warm cache — post-market refresh complete)
| Metric | Expected |
|--------|----------|
| yfinance calls per scan | **0** (cache serves all 50 symbols) |
| Scan duration | **< 5 seconds** (Step 1 only) |
| yfinance per-day calls | 1 post-market refresh (5d window, all 50 symbols) |
| Completed scans per day | **60–75** (approaching 5-min cadence) |
| Scheduler ticks skipped | ~0–5 (lock released in < 5s) |
| Cache hit rate | **~98%** (LTIM known gap = 1 miss) |

### Transition day (first day after deploy)
- **First scan:** cache empty → full yfinance backfill → 7–22 minutes (one-time)
- **Second scan onwards:** cache warm → < 5 seconds
- **Post-market:** refresh appends today's final bar → tomorrow ready from scan 1

---

## 12. Test Results

**15/15 tests pass** after fixes.

| # | Test | Result |
|---|------|--------|
| 1 | First run fetches yfinance + writes cache | ✅ PASS |
| 2 | Second scan uses cache, no yfinance call | ✅ PASS |
| 3 | Missing bars → only missing symbols fetch yfinance | ✅ PASS |
| 4 | Post-market job appends latest candle | ✅ PASS |
| 5 | Pre-market readiness detects complete cache | ✅ PASS |
| 6 | Stale cache (20 days old) returns None → BUY blocked | ✅ PASS |
| 7 | yfinance failure → cache-hit symbols still succeed | ✅ PASS |
| 8 | Kite LTP overrides current/execution price post-cache-hit | ✅ PASS |
| 9 | `ohlcv_source = local_yfinance_cache` on cache hit | ✅ PASS |
| 10 | Company master bootstraps from `config.SECTOR_MAP` | ✅ PASS |
| 11 | 1/6 missing company master → warning, not blocked | ✅ PASS |
| 12 | Cache DataFrame can be sliced as-of for backtest (no lookahead) | ✅ PASS |
| 13 | LTIM missing does not block other 50 symbols | ✅ PASS |
| 14 | Scan-count API returns `scan_count_today` (COMPLETED) + `rotation` | ✅ PASS |
| 15 | No live broker order API in any cache module | ✅ PASS |

---

## 13. Migration / Backfill Status

### On first deploy:
```
POST /ohlcv-cache/backfill          ← initial 6-month history for all 50 symbols
POST /ohlcv-cache/company-master/bootstrap  ← seed from config.SECTOR_MAP
```

**Tables auto-created** by `ensure_tables()` / `ensure_table()` on first call.  
**No existing data touched** — `scan_state`, `paper_trades`, `pipeline_events` are unaffected.  
**Backfill throttle:** runs as one `yf.download()` bulk call — takes 5–20 minutes once.  
**If run during market hours:** existing cache is used for the running scan; backfill for missing symbols only.

### Ongoing:
| Job | When | How |
|-----|------|-----|
| Post-market refresh | POST_CLOSE/CLOSED tick | `kv_claim_once` — once per IST day |
| Pre-market check | 08:45–09:00 IST (manual or scheduled) | `GET /ohlcv-cache/readiness` |
| Company master refresh | Weekly or manual | `POST /ohlcv-cache/company-master/bootstrap` |
| Full backfill | Manual only | `POST /ohlcv-cache/backfill?force=true` |

---

## 14. UI / API Updates

### New API endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/ohlcv-cache/status` | Per-symbol cache health + overall summary |
| POST | `/api/ohlcv-cache/backfill` | Trigger full 6-month backfill |
| POST | `/api/ohlcv-cache/postmarket-refresh` | Trigger post-market daily-bar append |
| GET | `/api/ohlcv-cache/readiness` | Pre-market readiness verdict |
| GET | `/api/ohlcv-cache/company-master` | List all company master entries |
| POST | `/api/ohlcv-cache/company-master/bootstrap` | Seed master from config |

### Dashboard fields now available for display:

| Field | Where to show |
|-------|--------------|
| `ohlcv_source` | Mission Control scan chip, Live Data Health |
| `cache_hit_rate_pct` | Mission Control scan info, AI Paper Trader |
| `latest_cached_date` | Mission Control, System Readiness |
| `last_postmarket_refresh` | Mission Control, Live Data Health |
| `yfinance_called_this_scan` | Live Data Health debug panel |
| `cache_age_days` | Per-symbol detail on scan result |
| Scan-count wording | Completed scans ≠ scheduler ticks — both shown separately |

### Corrected scan-count wording (all pages):
- **Completed scans** = `SCAN_COMPLETED` count from `pipeline_events` (authoritative)
- **Started scans** = `SCAN_STARTED` count (includes 1 incomplete per session typical)
- **Scheduler ticks** = every 5-minute clock pulse fired (most are lock-skipped)
- **After cache:** completed scans should approach 60–75/day (close to tick count)

---

## 15. Tomorrow-Readiness Verdict

| Check | Status |
|-------|--------|
| Cache tables created | ✅ Auto on first API call |
| Company master bootstrap | ⚠️ Run `POST /ohlcv-cache/company-master/bootstrap` once |
| Initial backfill | ⚠️ Run `POST /ohlcv-cache/backfill` tonight (5–20 min, once only) |
| Post-market refresh wired | ✅ Fires automatically on POST_CLOSE/CLOSED tick |
| Pre-market readiness check | ✅ Available at `GET /ohlcv-cache/readiness` |
| Kite session re-verify 09:00 IST | ⚠️ Manual — re-authenticate before first scan |

**If backfill runs tonight:** tomorrow's first scan will use local cache and complete in < 5 seconds.  
**Expected scan count 2026-08-19:** 60–75 completed scans (vs 18 today).

---

## 16. Kite Remains Live Execution Price Source

This change does **not** alter the Kite LTP overlay:

- `indicator_source` = `yfinance_daily_bars` — **unchanged, hardcoded**
- `ohlcv_source` = `yfinance_daily_bars` (origin) / `local_yfinance_cache` (storage) — **same data, different cache layer**
- `current_price_source` = `kite_live_ltp` when Kite session is verified — **unchanged**
- `execution_price_source` = `kite_live_ltp` when Kite session is verified — **unchanged**
- `quote_reliable` = `true` only when Kite LTP is valid — **unchanged**
- Kite LTP overlay still runs as Phase 2B after cache-served indicators — **unchanged**

Kite's role (live entry/exit price) is entirely separate from the OHLCV cache (historical indicator data). The cache only optimises the indicator data path.

---

## 17. Confirmation: No Live Orders

All modules in this implementation are explicitly read-only or advisory:

| Module | Order API calls |
|--------|----------------|
| `ohlcv_cache_store.py` | ❌ None |
| `nifty50_company_master_store.py` | ❌ None |
| `post_market_data_refresh.py` | ❌ None |
| `pre_market_data_readiness.py` | ❌ None |
| Modified `live_data_provider.py` | ❌ None |
| Modified `phase20_scheduler.py` | ❌ None (post-market hook only) |

Test 15 (`test_no_live_broker_order_api_called`) performs an AST scan of all four new modules for any order-placement patterns and confirms zero matches.

---

## New Files

| File | Purpose |
|------|---------|
| `artifacts/api-server/src/python/ohlcv_cache_store.py` | DB-backed OHLCV cache read/write/backfill |
| `artifacts/api-server/src/python/nifty50_company_master_store.py` | Company master store |
| `artifacts/api-server/src/python/post_market_data_refresh.py` | Post-market daily-bar append job |
| `artifacts/api-server/src/python/pre_market_data_readiness.py` | Pre-market readiness check |
| `artifacts/api-server/src/python/test_ohlcv_cache.py` | 15 tests (15/15 pass) |
| `artifacts/api-server/src/routes/ohlcvCache.ts` | 6 new API routes |
| `APEXQUANT_LOCAL_NIFTY50_DATA_STORE_AND_YFINANCE_FALLBACK_REPORT.md` | This report |

## Modified Files

| File | Change |
|------|--------|
| `live_data_provider.py` | Cache-first `fetch_batch()`; new fields on `SymbolFetchResult` |
| `phase20_scheduler.py` | Post-market OHLCV refresh wired to POST_CLOSE/CLOSED tick |
| `main.py` | 6 new commands: `ohlcv_cache_status`, `ohlcv_backfill`, `ohlcv_postmarket_refresh`, `pre_market_data_readiness`, `company_master_bootstrap`, `company_master_list` |
| `routes/index.ts` | `ohlcvCacheRouter` imported and registered |
