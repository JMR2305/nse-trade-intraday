# Phase 26A — Portfolio Pre-Check Visibility (Verification Report)

Date: 2026-08-09 · Scope: observability only (gate wiring itself is Task #15; no rule logic changed)

## Single source of validation logic

The Portfolio Engine remains the ONLY place pre-check rules are evaluated:

1. **Decision point** — `paper_trader.execute_buy()` calls
   `portfolio_bridge.pre_check()`, which runs the Portfolio Engine's
   `evaluate_allocation()` + `evaluate_limits()` and fails CLOSED on error.
   Nothing in this phase re-implements or re-evaluates any rule.
2. **Event emission** — immediately after `pre_check()` returns,
   `execute_buy` emits `PRECHECK_APPROVED` / `PRECHECK_REJECTED` (stage
   `PORTFOLIO_PRECHECK`) to the canonical pipeline event store. The payload
   **copies the exact `reasons` list returned by the engine** — allocation
   codes (`DAILY_LOSS_LIMIT_BREACHED`, `DRAWDOWN_LIMIT_BREACHED`,
   `INSUFFICIENT_BUYING_POWER`, `BELOW_MIN_ORDER_VALUE`),
   `LIMIT_BREACH:<limit_name>`, `PORTFOLIO_PRECHECK_ERROR: …`, and
   `PORTFOLIO_DISABLED`. Emission is fail-safe (`emit` never raises; a wrapper
   try/except guards the import) and never alters the trading decision
   (locked by `test_emit_failure_never_blocks_trading`).
3. **Replay** — `replay_engine._get_precheck_decisions(scan_id)` rebuilds
   decisions **purely from stored events**; `_build_stages_from_snapshot`
   consumes that map and never re-runs portfolio rules. Locked by
   `test_decisions_replayed_from_events_alone`.

## Stage placement & count consistency

- `pipeline_events.STAGES`: `PORTFOLIO_PRECHECK` inserted between `STRATEGY`
  and `RISK`; `PRECHECK_APPROVED`/`PRECHECK_REJECTED` registered in
  `COMPLETED_EVENT_TYPES`/`REJECTED_EVENT_TYPES`, so `stage_summary` (the one
  function that powers the Live Pipeline everywhere) counts them.
- Unified replay inserts a `portfolio_precheck` stage (order 6) with
  chaining `risk.stocks_in == portfolio_precheck.stocks_out`; pre-check-rejected
  symbols are removed from Risk/Decision/Execution symbol sets, so **rejected
  candidates never appear in Risk counts**. The count contract
  `in = out + rejected + pending + cancelled` holds for every stage
  (locked by `test_conservation_contract_holds`).
- **Approved ≠ pass-through.** The pre-check only evaluates actual BUY
  attempts, so the stage exposes explicit event-derived counts:
  `evaluated_count`, `approved_count` (approved events only), `rejected`,
  and `not_evaluated` (non-BUY symbols that flow through the funnel for
  conservation but were never evaluated). The Ops "Pre-Check Approved"
  number (`passed_precheck`) is the event-derived `approved` count — never
  the pass-through `stocks_out`.
- Consumers reading the same sources automatically agree: Mission Control
  panel & funnel, Live Command Center, Replay page (all data-driven from
  `stage_summary` / `build_replay`), plus explicit stage entries added to the
  Ops funnels (`passed_precheck`, replay-derived) and the AI Investigation
  Centre stage list / per-symbol journey.

## Honesty notes

- Wall-clock, the pre-check currently runs inside `execute_buy` (after the
  scan-level Risk gates emitted their events) — re-ordering the live gate is
  Task #15's scope. Events record the true decision; the replay presents the
  stage in the specified STRATEGY → PRE-CHECK → RISK funnel order.
- Symbols that never triggered a BUY attempt have no pre-check decision and
  pass through the stage untouched (`evaluated_count` on the stage shows how
  many were actually evaluated).
- Both production buy paths thread scan attribution: `phase20_executor`
  passes its explicit `scan_id`; `intelligence._execute_trades` resolves the
  canonical scan_id from the scan state store (fail-safe → `None`). Manual
  buys without a `scan_id` still emit events (global summaries) but are not
  attributed to a scan.
- `replay_engine.STAGES` (authoritative stage definition) includes
  `portfolio_precheck` at order 6, matching the built replay stages.

## Evidence

- Per-symbol journey: when the event-derived pre-check says BLOCKED, the
  Risk / AI Decision / Execution journey steps are marked SKIPPED (with the
  blocking reasons) instead of showing stale snapshot results.
- `test_portfolio_precheck_events.py` — 20 tests: every rejection rule's exact
  reason, canonical scan attribution through the intelligence buy path
  (incl. end-to-end event→replay reconstruction and fail-safe no-snapshot),
  reason, approved/disabled/error paths, fail-safe emission, stage vocabulary
  order, stage_summary counting, replay stage insertion/chaining/conservation,
  events-only replay, last-decision-wins, fail-safe event-store reads.
- `test_pipeline_events.py` — updated: 11 canonical stages, ordering locked.
- Full suites green: test_pipeline_events, test_portfolio_precheck_events,
  test_backtest_engine, test_phase4a_dashboard, test_research_lab,
  test_task489_display_only_marks, tests/test_replay_conservation,
  test_ops_centre_buy_count (182 python tests) · dashboard vitest for
  Mission/Session widgets (45) · monorepo typecheck clean.
- Live check: `/api/pipeline/summary` returns 11 stages incl.
  `PORTFOLIO_PRECHECK`; `/api/replay/sessions/latest` shows the stage at
  order 6 with exact chaining (48 → 48 → risk in 48).
