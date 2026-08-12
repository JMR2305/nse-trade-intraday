---
name: Backtest performance fix
description: Root cause of 5h+ backtest freezes and the three optimisations applied to backtest_runner.py's tick loop.
---

## Root cause of frozen runs (BT-e0b72dba58 and earlier)

Frozen runs showing "RUNNING" forever were caused by **missing heartbeat/sweep infrastructure** (pre-Task #631), not slow computation:
1. Worker hit Neon auth token expiry mid-run (token expires after ~30 min of DB inactivity; yfinance rate-limit could stall the DATA phase that long)
2. Worker crashed — no `_emergency_mark_failed()` existed
3. No sweep detected the orphaned RUNNING row
4. Progress display froze at last written tick

Tasks #631–633 fixed this: `_connect_with_retry()`, `_emergency_mark_failed()`, 30-min stale watchdog, sweep-on-read, 2-min server-side scheduler.

## Real-world timing (confirmed)

5-symbol, 15m, 30-day run on Neon Serverless dev environment:
- **~6 minutes** (356–358 s) — confirmed via BT-65c007735c and BT-a2be43c8d5 (both COMPLETED)
- Tick rate: ~1.6 ticks/second (0.625 s/tick real-world vs 219 ms isolated benchmark)
- Gap is Neon TLS handshake overhead per new psycopg2 connection under load (~100–200 ms/conn real vs 12–66 ms warm)

## Three optimisations in backtest_runner.py execute_run tick loop

Applied 2026-08-12:

1. **Event buffer** (`_evt_buf`): collect `derive_symbol_events()` output in-memory, flush via `emit_many()` every 5 ticks. Reduces 553 connections → 111. Saves ~60 s real-world.
2. **PORTFOLIO_UPDATED in buffer**: appended to `_evt_buf` instead of a separate `emit()` call every 5 ticks. Zero extra connections.
3. **Portfolio snapshot every 20 ticks** (down from 5): `portfolio_snapshot()` (reads all trades from DB) moved to `tick_i % 20` block. Heartbeat (`update_run`) and cancel/stale check stay at every 5 ticks.
4. **O(1) candle timestamp index** (`per_symbol_ts_idx`): pre-built dict before tick loop replaces O(n_candles) scan per tick.

**Why:** The heartbeat block at `tick_i % 5 == 4` MUST still run every 5 ticks or the 30-min stale watchdog marks the run STALE.

## Known silent import failures in _scan_one (harmless for backtests)

- `create_paper_order` from `paper_trader.py` — function does not exist; caught by `try/except ImportError` in `_scan_one`. Backtests have their own isolated ledger so this is intentional.
- `get_item_adjustment` from `adaptive_learning.py` — function does not exist; same pattern. Adaptive learning adjustments silently skipped in backtests.
