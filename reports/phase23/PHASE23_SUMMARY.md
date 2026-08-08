# Phase 23 — AI Live Trading Command Center: Part 1 Summary

**Date:** 8 August 2026
**Status:** Part 1 complete (Pipeline Event Store + Live Command Center). Parts 2–9 not started.
**Label:** PAPER TRADING / RESEARCH ONLY

---

## 1. What was built

### 1.1 Canonical Pipeline Event Store (the one source of truth)

A single append-only event stream that every dashboard renders from — no page-local
calculations, no demo data, no synthetic fallbacks.

| Component | Location |
|---|---|
| Event store module | `artifacts/api-server/src/python/pipeline_events.py` |
| Postgres table | `pipeline_events` (lazy `CREATE TABLE IF NOT EXISTS`, file fallback without `DATABASE_URL`) |
| API routes | `artifacts/api-server/src/routes/pipeline.ts` |
| Dispatcher commands | `main.py pipeline_events`, `main.py pipeline_summary` |
| Tests | `artifacts/api-server/src/python/test_pipeline_events.py` (9/9 passing) |

**Schema:** `id BIGSERIAL, ts, mode (LIVE|BACKTEST), run_id, scan_id, event_type, stage, symbol, payload JSONB`
with indexes on `(scan_id, id)` and `(mode, id DESC)`.

**Canonical stages (pipeline order):** SUPERVISOR → SCANNER → RESEARCH →
MARKET_INTELLIGENCE → MONITORING → STRATEGY → RISK → AI_DECISION → EXECUTION → PORTFOLIO.

**Event types:** scan lifecycle (`SCAN_STARTED`, `SCAN_FETCH_COMPLETED`, `SCAN_COMPLETED`,
`SCAN_FAILED`), per-symbol stage results (`SYMBOL_SCANNED`/`SYMBOL_REJECTED`,
`RESEARCH_COMPLETED`, `MARKET_INTELLIGENCE_COMPLETED`, `MONITORING_COMPLETED`,
`STRATEGY_SELECTED`/`STRATEGY_REJECTED`, `RISK_APPROVED`/`RISK_REJECTED`,
`BUY/SELL/WATCH/IGNORE_GENERATED`), and execution/portfolio
(`ORDER_SUBMITTED/EXECUTED/REJECTED/CANCELLED`, `POSITION_OPENED/UPDATED/CLOSED`,
`PORTFOLIO_UPDATED`).

**Design guarantees:**

- **Emission never breaks the pipeline.** `emit()` / `emit_many()` swallow all failures.
- **Counts cannot diverge from the scan.** Per-symbol events are derived from the
  authoritative scan result itself and written in one batch insert.
- **Explicit state semantics.** `COMPLETED_EVENT_TYPES` / `REJECTED_EVENT_TYPES`
  frozensets — no substring heuristics. `ORDER_CANCELLED` counts as rejected;
  `SCAN_STARTED` / `ORDER_SUBMITTED` are lifecycle markers.
- **Exact aggregates.** Stage summaries are computed in SQL over all matching rows
  (no row-limit truncation); the file fallback reports a `truncated` flag.
- **Bounded growth.** `prune_events(14)` runs fail-safe after every completed scan
  (14-day retention; a full 50-symbol scan emits ~341 events).
- **Mode isolation.** `mode='LIVE'` vs `'BACKTEST'` (+ `run_id`) so future backtests
  never pollute live dashboards.

### 1.2 Emit points wired into the real pipeline

| Emit point | File | Events |
|---|---|---|
| Scan lifecycle | `live_scan_engine.py` `run_live_scan()` | SCAN_STARTED, SCAN_FETCH_COMPLETED, SCAN_COMPLETED (+ retention prune) |
| Per-symbol stage decisions | `live_scan_engine.py` (post-analysis batch) | 7 events per successful symbol across SCANNER→AI_DECISION, incl. gate payloads and rejection reasons |
| Paper order execution | `phase20_executor.py` `create_paper_entry()` | ORDER_SUBMITTED, ORDER_EXECUTED, ORDER_REJECTED (risk agent + execute_buy paths), ORDER_CANCELLED (duplicate claim) |
| Position lifecycle | `phase20_executor.py` `record_exit()` | POSITION_OPENED/UPDATED/CLOSED, SELL_GENERATED |
| Portfolio state | both above, via `canonical_portfolio.build_canonical_portfolio()` | PORTFOLIO_UPDATED (cash, equity, open positions, P&L) |

### 1.3 API + live streaming

- `GET /api/pipeline/events` — filters: `since_id`, `scan_id`, `run_id`, `mode`,
  `event_type`, `stage`, `symbol`, `limit`, `newest_first`.
- `GET /api/pipeline/summary` — per-stage counts for the latest (or given) scan;
  5s cache + single-flight.
- **SSE bridge:** a tail poller (3s) republishes new events as `pipeline.event` on the
  existing `/api/stream` bus — and only runs while at least one SSE client is connected
  (`sseClientCount()` exported from `stream.ts`).
- `useLiveStream` hook now exposes `pipelineEventId`; the Command Center invalidates its
  query caches on each streamed event, so it reacts within ~1s instead of the next poll.

### 1.4 AI Live Trading Command Center (UI)

Route `/live-command-center` (`artifacts/trading-dashboard/src/pages/LiveCommandCenter.tsx`),
registered under the Operations agent in the sidebar.

Sections (all rendered purely from the event store + canonical endpoints):

1. **Live Pipeline rail** — the 10 stages with ✓/✗ counts, last symbol processed, and a
   pulse highlight on stages active in the last 60s during a scan.
2. **Live Event Feed** — newest-first stream of events with severity coloring and
   payload highlights (reason / action / strategy / trade id).
3. **Paper Portfolio** — equity, cash, realized/unrealized P&L and open positions from
   `/api/portfolio/snapshot` (canonical phase20 ledger).
4. **Rejection Analyzer** — every rejection in the current scan with per-type filter
   chips and full reasons ("nothing hidden").
5. Header: SSE connection state, market state, scan progress (stage + n/total) or last
   scan age.

Honest empty states throughout — no fabricated values.

---

## 2. Verification

- **Unit tests:** 9/9 in `test_pipeline_events.py` (roundtrip, filters, since_id,
  newest_first, mode isolation, batch emit, fail-safety, summary counts, empty states).
  Run against the file fallback — tests never touch the dev database.
- **Live end-to-end:** a forced real scan (`3079a4ad21c6`) emitted **341 events**:
  SUPERVISOR 2, SCANNER 51 (48✓ / 2✗ — LTIM & TATAMOTORS fetch failures surfaced as
  SYMBOL_REJECTED), RESEARCH/MI/MONITORING/STRATEGY/RISK/AI_DECISION 48 each.
  EXECUTION/PORTFOLIO 0 — correct: weekend, no entries.
- **UI verified by screenshot** at 1440px: pipeline rail, feed, portfolio, and rejection
  analyzer all populated from real data.
- **Typechecks clean** (api-server `tsc -b`, dashboard `tsc --noEmit`).
- **Architect code review completed;** all four findings fixed:
  1. No retention policy → added 14-day indexed prune after each scan.
  2. Tail poller ran with zero clients → now gated on SSE client count.
  3. Summary truncated at 2,000 rows + heuristic classification → SQL aggregates +
     explicit event-type sets + `truncated` flag.
  4. `pipeline.event` not consumed by the UI → `useLiveStream.pipelineEventId` +
     react-query invalidation.

---

## 3. Safety

- Paper trading / research only — no live broker calls introduced anywhere.
- Event emission is advisory instrumentation: any store failure is swallowed and the
  scan/trade proceeds unchanged.
- Auto paper entries remain OFF by default with exact-confirmation (Phase 20 unchanged).

---

## 4. Remaining Phase 23 scope (not started)

| Part | Scope |
|---|---|
| 2 | Historical Backtest Engine — persistent candle cache; run the SAME production pipeline over history (5m/10m/daily/week/month/custom); `mode='BACKTEST'` events; separate backtest ledger |
| 3–5 | Investigation Center (candle-by-candle decision replay), Trade Replay controls (play/pause/speeds/jump), Decision Explorer (full per-stock decision tree) |
| 6 | Missed Opportunities report |
| 7 | Strategy Optimizer (parameter sweeps: win rate / Sharpe / drawdown) |
| 8 | Performance Analytics breakdowns (strategy / regime / time) |
| 9 | Live Validation (replay ≡ live decision proof with mismatch log) + final validation report proving identical counts across all dashboards |

Existing building blocks for Part 2: `backtesting_engine.py`, `market_replay.py`
(no-lookahead replay), `walk_forward_validator.py`, `strategies.py`. No persistent
candle cache exists yet.
