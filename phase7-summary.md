# Phase 7 — Intelligence & Research Layer
**ApexQuant AI · NSE Intraday Paper Trading Platform**

---

## Overview

Phase 7 adds a five-module **Intelligence & Research Layer** on top of the live scan engine (Phase 7 core). Every module is **read-only and advisory-only** — zero writes to positions, zero execution side-effects. All data flows from the canonical Phase 7 scan snapshot via Postgres (`scan_state_store`) and cached signal data; no module triggers a new scan.

| Sub-phase | Module | Endpoints | Tests | Feature Flag |
|-----------|--------|-----------|-------|--------------|
| 7.1 | Market Intelligence Hub | 7 | 29 | `MARKET_INTELLIGENCE_HUB_ENABLED` |
| 7.2 | Event Intelligence | 8 | 68 | `EVENT_INTELLIGENCE_ENABLED` |
| 7.3 | Macro Intelligence | 8 | 81 | `MACRO_INTELLIGENCE_ENABLED` |
| 7.4 | Explainable AI Hub | 8 | 100 | `EXPLAINABLE_AI_ENABLED` |
| 7.5 | Research Lab | 8 | 96 | `RESEARCH_LAB_ENABLED` |
| **Total** | | **39** | **374** | |

---

## Phase 7 Core — Live Scan Engine

**Python package:** `artifacts/api-server/src/python/`  
**Key design decisions:**
- One canonical `scan_id` / `snapshot_ts` per scan cycle — never multiple concurrent snapshots
- Health endpoint probes only 3 symbols (fast check); full scan runs via `POST /live-data/scan/run`
- Quality gates: `STALE → WATCH`, `UNAVAILABLE → IGNORE` enforced in `live_scan_engine._apply_quality_gate()` — never in `market_scanner.py`
- Scan state (snapshot + lock) stored durably in Postgres; local JSON files are warm caches only
- Failed scans never overwrite a good snapshot; post-scan bundle publishes only when synchronised with 0 hard mismatches and monotonic `snapshot_ts`

---

## Phase 7.1 — Market Intelligence Hub

**Python package:** `artifacts/api-server/src/python/market_intelligence_hub/` (12 files)  
**Dashboard page:** `artifacts/trading-dashboard/src/pages/MarketIntelligenceHub.tsx`  
**Nav:** Analytics → Market Intelligence (Globe2 icon)

### What it does
Live market intelligence across breadth, sectors, volatility, regime and watchlist — with multi-timeframe analysis and CSV/JSON exports.

### Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/market-intelligence/summary` | Regime, breadth score, top sectors, VIX level |
| `GET /api/market-intelligence/sectors` | Sector-by-sector signal breakdown |
| `GET /api/market-intelligence/watchlist` | Per-symbol signal quality from cached scan |
| `GET /api/market-intelligence/breadth` | Advancing/declining ratio, breadth grade |
| `GET /api/market-intelligence/overview` | Multi-timeframe NIFTY/BankNifty + regime (slow ~3 s) |
| `GET /api/market-intelligence/export/csv` | Full data export as CSV |
| `GET /api/market-intelligence/export/json` | Full data export as JSON |

### Architecture notes
- `_get_scan_items()` cascades: Postgres `scan_state_store` → `intelligence_cache.json` → empty list (never triggers a full scan)
- `_get_regime()` fetches NIFTY/BankNifty/VIX from yfinance (~1 s)
- Multi-timeframe analysis runs 7 yfinance downloads in sequential threads (12 s timeout each, ~3 s total)
- Regime priority: `HIGH_VOLATILITY (VIX ≥ 25)` → `BULL` → `BEAR` → `LOW_VOLATILITY` → breadth-derived
- Breadth uses `final_action` from scan items as advancing/declining proxy — no live price needed
- Dashboard uses React Query `refetchInterval: 30_000`, all 5 queries fire in parallel on mount

---

## Phase 7.2 — Event Intelligence

**Python package:** `artifacts/api-server/src/python/event_intelligence/` (10 files)  
**Dashboard page:** `artifacts/trading-dashboard/src/pages/EventIntelligence.tsx`

### What it does
Advisory discovery and impact scoring for corporate, regulatory and news events affecting watchlist stocks. Generates prioritised timelines and daily briefs.

### Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/event-intelligence/summary` | Event count, high-impact count, alert level |
| `GET /api/event-intelligence/corporate` | Earnings, dividends, splits, buybacks per symbol |
| `GET /api/event-intelligence/regulatory` | SEBI notices, ASM/ESM flags, F&O bans |
| `GET /api/event-intelligence/news` | News sentiment and impact scores |
| `GET /api/event-intelligence/timeline` | Chronological event timeline for today/tomorrow |
| `GET /api/event-intelligence/brief` | Daily event brief (operator-ready summary) |
| `GET /api/event-intelligence/export/csv` | Full export as CSV |
| `GET /api/event-intelligence/export/json` | Full export as JSON |

### Architecture notes
- All event data is advisory; sources are scan-cache + config, zero live scraping
- Impact engine grades events: `HIGH / MEDIUM / LOW / MINIMAL`
- Events deduplicated by `(symbol, event_type, date)` tuple

---

## Phase 7.3 — Macro Intelligence

**Python package:** `artifacts/api-server/src/python/macro_intelligence/` (12 files)  
**Dashboard page:** `artifacts/trading-dashboard/src/pages/MacroIntelligence.tsx`

### What it does
Advisory macro dashboard covering global markets, economic calendar, FII/DII flows, commodity prices, currency rates, volatility surface and macro impact briefs for Indian equities.

### Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/macro-intelligence/summary` | Macro risk score, dominant theme, key signals |
| `GET /api/macro-intelligence/calendar` | Upcoming economic events with market-impact grade |
| `GET /api/macro-intelligence/global` | US, EU, Asia indices + overnight move |
| `GET /api/macro-intelligence/flows` | FII/DII provisional flows and net position |
| `GET /api/macro-intelligence/commodities` | Crude, Gold, Silver prices and trend |
| `GET /api/macro-intelligence/brief` | Operator-ready macro brief (narrative + bullets) |
| `GET /api/macro-intelligence/export/csv` | Full export as CSV |
| `GET /api/macro-intelligence/export/json` | Full export as JSON |

### Architecture notes
- Macro impact engine maps global signals to NSE regime bias (bullish/bearish/neutral)
- All data from yfinance + config; zero paid data sources required
- Economic calendar uses heuristic scheduling (RBI, FOMC, CPI dates baked in, not scraped)

---

## Phase 7.4 — Explainable AI Hub

**Python package:** `artifacts/api-server/src/python/explainable_ai/` (10 files)  
**Dashboard page:** `artifacts/trading-dashboard/src/pages/ExplainableAI.tsx`  
**Feature flag:** `EXPLAINABLE_AI_ENABLED=true`

### What it does
Explains every AI trading decision through factor contributions, confidence calibration, scenario analysis and decision history. Operators see **why** the AI recommended a signal, not just what it said.

### Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/explainable-ai/summary` | Overall explainability score, top factors, model health |
| `GET /api/explainable-ai/decision` | Latest decision with full factor breakdown |
| `GET /api/explainable-ai/contributions` | Per-feature contribution magnitudes and directions |
| `GET /api/explainable-ai/confidence` | Confidence calibration curve and reliability grade |
| `GET /api/explainable-ai/scenarios` | Counterfactual what-if scenario outcomes |
| `GET /api/explainable-ai/history` | Decision history with accuracy retrospective |
| `GET /api/explainable-ai/snapshot` | KPI snapshot for cross-phase aggregation |
| `GET /api/explainable-ai/export` | Full explanation export |

### Architecture notes
- Reads from `ai_decisions_cache` — uses the `decision` field (not `outcome`)
- All contributions are computed from the **exact evaluation payload** the executor used (append-only evidence)
- Scenario analysis is counterfactual-only; never fabricates fills or live outcomes
- `get_xai_snapshot()` is the upstream KPI hook consumed by Phase 7.5 and the Executive Dashboard
- 100/100 tests across decision explainer, contributions, confidence, scenarios, history, snapshot

---

## Phase 7.5 — Research, Simulation & Innovation Lab

**Python package:** `artifacts/api-server/src/python/research_lab/` (13 files)  
**Dashboard page:** `artifacts/trading-dashboard/src/pages/ResearchLab.tsx`  
**Feature flag:** `RESEARCH_LAB_ENABLED=true`

### What it does
A read-only advisory research workspace where operators explore strategy performance, simulate market scenarios, replay historical signals, run parameter experiments, compare regime profiles and benchmark the platform's research output against NIFTY and market baselines.

### Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/research-lab/summary` | Research score/100, grade, trend, module statuses |
| `GET /api/research-lab/strategies` | 7-strategy comparison (Trend, Mean Reversion, Momentum, Breakout, Range, Volatility, Sector Rotation) |
| `GET /api/research-lab/simulations` | 8-scenario advisory outcomes (Bull, Bear, Sideways, High/Low Vol, Gap Open, News, Macro Shock) |
| `GET /api/research-lab/replay` | Historical signal frame replay with replay summary |
| `GET /api/research-lab/benchmark` | Research vs NIFTY baseline vs market vs paper trading comparison |
| `GET /api/research-lab/reports` | Auto-generated research report (grade, narrative, recommendations) |
| `GET /api/research-lab/snapshot` | KPI snapshot: `research_score`, `grade`, `trend`, `expected_drawdown`, `benchmark_alpha` |
| `GET /api/research-lab/export` | Full data export (CSV or JSON via `?format=csv`) |

### Python package files
| File | Purpose |
|------|---------|
| `models.py` | Dataclasses, enums, grade/trend helpers, feature flag |
| `strategy_research.py` | 7-strategy profiles and comparison from signals |
| `scenario_simulation.py` | 8-scenario advisory outcome simulation |
| `historical_replay.py` | Replay frames from `signals_store` snapshots |
| `parameter_experiments.py` | Advisory parameter variant testing (5 axes) |
| `regime_comparison.py` | 6-regime profiles with win rate and best strategy |
| `risk_simulation.py` | Expected drawdown, capital usage, 7 stress scenarios |
| `performance_benchmark.py` | Research vs NIFTY vs market vs paper comparison |
| `innovation_workspace.py` | 5 seed experiments with status, tags, version history |
| `research_reports.py` | Auto-generated report aggregating all modules |
| `shared_services.py` | Public API with feature-flag guard on every function |
| `api.py` | Return-dict dispatch consumed by `main.py` |

### Dashboard tabs (9)
`Overview` · `Strategies` · `Scenarios` · `Replay` · `Parameters` · `Risk Sim` · `Benchmark` · `Workspace` · `Reports`

### Architecture notes
- Upstream data: `signals_store.load_signals()` + Phase 7.1/7.4/6.4 `get_*_snapshot()` — zero re-computation
- `get_research_lab_snapshot()` is the cross-phase KPI export hook for future Executive Dashboard tile
- **Route prefix bug fixed:** All Express routes use `/research-lab/...` not `/api/research-lab/...` because `app.use("/api", router)` strips the `/api` prefix before matching
- 96/96 tests including an AST safety guard that asserts no write-module imports exist in the package

---

## Shared Design Principles (all Phase 7 modules)

1. **Advisory-only** — every module is read-only; zero writes to trades, positions or scan state
2. **Cached data** — all modules read from the canonical scan snapshot or cached signals; no module triggers a new scan
3. **Feature flags** — each module has an `ENABLED` env-var flag; returns `{"status": "DISABLED"}` when off
4. **Route prefix** — all Express routes registered without `/api/` prefix (e.g. `/market-intelligence/summary`); the main app's `app.use("/api", router)` supplies the prefix
5. **Snapshot hooks** — each module exposes `get_*_snapshot()` returning a flat dict for cross-phase aggregation (Executive Dashboard, review packages)
6. **Test isolation** — all tests mock at the `_get_scan_items` / `_get_regime` / `signals_store` boundary; no DB or yfinance calls in tests
7. **Export support** — Phase 7.1–7.3 expose `/export/csv` and `/export/json`; Phase 7.5 exposes `/export?format=csv|json`

---

## File Map

```
artifacts/api-server/src/
├── python/
│   ├── market_intelligence_hub/     # Phase 7.1 (12 files, 29 tests)
│   ├── event_intelligence/          # Phase 7.2 (10 files, 68 tests)
│   ├── macro_intelligence/          # Phase 7.3 (12 files, 81 tests)
│   ├── explainable_ai/              # Phase 7.4 (10 files, 100 tests)
│   ├── research_lab/                # Phase 7.5 (13 files, 96 tests)
│   ├── test_event_intelligence.py
│   ├── test_macro_intelligence.py
│   ├── test_explainable_ai.py
│   └── test_research_lab.py
└── routes/
    ├── market-intelligence.ts
    ├── event-intelligence.ts
    ├── macro-intelligence.ts
    ├── explainable-ai.ts
    └── research-lab.ts

artifacts/trading-dashboard/src/pages/
    ├── MarketIntelligenceHub.tsx    # Phase 7.1
    ├── EventIntelligence.tsx        # Phase 7.2
    ├── MacroIntelligence.tsx        # Phase 7.3
    ├── ExplainableAI.tsx            # Phase 7.4
    └── ResearchLab.tsx              # Phase 7.5
```

---

## Environment Variables

| Variable | Value | Module |
|----------|-------|--------|
| `MARKET_INTELLIGENCE_HUB_ENABLED` | `true` | Phase 7.1 |
| `EVENT_INTELLIGENCE_ENABLED` | `true` | Phase 7.2 |
| `MACRO_INTELLIGENCE_ENABLED` | `true` | Phase 7.3 |
| `EXPLAINABLE_AI_ENABLED` | `true` | Phase 7.4 |
| `RESEARCH_LAB_ENABLED` | `true` | Phase 7.5 |

---

*Generated: 2026-07-30 · ApexQuant AI Platform*
