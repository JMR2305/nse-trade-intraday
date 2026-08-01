---
name: Phase 8.5 Operational Control Centre
description: Architecture, score formula, wiring decisions, and READ-ONLY enforcement for Phase 8.5.
---

## Rule
Phase 8.5 is **strictly read-only/advisory-only** — no write paths anywhere. The `advisory_only: True` key must appear in every response dict.

## Feature flag
`OPERATIONS_CENTER_ENABLED=true` (supports "1", "true", "yes" — matches `observability_center` style, not `risk_validation` style).

## Score formula
`ops_score = obs_score×0.25 + dq_score×0.30 + rv_score×0.30 + sched_score×0.15`
where sched_score=100 if scheduler status in (HEALTHY, OK, RUNNING) else 50.
Grade: A+≥92, A≥80, B≥68, C≥50, D<50.

## Upstream snapshots consumed (all via _safe() wrappers)
- `observability_center.shared_services.get_observability_snapshot()`
- `data_quality.shared_services.get_data_quality_snapshot()`
- `risk_validation.shared_services.get_risk_validation_snapshot()`
- `market_intelligence_hub.shared_services.get_market_intelligence_snapshot()`
- `paper_analytics.shared_services.get_paper_analytics_snapshot()`
- `phase20_store.get_scheduler_health()` / `list_scan_runs()` / `list_notifications()`

## Commands (main.py ops_* dispatch)
14 commands: ops_summary, ops_market, ops_paper, ops_risk, ops_data_quality, ops_observability, ops_flags, ops_jobs, ops_alerts, ops_checklist, ops_timeline, ops_snapshot, ops_export_json, ops_export_csv.

## Express routes
`/api/operations/{summary,market,paper,risk,data-quality,observability,flags,jobs,alerts,checklist,timeline,snapshot,export}`
Registered in `artifacts/api-server/src/routes/index.ts` via `operationsRouter`.

## React page
11-tab page at `/operations-center` in the Operations nav group.
Feature flag gate shows "Set OPERATIONS_CENTER_ENABLED=true" when disabled.
Export tab downloads via `${BASE_URL}api/operations/export?format=csv|json`.

**Why:** `BASE_URL` (not root-relative `/api/...`) is mandatory — all artifact routes are path-prefixed.

## Tests
57/57 passing. All upstream calls mocked via `patch.multiple(MOD, **_ALL_LOADERS)`.
