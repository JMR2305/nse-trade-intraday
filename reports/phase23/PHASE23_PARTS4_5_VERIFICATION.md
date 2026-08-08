# Phase 23 — Parts 4 & 5 Verification Report
## Advanced Replay Engine + AI Decision Explorer

Date: 2026-08-08
Verified run: `BT-85a4febee3` (Daily, 2026-07-06 → 2026-08-07, 5 symbols, 24 ticks, 891 events, 1 trade `BTT-24a92c97cf` ICICIBANK MACD Cross +₹89.08)

## Core guarantee: everything derives from the canonical Event Store

All Parts 4/5 features are implemented in a single READ-ONLY module,
`artifacts/api-server/src/python/backtest_replay.py`. It contains **no new
business logic**:

- It reads events exclusively via `pipeline_events.query_events(run_id=…, mode="BACKTEST")` — the same append-only Event Store written by the backtest runner (Part 1).
- It reads trades exclusively via `backtest_portfolio.trades(run_id)` — the isolated backtest ledger.
- It reads the timeline via the same candle cache slices the runner used.
- It never writes anything: no emits, no ledger mutations, no caches persisted.
- Explanations quote stage payloads **verbatim** (indicators, research stats, risk gate reasons/thresholds, confidence breakdown). No values are recomputed or fabricated; a missing symbol/trade returns `ok:false` — it never invents data.

## Deliverables & where they live

| # | Deliverable | Implementation | Verified |
|---|---|---|---|
| 1 | Replay bundle (union tick timeline, per-tick per-stage counters, portfolio trail, decisions, trade markers, processing_ms) | `replay_bundle()` → `GET /api/backtest/run/:id/replay` | 24 ticks / 891 events on real run; test `test_replay_bundle_synchronized` |
| 2 | Replay modes & controls (Candle/Trade/AI Decision/Day/Week/Month steps, speeds 1×–Max, stop, jump-to-timestamp, Jump to Next BUY/SELL/Trade/Rejection) | `InvestigationCenter.tsx` tick-cursor engine | Screenshot: controls render; cursor is a tick index over the bundle timeline |
| 3 | Animated pipeline visual (10 stages lit green/red from per-tick counters) | `PipelineFlow` component | Screenshot: stage chips + per-symbol verdict pills at cursor |
| 4 | AI Decision Explanation — Why BUY | `explain()` BUY branch: indicators, research, market, monitoring, strategy, risk gates, confidence, execution, position-size calc, target/stop, expected risk/reward %, exit logic | `explain ICICIBANK → BUY` via HTTP; test `test_explain_buy_and_reject` |
| 5 | Why REJECT with exact failed gates + relax analysis | `explain()` REJECTED branch: verbatim `failed_gates` (reason/threshold/value) + advisory 10-bar forward `_relax_analysis` | Test asserts threshold 0.75 / value 0.4 preserved exactly |
| 6 | Trade Story narrative | `trade_story()` → `GET …/story/:tradeId`; per-step jump buttons in UI | 19 steps, entry tick 0 → exit tick 23 on real trade; test `test_trade_story_narrative` |
| 7 | Chart overlays (entry/exit markers, stop/target dashed lines, rejected ×, missed ◆) | InvestigationCenter chart layer | Screenshot: overlay legend + marks visible |
| 8 | Event filters (all/buy/sell/rejected/cancelled + min confidence) | Event Timeline card | Screenshot: filter chips render |
| 9 | Global search over trades + events | `search()` → `GET …/search?q=` | `q=macd` → 1 trade, 42 events; test `test_search_finds_trades_and_events` |
| 10 | Replay validation engine (6 integrity checks) | `replay_verify()` → `GET …/replay-verify` | PASS on real run; test proves tampered ledger → FAIL (never masks) |

### Replay-verify checks (all PASS on `BT-85a4febee3`)
1. `no_duplicate_events` — event ids unique
2. `ticks_within_timeline` — every event scan_id maps into the run timeline
3. `execution_matches_ledger` — entry/exit events exist per ledger trade
4. `fill_prices_match_ledger` — event fill prices equal ledger fills
5. `portfolio_matches_replay` — last PORTFOLIO_UPDATED / metrics cash equals `portfolio_value`
6. `decision_matches_backtest` — stored `validate_run` verdict is MATCH

## Automated tests

`artifacts/api-server/src/python/test_backtest_engine.py` — **18/18 passing**
(13 pre-existing Parts 2/3 tests + 5 new `TestReplayExplorer` tests). New tests
run against a deterministic synthetic run seeded directly into the file-fallback
stores (events + ledger + candles) — no network, no DB, never the live phase20
ledger — because the explorer layer is read-only over the store; pipeline
equivalence itself is proven by the pre-existing `validate_run` test.

Negative paths covered: unknown trade/symbol fail loudly; tampered ledger flips
`replay_verify` to FAIL.

## Environment verification
- `pnpm exec tsc -b artifacts/api-server` — clean
- `pnpm --filter trading-dashboard exec tsc --noEmit` — clean
- All 5 endpoints exercised over HTTP against the running api-server
- `/investigation-center` screenshot confirms full page render
