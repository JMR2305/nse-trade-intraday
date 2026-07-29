---
name: Phase 5D.3 Strategy Intelligence
description: Shared analytics service — stable shared_services.py API designed for reuse by 5D.4 and 5D.5 without recalculation.
---

## Key design decisions

**shared_services.py is the canonical import point** for 5D.4 (AI Performance Intelligence) and 5D.5 (Executive Dashboard). They call `get_all_strategy_profiles()`, `get_summary_snapshot()`, etc. — never the individual sub-module functions directly.

**Why:** Prevents duplicate data loading and ensures consistent metrics across the dashboard.

**How to apply:** Any future phase that needs per-strategy stats, regime/sector/time breakdowns, or recommendations imports from `strategy_intelligence.shared_services`, not from `strategy_intelligence.api` (which is HTTP-layer only).

## Ranking algorithm (7 factors)
Net P&L 20%, Win Rate 20%, Profit Factor 20%, Risk-adj return 15%, Max Drawdown 15% (lower=better), Exec quality 10%, Consistency 10%.

## IST time slots
09:15–10:00, 10:00–11:00, 11:00–12:00, 12:00–13:00, 13:00–14:00, 14:00–15:30. Bucketed in `strategy_engine.py::_time_slot()` from UTC timestamp.

## main.py commands
strategy_summary, strategy_rankings, strategy_regimes, strategy_sectors, strategy_timing, strategy_recommendations — added after the performance_* block.

## Tests
31/31 at 0.49s. All recommendation classification paths covered (Increase Allocation, High Drawdown Risk, Underperforming, Promising, Neutral).
