# Task 482 — Portfolio Performance & Trade History Data Flow: Verification Report

Date: 2026-08-08 · PAPER TRADING / ADVISORY ONLY

## Root causes fixed
1. **Route collision / missing routes** — The frontend called `performance/summary|equity|drawdown|statistics|portfolio`, but `/performance/*` was mapped to the Phase 8.7 Performance Optimisation Centre (`perf_*` commands) and the other four routes didn't exist. Fixed by mounting the Phase 5D.2 portfolio analytics at **`/api/portfolio-performance/*`** (dispatching to `performance_summary|equity|drawdown|statistics|portfolio` Python commands) and pointing `PortfolioPerformance.tsx` there. The Optimisation Centre's `/performance/*` routes are untouched. Dashboard widgets (`WidgetRegistry`, `PerformanceWidget`, `TodaysPnlWidget`) already used `portfolio-performance/summary` and now resolve.
2. **Feature flag** — `PORTFOLIO_PERFORMANCE_ENABLED` now **defaults to enabled**; set `=false` to disable explicitly. (Env also has it set to `true`.)
3. **Wrong data keys / capital constant** — `performance_engine` read `avg_cost` from positions but the store persists `avg_price` (invested/open positions always came out ₹0), and hardcoded `INITIAL_CAPITAL = 500,000` while the store uses **₹50,000**. Now reads `avg_price` (with `avg_cost` fallback) and imports `INITIAL_CAPITAL` from `portfolio_store` (single source of truth).
4. **Trade correlation** — `execute_buy`/`execute_sell` accept `ledger_trade_id` and persist it as a real `phase20_trade_id` metadata field (no longer only inside the `reason` string). `phase20_executor.create_paper_entry` and both exit paths in `phase20_exits` pass the Phase 20 `trade_id`. Historical rows are covered by a **committed, idempotent migration**: `portfolio_store._backfill_phase20_trade_ids()` runs on every schema bootstrap, copies the id parsed from `reason` into metadata, only where metadata doesn't already carry one (never overwrites), and a read-side safety net in `_load_all_trades` derives the id for any row the migration hasn't touched yet.
5. **Session scope defined server-side** — `paper_trader.get_trades()` now returns only non-archived trades whose timestamp falls on the **current IST calendar day**, so "Current Session" can never leak a previous day's trades even if the daily archive reset is missed. `get_all_trades()` (scope=all) keeps the full history including archived rows.
6. **Misleading label** — "Executed Orders — Legacy / Demo Trades" renamed to "Executed Orders — Paper Trade Ledger"; a **Trade ID** column now shows `phase20_trade_id` (falls back to the legacy id).

## End-to-end trace (single BUY, same trade_id)
Trade **P20-4a5f909738** (BAJFINANCE × 8 @ ₹1,100.05, scan `65f39294fd62`):
- Decision/execution: `phase20_paper_trades` row (scan_id, snapshot_ts, strategy, confidence, evidence) ✓
- Paper trade: `paper_trades` row `61208e38` with `metadata.phase20_trade_id = P20-4a5f909738` ✓
- Portfolio: open BAJFINANCE position (cash ₹41,199.60, invested ₹8,800.40) ✓
- Trade History UI: Trade ID column shows `P20-4a5f909738` (Current Session); ALL TIME shows 12 trades incl. ARCHIVED ✓
- Performance: `/portfolio-performance/portfolio` open_positions + FINANCE sector allocation ✓
- Replay: unified replay is built from the latest canonical scan only (existing design); trades from the live scan appear with their trade_id ✓
- EOD: paper-mode reconciliation reads `phase20_paper_trades` by trade_id ✓

## API endpoints validated (all return real data, no nulls/demo)
| Endpoint | Result |
|---|---|
| GET /api/portfolio-performance/summary | ENABLED; value ₹50,000, cash ₹41,199.60, invested ₹8,800.40, full stats block |
| GET /api/portfolio-performance/equity?period=daily\|weekly\|monthly | series + daily_pnl + monthly_pnl (degrades gracefully at 1 point, no dummy data) |
| GET /api/portfolio-performance/drawdown | series + max/current drawdown stats |
| GET /api/portfolio-performance/statistics | trade stats, risk metrics, strategy contribution, top winners/losers |
| GET /api/portfolio-performance/portfolio | open positions, sector allocation ("No open positions" state when flat) |
| GET /api/trades (session) / ?scope=all | session = current IST trading day only (server-side date guard); all = full history incl. archived; both incl. `phase20_trade_id` |
| GET /api/phase20/ledger | full lifecycle rows with trade_id/scan_id |
| /api/performance/* (Optimisation Centre) | unchanged, still maps to `perf_*` |

## Database tables validated
- `paper_trades` (legacy ledger, `metadata.phase20_trade_id` populated + backfilled, `archived_at` scoping)
- `paper_portfolio` (cash/positions/pnl_history; positions keyed by `avg_price`)
- `phase20_paper_trades` (durable ledger, partial unique OPEN-per-symbol index)

## UI components validated (screenshots taken)
- `PortfolioPerformance.tsx` — real Portfolio Value/P&L/Win Rate/Profit Factor/Max Drawdown cards, equity curve, sector allocation pie (FINANCE)
- `Trades.tsx` — Trade ID column, honest "Paper Trade Ledger" label, session/all-time toggle, Phase 20 lifecycle table
- Workspace widgets — `portfolio-performance/summary` endpoint now exists

## Tests
Executed: `python -m pytest portfolio_performance/test_portfolio_performance.py test_task482_trades.py -q` → **56 passed**; `python -m unittest portfolio_performance.test_portfolio_performance` → **48/48 OK** (both re-run with a populated /tmp raw cache present); full monorepo typecheck command → clean.
- `portfolio_performance/test_portfolio_performance.py`: 48/48 — a real bug was found and fixed here: the engine's 30s /tmp raw-data cache leaked real dev data and prior tests' mocked state into later tests; the suite now bypasses the cache module-wide (setUpModule patchers), making results deterministic
- `test_task482_trades.py`: **8/8 pass** — reason-string parsing, guarded/idempotent backfill SQL, IST session-day filter, all-time scope
- `test_phase20.py`: 37/40 pass — the 3 failures (`TestExitsSafety` trailing-stop tests) are **pre-existing** and reproduce with all task changes stashed.
- Monorepo typecheck: clean.

## Notes / limits
- Metrics honestly report zeros when no round-trip has closed (0 closed trades today) — not fabricated values.
- Performance data uses a 30 s file TTL cache; clearing it on trade write is tracked separately (existing task #168).
