---
name: Phase 16 validation dashboard
description: Durable lessons from building the paper trading validation layer
---

**Rule:** AI decision cache entries use the `decision` field (values like NO_TRADE), not `final_action`/`action`. Any consumer must read `decision` first or counts silently come out zero.
**Why:** Phase 16 AI validation initially reported 0 recommendations despite 10 cached decisions; architect review caught it.
**How to apply:** When aggregating from ai_decisions_cache.json, parse `decision` → `final_action` → `action` and map NO_TRADE/AVOID to IGNORE.

**Rule:** Dashboard pages that need many Python-derived sections should call one combined CLI command (single spawn) instead of N parallel endpoints.
**Why:** 14 parallel python spawns took ~7s per page load; a combined `phase16_all` command returns everything in <1s.
**How to apply:** Add an aggregate `*_all` command in main.py and one route; keep per-section endpoints for targeted use.

**Rule:** Health verdict strings must match between backend and UI (backend emits PASS, not HEALTHY).
**Why:** UI showed failure styling for a passing health check.
