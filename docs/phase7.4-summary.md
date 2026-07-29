# Phase 7.4 — Explainable AI & Decision Intelligence Hub

**Status:** Complete  
**Date:** 2026-07-29  
**Classification:** Read-only · Advisory-only · Paper Trading

---

## Overview

Phase 7.4 adds a full Explainable AI & Decision Intelligence Hub to the ApexQuant AI NSE intraday paper-trading platform. It exposes the reasoning behind every signal in plain language — primary reasons, indicator contributions, confidence decomposition, scenario analysis, historical pattern matching, and operator action summaries — all derived from cached upstream snapshots without any re-computation. All outputs are advisory only; this module never places orders, modifies signals, writes to portfolio state, or touches any trading engine, risk parameters, or AI models.

---

## What Was Built

### Python Package — `artifacts/api-server/src/python/explainable_ai/`

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker |
| `models.py` | All dataclasses (`ExplainableDecision`, `IndicatorContribution`, `DecisionTreeNode`, `ScenarioAnalysis`, `HistoricalMatch`, `ConfidenceDecomposition`); grade/tier/trend helpers; `is_enabled()` / `disabled_response()` using `EXPLAINABLE_AI_ENABLED` flag |
| `decision_explainer.py` | `explain_decision(symbol, ...)` — reads signal from `signals_store`, builds primary/secondary reasons, decision tree with Technical / Market Context / Macro / Risk branches; `get_all_explainable_decisions()` for batch |
| `indicator_contributions.py` | `compute_contributions(symbol, signal, market_snap)` — 12-indicator breakdown (Trend, Momentum, Volume, Volatility, Relative Strength, Support, Resistance, Breakout, Liquidity, Sector Strength, Market Breadth, Watchlist Ranking); always sums to exactly 100% |
| `confidence_analyzer.py` | `compute_confidence(symbol, signal, market_snap, macro_snap, risk_snap)` — 8-dimension decomposition (Technical, Fundamental, Market, Event, Macro, Risk, Regime, Historical) weighted to produce a 0–100 overall score and reliability grade |
| `scenario_generator.py` | `generate_scenarios(symbol, signal, market_snap, macro_snap)` — BULLISH / NEUTRAL / BEARISH scenarios with probability, expected return, conditions, risk factors; confidence normalised from 0–100 to 0–1 so probabilities vary meaningfully |
| `historical_similarity.py` | `find_historical_matches(symbol, signal, snapshots)` — up to 5 past setups from `signals_store.load_signal_snapshots()` with ≥50% similarity across signal direction, regime, confidence, and risk level |
| `market_context_explainer.py` | Converts Phase 7.1 market snapshot → narrative + bullet points |
| `event_context_explainer.py` | Converts Phase 7.2 event snapshot → narrative + net sentiment |
| `macro_context_explainer.py` | Converts Phase 7.3 macro snapshot → narrative + VIX / FII / inflation bullets |
| `risk_explainer.py` | Converts Phase 6.4 risk snapshot → 5-dimension breakdown with LOW / MODERATE / ELEVATED / HIGH levels |
| `operator_summary.py` | `build_operator_summary(decision)` — 1-sentence why + top 3 factors + key risks + opportunities + action items; handles both 0–1 and 0–100 confidence scales |
| `shared_services.py` | Public interface: `get_summary()`, `get_decision(symbol)` (includes market/event/macro/risk context objects), `get_contributions(symbol)`, `get_confidence(symbol)`, `get_scenarios(symbol)`, `get_history(symbol)`, `get_explainable_ai_snapshot()`, `export_csv()`, `export_json()` |
| `api.py` | Return-dict command dispatch for `main.py`: `cmd_summary`, `cmd_decision`, `cmd_contributions`, `cmd_confidence`, `cmd_scenarios`, `cmd_history`, `cmd_snapshot`, `cmd_export` |

### API Routes — `artifacts/api-server/src/routes/explainable-ai.ts`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/explainable-ai/summary` | All current signals with signal type, grade, confidence, top reason |
| GET | `/api/explainable-ai/decision?symbol=` | Full decision for one symbol including structured `market_context`, `event_context`, `macro_context`, `risk_context` objects and operator summary |
| GET | `/api/explainable-ai/contributions?symbol=` | 12-indicator contribution breakdown (weights sum to 100%) |
| GET | `/api/explainable-ai/confidence?symbol=` | 8-dimension confidence decomposition with reliability grade |
| GET | `/api/explainable-ai/scenarios?symbol=` | BULLISH / NEUTRAL / BEARISH scenarios with probability, return, conditions |
| GET | `/api/explainable-ai/history?symbol=` | Up to 5 historical pattern matches with similarity score |
| GET | `/api/explainable-ai/snapshot` | Flat KPI dict for Phase 7.5 Research Lab aggregation |
| GET | `/api/explainable-ai/export?format=json\|csv` | Full decision set export |

All routes gated by `EXPLAINABLE_AI_ENABLED=true` (set).

### Dashboard — `artifacts/trading-dashboard/src/pages/ExplainableAI.tsx`

Eleven-tab React dashboard with a global symbol selector (dropdown) that drives all six symbol-specific queries simultaneously:

| Tab | Content |
|-----|---------|
| **Overview** | KPI tiles (total decisions, buy/sell/hold counts, avg confidence); full decision table with signal badge, grade, confidence bar, risk level, top reason |
| **Summary** | Operator action card — why sentence, top 3 factors, key risks, opportunities, action items; signal/grade/confidence/risk badges |
| **Decision** | Full decision details (price, target, stop-loss, regime, scores); primary reasons list |
| **Contributions** | 12-indicator horizontal bar chart with BULLISH / BEARISH / NEUTRAL colour coding and weight explanation |
| **Confidence** | 8-dimension progress bars with weight %, reliability grade badge, plain-language narrative |
| **Scenarios** | Three scenario cards (BULLISH / NEUTRAL / BEARISH) with probability badge, expected return, key conditions, risk factors |
| **History** | Up to 5 historical match cards with similarity %, date, outcome, match reasons |
| **Market** | Market Intelligence context narrative + bullet points (Phase 7.1 snapshot) |
| **Events** | Event Intelligence context narrative + net sentiment (Phase 7.2 snapshot) |
| **Macro** | Macro Intelligence context narrative + VIX / FII / upcoming events (Phase 7.3 snapshot) |
| **Risk** | Risk dimension breakdown with overall risk level badge (Phase 6.4 snapshot) |

### Infrastructure Changes

| File | Change |
|------|--------|
| `artifacts/api-server/src/routes/index.ts` | Import + `router.use(explainableAiRouter)` |
| `artifacts/api-server/src/python/main.py` | 8 `elif` handlers under `# Phase 7.4` comment |
| `artifacts/trading-dashboard/src/App.tsx` | Import `ExplainableAI` + `<Route path="/explainable-ai">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | `Lightbulb` icon nav entry "Explainable AI" after Macro Intelligence in Analytics group |

### Tests — `artifacts/api-server/src/python/test_explainable_ai.py`

**100 / 100 tests passing** across 14 test classes:

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestModels` | 11 | Feature flag, grade/tier helpers, dataclass fields, `to_dict()`, `primary_reasons` property |
| `TestMarketContextExplainer` | 5 | Narrative content, grade, unavailable fallback |
| `TestEventContextExplainer` | 5 | Net sentiment (bullish/bearish/neutral), zero-events path |
| `TestMacroContextExplainer` | 5 | VIX text, FII text, upcoming events |
| `TestRiskExplainer` | 5 | Dimension count, overall risk level, unavailable fallback |
| `TestIndicatorContributions` | 6 | 12 indicators, sum=100%, direction values, alias fields, no-signal fallback |
| `TestConfidenceAnalyzer` | 6 | 8 dimensions, grade, market override, narrative, `to_dict()` |
| `TestScenarioGenerator` | 10 | 3 scenarios, probabilities sum=1.0, bearish target < price, dual confidence scale (0–1 and 0–100), consistency between scales |
| `TestHistoricalSimilarity` | 5 | No snapshots, max results, similarity score range |
| `TestDecisionExplainer` | 8 | Signal type, grade, tree structure, no-signal path, extended fields (price/target/stop/regime) |
| `TestOperatorSummary` | 7 | Why sentence, action items, sell action, risks, opportunities with target |
| `TestAstSafety` | 1 | No write-module imports (`paper_portfolio`, `paper_trades`, `auto_paper`, `portfolio_store`) in any `.py` |
| `TestSharedServices` | 13 | All 8 endpoints, CSV/JSON export, disabled flag, decision+summary |
| `TestDecisionContextFields` | 11 | Decision response includes all four context objects with correct structure and content |

### Data Flow

```
signals_store.load_signals()          ← canonical signal cache
    ↓
decision_explainer.explain_decision()
    ↓ enriched with ──────────────────────────────────────────────────────────
    get_market_intelligence_snapshot()   (Phase 7.1 — zero re-computation)
    get_event_intelligence_snapshot()    (Phase 7.2 — zero re-computation)
    get_macro_intelligence_snapshot()    (Phase 7.3 — zero re-computation)
    get_risk_optimisation_snapshot()     (Phase 6.4 — zero re-computation)
    ↓
ExplainableDecision + market_context + event_context + macro_context + risk_context
    ↓
operator_summary.build_operator_summary()
    ↓
/api/explainable-ai/decision?symbol=   →   ExplainableAI.tsx dashboard tabs
```

### Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `EXPLAINABLE_AI_ENABLED` | `true` | Feature flag for all 8 routes and Python module |

---

## Open Tasks

The following tasks are currently open in the project. They are grouped by area.

### Proposed (not yet started)

#### Explainable AI follow-ups (Phase 7.4)

| # | Title | Category |
|---|-------|----------|
| 196 | Confirm the AI explanation updates within 30 seconds after a new scan, not just on page reload | next_steps |
| 197 | Wire decision-tree reasoning into the Decision tab so operators can follow each signal step-by-step | next_steps |
| 198 | Prevent misleading 'No signal found' messages when the watchlist has changed but the scan has not re-run | next_steps |

#### Executive Dashboard

| # | Title |
|---|-------|
| 193 | Confirm the Executive Dashboard macro tile updates within 30 seconds when VIX spikes above 20 |

#### Portfolio & Performance

| # | Title |
|---|-------|
| 159 | Show a live P&L sparkline and key stats on the Portfolio page so operators don't have to navigate away |
| 24 | Show equity curve and P&L history on the Portfolio page so operators can see performance over time |
| 129 | Make sure a partial position exit immediately updates the sector exposure badge, not just the full-close |
| 59 | Make sure the exposure badge updates immediately when the API returns fresh data, not after a full page reload |

#### Paper Trading & Auto-Paper

| # | Title |
|---|-------|
| 168 | Confirm the performance cache clears itself when a new paper trade is recorded, not just after 30 seconds |
| 182 | Confirm the readiness score also updates when auto-paper entries open, not only when positions close |

#### Trade Decisions & AI

| # | Title |
|---|-------|
| 171 | Warn operators on the Trade Decisions page when AI accuracy has been declining for the past 30 days |
| 166 | Warn operators when a stock's strategy has a poor track record in today's regime |

#### Strategy & Execution Engine

| # | Title |
|---|-------|
| 68 | Make sure limit edits take effect in running strategies without waiting for the next order |
| 15 | Wire portfolio pre-check into the signal flow so exposure and capital limits are enforced before RC-8 sees an order |
| 108 | Confirm the config panel refreshes in the browser the moment an operator saves a limit, not after the next poll |

#### Broker & Execution

| # | Title |
|---|-------|
| 37 | Show missed-reconciliation alerts on the Broker Execution page so operators see them in context |
| 36 | Run the reconciliation probe automatically so operators don't have to call it manually |
| 57 | Confirm the Reopen cutoff is enforced on the server so a direct API call can't bypass it |

#### Server / API Reliability

| # | Title |
|---|-------|
| 69 | Confirm overrides survive a hot-reload of the API server so operators don't lose mid-session settings unexpectedly |
| 106 | Confirm the consolidated outage banner disappears in the browser when the API recovers, not just in unit tests |
| 13 | Start the expiry monitor automatically when the adapter goes live so it can't be forgotten |
| 114 | Set production API URLs as environment variables so deployed connectivity is explicit, not inferred |

#### Reconciliation & Data Quality

| # | Title |
|---|-------|
| 180 | Prevent the 09:20 reconciliation from running when actual prices are all null and producing a misleading empty accuracy report |

---

## Known Limitations & Future Work

- **Decision tree visualisation** (Task #197): The backend computes a full nested `DecisionTreeNode` tree (Technical → Trend / Momentum / Volume, Market Context, Macro, Risk). The Decision tab currently shows primary reasons as a flat list; a collapsible tree UI is a follow-up.
- **Historical matches** (Task #196): Historical similarity requires prior scan snapshots from `signals_store.load_signal_snapshots()`. In a fresh environment with no scan history the History tab will show "No matches found" until several scans have run.
- **Refresh latency** (Task #196): All queries poll every 60 seconds. After a new scan completes, explanations may lag up to 60 seconds before refreshing.
- **Fundamental score**: Hardcoded at 50/100 in the confidence decomposition pending a fundamental analytics pipeline.
- **Phase 7.5 Research Lab**: `get_explainable_ai_snapshot()` is ready and returns a flat KPI dict (`explainable_ai_score`, `grade`, `total_decisions`, `avg_confidence`, `buy_count`, `sell_count`, `hold_count`) for the next phase to aggregate.
