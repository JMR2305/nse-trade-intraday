---
name: Dashboard scan GET side effect
description: Prevent accidental Phase 7 scans during read-only market-session observation.
---

**Rule:** Observation routes must load the latest durable canonical snapshot;
they must never call the canonical scan engine. `/api/live-data/recommendations`
and `/api/live-data/scan` now follow that rule.

**Why:** A prior market-open cold-cache path delegated to `getP7Scan()`, which
spawned `phase7_scan`. That made a harmless dashboard GET create market evidence
and obscured the scheduler's authority.

**How to apply:** Return an explicit no-snapshot response when nothing is
durable; reject `force` on GET. Keep compute behind the explicit POST action
and preserve that scan's trigger origin. A scheduled session is certifying only
when the stored origin is `SCHEDULED`.