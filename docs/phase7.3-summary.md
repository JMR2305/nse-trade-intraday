# Phase 7.3 — Economic & Macro Intelligence Hub

**Status:** Complete  
**Date:** 2026-07-29  
**Classification:** Read-only · Advisory-only · Paper Trading

---

## Overview

Phase 7.3 adds a full Economic & Macro Intelligence Hub to the ApexQuant AI NSE intraday paper-trading platform. It aggregates RBI monetary policy events, India VIX, global market indices, inferred FII/DII flows, currency pairs, and commodity prices into a single operator-facing dashboard. All outputs are advisory — this module never places orders, modifies signals, writes to portfolio state, or touches any trading engine, risk parameters, or AI models.

---

## What Was Built

### Python Package — `artifacts/api-server/src/python/macro_intelligence/`

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker |
| `models.py` | `MacroEvent` dataclass; all enums and constants (`DIR_*`, `CAT_*`, `RISK_*`, `PRI_*`); `is_enabled()`, `disabled_response()`, `macro_grade()`, `priority_from_score()`, `trend_label()` |
| `economic_calendar.py` | Static calendar: RBI MPC (6×/year), CPI, WPI, GDP, IIP, Manufacturing PMI, Services PMI, Trade Balance, Union Budget, and major global events (FOMC, ECB). Returns `upcoming`, `recent`, and `next_critical` |
| `global_markets.py` | yfinance fetcher for Dow, NASDAQ, S&P 500, FTSE 100, DAX, Nikkei 225, Hang Seng, Shanghai Composite, GIFT Nifty proxy; blends Phase 7.1 regime health; computes `global_sentiment_score` (0–100) and `sentiment_label` |
| `market_flows.py` | Infers FII/DII posture from scan signal distribution and Phase 7.1 breadth data; computes sector rotation table sorted by avg opportunity score; includes liquidity trend and mandatory disclaimer |
| `currency_intelligence.py` | yfinance USD/INR, EUR/INR, JPY/INR, GBP/INR, and Dollar Index (DXY); `currency_volatility` label; `currency_risk_score`; sector impact descriptions |
| `commodity_intelligence.py` | yfinance Gold, Silver, Crude Oil (Brent), Natural Gas, Copper; trend/volatility classification; negative-sector mapping; `inflation_risk` label; crude and gold impact descriptions |
| `volatility_intelligence.py` | yfinance `^INDIAVIX`; EXPANSION / CONTRACTION / STABLE regime; LOW / MEDIUM / HIGH / EXTREME risk levels; options environment (CHEAP / NORMAL / EXPENSIVE); VIX zone table |
| `macro_impact_engine.py` | Per-event impact scoring, historical pattern database (RBI, CPI, GDP, FOMC, budget), `generate_impact_analysis()`, `get_impact_summary()` with sector heat map |
| `macro_brief.py` | `generate_daily_brief()` — market outlook label, risk alerts (VIX spike, FII outflow, high crude, pre-critical-event), currency/commodity/FII/DII summaries, trading considerations list, `brief_score` + `brief_grade` |
| `shared_services.py` | Stable public interface: `get_summary()`, `get_calendar()`, `get_global()`, `get_flows()`, `get_commodities()`, `get_brief()`, `get_macro_intelligence_snapshot()`, `export_csv()`, `export_json()` |
| `api.py` | Command dispatch: `cmd_summary`, `cmd_calendar`, `cmd_global`, `cmd_flows`, `cmd_commodities`, `cmd_brief`, `cmd_export_csv`, `cmd_export_json` |

### API Routes — `artifacts/api-server/src/routes/macro-intelligence.ts`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/macro-intelligence/summary` | Macro score, grade, VIX, FII posture, inflation risk, next critical event |
| GET | `/api/macro-intelligence/calendar` | Full static economic calendar with upcoming/recent split |
| GET | `/api/macro-intelligence/global` | Global index prices, change %, sentiment score, session groupings |
| GET | `/api/macro-intelligence/flows` | FII/DII posture, sector rotation table, liquidity trend |
| GET | `/api/macro-intelligence/commodities` | Commodity prices + currency pairs + VIX (combined) |
| GET | `/api/macro-intelligence/brief` | Full daily macro brief with risk alerts and trading considerations |
| GET | `/api/macro-intelligence/export/csv` | Economic calendar as downloadable CSV |
| GET | `/api/macro-intelligence/export/json` | Economic calendar as downloadable JSON |

### Dashboard — `artifacts/trading-dashboard/src/pages/MacroIntelligence.tsx`

Nine-tab React dashboard:

| Tab | Content |
|-----|---------|
| **Overview** | Macro score ring (0–100), sentiment, VIX, FII posture, inflation risk, next critical event card |
| **Daily Brief** | Brief score ring, market outlook, risk alerts, global/currency/commodity/FII-DII summaries, trading considerations |
| **Economic Calendar** | Full event list with importance badges, priority badges, direction icons, affected sectors |
| **Global Markets** | Index cards grouped by Asia / Europe / US sessions; bullish/bearish/neutral counts |
| **Market Flows** | FII/DII posture cards, top inflow/outflow sectors, sector rotation table with disclaimer |
| **Currency** | Pair table (USD/INR, EUR/INR, JPY/INR, GBP/INR, DXY), volatility label, impact descriptions |
| **Commodities** | Five commodity cards (Gold, Silver, Crude, NG, Copper), risk score, inflation risk |
| **India VIX** | Current VIX, regime, risk level, options environment, VIX zone table, today's change |
| **Macro Impact** | High-importance upcoming events with historical context, trading risk, opportunity notes |

Export CSV and Export JSON buttons available in the header on all tabs.

### Wiring Changes

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/main.py` | +8 `elif` handlers for `macro_intelligence_*` commands |
| `artifacts/api-server/src/routes/index.ts` | Import + `router.use(macroIntelligenceRouter)` |
| `artifacts/trading-dashboard/src/App.tsx` | `import MacroIntelligence` + `<Route path="/macro-intelligence">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | `Globe` icon nav entry "Macro Intelligence" added after "Event Intelligence" in the Analytics group |

---

## Test Coverage

**File:** `artifacts/api-server/src/python/test_macro_intelligence.py`  
**Result:** 81 / 81 passed

| Test class | Tests | Coverage |
|------------|-------|---------|
| `TestFeatureFlag` | 5 | Enabled/disabled flag, disabled response shape, disabled blocks summary |
| `TestModels` | 6 | `MacroEvent.to_dict()`, all grade/priority/trend helpers, constants |
| `TestEconomicCalendar` | 9 | RBI, CPI/WPI, GDP, IIP/PMI, budget, global events, importance scores, required fields |
| `TestGlobalMarkets` | 5 | Structure, sentiment score range, label validity, indices present, session groupings |
| `TestMarketFlows` | 5 | Structure, FII/DII fields, sorted sector rotation, disclaimer present |
| `TestCurrencyIntelligence` | 5 | Structure, USD/INR + DXY present, volatility label, risk score range, impact strings |
| `TestCommodityIntelligence` | 5 | Structure, all 5 commodities, trend validity, risk score range, inflation risk |
| `TestVolatilityIntelligence` | 6 | Structure, regime validity, risk level validity, VIX score range, options environment, interpretation |
| `TestMacroImpactEngine` | 7 | Impact analysis structure, sorted by importance, empty summary, direction counts, sector heat, RBI historical pattern, top opportunities |
| `TestMacroMasterBrief` | 6 | Structure, score range, outlook label, VIX spike alert, FII sell alert, trading considerations |
| `TestSharedServices` | 8 | All 6 endpoints enabled, advisory_only flag on all, snapshot never raises |
| `TestExport` | 3 | CSV non-empty with header, JSON parseable, disabled when flag off |
| `TestAPIDispatch` | 8 | All 8 `cmd_*` functions return correct status |
| `TestAdvisoryOnlySafety` | 3 | AST scan — zero forbidden write imports across entire package; advisory flag on summary; models clean |

---

## Configuration

| Environment Variable | Value | Effect |
|---------------------|-------|--------|
| `MACRO_INTELLIGENCE_ENABLED` | `true` | Enables all 8 endpoints and the dashboard |

Set to `false` to return `{"status": "DISABLED"}` from every endpoint without error.

---

## Architecture Notes

### Data Sources
- **Economic calendar:** Fully static — anchored to the current year. No external API calls.
- **Global indices / currencies / commodities / VIX:** `yfinance` — session-cached for 5 minutes per module.
- **FII/DII flows:** Inferred from `signals_cache.get_latest_signals()` + Phase 7.1 breadth data. Not real SEBI data — disclaimer included in all flow responses.
- **Regime context:** Phase 7.1 `market_intelligence_hub.shared_services.get_summary()` — used for global sentiment blending.

### Snapshot Contract
`get_macro_intelligence_snapshot()` returns a flat KPI dict (same pattern as Phase 5D.5, 7.1, 7.2) for the Executive Dashboard and any downstream phase. It never raises — all errors produce safe defaults. Phase 7.4 (Explainable AI) and Phase 7.5 (Research Lab) can consume it without any changes to this module.

### Advisory-Only Enforcement
An AST safety test (`TestAdvisoryOnlySafety.test_no_write_imports_in_package`) scans every `.py` file in the `macro_intelligence/` package and asserts zero imports from: `order_executor`, `trade_executor`, `portfolio_writer`, `signal_writer`, `strategy_mutator`, `risk_engine_writer`, `model_trainer`, `execution_engine`.

### Phase 7 Pattern Compliance
All modules follow the established Phase 7.1/7.2 conventions:
- Python sub-package → `shared_services.py` public interface → `api.py` command dispatch → `main.py` `elif` chain → TypeScript `spawn`/`runPython` routes → React tabbed page.
- Module-level `_cache: dict` with 5-minute TTL via `_cache_ts`.
- `available: true`, `advisory_only: true` on every successful response.

---

## Follow-up Tasks Proposed

| Task | Category |
|------|---------|
| #192 — Surface macro regime context (VIX, FII, crude) alongside each AI signal's confidence | `next_steps` |
| #193 — Test that Executive Dashboard macro tile updates correctly when VIX spikes above 20 | `test_gaps` |
| #194 — Alert operators when crude moves >3% intraday with affected-sector list | `next_steps` |
