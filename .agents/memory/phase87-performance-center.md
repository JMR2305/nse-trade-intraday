---
name: Phase 8.7 Performance Optimisation Centre
description: Architecture, score formula, upstream reuse rules, and routing gotchas for Phase 8.7.
---

## Feature flag
`PERFORMANCE_CENTER_ENABLED=true` (supports "1", "true", "yes").

## Performance score formula (6-domain)
```
overall = api×0.20 + db×0.20 + cache×0.15 + scheduler×0.15 + resources×0.20 + frontend×0.10
```
Weights sum to 1.00 (verified by test).

## Snapshot formula (lightweight — for Phase 8.8)
```
snapshot_score = obs_score×0.45 + ops_score×0.30 + resource_score×0.25
```

## Critical route pattern
All performance.ts routes MUST import from `../lib/python-env` (not inline PYTHON_DIR/PYTHON_BIN). Using `path.join(__dirname, "../python")` resolves to the wrong path once built (`dist/index.mjs`).

## Upstream modules (read-only, _safe wrapped)
observability_center: api_metrics, db_metrics, cache_metrics, job_monitor, system_health.
operations_center.shared_services: get_operations_snapshot().
security_center.shared_services: get_security_snapshot().
phase20_store: list_scan_runs(limit=20) for benchmark.

## No duplicate profiling rule
Never introduce new profiling probes. All data must derive from existing phase 8.1–8.6 infrastructure.

## Frontend bundle detection
`dist/assets` only exists in production builds; 0 KB in dev mode is expected and not an error.

## Commands (main.py perf_* dispatch)
13 commands: perf_summary, perf_api, perf_database, perf_cache, perf_scheduler, perf_resources, perf_frontend, perf_scalability, perf_benchmark, perf_recommendations, perf_snapshot, perf_export_json, perf_export_csv.

## Tests
70/70 passing. weights_sum_to_1 test guards the formula.

**Why:** Score formula weights must always sum to 1.00 — if domains are added/removed, rebalance all weights.
