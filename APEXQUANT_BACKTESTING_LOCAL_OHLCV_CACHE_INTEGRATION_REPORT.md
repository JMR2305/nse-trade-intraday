# ApexQuant AI — Backtesting ↔ Local OHLCV Cache Integration Report

**Date:** 2026-08-19 (IST)
**Scope:** Wire all daily (1d) backtest data fetches through the local
`daily_ohlcv_cache` (PostgreSQL), matching the live-scan cache-first path.
Intraday (5m/15m/1h) remains on the existing engines, unchanged.

---

## 1. What Changed

### New module: `backtest_data_bridge.py`
`fetch_candles_for_backtest(symbol, interval, period, start_date, end_date) → (df, source)`

Priority chain for `interval == "1d"`:
1. **Local cache (as-of read)** — `read_symbol_from_cache(sym, end_date=...)` filters
   bars to `trading_date <= end_date` and judges freshness relative to `end_date`,
   so historical windows are never rejected for being "old vs today".
2. **yfinance** via `market_data_engine.fetch_candles_df` for misses or when the
   cache does not cover the requested window (±7-day trading-calendar slack).
3. **Write-back** — real yfinance bars are upserted into the cache so the next
   run is a cache hit.

Sources returned: `local_ohlcv_cache` | `yfinance` | `mock` | `none`.

**Mock safety:** if `market_data_engine` fell back to synthetic candles, the
bridge returns `source="mock"`, logs a WARNING, and **never** writes them to
the cache. Consumers gate on this explicitly (see below).

### `ohlcv_cache_store.py`
`read_symbol_from_cache()` gained an optional `end_date` parameter for as-of
(backtest) reads. Live-scan callers are unaffected (parameter defaults to None,
behaviour identical).

### Call sites wired to the bridge (all 1d-capable)
| File | Sites | Notes |
|------|-------|-------|
| `backtesting_engine.py` | `run_backtest()`, `run_strategy_lab()` | `BacktestResult.data_source` now reports the true bridge source instead of hard-coded `"yfinance"` |
| `validation_v2_engine.py` | 4 sites (replay ×2, optimizer pre-fetch ×2) | data-source gates updated to accept `yfinance` **or** `local_ohlcv_cache` (the cache only ever contains real yfinance bars); mock still blocks the symbol/run |
| `strategy_optimizer.py` | `optimize()` fetch | mock source now returns an explicit error instead of silently optimising on synthetic data |

`backtest_replay.py` uses `historical_data_engine` (intraday) — no change needed.

---

## 2. Safety Guarantees (verified)

- **No live orders / paper ledger writes:** the bridge contains zero references
  to `paper_trades`, `paper_portfolio`, order placement, or execution paths
  (enforced by test 8, an AST/source check).
- **No mock data in the cache:** write-back only occurs when
  `get_last_source() == "yfinance"` (test 3).
- **No silent empty data:** empty results return `(empty df, "none")` and all
  callers keep their existing "insufficient data" error paths.
- **Intraday untouched:** non-1d intervals bypass the cache (test 4).

---

## 3. Test Evidence

`test_backtest_ohlcv_integration.py` — **11/11 passed** (all DB/yfinance mocked):
1. Warm cache hit skips yfinance entirely; window sliced correctly
2. Cache miss → yfinance fetch + write-back with source="yfinance"
3. Mock candles surfaced as `mock`, never written to cache
4. Intraday (15m) bypasses cache
5. `end_date` forwarded to the as-of cache read
6. Cache not covering a 2-year window falls through to yfinance
7. `run_backtest()["data_source"]` reflects the bridge source
8. Period-only request (e.g. "3mo") against an oversized warm cache is sliced
   to the period window — never silently widened to the cache's full history
9. `run_backtest()` blocks mock candles with an explicit error
10. `run_strategy_lab()` blocks mock candles with explicit error entries
11. Bridge module has no trading side effects

**Review-round hardening:** period-only requests are normalised to explicit
date bounds inside the bridge (`_effective_window`), and mock candles are now
blocked with explicit errors at *every* public backtest entry point
(`run_backtest`, `run_strategy_lab`, Validation V2, both optimizers).

`test_ohlcv_cache.py` — **18/18 still pass** (no regression from the
`end_date` parameter).

---

## 4. Live Verification (dev DB, warm cache)

```
fetch_candles_for_backtest("RELIANCE", 1d, 90d window)
  → source=local_ohlcv_cache, 64 bars, 241 ms

run_backtest(TCS, trend_rider, 90d, 1d)
  → data_source=local_ohlcv_cache, 29 ms total
```

Previously every backtest paid a fresh yfinance download per symbol; a warm
cache now serves the whole daily backtest data path in milliseconds.

---

## 5. Operational Notes

- Requests longer than the cached history (e.g. strategy optimizer's 2-year
  fetch) automatically fall back to yfinance and extend the cache via
  write-back, so the second 2-year run is a cache hit.
- Production needs the pending republish + cache bootstrap/backfill (see
  `APEXQUANT_PRODUCTION_OHLCV_CACHE_FIRST_SCAN_PROOF.md`) before this path
  is warm in prod.
