---
name: Phase 6.1 Paper Trading Validation
description: Read-only data collection framework; FIFO BUY→SELL matching; 7 quality checks; stable get_validation_snapshot() for future phases.
---

## Key design decisions

**FIFO matching** — `validation_collector._fifo_match()` pops from `buy_queues[symbol]` in chronological order. Does not handle partial-quantity splits; full-lot pairs only.

**Per-trade enrichment fallback chain:**
- `execution_quality_score`: SELL metadata first → session avg from `execution_quality.api.get_summary()` fallback
- `executive_score_snapshot`: current session snapshot from `get_executive_snapshot()` (NOT historical per-trade — see known limitation)
- All other AI fields: BUY metadata only (stored at entry time by the trading engine)

**Background safety:** collection is invoked only from API endpoints via main.py. Never called from trading engine hot path.

**Quality score** — weighted: missing/dup/timestamp/negative-qty/impossible-price/corrupted = weight 1.0; incomplete_ai = weight 0.5 (warning not error). Score = 100 − (weighted_issues / total_records × 100).

## Stable future interface
`get_validation_snapshot()` — flat dict: total_validated_trades, validation_win_rate, validation_net_pnl, avg_ai_confidence, avg_execution_score, max_drawdown.

## Tests: 33/33 at 0.20s
All mocks patch `paper_trading_validation.validation_collector` not `portfolio_store` directly.
Use `_patch_load_trades(trades)` helper to patch `sys.modules["portfolio_store"]`.

## Known gaps
- executive_score_snapshot is current-session, not per-trade-at-execution-time
- Partial fills (split lots) not handled in FIFO
- PDF export is a stub (NOT_IMPLEMENTED)
