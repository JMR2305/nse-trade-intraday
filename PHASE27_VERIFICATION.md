# Phase 27A + 27B — Verification Report

**Historical Backtesting Engine + AI Live Trading Command Center**
Date: 2026-08-09 · PAPER TRADING / RESEARCH ONLY · No trading logic modified.

Phase 27 was delivered by extending the existing canonical infrastructure
(Phase 23 backtest engine, Pipeline Event Store, unified replay snapshot,
canonical portfolio) rather than duplicating it — satisfying the spec's
"no duplicate data source / no simplified calculations" constraints by
construction.

## Part A — Historical Backtest Engine

Engine: `artifacts/api-server/src/python/backtest_runner.py` (Phase 23) —
replays the **exact production pipeline** (`live_scan_engine._scan_one`:
Supervisor → Scanner → Research → Market Intelligence → Monitoring →
Strategy → Risk → AI Decision → Execution → Portfolio → Learning) over
as-of candle slices with an isolated ledger. UI: **AI Investigation Center**
(`/investigation-center`).

| Spec requirement | Status |
|---|---|
| 5-minute NSE candles | ✅ (`interval=5m`) |
| 10-minute NSE candles | ✅ (`interval=10m`, resampled from 5m) — plus 15m/1d |
| Last Week / Month / 3M presets | ✅ existing |
| **6-month / 1-year presets** | ✅ **added this phase** |
| Custom date range | ✅ existing |
| Exact production code paths | ✅ `_scan_one` + `phase20_executor`, no second engine |
| Replay speeds 1× / 5× / 20× / 100× / Instant | ✅ **speed set aligned this phase** (Instant jumps to the final tick) |
| Per-candle: time, candle, stock, agent, decision | ✅ tick readout **extended this phase** with current agent / stock / decision |
| Run storage: id, duration, stocks, signals, orders, win rate, PnL, drawdown | ✅ `backtest_runs` + `backtest_trades` (Postgres, JSON fallback) |

Honesty guard added: selecting an intraday interval with a range beyond the
~55-day provider history shows an explicit warning — older candles are
reported as missing data, never fabricated.

## Part B — AI Live Trading Command Center

Page: `/live-command-center` (`LiveCommandCenter.tsx`), all numbers from
canonical sources — Pipeline Event Store (`/api/pipeline/*`), unified replay
snapshot (`/api/replay/sessions/latest`), canonical portfolio
(`/api/portfolio/snapshot`), per-cycle log (`/api/ops-centre/cycle-log`).

Added this phase:
- **Scan Cycle card** — cycle #, duration, stocks scanned, universe, market state.
- **Per-stage detail** on the pipeline rail — in/out counts, pending, and
  **average per-symbol processing time** (new `avg_symbol_ms` computed in
  `pipeline_events.stage_summary()` — SQL `LAG()` window over each symbol's
  event sequence per scan; identical definition in the file fallback).
- **BUY / WATCH candidate cards** from replay-snapshot decisions, each symbol
  deep-linking to the AI explanation page.
- **Capital & Exposure card** — deployed capital, utilisation % with bar,
  sector distribution (canonical `sector_exposures`).
- **Pause / Resume** control (freezes all polling + SSE invalidation) and
  **Replay cycle** link to Mission Control.
- Portfolio card fixed to the canonical snapshot schema
  (`open_positions`, `unrealised_pnl`, `realised_pnl_today`, `avg_entry_price`).
- Rejection Analyzer, live event feed, SSE-driven refresh: existing, unchanged.

## Validation checklist (from spec)

- ✅ Existing tests keep passing — Python: 971 unit tests green including
  28 pipeline/replay tests; new `test_pipeline_stage_timing.py` (3 tests)
  covers the avg-time definition, per-scan isolation, and field presence.
- ✅ No duplicate data source — every number derives from the event store,
  replay snapshot, cycle log, or canonical portfolio; no frontend counters.
- ✅ Read-only — no trading logic touched; Part B issues only GETs.
- ✅ Mobile responsive — verified at 402×874 (cards stack single-column).
- ✅ Uses existing event stream — SSE bridge (`/api/stream` pipeline.event)
  invalidates queries; pause suspends it.
- ✅ No regression — `tsc --noEmit` clean; the only failing dashboard test
  file (`freshness-coverage.test.ts`, 65 tests) fails identically on the
  untouched tree (pre-existing environment issue, unrelated).

## Review round
Architect review flagged (1) replay-snapshot field names (`id`/`stocks_in`/
`stocks_out`/`final_action`, plus the `market_data`↔`SCANNER` stage alias) and
(2) file-fallback event ordering not matching SQL's `(ts, id)` tie-break.
Both fixed; a tie-timestamp regression test added (4 timing tests total);
verified live — stage rail shows in/out counts and 6 BUY / 27 WATCH
candidates from the latest scan.

## Screenshots verified
- `/live-command-center` desktop 1280×720 and mobile 402×874.
- `/investigation-center` desktop with new presets and speed controls.
