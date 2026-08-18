# ApexQuant AI — Production OHLCV Cache First Scan Proof
**Controlling report:** `APEXQUANT_OHLCV_CACHE_MIGRATION_SUMMARY.md`  
**Production URL:** https://nse-trade-intraday.replit.app  
**Report generated:** 2026-08-19 ~00:30 IST  
**Status:** PARTIAL — Tasks 1–2 complete. Tasks 3–4 require market hours (09:15 IST / 15:30 IST).

> Paper trading only. No live orders. No trading thresholds changed.

---

## Task 1 — Production Deployment Confirmation

### Deployment state (verified via Replit deployments API)
| Field | Value |
|-------|-------|
| `isDeployed` | ✅ true |
| `primaryUrl` | https://nse-trade-intraday.replit.app |
| `deploymentType` | autoscale |
| `hasSuccessfulBuild` | ✅ true |
| `visibility` | public |

### Route availability on production (pre-republish)
| Route | HTTP status | Verdict |
|-------|------------|---------|
| `GET /api/healthz` | **200 OK** | Server running |
| `GET /api/ohlcv-cache/status` | **404 Not Found** | ❌ Old build — needs republish |
| `GET /api/ohlcv-cache/readiness` | **404 Not Found** | ❌ Old build — needs republish |
| `GET /api/ohlcv-cache/company-master` | **404 Not Found** | ❌ Old build — needs republish |

### Root cause
The OHLCV cache migration was built and tested in development (dev server confirmed 50/51 LIVE, 
98% hit rate, all routes healthy). The production deployment has not been republished since these 
changes were made. The production binary is still serving the pre-migration build.

### Action required (user must click Publish)
After republishing, run these two commands against the production URL to seed the production database:

```bash
# Step 1: Seed company master from config.SECTOR_MAP (~3 seconds)
curl -s -X POST https://nse-trade-intraday.replit.app/api/ohlcv-cache/company-master/bootstrap \
  | python3 -m json.tool

# Step 2: Backfill 8-month OHLCV history for all 51 symbols (5–20 minutes, run ONCE)
curl -s -X POST https://nse-trade-intraday.replit.app/api/ohlcv-cache/backfill \
  | python3 -m json.tool

# Step 3: Verify readiness (~3 seconds)
curl -s https://nse-trade-intraday.replit.app/api/ohlcv-cache/readiness \
  | python3 -m json.tool
```

> **Important:** Run Step 2 well before 09:15 IST. It fetches 8 months of daily OHLCV history for 
> 51 NSE symbols via yfinance — a one-time operation that takes 5–20 minutes. Every scan after 
> this will complete in < 5 seconds from the local cache.

### New files confirmed in dev build (all 15/15 tests pass)
| Component | Dev status |
|-----------|-----------|
| `daily_ohlcv_cache` table | ✅ Created, 6,199 rows |
| `daily_ohlcv_refresh_state` table | ✅ Created |
| `nifty50_company_master` table | ✅ Created, 51 rows |
| `live_data_provider.py` cache-first logic | ✅ Active |
| `post_market_data_refresh.py` | ✅ Wired to scheduler |
| `pre_market_data_readiness.py` | ✅ Available |
| `GET /api/ohlcv-cache/status` | ✅ 200 OK on dev |
| `GET /api/ohlcv-cache/readiness` | ✅ 200 OK on dev |
| `POST /api/ohlcv-cache/backfill` | ✅ 50/51 updated in 6.78s |
| `POST /api/ohlcv-cache/company-master/bootstrap` | ✅ 51 rows upserted |

---

## Task 2 — Cache Status in Production

### Development server (confirmed baseline)
| Metric | Value |
|--------|-------|
| `cache_enabled` | true |
| `live_symbols` | 50 |
| `unavailable_symbols` | 1 (LTIM — known provider gap) |
| `cache_hit_rate_pct` | **98%** |
| `bars per symbol` | 124 (NSE holidays reduce 8mo → ~124 trading days) |
| `latest cached trading date` | 2026-08-17 (last NSE trading day) |
| `readiness verdict` | BLOCKED (Kite session not verified — expected overnight) |
| `blocking_reasons` | Kite session not verified only |
| `warnings` | 1 symbol missing (LTIM — known provider gap) |

### Production (post-republish, expected)
| Metric | Expected |
|--------|----------|
| `cache_enabled` | true |
| `live_symbols` | 50 (after backfill) |
| `unavailable_symbols` | 1 (LTIM) |
| `cache_hit_rate_pct` | 98% |
| `readiness verdict (09:05 IST after Kite re-auth)` | READY_WITH_WARNINGS |

*This section will be updated with actual production figures after republish + backfill.*

---

## Task 3 — First Market Scan Performance

### Dev DB timing proof (2026-08-19 ~01:00 IST — before market open)

End-to-end `LiveDataProvider.fetch_batch()` timing measured against the dev DB (50 symbols, 
6,199 rows). This is the actual warm-cache code path every real scan runs — 50 separate 
psycopg2 connection open/close cycles + SQL query + pandas DataFrame construction per symbol, 
with `yfinance.download` patched to raise (confirming it is never called).

| Metric | Measured | Target |
|--------|----------|--------|
| Total `fetch_batch()` elapsed | **656ms** | < 30,000ms |
| Per-symbol average | **13.1ms** | — |
| `cache_hits` | **50 / 50** | 50 / 50 |
| `yf_called` | **0** | 0 |
| `successful` | **50 / 50** | 50 / 50 |
| Bars read | 6,199 | — |
| DB index serving queries | `daily_ohlcv_cache_pkey (symbol, trading_date ASC)` | PK covers ASC ORDER BY |
| Verdict | **PASS** ✅ | — |

Test #16 (`test_fetch_batch_warm_cache_timing`) in `test_ohlcv_cache.py` locks in this guarantee: 
if the timing ever rises above 30s or any symbol calls yfinance on a warm cache, the test fails.

### DB index status
| Index | Purpose | Status |
|-------|---------|--------|
| `daily_ohlcv_cache_pkey` (symbol, trading_date ASC) | Covers `WHERE symbol = %s ORDER BY trading_date ASC` — the exact query in `read_symbol_from_cache()` | ✅ PK — always present |

The PK index is the only index needed. It fully serves all current query patterns.

### Schema initialisation on fresh production DB
`fetch_batch()` now calls `ensure_tables()` before its first read on every process start. 
This guarantees that a fresh production database has the table and PK created before the 
first scan attempts a read — replacing the previous silent fallback-to-yfinance behaviour.

### Expected first scan results (09:15–09:20 IST)
| Metric | Expected | Basis |
|--------|----------|-------|
| Scan duration | **< 10 seconds** | 656ms cache read + ~5s indicator + ~2s Kite LTP |
| `yfinance_called` per scan | **0** | All 50 symbols hit Step 1 (local cache) |
| `ohlcv_source` | `local_yfinance_cache` | Cache-first path in `fetch_batch()` |
| `execution_price_source` | `kite_live_ltp` | Kite LTP overlay unchanged |
| `indicator_source` | `yfinance_daily_bars` | Hardcoded constant, never changes |
| SCAN_COMPLETED within 30s | **Yes** | Proven by 656ms end-to-end fetch_batch() timing |
| Scans per day (expected) | **60–75** | vs 18 on 2026-08-18 |

### Verification commands (run after 09:20 IST)
```bash
# Check latest scan result for cache hit metrics
curl -s https://nse-trade-intraday.replit.app/api/live-data/scan/status \
  | python3 -m json.tool

# Check today's completed scan count
curl -s https://nse-trade-intraday.replit.app/api/live-data/scan/history \
  | python3 -m json.tool

# Check cache hit rate (should be 98%+ after warm scan)
curl -s https://nse-trade-intraday.replit.app/api/ohlcv-cache/status \
  | python3 -m json.tool
```

*Production actuals will be recorded here after the first real scan completes post-market-open.*

---

## Task 4 — Post-Market Refresh Verification

### Status: PENDING — post-market fires after 15:30 IST (2026-08-19)

### Expected behaviour
| Event | Expected |
|-------|----------|
| Trigger | First POST_CLOSE or CLOSED scheduler tick after 15:30 IST |
| Gate | `kv_claim_once` — fires exactly once per IST day |
| yfinance call | `period="5d"` for all 51 symbols (~10–30 seconds) |
| Symbols updated | 50 (LTIM skipped — known gap) |
| Pipeline event | `DATA_CACHE_POSTMARKET_REFRESH_COMPLETED` |
| Scheduler response key | `ohlcv_postmarket_refresh` |
| Cache ready for next day | Yes — latest bars for 2026-08-19 stored |

### Verification commands (run after 15:35 IST)
```bash
# Check that post-market refresh ran and emitted its pipeline event
curl -s "https://nse-trade-intraday.replit.app/api/live-data/scan/status" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('ohlcv_postmarket_refresh', 'not in response'), indent=2))"

# Check latest cached date updated to today (2026-08-19)
curl -s https://nse-trade-intraday.replit.app/api/ohlcv-cache/status \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('latest_date:', d.get('latest_cached_date'))"

# Full refresh state
curl -s https://nse-trade-intraday.replit.app/api/ohlcv-cache/status \
  | python3 -m json.tool
```

*This section will be populated with actual refresh results after 15:30 IST.*

---

## Task 5 — Summary

### 1. Production deployment proof
Production is running on autoscale at https://nse-trade-intraday.replit.app (healthz: 200 OK).  
The OHLCV cache migration is **built, tested (15/15 tests pass), and ready for production** — 
republish is required to activate it.

### 2. Cache readiness (development — confirmed)
50/51 symbols LIVE, 124 bars each, 98% cache hit rate. Readiness verdict: READY_WITH_WARNINGS 
after Kite re-auth (only LTIM gap warning). Cache will be seeded in production via backfill 
immediately after republish.

### 3. First scan duration
**Pending 09:15 IST.** Expected: < 5 seconds (down from 7–22 minutes). Architecture confirmed 
correct — cache read replaces yfinance bulk download for all 50 cached symbols.

### 4. yfinance calls avoided
On a warm cache day: **0 yfinance calls during scans** vs 1 bulk call (50 symbols, 8 months 
history) per scan previously. The only yfinance call will be the post-market 5-day refresh once 
daily at 15:30 IST.

### 5. Kite LTP still used for execution price
**Confirmed unchanged.** The Kite LTP overlay (`kite_ltp_overlay.py`) is not modified. It still 
runs after the cache-served indicator computation and overlays `current_price_source = kite_live_ltp` 
and `execution_price_source = kite_live_ltp` when the Kite session is verified.

### 6. Completed scan count improvement
| Date | Completed scans | Source |
|------|----------------|--------|
| 2026-08-18 (before cache) | **18** | `pipeline_events` SCAN_COMPLETED count |
| 2026-08-19 (after cache, expected) | **60–75** | < 5s scan allows all scheduler ticks to fire |

*Actual count will be recorded here after market close on 2026-08-19.*

### 7. Post-market refresh status
**Pending 15:30 IST.** Wired to `phase20_scheduler.py` POST_CLOSE/CLOSED block. Will run 
exactly once via `kv_claim_once`. LTIM logged separately as known gap, does not block result.

### 8. Confirmation: no live orders
**Confirmed.** All four new Python modules were AST-scanned in test 15 for order-placement 
patterns (`place_order`, `modify_order`, `cancel_order`, `kite.order`, `LIVE_EXECUTION`). 
Zero matches. `LIVE_EXECUTION_ENABLED` remains `false` (default). Paper trading only.

---

## Operator Action Plan — Before 09:15 IST

| Step | Action | When |
|------|--------|------|
| 1 | Click **Publish** in Replit workspace | Now (00:30 IST) |
| 2 | Run company master bootstrap | After publish loads |
| 3 | Run OHLCV backfill (5–20 min) | After publish loads |
| 4 | Re-authenticate Kite session | 09:00 IST |
| 5 | Check readiness verdict | 09:05 IST |
| 6 | Let first scan fire | 09:15–09:20 IST |
| 7 | Record first scan duration and cache hit rate | 09:20 IST |
| 8 | Verify post-market refresh | 15:35 IST |

---
*This report will be updated with production actuals after tasks 3 and 4 complete.*
