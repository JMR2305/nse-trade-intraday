---
name: Portfolio Postgres store
description: How paper trading state (portfolio, trades, signals) is persisted in Postgres
---

# Portfolio Postgres store

## The rule
Portfolio state (cash, positions, pnl_history) and individual trade records live in Postgres via `portfolio_store.py`. Signals and AI decisions live in `signals_store.py`. Both modules auto-create their tables on first use using `CREATE TABLE IF NOT EXISTS` via psycopg2 — no drizzle-kit migrations needed for the Python-managed tables.

**Why:** Replit Autoscale containers are ephemeral — local JSON files (state.json, signals_cache.json) are lost on restart. Postgres survives.

## How to apply
- `_load_state()` / `_save_state()` in `paper_trader.py` delegate to `portfolio_store.load_state()` / `portfolio_store.save_state()`.
- `portfolio_store.save_state()` always writes a local warm-cache copy (`state.json`) first, then upserts to Postgres.
- Trades use `INSERT ... ON CONFLICT DO NOTHING` so re-saving an identical state never duplicates rows.
- `portfolio_store.delete_all_trades()` must be called on portfolio reset to clear the `paper_trades` table.
- `signals_store.py` provides save/load for keys: `signals`, `ai_decisions`, `opportunity_scan`, `market_context`.

## Tables (auto-created by Python)
- `paper_portfolio` — single row (id=1), cash + positions + pnl_history as JSONB
- `paper_trades` — one row per trade, metadata JSONB for extended fields
- `signals_cache` — key-value, one row per cache type

## TypeScript / Drizzle
The same three tables are declared in `lib/db/src/schema/index.ts` as Drizzle tables for type-safe TS access. `drizzle-kit push` cannot run non-interactively in Replit's shell — use `executeSql()` in `code_execution` or rely on Python's auto-create.

- Portfolio reset is a SOFT reset: it archives paper_trades (archived_at stamp) via archive_all_trades(); never reintroduce DELETE. Default trade loads filter archived_at IS NULL; all-time via load_all_trades_any() / GET /api/trades?scope=all.
