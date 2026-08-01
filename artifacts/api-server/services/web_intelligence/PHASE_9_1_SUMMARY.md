# Phase 9.1 — ApexQuant AI Unified Command Centre

## Status: COMPLETE

**Date:** 2026-08-01  
**Type:** READ-ONLY · ADVISORY-ONLY  
**Feature flag:** `COMMAND_CENTER_ENABLED=true`

---

## Purpose

Single aggregation dashboard that pulls snapshot data from all existing modules into one page.  
No new calculations — every number is taken directly from upstream `get_*_snapshot()` calls.

---

## Files Created

### Python Module
| File | Purpose |
|------|---------|
| `src/python/command_center/__init__.py` | Package marker |
| `src/python/command_center/models.py` | Feature flag, grade helpers, QUICK_ACTIONS, constants |
| `src/python/command_center/shared_services.py` | All aggregation logic, 4 public functions + snapshot + export |
| `src/python/command_center/api.py` | CLI command wrappers for main.py dispatch |
| `src/python/test_command_center.py` | **81/81 tests pass** |

### API Route
| File | Routes |
|------|--------|
| `src/routes/command-center.ts` | `GET /api/command-center/summary` |
| | `GET /api/command-center/briefing` |
| | `GET /api/command-center/alerts` |
| | `GET /api/command-center/timeline` |
| | `GET /api/command-center/export?format=json|csv` |

### Frontend
| File | Purpose |
|------|---------|
| `artifacts/trading-dashboard/src/pages/CommandCenter.tsx` | 13-section React dashboard |

---

## Files Modified

| File | Change |
|------|--------|
| `src/python/main.py` | 7 new `cmd_center_*` commands dispatched |
| `src/routes/index.ts` | `commandCenterRouter` imported and registered |
| `artifacts/trading-dashboard/src/App.tsx` | Import + `/command-center` route added |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | "Command Centre" added as FIRST item in Operations group |

---

## Upstream Snapshot Interfaces Consumed

| Module | Function |
|--------|----------|
| `market_intelligence_hub` | `get_market_intelligence_snapshot()`, `get_overview()` |
| `paper_analytics` | `get_paper_analytics_snapshot()` |
| `executive_dashboard` | `get_executive_snapshot()` |
| `ai_performance` | `get_ai_snapshot()` |
| `risk_validation` | `get_risk_validation_snapshot()` |
| `data_quality` | `get_data_quality_snapshot()` |
| `observability_center` | `get_observability_snapshot()` |
| `operations_center` | `get_operations_snapshot()` |
| `security_center` | `get_security_snapshot()` |
| `performance_center` | `get_performance_snapshot()` |
| `deployment_center` | `get_deployment_snapshot()` |
| `phase20_store` | `list_notifications()`, `list_scan_runs()`, `get_scheduler_health()` |

---

## API Endpoints

| Endpoint | Timeout | Description |
|----------|---------|-------------|
| `GET /api/command-center/summary` | 90s | Full platform snapshot — all 12 sections |
| `GET /api/command-center/briefing` | 60s | Natural-language AI daily briefing |
| `GET /api/command-center/alerts` | 60s | Aggregated alerts by severity (CRITICAL/WARNING/INFO) |
| `GET /api/command-center/timeline` | 30s | Session timeline from scans + notifications |
| `GET /api/command-center/export?format=json` | 90s | Full JSON export |
| `GET /api/command-center/export?format=csv` | 90s | CSV export of key KPIs |

---

## React Page Sections

| # | Section | Data Source |
|---|---------|-------------|
| Header | Platform header bar | summary: platform_score, scheduler_status |
| 1 | Market Overview | summary.market (regime, indices, breadth, sectors) |
| 2 | Portfolio Snapshot | summary.portfolio (executive + paper analytics) |
| 3 | Today's Trading | summary.trading (paper analytics) |
| 4 | AI Summary | summary.ai (ai_performance snapshot) |
| 5 | Risk Summary | summary.risk (risk_validation snapshot) |
| 6 | Market Intelligence | summary.market_intelligence (market_intelligence_hub) |
| 7 | System Health | summary.system_health (6 Phase 8 module scores) |
| 8 | Watchlist | summary.watchlist (market overview watchlist) |
| 9 | Alert Centre | alerts endpoint (aggregated + severity-sorted) |
| 10 | AI Daily Briefing | briefing endpoint (natural language) |
| 11 | Quick Actions | summary.quick_actions (8 nav shortcuts) |
| 12 | Session Timeline | timeline endpoint (scans + notifications) |

---

## Platform Score Formula

```
platform_score = obs×0.20 + ops×0.20 + dq×0.20 + sec×0.15 + perf×0.15 + deploy×0.10
```

All inputs are existing snapshot scores — zero new computation.

---

## Stable Downstream Interface

```python
from command_center.shared_services import get_command_center_snapshot
snapshot = get_command_center_snapshot()
# Returns: { available, advisory_only, read_only, platform_score, platform_grade, platform_status, generated_at }
```

---

## Test Results

```
81 passed in 0.91s
```

Coverage: feature flag · grade helpers · platform score · summary (15 tests) ·  
briefing (10 tests) · alerts (8 tests) · timeline (9 tests) · snapshot (4 tests) ·  
export (6 tests) · API commands (7 tests) · read-only guarantee (3 tests)

---

## Safety Guarantees

- `advisory_only: true` on every response — enforced by test
- `read_only: true` on every response — enforced by test
- `execution_mode: "PAPER_TRADING"` — enforced by test
- No SQL writes (`DELETE`, `INSERT`, `DROP`) in source — AST-level test
- No order placement, no portfolio mutation, no config change
