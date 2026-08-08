---
name: Broker page & paper reconciliation
description: Broker/Execution page data sources, paper-mode EOD reconciliation rules, paper_trader state API
---

- `paper_trader` no longer exposes `STATE_FILE` — state lives in Postgres via `portfolio_store`. Always go through `paper_trader._load_state()` (DB with file fallback). **Why:** direct file reads miss DB state and broke the Broker page with an ImportError.
- Broker page live figures come from `GET /api/broker/paper-summary` (`phase8_paper_summary` command) — computed from `phase20_paper_trades` only, the same source Replay/Portfolio use. Bootstrap the ledger schema (`phase20_executor._ensure_schema`) before querying so a fresh DB returns zeros, not a 500.
- Paper-mode EOD reconciliation must reconcile the phase20 ledger (today's rows by fill/exit date), never hardcode `orders_checked=0`. Status semantics: OPEN and EXIT_PENDING are both filled positions; CANCELLED needs no fill price. Discrepancy dicts must use the persistence schema keys (`discrepancy_type`, `trading_symbol`, `description`, `internal_order_id`) or `_persist_run` inserts fail silently.
- `build_replay` must NEVER fall back to the latest snapshot when a requested historical scan isn't archived — return an explicit `not_found` error (silently replaying a different scan mixes trade IDs across sessions).
