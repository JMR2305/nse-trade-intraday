---
name: Phase 8.8 Deployment & DR Centre
description: Architecture, score formula, backup proxy approach, and routing conventions for Phase 8.8.
---

## Feature flag
`DEPLOYMENT_CENTER_ENABLED=true` (supports "1", "true", "yes").

## DR Score formula (5-domain, weights sum to 1.00)
```
dr_score = readiness×0.25 + infra×0.25 + backup×0.20 + config×0.15 + continuity×0.15
```
Verified by `TestScoreFormula.test_weights_sum_to_1`.

## Stable downstream interface
`get_deployment_snapshot()` in `shared_services.py` — lightweight dict for Phase 8.9+ consumers; no raw metric recalculation.

## Backup validation approach
No dedicated backup infrastructure exists. Backup validation proxies through `phase20_store.list_scan_runs()`:
- Latest `completed` scan → backup timestamp
- Age ≤ 24h → READY; 24–72h → DEGRADED; > 72h → NOT_READY
- `backup_size_kb` is always None (direct DB query avoided to stay read-only)

## Routing convention
All routes in `deployment.ts` import `{ PYTHON_BIN, PYTHON_DIR }` from `"../lib/python-env"` (not inline).
Commands follow the `deploy_*` prefix in `main.py`.

## Upstream modules (read-only, _safe wrapped)
- `observability_center.shared_services.get_observability_snapshot()` — API availability probe
- `observability_center.system_health.get_system_health()` — mem/CPU/disk
- `observability_center.db_metrics.get_db_metrics()` — DB connectivity
- `phase20_store.list_scan_runs()` — backup proxy
- `phase20_store.get_scheduler_health()` — scheduler status

## Tests
109/109 passing.

**Why:** Backup age thresholds (24h/72h) are advisory policy — change `BACKUP_MAX_AGE_HOURS` in models.py to adjust without touching business logic.
