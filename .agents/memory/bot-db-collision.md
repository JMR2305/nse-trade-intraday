---
name: Trading bot DB collision & migration state
description: intraday-trading-bot shares the workspace Postgres with the API server; alembic never applied; table-name collision on broker_reconciliation_runs.
---

- `intraday-trading-bot/.env` points INTRADAY_DATABASE_URL(_SYNC) at the SAME helium/heliumdb Postgres the API server uses.
- The bot's Alembic migrations (0001–0007) have NEVER been applied to that DB: no `alembic_version`, none of the bot's tables (e.g. `broker_order_correlations`) exist in dev or prod.
- **Why this matters:** migration 0006 `create_table`s `broker_reconciliation_runs` / `broker_reconciliation_discrepancies` — names the API server's Python store already owns in that DB with a *different* column set (api store has `error`, no `id`). Running `alembic upgrade head` against the shared DB fails on collision.
- **How to apply:** before any live bot session, the bot needs a separate database (or schema) for its Alembic-managed tables; never run its migrations into the shared workspace DB as-is.
- Dashboard-side reconciliation tables are NOT Alembic-managed: `eod_reconciliation.py` self-heals with `ADD COLUMN IF NOT EXISTS` at runtime — prod gets new columns only after a republish ships the new Python.
- Alembic CLI note: `migrations/env.py` builds an async engine from `sqlalchemy.url`, so the URL must be `postgresql+asyncpg://` (a sync psycopg2 URL makes `alembic current` crash).
