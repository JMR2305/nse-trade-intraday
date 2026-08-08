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
