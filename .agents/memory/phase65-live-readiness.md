---
name: Phase 6.5 Live Readiness
description: Live Readiness & Operational Validation Framework — module structure, scoring formula, key design decisions.
---

# Phase 6.5 — Live Readiness & Operational Validation

## Feature flag
`READINESS_VALIDATION_ENABLED=true` — set in shared env.

## Python module
`artifacts/api-server/src/python/live_readiness/` (10 files)
- Separate from `readiness_checker.py` (Phase 8 broker checker) — intentional; Phase 8 imports `execution_engine`.
- `shared_services.py` exposes `get_readiness_snapshot()` as the stable downstream interface.
- `api.py` is the thin main.py dispatch façade.

## Scoring formula (weighted)
SystemHealth 20%, DataQuality 20%, APIHealth 15%, Config 15%, Security 15%, Recovery 15%.
GO/NO-GO: score ≥ 80 + zero required-FAIL → READY; ≥ 60 → READY WITH OBSERVATIONS; else NOT READY.

**Why:** Data quality has the most room to improve with more paper trades; system health reflects module availability not hardware metrics (no psutil dependency — stdlib only).

## Tests
50/50 passing (3.66s). Data quality checker test pattern: patch `_get_records` on the module object, not via `unittest.mock.patch`, to avoid import-path issues.

## API endpoints (8 total)
`readiness_summary`, `readiness_system`, `readiness_data`, `readiness_recovery`, `readiness_security`, `readiness_report`, `readiness_export_csv`, `readiness_export_json` — all in main.py dispatch.

## Wiring
- `routes/readiness.ts` + registered in `routes/index.ts`
- Route: `/live-readiness` in App.tsx
- Nav: Analytics → Live Readiness (Rocket icon) in AppLayout.tsx

## Security invariant
`advisory_only_flags` check fails if `AUTO_EXECUTION_ENABLED=true` or `LIVE_ORDERS_ENABLED=true` — this is an enforced advisory-only gate, not advisory commentary.

## PGPASSWORD note
`PGPASSWORD` is a runtime-managed key whose value matches a known weak-password pattern — triggers `secrets_not_exposed` FAIL. This is a false-positive in dev; the check is still correct and intentional.
