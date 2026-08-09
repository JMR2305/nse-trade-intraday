---
name: Phase 23 Pipeline Event Store
description: Canonical append-only pipeline event stream — schema, emit rules, summary semantics, SSE bridge
---

# Phase 23 — canonical Pipeline Event Store

`pipeline_events.py` is the ONE event stream all live dashboards render from
(table `pipeline_events`, lazy CREATE via scan_state_store helper, file
fallback capped at 5000 rows).

Rules:
- **Emits never raise** — `emit()` / `emit_many()` swallow everything; a
  broken event store must never break a scan or trade.
- **Per-symbol events are batched** (`emit_many`, one insert) and derived
  from the authoritative scan result (`recs`) AFTER analysis — counts can't
  diverge from the scan by construction.
- **Mode isolation**: `mode='LIVE'` vs `'BACKTEST'` (+ `run_id`); backtests
  must never pollute live dashboards.
- **Explicit state semantics**: `COMPLETED_EVENT_TYPES` /
  `REJECTED_EVENT_TYPES` frozensets — never substring heuristics.
  ORDER_CANCELLED counts as rejected; SCAN_STARTED / ORDER_SUBMITTED are
  lifecycle markers (events only).
- **Summary aggregates in SQL** (no row-limit truncation on Postgres); file
  fallback sets `truncated` flag.
- **Retention**: `prune_events(14)` runs fail-safe after every SCAN_COMPLETED
  emit — without it the table grows ~350 events/scan forever.
- **SSE bridge** (`routes/pipeline.ts` `startPipelineTail`): polls every 3s
  but ONLY while `sseClientCount() > 0` (exported from stream.ts); publishes
  `pipeline.event` on the bus. `useLiveStream` exposes `pipelineEventId`;
  pages invalidate react-query caches on it.

Emit points: live_scan_engine (SCAN_STARTED/FETCH_COMPLETED/per-symbol
batch/SCAN_COMPLETED), phase20_executor (ORDER_* / POSITION_* /
PORTFOLIO_UPDATED via canonical_portfolio).

UI: `/live-command-center` (LiveCommandCenter.tsx) renders purely from
`/pipeline/summary` + `/pipeline/events` + `/portfolio/snapshot` +
`/live-data/scan/status`. Honest empty states; no page-local pipeline math.

**Why:** Phase 23 directive — one event stream, identical counts everywhere,
no hidden rejections.
**How to apply:** any new pipeline stage or trading action must emit here
(fail-safe) and dashboards must read events, not recompute.

## Per-event timestamps (stage timing fix)
Batch-derived symbol events all shared one insert timestamp, so operator-analytics stage timings read 0ms.
**Rule:** `_scan_one` records true per-stage ISO timestamps in a non-dataclass attr `rec._stage_ts` (kept out of asdict snapshots); `derive_symbol_events` attaches `ts` per event; `pipeline_events.emit/emit_many` honor explicit `ts` via `COALESCE(%s::timestamptz, NOW())` (file fallback uses the given ts too). MARKET_INTELLIGENCE/MONITORING are derived views → honestly ~0ms; RESEARCH carries the bulk.
