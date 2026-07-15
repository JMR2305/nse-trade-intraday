---
name: Phase 15 canonical context
description: Rules for the unified scan context, consistency checker severities, and risk-gate sizing.
---

Rule: every page/module derives values — including market regime — from the
canonical phase7 scan snapshot (phase15_scan_context). Other caches (e.g.
phase13 regime) may only be fallbacks, never preferred, because they can come
from a different snapshot time.

**Why:** Architect review failed Phase 15 when phase13's cached regime was
preferred over the scan's own regime — it injected cross-snapshot state and
broke the "single source of truth" objective.

**How to apply:** When adding new derived data or pages, read through the
unified context. Consistency checker severities: ERROR/CRITICAL (hard,
same-snapshot disagreement), STALE_SOURCE (cache mtime >5min from snapshot_ts),
MISSING_SOURCE (cache missing/empty — must be surfaced, never silently PASS).
Risk gate must size an intended quantity (risk budget & cash bounded) and
evaluate post-trade exposure/sector limits, not current-state-only per-share
heuristics.
