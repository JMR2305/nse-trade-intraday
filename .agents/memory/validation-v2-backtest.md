---
name: Validation V2 backtest pitfalls
description: Gotchas discovered while running the first AI Validation V2 backtest end-to-end
---

# Validation V2 backtest pitfalls

- **Stale table schemas**: `_ensure_tables()` uses CREATE TABLE IF NOT EXISTS — existing tables never gain new columns. The migration block must ALTER TABLE ADD COLUMN IF NOT EXISTS for every column added after first ship (`strategies` was missing and the run-insert silently failed). Never `except: pass` around the run-record INSERT — surface the error.
- **`_decide()` data gate reads process-global last-source**: `data_ok = err is None and get_last_source(sym)=="yfinance"`. Two traps:
  - the replay must set `"source"`-independent state: the per-strategy bootstrap `run_backtest()` re-fetch can fail → flips the tracked source to "mock" → every replay bar becomes "Data unavailable". Fix: capture the replay df's source after fetch and restore `_LAST_SOURCES[sym]` before each `_run_symbol_replay`.
  - mock fallback candles pass silently otherwise — the engine now skips a symbol with an explicit `symbol_errors` entry when source != yfinance.
- **yfinance rate limits are the main operational hazard**: repeated backtests (8 symbols × 5 strategy bootstraps) trip YFRateLimitError; fetch falls back to mock. Wait ~4–5 min before rerunning; verify with a direct `_fetch_yfinance` probe first.
- **`current_market_regime()` per-bar cost**: `_decide()` builds `MarketContext("6mo")` (2 index downloads) on every call. Now cached 10 min per process in adaptive_learning — without the cache a bar-by-bar replay stalls for hours under rate limiting.
- **Rule-fraction confidence saturates at 100 on entry-signal bars** → _decide() lands in the STRONG_BUY band which requires ≥20 walk-forward trades → BUY∧entry_signal was structurally impossible and runs produced 0 trades. The bridge caps confidence at 82 (BUY band) while wf trades < 20.
- **psycopg2 returns JSONB as Python objects**, not strings — never bare `json.loads(row["jsonb_col"])`; use an isinstance-tolerant loader.
- The V2 page supports `?tab=<id>` deep links (e.g. `/validation-v2?tab=playback`).
