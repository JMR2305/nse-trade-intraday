# Phase 8.5 — Operational Control Centre
## ApexQuant AI · Build Summary

---

## Objective

Build a comprehensive **read-only / advisory-only** Operational Control Centre that aggregates live platform health data from all prior phases (8.1 Observability, 8.3 Data Quality, 8.4 Risk Validation, Phase 7 Market / Event / Macro Intelligence, paper trading, and the scheduler) into a single operator-facing console with 11 dashboard tabs and a composite Operations Score.

**Hard constraint:** The module never places orders, modifies portfolio, strategies, AI models, risk parameters, feature flags, or restarts services. Every API response carries `advisory_only: true`.

---

## Feature Flag

| Variable | Values accepted | Default |
|---|---|---|
| `OPERATIONS_CENTER_ENABLED` | `true`, `1`, `yes` | `false` (disabled) |

When the flag is off every endpoint returns `{ "status": "DISABLED", "available": false }` and the dashboard tab shows a setup prompt.

---

## Files Delivered

### Python Module — `artifacts/api-server/src/python/operations_center/`

| File | Purpose |
|---|---|
| `__init__.py` | Package marker + advisory-only docstring |
| `models.py` | Feature-flag helpers, grade/trend functions, status constants, checklist phase logic, `KNOWN_FLAGS` list (20 flags), dataclasses (`OpsAlert`, `TimelineEvent`, `ChecklistItem`) |
| `shared_services.py` | Aggregation layer — all upstream snapshot loaders wrapped in `_safe()`, score computation, market status, paper trading status, alert aggregation, checklist builder, timeline builder, feature-flag enumerator, export helpers. Exposes `get_operations_snapshot()` as the stable downstream interface |
| `api.py` | 14 CLI command functions called by `main.py` dispatch |
| `test_operations_center.py` | 57-test suite covering all modules, all endpoints, grade helpers, flag logic, alert aggregation, checklist, timeline, jobs, export |

### Express Route — `artifacts/api-server/src/routes/operations.ts`

Inline `runPython` helper (matches all prior phase patterns). Registers 14 routes:

```
GET /api/operations/summary
GET /api/operations/market
GET /api/operations/paper
GET /api/operations/risk
GET /api/operations/data-quality
GET /api/operations/observability
GET /api/operations/flags
GET /api/operations/jobs
GET /api/operations/alerts
GET /api/operations/checklist
GET /api/operations/timeline
GET /api/operations/snapshot
GET /api/operations/export        (?format=json|csv)
```

### React Page — `artifacts/trading-dashboard/src/pages/OperationsCenter.tsx`

11-tab dashboard at `/operations-center`, registered in the **Operations** nav group:

| Tab | Data source | Refresh interval |
|---|---|---|
| **Overview** | `/operations/summary` | 20 s |
| **Market** | `/operations/market` | 15 s |
| **Paper Trading** | `/operations/paper` | 15 s |
| **Risk** | `/operations/risk` | 30 s |
| **Data Quality** | `/operations/data-quality` | 30 s |
| **Observability** | `/operations/observability` | 20 s |
| **Jobs** | `/operations/jobs` | 15 s |
| **Alerts** | `/operations/alerts` | 15 s |
| **Checklist** | `/operations/checklist` | 30 s |
| **Timeline** | `/operations/timeline` | 30 s |
| **Export** | Client-side fetch on demand | — |

### Wiring Changes

| File | Change |
|---|---|
| `artifacts/api-server/src/routes/index.ts` | Import + `router.use(operationsRouter)` |
| `artifacts/api-server/src/python/main.py` | 14 `ops_*` command dispatchers (after Phase 8.4 block) |
| `artifacts/trading-dashboard/src/App.tsx` | Import `OperationsCenter` + `<Route path="/operations-center">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Nav entry in **Operations** group |

---

## Architecture

### Operations Score (0–100)

```
ops_score = observability_score × 0.25
          + data_quality_score  × 0.30
          + risk_validation_score × 0.30
          + scheduler_score     × 0.15

scheduler_score = 100  if status ∈ {HEALTHY, OK, RUNNING}
                = 50   otherwise
```

### Grade Mapping

| Grade | Score range |
|---|---|
| A+ | ≥ 92 |
| A  | ≥ 80 |
| B  | ≥ 68 |
| C  | ≥ 50 |
| D  | < 50 |

### Platform Status

| Condition | Status |
|---|---|
| Score ≥ 80, 0 critical DQ issues, obs not DOWN/DEGRADED | `OPERATIONAL` |
| Score ≥ 50 or critical ≤ 2 | `DEGRADED` |
| Otherwise | `DOWN` |

### Upstream Snapshot Consumers

All upstream calls use `_safe(fn, default)` — any exception returns the default; the Centre never propagates upstream failures to operators.

| Upstream module | Snapshot function |
|---|---|
| `observability_center` | `get_observability_snapshot()` |
| `data_quality` | `get_data_quality_snapshot()` |
| `risk_validation` | `get_risk_validation_snapshot()` |
| `market_intelligence_hub` | `get_market_intelligence_snapshot()` |
| `paper_analytics` | `get_paper_analytics_snapshot()` |
| `phase20_store` | `get_scheduler_health()`, `list_scan_runs()`, `list_notifications()` |

---

## Daily Operator Checklist

Auto-generated based on current IST time. Six phases with auto-status resolution where possible:

| Phase | IST window | Items |
|---|---|---|
| Morning | Before 09:00 | 8 items — platform health, Kite session, scheduler, risk limits |
| Pre-Open | 09:00–09:15 | 6 items — IEP/IEQ data, AI signals, risk score, regime |
| Market Open | 09:15–09:30 | 5 items — live signals, auto-paper state, first scan |
| Mid-Session | 09:30–14:00 | 6 items — exposure, P&L, data freshness, scheduler heartbeat |
| Closing | 14:00–15:30 | 5 items — position review, EOD signals, reconciliation |
| End of Day | After 15:30 | 7 items — session report, trade reconciliation, alerts cleared |

Items marked `OK` / `WARNING` / `UNKNOWN` from live platform state; `UNKNOWN` = manual verification required.

---

## Alert Aggregation

Pulls from four sources, normalised to a common schema:

| Source | Pull method |
|---|---|
| Observability Center | `get_alerts()` → `alerts[]` list |
| Data Quality | `get_data_quality_snapshot()` → `issues[]` |
| Risk Validation | `get_risk_validation_snapshot()` → `alerts[]` |
| Scheduler / Phase 20 | `list_notifications()` unread items as INFO |

Severity buckets: `CRITICAL` / `WARNING` / `INFO` / `resolved`.

---

## Feature Flags Display

20 known flags enumerated across 5 categories (`core`, `trading`, `intelligence`, `analytics`, `ai`, `experimental`). Read-only — `read_only: true` in every response. No editing path exists.

---

## Export

| Format | Endpoint | Content |
|---|---|---|
| JSON | `GET /api/operations/export?format=json` | Full snapshot of all 11 sub-modules |
| CSV | `GET /api/operations/export?format=csv` | Score metrics table (metric, value) |

Download triggers via `Content-Disposition: attachment` header.

---

## Test Coverage

**57 / 57 tests — all passing (0.53 s)**

| Test class | Tests | Coverage |
|---|---|---|
| `TestFeatureFlag` | 5 | Flag gate, all endpoints disabled |
| `TestSnapshotAggregation` | 9 | Score formula, platform status, snapshot keys |
| `TestSummary` | 4 | Required keys, grade validity |
| `TestMarket` | 3 | Keys, advisory flag, bool market_open |
| `TestAlerts` | 4 | Aggregation, DQ issues, obs alerts, count consistency |
| `TestChecklist` | 5 | Keys, items structure, phase string, completion pct |
| `TestTimeline` | 4 | Keys, scan run events, event fields |
| `TestJobs` | 3 | Keys, failed run detection, advisory flag |
| `TestFeatureFlags` | 5 | Keys, read_only, env-driven enabled list |
| `TestExport` | 4 | JSON keys, advisory flag, CSV format, CSV header |
| `TestApiCommands` | 2 | All 14 commands return dicts, snapshot available |
| `TestGradeHelpers` | 8 | All grade thresholds, all trend labels |
| `TestChecklistPhase` | 2 | KNOWN_FLAGS count and structure |

---

## Downstream Interface

```python
from operations_center.shared_services import get_operations_snapshot

snap = get_operations_snapshot()
# Returns:
# {
#   "available": True,
#   "advisory_only": True,
#   "operations_score": float,
#   "grade": "A+" | "A" | "B" | "C" | "D",
#   "platform_status": "OPERATIONAL" | "DEGRADED" | "DOWN",
#   "observability_score": float,
#   "quality_score": float,
#   "validation_score": float,
#   "scheduler_status": str,
#   "generated_at": ISO-8601 str,
# }
```

Stable for Phase 8.6, 8.7, 8.8, or any future consumer.

---

## Deployment Checklist

- [x] `OPERATIONS_CENTER_ENABLED=true` set in environment
- [x] API server restarted (build + start confirmed clean)
- [x] `/api/operations/summary` → 200 in under 250 ms
- [x] Dashboard nav entry **Operations Center** visible under Operations group
- [x] 11 tabs render; disabled state shows setup prompt when flag is off
- [x] 57/57 unit tests passing

---

*Phase 8.5 complete — READ-ONLY · ADVISORY-ONLY*
