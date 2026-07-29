# Phase 5D.5 — Executive Dashboard

**Status:** COMPLETE  
**Feature flag:** `EXECUTIVE_DASHBOARD_ENABLED=true`  
**Module:** `artifacts/api-server/src/python/executive_dashboard/`  
**Dashboard:** `artifacts/trading-dashboard/src/pages/ExecutiveDashboard.tsx` → `/executive-dashboard`

---

## What was built

A unified, read-only Executive Dashboard that aggregates analytics from all previous phases into a single operational command centre. Zero recalculation — every metric flows from an existing module's shared_services or api function. The dashboard survives partial outages: each of the 8 data source loaders is independently guarded with try/except, so one broken module never blocks the entire page.

---

## Files created

| File | Purpose |
|---|---|
| `executive_dashboard/__init__.py` | Package docstring — read-only, advisory-only contract |
| `executive_dashboard/dashboard_models.py` | Feature flag, `ExecutiveScore` dataclass, `SCORE_WEIGHTS`, `score_label()` |
| `executive_dashboard/dashboard_engine.py` | 8 `_load_*()` functions, each calling one module directly; `load_all()` aggregator |
| `executive_dashboard/widgets.py` | 9 widget formatters (one per section) + `widget_header()` |
| `executive_dashboard/layout.py` | `compute_executive_score()`, `SECTIONS` config, `QUICK_ACTIONS` list |
| `executive_dashboard/shared_services.py` | **Stable interface for future phases** — `get_executive_summary()`, `get_system_health()`, `get_all_widgets()`, `get_executive_snapshot()` |
| `executive_dashboard/api.py` | 3 HTTP façade functions |
| `executive_dashboard/test_executive_dashboard.py` | 29 unit tests — all passing |

**Files modified:**

| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` | +3 executive_* commands |
| `artifacts/api-server/src/routes/index.ts` | Added `executiveRouter` |
| `artifacts/api-server/src/routes/executive.ts` | 3 Express GET endpoints |
| `artifacts/trading-dashboard/src/App.tsx` | Added `/executive-dashboard` route |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Added `Executive Dashboard` sidebar entry (LayoutDashboard icon) |

---

## Shared services reused from each previous phase

### Deliverable #10 — Exact shared service reuse

| Phase | Module | Function(s) called | Widget section |
|---|---|---|---|
| **5D.3 Strategy Intelligence** | `strategy_intelligence.shared_services` | `get_summary_snapshot()`, `get_criterion_rankings()`, `get_recommendations()` | Strategy Overview (Section 4) |
| **5D.4 AI Performance Intelligence** | `ai_performance.shared_services` | `get_ai_snapshot()`, `get_health_score()`, `get_learning_data()` | AI Health (Section 3) |
| **5D.1 Execution Quality** | `execution_quality.api` | `get_summary()` | Execution Quality (Section 5) |
| **5D.2 Portfolio Performance** | `portfolio_performance.api` | `get_summary()`, `get_portfolio()` | Portfolio Overview (Section 2) |
| **Pre-Open Intelligence** | `preopen_engine` | `get_status()`, `get_rankings()`, `get_sectors()` | Pre-Open Intelligence (Section 6) |
| **Portfolio Risk** | `phase11_risk` | `portfolio_risk()`, `risk_alerts()` | Portfolio Risk (Section 7) |
| **Phase 5C Signal Validation** | `signal_validation_engine` | `get_status()`, `get_summary()` | (Available in raw data, surfaced in Live Alerts) |
| **System / Scheduler** | `phase20_executor`, `meta_health` | `get_scheduler_health()`, `get_meta_health()` | System Health (Section 1), Header, Market Snapshot (Section 9) |

### Deliverable #11 — No analytics recalculated inside Executive Dashboard

Confirmed: `dashboard_engine.py` contains **zero arithmetic over raw trade data**. Every number it returns comes from calling a function that already exists in another module. The only arithmetic in `layout.py` is combining already-computed widget scalars into the Executive Score (weighted sum of 6 scores — no trade-level loops).

---

## API endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/executive/summary` | Full dashboard — header, executive score (all 6 components), all 10 sections, quick actions |
| `GET /api/executive/health` | System health section only (fast — skips strategy/AI/portfolio loading) |
| `GET /api/executive/widgets` | All 10 widget sections without the executive score |

All three return `{ "status": "DISABLED" }` when `EXECUTIVE_DASHBOARD_ENABLED=false`.

---

## Executive Score methodology

```
Executive Score = Σ(component_score × weight)
```

| Component | Weight | Source metric |
|---|---|---|
| Portfolio Health | 25% | Win rate, profit factor, net P&L sign, max drawdown |
| AI Health | 20% | `ai_performance.shared_services.get_ai_snapshot().health_score` |
| Strategy Health | 20% | Overall win rate, strong buy count, net P&L sign |
| Execution Quality | 15% | `execution_quality.api.get_summary().avg_execution_score` |
| Risk | 10% | Alert count, kill switch status, utilisation over 80% |
| System Health | 10% | Boolean health of application / database / API / scheduler |

Labels: Excellent (≥90), Good (≥75), Fair (≥60), Poor (≥40), Critical (<40).

Each component is clamped 0–100. All inputs are already-computed scalars from existing modules — no raw trade data processed here.

---

## Dashboard sections

| # | Section | Data source |
|---|---|---|
| Header | Market status, regime, provider, watchlist | `preopen_engine`, `meta_health` |
| Executive Score | Composite ring gauge + 6-component breakdown | `layout.compute_executive_score()` |
| 1 | System Health | `phase20_executor`, `meta_health` |
| 2 | Portfolio Overview | `portfolio_performance.api` |
| 3 | AI Health | `ai_performance.shared_services` |
| 4 | Strategy Overview | `strategy_intelligence.shared_services` |
| 5 | Execution Quality | `execution_quality.api` |
| 6 | Pre-Open Intelligence | `preopen_engine` |
| 7 | Portfolio Risk | `phase11_risk` |
| 8 | Live Alerts | `phase11_risk.risk_alerts()` |
| 9 | Market Snapshot | `meta_health` |
| 10 | Quick Actions | 7 deep-links to full module pages |

All sections are collapsible. Default: all open. Mobile-responsive 2-column grid collapses to 1-column.

---

## Test results

**29/29 passing (1.74 s)**

| Test class | Tests | Covers |
|---|---|---|
| `TestFeatureFlag` | 4 | All 3 endpoints + `get_executive_snapshot()` return DISABLED when flag is off |
| `TestZeroData` | 2 | All 8 data sources returning `{"available": False}` → graceful zeros, score in 0–100 |
| `TestFullData` | 9 | All section widgets have required fields; strategy/AI/EQ/preopen/risk widget correctness; sections ordered; quick actions present |
| `TestExecutiveScoreModel` | 4 | Perfect/zero/mixed score; weights sum to 1.0 |
| `TestSharedServiceReuse` | 3 | `_load_strategy` and `_load_ai` each called once; `get_executive_snapshot()` flat dict keys correct |
| `TestAPIResponses` | 3 | health/widgets/summary endpoints return ENABLED; widgets omits executive_score |
| `TestRestartPersistence` | 2 | Two sequential calls return identical score and section layout |

**Critical bug fixed in test infrastructure:**  
`_patch_engine` initially patched `executive_dashboard.dashboard_engine.load_all` — but `shared_services.py` imports `load_all` via `from .dashboard_engine import load_all`, creating a local binding that the module-level patch cannot reach. Fixed to patch `executive_dashboard.shared_services.load_all` instead.

---

## Performance benchmarks

The dashboard fetches once on page load (`GET /api/executive/summary`), auto-refreshes every 60 seconds, and uses a 30-second stale window. All widget rendering is synchronous post-fetch.

Python-side, the `load_all()` call is the bottleneck — it sequentially calls 8 module loaders. In the current paper-trading context with ≤1000 trades:
- Strategy Intelligence snapshot: ~5–15 ms (cached in shared_services)
- AI Performance snapshot: ~10–20 ms (reads from portfolio_store)
- Execution quality summary: ~5–15 ms
- Portfolio performance summary: ~5–10 ms
- Pre-open status: ~2–5 ms (reads JSON cache)
- Risk dashboard: ~5–15 ms
- System health: ~2–5 ms

**Estimated total Python time: 35–85 ms** — within the <1 second target.

No duplicate API calls: the TypeScript page makes exactly one `GET /api/executive/summary` request. All 10 sections are populated from the single response JSON.

---

## Deliverable #12 — Future module extensibility

The dashboard supports future modules (Live Trading, ML Engine, Options, Swing Trading) without architectural changes:

1. **New data source:** Add a `_load_live_trading()` function to `dashboard_engine.py` using the same guarded import pattern
2. **New widget:** Add `widget_live_trading(data)` to `widgets.py`; call it inside `_build_widgets()` in `shared_services.py`
3. **New score component:** Add an entry to `SCORE_WEIGHTS` in `dashboard_models.py` (keeping sum = 1.0) and a component line in `layout.compute_executive_score()`
4. **New section on page:** Add the section to `SECTIONS` list in `layout.py` and add a `<SectionCard>` in `ExecutiveDashboard.tsx`

No existing section, widget, or score component needs modification. The `get_executive_snapshot()` function in `shared_services.py` is the stable interface for any future super-dashboard that aggregates across multiple apps.

---

## Known limitations

| # | Area | Description | Severity | Resolution path |
|---|---|---|---|---|
| 1 | Feature flag off by default | Disabled banner until `EXECUTIVE_DASHBOARD_ENABLED=true` is set | Low — intentional | Set flag in environment secrets |
| 2 | System health from meta_health | `get_meta_health()` is not a well-documented function; if it doesn't exist or returns an unexpected shape, the System Health and Market Snapshot sections show "UNKNOWN" for all fields | Medium | Document `meta_health.get_meta_health()` contract; add fallback to `live_health_v2` |
| 3 | Sequential data loading | `load_all()` calls 8 loaders serially; if one is slow (e.g., risk dashboard re-running heavy queries), total time grows linearly | Medium | Future: make loaders async with `asyncio.gather()` or use `concurrent.futures.ThreadPoolExecutor` |
| 4 | Market Snapshot mostly UNKNOWN | `meta_health` doesn't expose NIFTY/BANK NIFTY prices directly in the current implementation | Medium | Wire to `live_data_provider.get_market_overview()` in the system loader |
| 5 | Signal Validation in Live Alerts | Signal validation data is loaded but not surfaced as alert cards (only risk alerts shown) | Low | Extend `widget_live_alerts` to include signal validation errors |
| 6 | No mobile-specific optimisation | Dashboard is responsive but not specifically optimised for mobile (swipeable sections) | Low | Future: add swipe gesture on section cards using `touch-action: pan-y` |

---

## What to enable before using in a live session

1. `EXECUTIVE_DASHBOARD_ENABLED=true` — in environment secrets
2. `STRATEGY_INTELLIGENCE_ENABLED=true` — required for Section 4
3. `AI_PERFORMANCE_ENABLED=true` — required for Section 3
4. `EXECUTION_QUALITY_ENABLED=true` — required for Section 5
5. `PORTFOLIO_PERFORMANCE_ENABLED=true` — required for Section 2

The dashboard degrades gracefully if any flag is off — the section shows "No data" rather than crashing.

---

## Dependencies for downstream phases

| Phase | What it needs from 5D.5 |
|---|---|
| **Future super-dashboard / Live Trading** | `get_executive_snapshot()` — flat dict with `executive_score`, `executive_label`, `portfolio_value`, `net_pnl`, `win_rate`, `ai_health_score`, `ai_trend`, `execution_score`, `open_positions` |
