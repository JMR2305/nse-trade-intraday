---
name: Two-environment DB architecture
description: Production and local dev databases are completely separate. Never assume they share state, positions, or settings.
---

## The rule

Production (`nse-trade-intraday.replit.app`) and local dev (`localhost:8080`) are two independent database instances. Any settings change, position creation, or ledger write in one does NOT appear in the other.

**Why:** Confirmed by Phase 0 evidence capture. Production had `initial_capital=500000`, local dev had `initial_capital=100000`. Production had `config_hash=7d842d4e59648fe7`, dev had `efaf1e0cd1acddf2`. After Option C pause, production new hash = `81df262bfdbdaaf5`, dev new hash = `cced4e9be73e79cd`.

**How to apply:**
- Any settings change that must apply to both environments requires TWO separate API calls.
- Never infer production state from dev queries or vice versa.
- Kite login validation must query the same deployed callback/API environment as the login; a missing local-development token does not disprove a valid Autoscale production session.
- The bot DB (intraday-trading-bot) is yet a third database — it targeted the shared workspace DB but alembic was never applied; do not conflate it with either of the two environments above.
- In API server code, the DB connection URL is environment-specific and determined by the runtime environment, not by any code setting.
