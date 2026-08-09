---
name: Reconciliation publish bridge
description: Isolation-preserving data path from the intraday trading bot to the dashboard API server.
---

The intraday trading bot is architecturally isolated (own repl + INTRADAY_DATABASE_URL, per docs/PHASE_0_ISOLATION_CHECKLIST.md). The dashboard must never read the bot's database directly.

**Rule:** any bot-produced value the dashboard needs must be *published* by the bot to an authenticated API-server endpoint that upserts into the API server's own store (the UI's single source of truth).

**Why:** code review rejects (and the isolation checklist forbids) coupling the dashboard to the bot DB; matching column names across two databases does nothing.

**How to apply:** pattern = bot-side fail-open async publisher (env-gated by RECON_PUBLISH_URL/RECON_PUBLISH_TOKEN, never breaks the producing operation) → POST with X-Recon-Publish-Token shared secret → API route (503 when token unset, 401 on mismatch) → Python ingestion function with ON CONFLICT (run_id) DO UPDATE idempotency. First instance: reconciliation summaries incl. paper_fallback_count (reconciliation_publisher.py → /broker/reconciliation/publish → publish_reconciliation_summary in eod_reconciliation.py).

Also: bot test suite collection needs python-jose + passlib installed in .pythonlibs (conftest imports the full app).
