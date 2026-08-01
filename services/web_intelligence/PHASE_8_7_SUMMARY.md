# Phase 8.7 — Performance Optimisation & Scalability Framework
## ApexQuant AI · Build Summary

---

## Objective

Build a comprehensive **read-only / advisory-only** Performance Optimisation & Scalability Framework that continuously analyses platform performance and recommends optimisation opportunities. It monitors, profiles, benchmarks and recommends — never modifies.

**Hard constraint:** The module MUST NEVER:
- Modify algorithms, AI models, or strategies
- Modify database records
- Restart services or change configuration automatically
- Place orders or modify portfolio
- Auto-apply any optimisation

Every API response carries `advisory_only: true` and `read_only: true`.

---

## Feature Flag

| Variable | Values accepted | Default |
|---|---|---|
| `PERFORMANCE_CENTER_ENABLED` | `true`, `1`, `yes` | `false` (disabled) |

When the flag is off every endpoint returns `{ "status": "DISABLED", "available": false }`.

---

## Files Delivered

### Python Module — `artifacts/api-server/src/python/performance_center/`

| File | Purpose |
|---|---|
| `__init__.py` | Package marker with advisory-only enforcement docstring |
| `models.py` | Feature-flag helpers, `perf_grade()`, `perf_trend()`, all performance thresholds, `FUTURE_AGENTS` list (10 agents), `PerfRecommendation` / `BenchmarkRecord` dataclasses |
| `shared_services.py` | Full performance engine — 6 domain scorers, all 13 endpoint functions, `_safe()` wrapper, upstream loaders, export helpers. Exposes `get_performance_snapshot()` as stable downstream interface |
| `api.py` | 13 CLI command functions dispatched by `main.py` |
| `test_performance_center.py` | 70-test suite (all passing) |

### Express Route — `artifacts/api-server/src/routes/performance.ts`

Inline `runPython` pattern (consistent with all prior phases). Registers 12 routes:

```
GET /api/performance/summary
GET /api/performance/api
GET /api/performance/database
GET /api/performance/cache
GET /api/performance/scheduler
GET /api/performance/resources
GET /api/performance/frontend
GET /api/performance/benchmark
GET /api/performance/scalability
GET /api/performance/recommendations
GET /api/performance/snapshot
GET /api/performance/export          (?format=json|csv)
```

### React Page — `artifacts/trading-dashboard/src/pages/PerformanceCenter.tsx`

11-tab dashboard at `/performance-center`, registered in the **Operations** nav group as **Performance Centre**:

| Tab | Data source | Refresh |
|---|---|---|
| **Overview** | `/performance/summary` | 20 s |
| **API** | `/performance/api` | 20 s |
| **Database** | `/performance/database` | 30 s |
| **Cache** | `/performance/cache` | 30 s |
| **Scheduler** | `/performance/scheduler` | 20 s |
| **Resources** | `/performance/resources` | 15 s |
| **Frontend** | `/performance/frontend` | 60 s |
| **Benchmark** | `/performance/benchmark` | 30 s |
| **Recommendations** | `/performance/recommendations` | 30 s |
| **Scalability** | `/performance/scalability` | 60 s |
| **Export** | Client-side fetch on demand | — |

### Wiring Changes

| File | Change |
|---|---|
| `artifacts/api-server/src/routes/index.ts` | Already registered at line 69 (pre-existing stub slot) |
| `artifacts/api-server/src/python/main.py` | 13 `perf_*` command dispatchers (after Phase 8.6 block) |
| `artifacts/trading-dashboard/src/App.tsx` | Import `PerformanceCenter` + `<Route path="/performance-center">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Nav entry **Performance Centre** under Operations group |

---

## Architecture

### Upstream Modules Reused (No Duplicate Profiling)

All calls wrapped in `_safe(fn, default)` — upstream failures never propagate.

| Upstream module | Data consumed |
|---|---|
| `observability_center.api_metrics` | In-process API request log (count, avg, p95, error rate, endpoint breakdown) |
| `observability_center.db_metrics` | DB connection probe, latency, pool config |
| `observability_center.cache_metrics` | 6 module caches — entry count, freshness, stale detection |
| `observability_center.job_monitor` | Scheduler status, scan age, job list, health score |
| `observability_center.system_health` | `/proc` memory, CPU load, disk, process RSS, feature flags |
| `operations_center.shared_services` | `get_operations_snapshot()` — ops score for snapshot |
| `security_center.shared_services` | `get_security_snapshot()` — security score for context |
| `phase20_store` | `list_scan_runs(limit=20)` — scan duration history for benchmark |

No new profiling is introduced. All data derives from existing Phase 8.1–8.6 infrastructure.

### Performance Score Formula — Summary Endpoint

```
performance_score = api_score      × 0.20
                  + db_score       × 0.20
                  + cache_score    × 0.15
                  + scheduler_score × 0.15
                  + resource_score × 0.20
                  + frontend_score × 0.10
```

Weights sum to 1.00 (verified by `test_weights_sum_to_1`).

### Snapshot Interface Formula (lightweight — for Phase 8.8 downstream)

```
performance_score = obs_score  × 0.45
                  + ops_score  × 0.30
                  + res_score  × 0.25
```

### Grade Mapping

| Grade | Score |
|---|---|
| A+ | ≥ 92 |
| A  | ≥ 80 |
| B  | ≥ 68 |
| C  | ≥ 50 |
| D  | < 50 |

### Trend Labels

| Trend | Condition |
|---|---|
| IMPROVING | current > baseline + 5 |
| DEGRADING | current < baseline − 5 |
| STABLE    | within ±5 of baseline |

---

## Performance Methodology

### 1 — API Performance

- Source: `observability_center.api_metrics` in-process circular buffer (max 100 requests)
- Measures: request count, avg/p95 latency, error rate, slow requests (>500 ms), endpoint breakdown
- Score: starts at 100, penalised for avg > 300 ms, p95 > 800 ms, error rate > 2%
- Note: reflects Python-process requests only; TypeScript-layer telemetry is separate

### 2 — Database Performance

- Source: `observability_center.db_metrics` — `SELECT 1` probe via psycopg2 or socket fallback
- Measures: connection latency, connected/disconnected, pool config, slow query threshold
- Score: starts at 100, penalised for latency > 50 ms; 20/0 for disconnected/unknown

### 3 — Cache Performance

- Source: `observability_center.cache_metrics` — inspects 6 Python module `_cache` dicts via `sys.modules`
- Measures: total entries, stale entries (> 2 min), hit rate estimate, memory estimate (2 KB/entry)
- Score: `hit_rate_est − (stale_count × 5)`, floor 0

### 4 — Scheduler Performance

- Source: `observability_center.job_monitor` + `phase20_store.list_scan_runs(limit=20)`
- Measures: scheduler status, last scan age, job list, avg/max scan duration from history
- Score: HEALTHY → 90, DEGRADED → 55, UNKNOWN → 30

### 5 — Resource Performance (CPU, Memory, Disk, Python Process, Node Processes)

- Source: `observability_center.system_health` — pure `/proc` filesystem reads (no external tools)
- Measures: memory usage %, CPU load average (1/5/15 min), disk usage %, RSS/VM/threads for Python worker, Node process count from `/proc/*/comm`
- Score: starts at 100, penalised for mem > 80%, CPU load > 2.0, disk > 85%

### 6 — Frontend Performance

- Source: `dist/assets` directory size measurement (production build only)
- Measures: total JS+CSS bundle size, estimated page load (heuristic: KB/100 × 80 + 400 ms), build feature flags (lazy loading, code splitting, Vite, React Query)
- Score: starts at 100, penalised for bundle > 1,500 KB
- Note: real Core Web Vitals require browser-side instrumentation; dev-mode bundle = 0 KB is expected

### 7 — Benchmark

- Source: `phase20_store.list_scan_runs(limit=20)` — duration history
- Compares: current session (last 5 runs), rolling average (last 20), peak (best), worst
- Trend: latest vs rolling average ±10% threshold

### 8 — Recommendations Engine

- Aggregates all 6 sub-modules and generates advisory suggestions with domain, severity (INFO/WARNING/CRITICAL), title, and detail
- Examples generated:
  - API: "API response time above target" / "API error rate elevated"
  - DB: "Database connection latency above target" / "Database unreachable"
  - Cache: "Multiple stale cache entries" / "Cache hit rate below target"
  - Scheduler: "Scheduler approaching execution limit"
  - Resources: "Memory usage approaching limit" / "CPU load elevated" / "Disk usage high"
  - Frontend: "Dashboard bundle size above threshold"
- If no issues: "Platform performance within all targets" (INFO)
- **NEVER auto-applies any recommendation**

### 9 — Scalability Estimation

- Current capacity: max symbols per scan (mem_free_mb / 2), concurrent users (cpu_headroom × 5), scheduler slots, scheduler load %, headroom %
- Recommended capacity: 2× current, capped at MAX_SYMBOLS_PER_SCAN=500, CONCURRENT_USER_TARGET=20
- Multi-agent readiness: 10 future agent roles listed; agents_possible = mem_free_mb / 128 MB estimate
- All estimates are heuristic; production sizing requires load testing

---

## Scalability Design

### Future Multi-Agent Architecture Readiness

The `get_performance_snapshot()` interface is designed so that Phase 8.8 (Deployment & Disaster Recovery) and a future multi-agent orchestrator can query performance health without any architectural changes:

```python
from performance_center.shared_services import get_performance_snapshot

snap = get_performance_snapshot()
# Returns (lightweight — no DB probe, no dependency scan):
# {
#   "available": True,
#   "advisory_only": True,
#   "read_only": True,
#   "performance_score": float,   # 0–100
#   "grade": "A+" | "A" | "B" | "C" | "D",
#   "obs_score": float,
#   "ops_score": float,
#   "resource_score": float,
#   "generated_at": ISO-8601 str,
# }
```

The 10 future agent roles registered in `FUTURE_AGENTS`:
- Market Data Agent, Research Agent, Market Intelligence Agent, Stock Monitoring Agent
- Strategy Agent, Risk Agent, AI Decision Agent, Execution Agent, Learning Agent, Supervisor Agent

---

## Test Coverage

**70 / 70 tests — all passing (1.74 s)**

| Test Class | Tests | Coverage |
|---|---|---|
| `TestFeatureFlag` | 5 | Flag gate, disabled by default, summary disabled when flag off |
| `TestGradeHelpers` | 8 | All 5 grades, all 3 trends |
| `TestApiPerformance` | 5 | Keys, advisory, score range, grade, targets |
| `TestDatabasePerformance` | 5 | Keys, advisory, score range, connection keys, targets |
| `TestCachePerformance` | 5 | Keys, advisory, score range, hit rate range, targets |
| `TestSchedulerPerformance` | 5 | Keys, advisory, score range, jobs list, scan timing keys |
| `TestResourcePerformance` | 5 | Keys, advisory, score range, memory keys, node process count |
| `TestFrontendPerformance` | 4 | Keys, advisory, score range, bundle keys |
| `TestScalability` | 5 | Keys, advisory, capacity keys, agent list, max symbols > 0 |
| `TestBenchmark` | 4 | Keys, advisory, trend valid, comparison keys |
| `TestRecommendations` | 5 | Keys, advisory, ≥1 rec, rec schema, severity values |
| `TestSummary` | 5 | Keys, advisory, score range, all 6 component scores, weights sum to 1.0 |
| `TestSnapshot` | 3 | Keys, available, advisory + read_only |
| `TestExport` | 4 | JSON keys, advisory, CSV key, CSV format |
| `TestApiCommands` | 2 | All 13 cmds return dicts, snapshot available |

---

## GitHub-Inspired Enhancements

Inspired by performance monitoring patterns from reviewed projects (without copying implementations):

| Enhancement | Implementation |
|---|---|
| **Multi-domain performance scoring** | 6-domain weighted composite score (API 20%, DB 20%, Cache 15%, Scheduler 15%, Resources 20%, Frontend 10%) |
| **Query profiling** | DB latency probe, slow query threshold advisory, endpoint breakdown by avg latency |
| **Cache analytics** | 6 in-process cache monitoring with hit-rate estimation and stale detection |
| **Scheduler analytics** | Scan duration history from phase20_store, avg/max/trend, job queue monitoring |
| **Scalability estimation** | Heuristic capacity model (symbols, users, agents) from live resource metrics |
| **Optimisation recommendations** | Prioritised advisory suggestions (CRITICAL/WARNING/INFO) per domain with actionable detail |

---

## Known Limitations

| Limitation | Reason |
|---|---|
| API metrics are per-process only | In-process circular buffer; TypeScript-layer metrics require middleware instrumentation |
| Frontend metrics are heuristic | Real Core Web Vitals require browser-side instrumentation (Lighthouse, web-vitals library) |
| Bundle size = 0 in dev mode | `dist/assets` does not exist until a production build; 0 KB is expected in development |
| DB pool introspection is partial | Active/idle connection counts require ORM instrumentation (not available without modifying the ORM layer) |
| Benchmark is scan-duration only | Cross-session API latency benchmarking requires persistent timing storage (e.g., Redis time series) |
| Cache hit rate is estimated | True hit/miss counting requires instrumented cache wrappers; current metric is freshness-based |
| Scalability estimates are heuristic | Production sizing requires load testing; these are advisory order-of-magnitude estimates |

---

## Deployment Checklist

- [x] `PERFORMANCE_CENTER_ENABLED=true` set in environment
- [x] API server restarted — build clean, all routes registered
- [x] 12 endpoints under `/api/performance/*` responding
- [x] Dashboard nav entry **Performance Centre** visible under Operations group
- [x] 11 tabs render; disabled state shows setup prompt when flag is off
- [x] All responses carry `advisory_only: true` and `read_only: true`
- [x] Export tab generates advisory-only JSON/CSV
- [x] 70/70 unit tests passing (1.74 s)

---

## PHASE 8.7 COMPLETE

All deliverables provided:

1. ✅ **Files created** — 5 Python module files, 1 Express route, 1 React page
2. ✅ **Files modified** — `main.py`, `App.tsx`, `AppLayout.tsx`
3. ✅ **Shared services reused** — observability_center (4 sub-modules), operations_center, security_center, phase20_store
4. ✅ **APIs** — 12 GET endpoints under `/api/performance/*`
5. ✅ **Dashboard** — 11-tab React page at `/performance-center`
6. ✅ **Test count** — 70 tests
7. ✅ **Test results** — 70/70 passing (1.74 s)
8. ✅ **Performance methodology** — 9-domain analysis (API, DB, Cache, Scheduler, Resources, Frontend, Benchmark, Recommendations, Scalability)
9. ✅ **Known limitations** — documented above
10. ✅ **GitHub-inspired enhancements** — 6 patterns applied
11. ✅ **Future integration** — `get_performance_snapshot()` stable interface ready for Phase 8.8 and 10-agent multi-agent readiness table
12. ✅ **READ-ONLY and ADVISORY-ONLY** — confirmed; `advisory_only: true` + `read_only: true` in every response; no write paths exist anywhere in the module; no auto-optimisations

*Phase 8.7 complete — READ-ONLY · ADVISORY-ONLY*
