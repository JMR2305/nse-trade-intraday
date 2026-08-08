---
name: Portfolio config overrides hot-reload
description: How operator limit edits reach both fresh Python processes and long-lived services without restart.
---

Operator limit edits persist to a durable Python-side override store (Postgres, file fallback, env kill switch `PORTFOLIO_OVERRIDES_DISABLED=1` for hermetic tests).

**Rules:**
- The durable store is authoritative; Node keeps NO in-memory override copy (memory goes stale relative to what strategies enforce).
- Long-lived services: collaborators capture their own config reference at construction, so swapping the service's config attribute alone does nothing. Config hot-swap must go through the single service-level `apply_config()` which updates every config-holding collaborator; a change-stamp check at each decision entry point triggers it.
- Writes use atomic JSONB `||` merge (concurrent edits on different fields can't lose updates); set-time validation constructs the full config; read-time is fail-open to env config (a broken store must never block the pipeline).

**Why:** every route/scheduler Python spawn is fresh, but the executor process is long-lived; both paths must see edits on the next decision cycle.

**Pitfall:** tests asserting env-default config values must set the kill switch or persisted dev-DB overrides leak in and fail them.
