# Production Monitoring & Observability Center — ApexQuant AI
## Comprehensive Build Summary

---

## 1. Overview

The **Production Monitoring & Observability Center** (Phase 8.1) is a read-only, advisory-only subsystem that gives operators a live, consolidated view of the health, performance, errors, alerts, and audit history of the entire ApexQuant AI platform. It does not trigger trades, modify risk parameters, or mutate any data.

| Item | Value |
|---|---|
| Phase label | 8.1 |
| Feature flag | `OBSERVABILITY_CENTER_ENABLED=true` |
| Python package | `artifacts/api-server/src/python/observability_center/` |
| Frontend page | `artifacts/trading-dashboard/src/pages/ObservabilityCenter.tsx` |
| Total Python LOC | ~1,809 lines across 13 files |
| Frontend LOC | ~730 lines (12-tab React page) |
| Test suite | 95 / 95 passing |
| Safety contract | READ-ONLY · ADVISORY-ONLY · never calls live data functions from probes |

---

## 2. Architecture

### 2.1 Module Map

```
observability_center/
├── models.py               — Dataclasses (ObsAlert, AuditEntry), enums, grade/trend helpers
├── system_health.py        — /proc-based resource probes: memory, CPU, disk, process, env
├── api_metrics.py          — In-process request log (circular buffer, max 100); latency stats
├── db_metrics.py           — Postgres connectivity probe; pool usage estimation
├── cache_metrics.py        — Cache entry counts across all module _cache dicts
├── job_monitor.py          — Scheduler job list + scan-state (Postgres-backed) readout
├── error_monitor.py        — In-process error log (circular buffer, max 200); error rate/h
├── alert_engine.py         — Cross-module alert generation; SHA-1 dedup; severity routing
├── audit_tracker.py        — In-process audit log (circular buffer, max 500); startup seed
├── performance_dashboard.py — Module response times via import-check probes (no live calls)
├── availability.py         — Per-module feature-flag + importability check; uptime metrics
├── shared_services.py      — Public API aggregator (safe-loader pattern; score formula)
└── api.py                  — Command dispatch for main.py (cmd_summary, cmd_system, …)
```

### 2.2 In-Process Circular Buffers

| Buffer | Max size | Purpose |
|---|---|---|
| `api_metrics._request_log` | 100 entries | API endpoint latencies & status codes |
| `error_monitor._error_log` | 200 entries | Application / API / validation errors |
| `audit_tracker._audit_log` | 500 entries | Operator actions, config changes, flag toggles |
| `alert_engine._active_alerts` | Unbounded dict | Keyed by SHA-1 fingerprint (`category:title`) |

---

## 3. API Endpoints

All routes are served under the `/api/observability/` prefix by the Node.js Express server, which spawns the Python command via the standard `runPython` bridge.

| Endpoint | Python command | Description |
|---|---|---|
| `GET /api/observability/summary` | `cmd_summary()` | Unified score, grade, trend, all sub-system statuses |
| `GET /api/observability/system` | `cmd_system()` | Memory, CPU, disk, process info, feature flags, DB + cache + jobs |
| `GET /api/observability/performance` | `cmd_performance()` | Module response-time probes + API latency histogram |
| `GET /api/observability/errors` | `cmd_errors()` | Error log, error rate/h, category breakdown |
| `GET /api/observability/alerts` | `cmd_alerts()` | Active/resolved alerts with severity and dedup fingerprints |
| `GET /api/observability/audit` | `cmd_audit()` | Operator audit timeline with categories and timestamps |
| `GET /api/observability/snapshot` | `cmd_snapshot()` | Flat KPI dict for Executive Dashboard integration |
| `GET /api/observability/export` | `cmd_export_json()` | Full JSON export of all sub-module payloads |
| `GET /api/observability/export-csv` | `cmd_export_csv()` | CSV export of summary KPIs |

---

## 4. Scoring Model

The **Observability Score** (0–100) is a weighted composite aggregated in `shared_services._compute_obs_score()`:

| Dimension | Weight | Source |
|---|---|---|
| System health | 25 pts | `system_health.health_score` |
| Database health | 20 pts | `db_metrics.health_score` |
| API health | 20 pts | `api_metrics.status == HEALTHY` → 100, else 50 |
| Scheduler / jobs | 15 pts | `job_monitor.scheduler_status`: HEALTHY→100, DEGRADED→50, else→25 |
| Error rate | 10 pts | `max(0, 10 − error_rate_per_h × 0.5)` |
| Availability | 10 pts | `availability.overall_availability_pct / 100 × 10` |

### Grade Thresholds

| Grade | Score |
|---|---|
| A+ | ≥ 92 |
| A | ≥ 80 |
| B | ≥ 68 |
| C | ≥ 50 |
| D | < 50 |

---

## 5. Sub-Module Details

### 5.1 System Health (`system_health.py`)
Reads directly from the Linux `/proc` filesystem — no external packages.

- **Memory**: `/proc/meminfo` → total, used, free (MB), usage% → `DEGRADED` if > 85%
- **CPU**: `/proc/stat` → 2-sample diff for real usage% → `DEGRADED` if > 80%
- **Disk**: `os.statvfs("/")` → used%, `DEGRADED` if > 90%
- **Process**: PID, thread count, open file descriptors
- **Feature flags**: reads all `*_ENABLED` env vars; counts enabled/total
- **Environment**: checks `DATABASE_URL`, `SESSION_SECRET` presence (not values)
- **Uptime**: `/proc/uptime` parsed to hours

### 5.2 API Metrics (`api_metrics.py`)
- `record_request(endpoint, method, status_code, elapsed_ms)` called from request middleware
- Stats computed per session: total requests, avg/p95/p99 latency, error rate, endpoint breakdown
- Status: `HEALTHY` if error rate < 5%, `DEGRADED` if < 20%, `DOWN` otherwise

### 5.3 Database Metrics (`db_metrics.py`)
- Probes Postgres using `socket.create_connection(..., timeout=1)` + `psycopg2.connect(connect_timeout=1)`
- Reports: connection latency (ms), version, active connections
- Pool usage estimated via `pg_stat_activity`
- **Timeout kept at 1 second** — longer values cause the summary endpoint to stall when DB is unreachable

### 5.4 Cache Metrics (`cache_metrics.py`)
- Inspects `_cache` dicts across all enabled modules via `importlib.import_module` + `getattr`
- Reports: total cache entries, per-module entry counts, oldest/newest timestamps

### 5.5 Job Monitor (`job_monitor.py`)
- Reads current scan state from Postgres (`scan_state_store`) to get last scan's `scan_id`, `snapshot_ts`, and status
- Lists background jobs defined in the scan scheduler
- Reports: scheduler status, active job count, last scan time, next estimated run

### 5.6 Error Monitor (`error_monitor.py`)
- `record_error(module, error_type, message, severity)` called at exception sites
- Computes error rate per hour from timestamps in the rolling log
- Category breakdown: SYSTEM / API / VALIDATION / DB / SCAN / OTHER

### 5.7 Alert Engine (`alert_engine.py`)
- Consumes payloads from all sub-monitors and generates `ObsAlert` objects
- **Dedup**: SHA-1 fingerprint of `category:title` — same alert never fires twice
- Auto-resolves alerts when conditions recover (`_clear_if_healthy`)
- Severity matrix:

| Condition | Severity |
|---|---|
| Memory > 90%, CPU > 90%, DB DOWN | CRITICAL |
| Memory > 85%, Scheduler DEGRADED, error rate > 10/h | WARNING |
| First scan run, feature flag changes | INFO |

### 5.8 Audit Tracker (`audit_tracker.py`)
- `record_audit(action, actor, detail, category)` called at config-change sites
- Seeds startup entry on first import
- `get_audit_timeline()` returns chronological log with category counts

### 5.9 Performance Dashboard (`performance_dashboard.py`)
- Probes each Phase 7 module by checking importability + `hasattr` — **never calls the snapshot functions**
- Response-time grades: FAST (< 100 ms), NORMAL (< 500 ms), SLOW (< 2,000 ms), VERY_SLOW
- Overall performance score: weighted average of module response grades

### 5.10 Availability (`availability.py`)
- Per-module availability: checks feature flag + `importlib.import_module` + `callable(getattr(mod, fn))` — **import-check only, never live call**
- Process uptime derived from `time.time() - _process_start`
- Modules tracked: Market Intelligence, Event Intelligence, Macro Intelligence, Explainable AI, Research Lab, Observability Center itself

---

## 6. Critical Design Constraints

### 6.1 Never call Phase 7 snapshot functions from observability probes

This is the single most important architectural rule of the Observability Center.

**Problem**: All Phase 7 snapshot functions (`get_market_intelligence_snapshot()`, `get_research_lab_snapshot()`, etc.) perform live data fetches — yfinance HTTP calls, DB reads, multi-timeframe calculations. Each takes 2–3 seconds. Calling 5 modules = ~15 seconds total, which causes every observability endpoint to time out at the ~4-second dashboard poll.

**Rule**: In `performance_dashboard._probe_snapshots()` and `availability._module_availability()`, only check module *existence and importability*:

```python
mod = sys.modules.get(module_path) or importlib.import_module(module_path)
ok  = callable(getattr(mod, fn_name, None))  # ← check presence, never call
```

### 6.2 Database probe timeout = 1 second

`db_metrics.py` uses `connect_timeout=1` and `socket.create_connection(..., timeout=1)`. Longer timeouts stall the summary endpoint when the database is unreachable.

### 6.3 All outputs are advisory-only

No sub-module writes to any trading, portfolio, strategy, signal, risk, or AI model state. Every Python file has a `READ-ONLY. ADVISORY-ONLY.` docstring as an explicit contract.

### 6.4 Safe-loader pattern in shared_services.py

Every sub-module is loaded through a `_safe(fn, default)` wrapper. If any probe throws, it returns a typed default dict so the summary endpoint always responds — a broken sub-module never crashes the whole observability view.

---

## 7. Data Models

### ObsAlert

```python
@dataclass
class ObsAlert:
    alert_id:     str        # "{category}_{sha1_fingerprint[:12]}"
    severity:     str        # CRITICAL | WARNING | INFO
    category:     str        # SYSTEM | API | DATABASE | CACHE | JOB | ERROR | PERFORMANCE | AVAILABILITY
    title:        str
    detail:       str
    generated_at: str        # ISO-8601 UTC
    acknowledged: bool = False
    resolved:     bool = False
```

### AuditEntry

```python
@dataclass
class AuditEntry:
    entry_id:  str
    action:    str
    actor:     str
    detail:    str
    timestamp: str        # ISO-8601 UTC
    category:  str = "SYSTEM"
```

### Flat Observability Snapshot (for Executive Dashboard)

```python
{
  "observability_score":  float,   # 0–100
  "grade":                str,     # A+ | A | B | C | D
  "trend":                str,     # IMPROVING | STABLE | DEGRADING
  "system_status":        str,     # HEALTHY | DEGRADED | DOWN | UNKNOWN
  "db_status":            str,
  "scheduler_status":     str,
  "error_rate_per_h":     float,
  "availability_pct":     float,
  "performance_score":    float,
  "uptime_hours":         float,
  "available":            bool,
}
```

---

## 8. Frontend Dashboard

**File**: `artifacts/trading-dashboard/src/pages/ObservabilityCenter.tsx` (~730 lines)

The dashboard is a **12-tab React page** accessible via the Monitor icon in the main navigation sidebar.

| Tab | Data source | Key displays |
|---|---|---|
| Summary | `/api/observability/summary` | Observability score ring, grade badge, 6-dimension status cards |
| System | `/api/observability/system` | Memory, CPU, disk gauges; process info; feature flag table |
| Database | `/api/observability/system` (db) | Connection status, latency, pool usage, version |
| Cache | `/api/observability/system` (cache) | Per-module cache entry counts |
| Jobs | `/api/observability/system` (jobs) | Scheduler status, job list, last/next scan times |
| Performance | `/api/observability/performance` | Module response-time table, grade badges |
| API Metrics | `/api/observability/performance` (api) | Endpoint breakdown, p95/p99 latency, error rate |
| Errors | `/api/observability/errors` | Error log table, rate chart, category breakdown |
| Alerts | `/api/observability/alerts` | Alert cards (CRITICAL / WARNING / INFO); resolve history |
| Audit | `/api/observability/audit` | Chronological timeline, category filters |
| Availability | `/api/observability/summary` | Per-module availability badges, uptime counter |
| Export | `/api/observability/export` | JSON / CSV download buttons |

---

## 9. Integration Points

| Consuming system | Integration |
|---|---|
| Executive Dashboard | `get_observability_snapshot()` → flat KPI dict fed into `widget_system_health()` |
| Error middleware (Node.js) | Calls `record_error()` on Python-bridge failures |
| Request middleware | Calls `record_request()` for every API response |
| Audit hooks | Operator save/delete events call `record_audit()` |
| Feature flag changes | Detected automatically at probe time; emits INFO alert |

---

## 10. Test Suite

**File**: Python unit tests (95 tests, 95 passing)

| Test class | Coverage |
|---|---|
| `TestModelsDisabledFlag` | Feature flag off → disabled response shape |
| `TestModelsGradeThresholds` | All 5 grade bands (A+, A, B, C, D) |
| `TestModelsTrendLabel` | IMPROVING / STABLE / DEGRADING boundaries |
| `TestSystemHealth` | Memory/CPU/disk/process/flags/env probes |
| `TestApiMetrics` | Request recording, latency stats, endpoint breakdown |
| `TestDbMetrics` | Successful probe, failure/timeout path |
| `TestCacheMetrics` | Multi-module cache inspection |
| `TestJobMonitor` | Scheduler read, scan-state fallback |
| `TestErrorMonitor` | Error recording, rate calculation, category breakdown |
| `TestAlertEngine` | Alert generation per sub-monitor, dedup, resolve |
| `TestAuditTracker` | record_audit, startup seed, timeline format |
| `TestPerformanceDashboard` | Module probe (import-check only, no live calls) |
| `TestAvailability` | Flag-gated availability, module reachability, uptime |
| `TestSharedServices` | Summary score formula, safe-loader fallbacks |
| `TestExportHelpers` | CSV and JSON export format |

**Key test setup**: All Phase 7 snapshot modules are mocked via `sys.modules` before import to keep the test suite fast (no network I/O).

---

## 11. File Reference

| File | Lines | Role |
|---|---|---|
| `observability_center/models.py` | 113 | Dataclasses, enums, grade/trend helpers, feature flag |
| `observability_center/system_health.py` | 225 | /proc-based resource probes |
| `observability_center/api_metrics.py` | 123 | Request log + latency stats |
| `observability_center/db_metrics.py` | 133 | Postgres connectivity probe |
| `observability_center/cache_metrics.py` | 102 | Module cache inspection |
| `observability_center/job_monitor.py` | 140 | Scheduler + scan-state readout |
| `observability_center/error_monitor.py` | 108 | Error log + rate calculation |
| `observability_center/alert_engine.py` | 177 | Cross-module alert generation |
| `observability_center/audit_tracker.py` | 104 | Operator action audit log |
| `observability_center/performance_dashboard.py` | 116 | Module response-time probes |
| `observability_center/availability.py` | 116 | Uptime + per-module availability |
| `observability_center/shared_services.py` | 325 | Public API, score formula, export |
| `observability_center/api.py` | 24 | Command dispatch for main.py |
| `ObservabilityCenter.tsx` | ~730 | 12-tab React frontend page |

---

## 12. Deployment Checklist

1. Set `OBSERVABILITY_CENTER_ENABLED=true` in shared environment variables.
2. Verify `DATABASE_URL` is set — `db_metrics.py` uses it for the Postgres probe.
3. Confirm the Node.js request middleware calls `record_request()` for every API response.
4. Add `record_error()` calls at any new exception catch sites in the Python bridge.
5. The frontend auto-polls every 30 seconds; no additional scheduler registration required.
6. For high-traffic deployments, consider reducing the API metrics buffer from 100 → 500 entries in `api_metrics.py` to preserve more history.

---

*Document generated: 2026-07-31 · ApexQuant AI — Phase 8.1 Production Monitoring & Observability Center*
