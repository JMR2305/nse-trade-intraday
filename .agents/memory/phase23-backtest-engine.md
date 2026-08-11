---
name: Phase 23 backtest engine
description: Historical backtest engine + Investigation Center — same-pipeline rules, isolation, cache, validation
---

# Phase 23 Parts 2/3 — Historical Backtest Engine

- **Same-pipeline rule**: backtests call `live_scan_engine._scan_one` directly
  with an as-of DataFrame slice; NEVER build a second decision engine. Event
  shapes come from the shared `live_scan_engine.derive_symbol_events(recs,
  scan_id, mode, run_id)` used by both LIVE and BACKTEST.
- **Isolation**: backtest trades live in `backtest_runs`/`backtest_trades`
  (partial unique index (run_id, symbol) WHERE status='OPEN' blocks duplicate
  opens). The live phase20 ledger must never be touched; tests assert this.
- **No look-ahead**: `build_asof_df` — daily bars ≤ ts; intraday builds a
  partial "today" bar from candles ≤ ts. No same-bar exits (skip exit check
  when fill_ts == current tick ts).
- **Candle cache** (`historical_data_engine.py`): coverage windows in
  `backtest_candle_meta` prevent any re-download; 10m resampled from cached
  5m; intraday >~55 days back = explicit error, never silent truncation.
- **Validation**: `validate_run` re-runs `_scan_one` on the same cached as-of
  data and diffs decisions → verdict MATCH/MISMATCH with per-decision
  mismatch rows; determinism holds because cache is the single data source.
- **Execution model**: detached `backtest_exec` processes must claim the run
  atomically (PENDING→RUNNING conditional update) so a retried/duplicate exec
  can never replay the same run twice.
- **Replay-input capture**: the run must persist the exact per-tick cash
  (change-compressed) and an adaptive-learning state fingerprint; validation
  replays with those, and reports INDETERMINATE (not MATCH/MISMATCH) when
  learning state changed or nothing could be checked.
- Backtest scan_ids index the UNION timeline; a symbol's own event ticks map
  1:1 to its candles — always map replay cursors via the symbol's distinct
  event ticks, never via raw union tick index.

## Parts 4/5 — Replay Explorer lessons
- END_OF_BACKTEST POSITION_CLOSED events are emitted with scan_id=run_id (no -T tick suffix); exit tick must fall back to mapping ledger exit_ts onto the timeline.
- Run metrics key is `portfolio_value` (not final_value); trades columns are scan_id/fill_ts/fill_price/exit_ts/exit_rule/strategy_name (no entry_* variants).
- UI replay cursor must be a TICK index over the bundle's union timeline, mapped to candles via last-candle-ts ≤ tick-ts — per-symbol candle indices desync the pipeline/portfolio views.
- Explorer tests must seed a deterministic synthetic run directly into the stores (events+ledger+candles); pipeline-driven fixtures are fragile because confidence calibration state can turn all decisions to IGNORE.
- portfolio↔replay verify: END_OF_BACKTEST closes happen after the last PORTFOLIO_UPDATED, so compare last portfolio event OR metrics cash against metrics portfolio_value.

## Capital deployment fix (Aug 2026)
- Backtest sizing is settings-driven via `resolve_sizing(cfg)` (`cfg.sizing` from POST /api/backtest/run); defaults reproduce old 1%/25% constants. `main.py backtest_start` must pass new cfg keys through — it rebuilds the config dict and silently drops unknown keys.
- Scale-in tranches: `backtest_trades.tranche` col; unique OPEN index is (run_id, symbol, tranche). Tranche 0 preserves one-position rule. SCALE_IN_APPROVED/REJECTED/EXECUTED events with exact reasons.
- Time-of-day volume normalization: opt-in `volume_time_normalized`, intraday only, attached via df.attrs in build_asof_df (both execute_run AND validate_run must pass the flag for parity); consumed in _scan_one only when data_source=="backtest_cache".
- concurrent backtest workers deadlocked on _ensure_schema DDL → pg_advisory_xact_lock serializes it; create replacement index before dropping the old one.
- resolve_sizing strictly validates (finite, bounded, JSON bools) — NaN comparisons silently bypass caps otherwise.
