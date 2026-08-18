---
name: Local NIFTY 50 OHLCV Cache
description: Cache-first fetch architecture replacing per-scan yfinance bulk download; post-market refresh wiring; API routes and test conventions.
---

## Rule
All live scans must read from `daily_ohlcv_cache` (Postgres) before calling yfinance. yfinance is a fallback for cache misses only. Results are always written back to cache after a yfinance fetch.

**Why:** yfinance bulk download for 50 symbols takes 7–22 minutes per scan. With cache, scan time drops to < 5 seconds. Completed scans per day goes from 18–25 to 60–75.

**How to apply:** fetch_batch() in live_data_provider.py (Step 1: cache, Step 2: yfinance bulk for misses, Step 3: per-symbol fallback for stragglers). Cache write happens at Steps 2 and 3.

## Key constants
- `OHLCV_CACHE_ENABLED` env flag — default true; set false to test yfinance-only path
- Max cache age for scan: 3 days (configurable in ohlcv_cache_store.py via `MAX_CACHE_AGE_DAYS`)
- Min bars required: 126 (≈ 6 months of trading days)
- Post-market gate: `kv_claim_once("ohlcv_postmarket_refresh:{YYYY-MM-DD}")` — once per IST day

## Scheduler wiring
Post-market refresh fires at the first POST_CLOSE/CLOSED tick (after 15:30 IST).
Output key in scheduler response: `ohlcv_postmarket_refresh`.

## LTP lookup key
`build_symbol_overlay()` in kite_ltp_overlay.py looks up `ltps.get(symbol.upper())` — key is `"RELIANCE"`, NOT `"RELIANCE.NS"`. Tests must use bare symbol as ltps key.

## Multi-index bulk DataFrame axis order
yfinance `group_by='ticker'` puts **tickers in level 0**, prices in level 1.
`bulk["RELIANCE.NS"]` → DataFrame with open/high/low/close/volume columns.
Tests using `_make_multiindex_bulk` must use `[tickers, prices]` product order (tickers first).

## Company master threshold
`COMPANY_MASTER_MIN_PCT = 0.80` — if fewer than 80% of universe symbols are in master → BLOCKED.
1/2 missing (50% coverage) = BLOCKED. Need ≥ 6 symbols with 1 missing to get a WARNING.

## Initial bootstrap required
After first deploy run these once:
1. `POST /api/ohlcv-cache/backfill` — 6-month history for all 50 symbols (5–20 min)
2. `POST /api/ohlcv-cache/company-master/bootstrap` — seed from config.SECTOR_MAP

## LTIM.NS
Known yfinance provider gap — not returned in bulk downloads. Handled as `known_missing_ltim` in post-market refresh result. Never blocks other symbols.

## Correct scan count truth
- SCAN_COMPLETED events = authoritative count (was 18 on 2026-08-18)
- SCAN_STARTED events = includes 1 incomplete per session (was 19)
- "77 scans" in old docs = scheduler tick count (not completed scans)
- After cache: expect 60–75 completed scans per session
