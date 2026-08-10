# AI Validation Centre V2 — Status Report

**Date:** 10 August 2026
**Page:** `/validation-v2` (NSE Trading Dashboard → AI Validation Centre V2)
**Mode:** PAPER / RESEARCH ONLY — every response is labelled Advisory Only; nothing here places live orders or changes production parameters.

---

## 1. What it is

A production-parity backtesting and AI-validation workbench. It replays real historical NSE candles through the **same decision pipeline the live system uses** (`backtesting_engine.run_backtest` strategy hooks + `decision_service._decide`), walk-forward with point-in-time stats so there is no look-ahead bias. Results are persisted to dedicated Postgres tables and explored through a 10-tab dashboard page.

## 2. What is developed (all 10 tabs)

| Tab | What it does |
|---|---|
| **Overview** | Run count, overall win rate, top missed ticker, best optimizer Sharpe, advisory banner, navigation cards, recent runs |
| **Backtest Runner** | Configure symbol(s)/strategy/period/interval/capital/stop/target/confidence; starts an async run; live progress polling (3s) + run history |
| **Trade Simulation** | Per-run trade list and drilldown: entry/exit, P&L, MFE/MAD excursions |
| **Missed Opps** | Rejected decisions whose subsequent move met the threshold — with filters and jump-to-run |
| **AI vs Market** | Recommendation distribution vs realized market outcomes |
| **Param Optimizer** | Grid search (≤200 combos) with ranked results, best config, and recommendation |
| **Explainability** | Per-decision pipeline scorecard: confidence, reason, filters, rejection details |
| **Session Playback** | Event timeline with scrubber, play/pause, rewind/fast-forward |
| **Performance** | Daily/weekly/monthly KPIs: win/loss rates, P&L, drawdown, profit factor, expectancy, Sharpe, holding days, confidence, best/worst trades |
| **Model Comparison** | Current vs candidate config with deltas and verdict |

## 3. Backend delivered

**API endpoints** (`artifacts/api-server/src/routes/validation-v2.ts`):

- `POST /validation-v2/backtest/run` — start an async run (caps: ≤20 symbols, ≤730-day span)
- `GET /validation-v2/backtest` — recent run summaries
- `GET /validation-v2/backtest/:runId` — full run detail (config, progress, decisions sample, trades, missed opps, stats)
- `GET /validation-v2/missed-opportunities` — all or run-scoped missed rows
- `POST /validation-v2/optimizer/run` and `GET /validation-v2/optimizer/recommendation`
- `POST /validation-v2/model-comparison`
- `GET /validation-v2/performance?period=daily|weekly|monthly`
- `GET /validation-v2/session-timeline/:runId`

Every response carries `X-Advisory-Only: true` and `X-Paper-Trading: true` headers.

**Python engine** (`artifacts/api-server/src/python/validation_v2_engine.py`): per-symbol candle replay, trade simulation with stop/target/confidence applied per bar, MFE/MAD enrichment, missed-opportunity detection with improvement suggestions, aggregate stats, rejection distribution, optimizer, model comparison, timeline, and performance analytics.

**Database** (auto-created): `validation_v2_runs`, `validation_v2_decisions`, `validation_v2_trades`, `validation_v2_missed`, `validation_v2_optimizer_runs` — with foreign-key cascade and run indexes.

## 4. What is verified working right now

- ✅ Page registered and reachable at `/validation-v2` (App.tsx + sidebar navigation)
- ✅ Live API check (today): `GET /validation-v2/backtest` returns `{"runs":[],"count":0,"label":"PAPER / RESEARCH ONLY — Advisory Only"}` — healthy, no runs recorded yet
- ✅ Live API check (today): `GET /validation-v2/performance` responds correctly with "No backtest trades found. Run a backtest first."
- ✅ Python test suite: `test_validation_v2.py` — 15 test functions/classes covering replay, optimizer, and edge cases
- ✅ Dashboard tests: 4 test files (contract, markers, filter, query-invalidation) — ~39 test cases
- ✅ No TODO/FIXME/stub markers anywhere in the page, routes, or engine — the feature is code-complete

## 5. Guardrails & limits

- Advisory/paper only — never places live orders or auto-modifies production parameters
- Server caps: 20 symbols per run, 730-day date span, 200 optimizer combinations (engine-side optimizer symbol cap: 8)
- Persistence requires `DATABASE_URL` (present in this workspace); without it the engine degrades gracefully
- Run detail returns a *sample* of decisions; the full decision set lives in the database

## 6. Current state & next step

Everything is built, tested, and responding — but **no backtest run has been executed yet**, so all tabs currently show empty states. The natural next step is to launch a first backtest from the Backtest Runner tab (e.g. a handful of watchlist symbols over the last 6 months) to populate Overview, Performance, Missed Opps, and Playback with real data.
