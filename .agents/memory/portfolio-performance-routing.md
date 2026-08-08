---
name: Portfolio performance routing & session semantics
description: Architectural constraints for portfolio analytics routing, trade correlation, and session scoping.
---

- Two features both claim "performance": portfolio analytics must stay under its own `/portfolio-performance/*` namespace; `/performance/*` belongs to the Performance Optimisation Centre. **Why:** they collide on `/performance/summary` and remapping silently breaks one of them.
- Cross-store trade correlation must be a real metadata field, never only embedded in a human-readable reason string; keep a guarded idempotent backfill for historical rows (only fill NULLs, never overwrite).
- "Current Session" is defined server-side as the current IST calendar day, not merely "non-archived". **Why:** a missed daily archive reset would otherwise leak yesterday's trades into today's view and analytics.
- Analytics readers of portfolio positions must not assume field names — verify persisted keys and pull capital constants from the store module, never hardcode copies.
