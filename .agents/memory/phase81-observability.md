---
name: Phase 8.1 Observability Center
description: Architecture and critical lessons for the Production Monitoring & Observability Center.
---

# Phase 8.1 — Production Monitoring & Observability Center

## Architecture
- Package: `artifacts/api-server/src/python/observability_center/`
- 12 sub-modules: models, system_health, api_metrics, db_metrics, cache_metrics,
  job_monitor, error_monitor, alert_engine, audit_tracker, performance_dashboard,
  availability, shared_services + api.py
- 6 routes: `/observability/summary|system|performance|errors|alerts|audit`
  (+ `/snapshot` and `/export`)
- Feature flag: `OBSERVABILITY_CENTER_ENABLED=true`
- Dashboard: `artifacts/trading-dashboard/src/pages/ObservabilityCenter.tsx`
  (12-tab React page, Monitor icon in nav)

## Critical: Never call Phase 7 snapshot functions from observability probes
`performance_dashboard._probe_snapshots()` and `availability._module_availability()`
must ONLY check `sys.modules` + `importlib.import_module` + `hasattr` —
never call the actual snapshot functions (e.g. `get_market_intelligence_snapshot()`).
Calling them triggers yfinance/network requests (2–3s per module × 5 modules = 15s total),
causing the summary/performance/alerts endpoints to time out at ~4 seconds.

**Why:** All Phase 7 snapshot functions do live data fetches. They are fine to call
from their own routes (user accepts the latency) but not from observability probes
that are called on every dashboard poll.

**How to apply:** In any new observability sub-module that needs to check module
health, use this pattern:
```python
mod = sys.modules.get(module_path) or importlib.import_module(module_path)
ok = callable(getattr(mod, fn_name, None))  # ← check existence, never call
```

## DB probe timeout
Keep `connect_timeout=1` and `socket.create_connection(..., timeout=1)` in db_metrics.py.
Longer timeouts (e.g. 3s) cause the summary endpoint to stall when DB is unreachable.

## Test count
95/95 tests in test_observability_center.py. Tests mock all Phase 7 snapshot
modules via `sys.modules` before import — critical for fast test execution.

## In-process circular buffers
- `api_metrics._request_log` max 100 entries
- `error_monitor._error_log`  max 200 entries
- `audit_tracker._audit_log`  max 500 entries
- `alert_engine._active_alerts` dict keyed by SHA-1 fingerprint

## Score formula (0–100)
System 25pts + DB 20pts + API 20pts + Jobs 15pts + Errors 10pts + Availability 10pts
