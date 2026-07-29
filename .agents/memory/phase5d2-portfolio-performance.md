---
name: Phase 5D.2 portfolio performance
description: Read-only portfolio performance intelligence module; analytics engine, 5 API endpoints, dashboard page.
---

## Feature flag
`PORTFOLIO_PERFORMANCE_ENABLED=true` — without it every endpoint returns `{"status":"DISABLED"}`.

## Module layout
`artifacts/api-server/src/python/portfolio_performance/`
- `performance_models.py` — dataclasses + is_enabled/disabled_response
- `equity_curve.py` — daily/weekly/monthly curves + daily_pnl/monthly_pnl bars
- `drawdown.py` — max drawdown, current drawdown, recovery % from annotated EquityPoint list
- `statistics.py` — trade stats, risk metrics, period P&L cuts, sector allocation, strategy contribution
- `performance_engine.py` — orchestrator; FIFO BUY→SELL matching (same pattern as EQ module)
- `api.py` — 5 public functions: get_summary, get_equity, get_drawdown, get_statistics, get_portfolio
- `test_portfolio_performance.py` — 26 tests, all passing

## Express route
`artifacts/api-server/src/routes/performance.ts` — registered in `routes/index.ts` before tradingRouter.

## Main.py commands
`performance_summary`, `performance_equity <period>`, `performance_drawdown`, `performance_statistics`, `performance_portfolio` — added after the execution_quality block.

## Dashboard
`artifacts/trading-dashboard/src/pages/PortfolioPerformance.tsx`  
Route: `/portfolio-performance`  
Sidebar: Analytics group, icon TrendingUp  

## Performance benchmarks (local, no DB)
summary: ~52ms, equity/drawdown/statistics/portfolio: 15–19ms each (all well under 100ms target).

**Why:** FIFO BUY→SELL matching was reused from `execution_quality/metrics.py` — do not reinvent, import the pattern. pnl_history is `[{timestamp, value}]` where `value` is total equity; equity curve is derived directly from these rows.

**How to apply:** Always gate reads on `is_enabled()`. Equity points must be sorted before annotating drawdown. `_sector_of` from market_scanner is best-effort — wrap in try/except returning "Unknown".
