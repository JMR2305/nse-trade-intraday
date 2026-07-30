# Phase 7.5 — Research, Simulation & Innovation Lab
**ApexQuant AI · NSE Intraday Paper Trading Platform**

---

## Objective

Build a comprehensive read-only **Research, Simulation & Innovation Lab** that lets operators explore strategy performance, simulate market scenarios, replay historical signals, run parameter experiments, compare regime profiles and benchmark the platform's research output — all advisory-only, zero execution side-effects.

---

## At a Glance

| Item | Detail |
|------|--------|
| **Feature flag** | `RESEARCH_LAB_ENABLED=true` |
| **Python package** | `artifacts/api-server/src/python/research_lab/` |
| **Route file** | `artifacts/api-server/src/routes/research-lab.ts` |
| **Dashboard page** | `artifacts/trading-dashboard/src/pages/ResearchLab.tsx` |
| **Endpoints** | 8 GET routes under `/api/research-lab/*` |
| **Tests** | **96 / 96 passing** (13 test classes) |
| **Nav entry** | Analytics → Research Lab (FlaskConical icon) |

---

## API Endpoints

All routes are registered as `/research-lab/...` in the Express router (the main app mounts the router at `/api`, so the full public path is `/api/research-lab/...`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/research-lab/summary` | Research score /100, grade (A–F), trend, enabled-module list, top strategy, dominant regime |
| `GET` | `/api/research-lab/strategies` | 7-strategy comparison with win rate, trade count, avg return, grade and recommendation |
| `GET` | `/api/research-lab/simulations` | 8-scenario advisory outcomes with expected P&L, risk score, probability, suitability |
| `GET` | `/api/research-lab/replay` | Historical signal frame replay (frames list + replay summary) |
| `GET` | `/api/research-lab/benchmark` | Research vs NIFTY baseline vs market vs paper trading performance comparison |
| `GET` | `/api/research-lab/reports` | Auto-generated research report (narrative, grade, per-module findings, recommendations) |
| `GET` | `/api/research-lab/snapshot` | Flat KPI dict for cross-phase aggregation (`research_score`, `grade`, `trend`, `expected_drawdown`, `benchmark_alpha`) |
| `GET` | `/api/research-lab/export` | Full data export — JSON (default) or CSV via `?format=csv` |

---

## Python Package — File by File

```
artifacts/api-server/src/python/research_lab/
├── __init__.py                # Package marker
├── models.py                  # Dataclasses, enums, grade/trend helpers, RESEARCH_LAB_ENABLED flag
├── strategy_research.py       # 7-strategy profiles from signals (see below)
├── scenario_simulation.py     # 8-scenario advisory outcome simulation (see below)
├── historical_replay.py       # Replay frames from signals_store snapshots + replay_summary()
├── parameter_experiments.py   # Advisory parameter variant testing across 5 axes
├── regime_comparison.py       # 6-regime profiles with win rate, drawdown, best strategy
├── risk_simulation.py         # Expected drawdown, capital usage, 7 stress scenarios
├── performance_benchmark.py   # Research vs NIFTY baseline vs market vs paper comparison
├── innovation_workspace.py    # 5 seed experiments with status, tags, version history
├── research_reports.py        # Auto-generated report aggregating all modules
├── shared_services.py         # Public API — all 9 service functions with feature-flag guard
└── api.py                     # Return-dict dispatch consumed by main.py
```

### Strategy Research (`strategy_research.py`)
Compares **7 strategies** across the signal history:

| Strategy | Focus |
|----------|-------|
| Trend Following | Sustained directional moves |
| Mean Reversion | Overextension snapback |
| Momentum | Relative strength / rate of change |
| Breakout | Price breaking structure levels |
| Range Bound | Support/resistance oscillation |
| Volatility | Expansion / contraction plays |
| Sector Rotation | Cross-sector relative strength |

Each profile returns: `win_rate`, `avg_return`, `trade_count`, `max_drawdown`, `sharpe_ratio`, `grade`, `recommendation`, `best_regime`.

### Scenario Simulation (`scenario_simulation.py`)
Simulates **8 market scenarios** as advisory outcomes:

| Scenario | Trigger |
|----------|---------|
| Bull Market | Broad upside momentum |
| Bear Market | Broad selling pressure |
| Sideways / Consolidation | Range-bound, low conviction |
| High Volatility | VIX spike, wide swings |
| Low Volatility | Calm tape, tight ranges |
| Gap Open | Large pre-market gap |
| News Shock | High-impact corporate/macro event |
| Macro Shock | RBI, Fed, global risk event |

Each scenario returns: `expected_return`, `expected_drawdown`, `win_probability`, `risk_score`, `suitability`, `recommended_strategies`, `caution_note`.

### Regime Comparison (`regime_comparison.py`)
Profiles strategy performance across **6 market regimes**:
`BULL` · `BEAR` · `RANGE_BOUND` · `VOLATILE` · `LOW_VOLATILITY` · `TRANSITION`

Each regime returns: `win_rate`, `avg_return`, `trade_count`, `best_strategy`, `avoid_strategies`, `risk_level`, `operator_note`.

### Risk Simulation (`risk_simulation.py`)
- Expected drawdown distribution (5th / 25th / 50th / 75th / 95th percentile)
- Capital usage efficiency
- Risk/reward distribution histogram
- **7 stress scenarios:** Flash Crash, Liquidity Crisis, Rate Shock, Sector Meltdown, FII Exodus, Circuit Breaker, Gap Down Open

### Performance Benchmark (`performance_benchmark.py`)
Four-way comparison:
1. **Research engine output** — scored advisory signals
2. **NIFTY 50 baseline** — buy-and-hold equivalent
3. **Market average** — broad market proxy
4. **Paper trading actuals** — platform's real paper P&L

Returns: `alpha`, `beta`, `sharpe_ratio`, `information_ratio`, `benchmark_grade` per comparison pair.

### Innovation Workspace (`innovation_workspace.py`)
5 seed experiments pre-loaded:
- ML Signal Fusion prototype
- Sentiment integration experiment
- Options flow overlay
- Adaptive position sizing
- Cross-sector arbitrage signals

Each experiment has: `status` (ACTIVE/PAUSED/COMPLETED/ARCHIVED), `version`, `tags`, `hypothesis`, `current_finding`, `version_history`.

### Research Reports (`research_reports.py`)
Auto-generates a report aggregating all modules. Report structure:
- Executive summary (grade A–F, one-line verdict)
- Per-module findings (strategies, scenarios, regimes, risk, benchmark)
- Recommendations list (actionable, operator-facing)
- Methodology note (advisory-only disclosure)

### `shared_services.py` — Public API
| Function | Returns |
|----------|---------|
| `get_summary()` | Top-level research summary |
| `get_strategies()` | All 7 strategy profiles |
| `get_simulations()` | All 8 scenario outcomes |
| `get_replay()` | Historical replay frames + summary |
| `get_benchmark()` | 4-way benchmark comparison |
| `get_reports()` | Auto-generated research report |
| `get_research_lab_snapshot()` | Flat KPI dict for cross-phase use |
| `export_csv()` | CSV string of all data |
| `export_json()` | JSON dict of all data |

All functions check `RESEARCH_LAB_ENABLED` first and return `{"status": "DISABLED"}` if the flag is off.

---

## Dashboard — 9 Tabs

`artifacts/trading-dashboard/src/pages/ResearchLab.tsx`

| Tab | Content |
|-----|---------|
| **Overview** | Research score tile, grade badge, trend indicator, module health grid |
| **Strategies** | Table of 7 strategies with grade, win rate, avg return, recommendation |
| **Scenarios** | 8-scenario cards with expected return/drawdown, probability, risk score |
| **Replay** | Historical frame timeline, replay summary, signal quality chart |
| **Parameters** | 5-axis parameter experiment results (confidence, RSI, stop-loss, target, volume) |
| **Risk Sim** | Drawdown percentile chart, stress scenario table, capital usage gauge |
| **Benchmark** | 4-way comparison table: research vs NIFTY vs market vs paper P&L |
| **Workspace** | Innovation experiment cards with status badges and version history |
| **Reports** | Auto-generated research report with narrative and recommendations |

Polling interval: `refetchInterval: 60_000` (60 seconds).

---

## Test Coverage — 96 / 96

| Test Class | What it tests |
|------------|---------------|
| `TestResearchLabModels` | Dataclasses, grade helpers, trend helpers |
| `TestStrategyResearch` | 7-strategy profile generation, top strategy selection |
| `TestScenarioSimulation` | 8-scenario outcomes, risk/return ranges |
| `TestHistoricalReplay` | Frame generation, replay summary |
| `TestParameterExperiments` | 5-axis variant results, best-variant selection |
| `TestRegimeComparison` | 6-regime profiles, best/avoid strategy logic |
| `TestRiskSimulation` | Drawdown percentiles, 7 stress scenarios |
| `TestPerformanceBenchmark` | 4-way comparison, alpha/sharpe calculation |
| `TestInnovationWorkspace` | 5 experiments, status transitions, version history |
| `TestResearchReports` | Report generation, grade derivation, recommendations |
| `TestSharedServices` | Feature flag guard, all 9 service functions |
| `TestAPIDispatch` | `api.py` command dispatch (8 commands) |
| `TestASTSafety` | **Static guard** — asserts no write-module imports exist in the package |

Run: `cd artifacts/api-server/src/python && RESEARCH_LAB_ENABLED=true python -m pytest test_research_lab.py -q`

---

## Infrastructure Changes

| File | Change |
|------|--------|
| `artifacts/api-server/src/routes/index.ts` | `import researchLabRouter` + `router.use(researchLabRouter)` |
| `artifacts/api-server/src/python/main.py` | 8 `elif` handlers under `# Phase 7.5` |
| `artifacts/trading-dashboard/src/App.tsx` | `ResearchLab` import + `/research-lab` route |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | `FlaskConical` nav entry in Analytics group |

---

## Key Architecture Decisions

### 1. Read-only / advisory-only
No writes to `paper_trades`, `signals_cache`, `scan_state`, or any Postgres table. All computations are over cached signals.

### 2. Upstream data only
Data flows from `signals_store.load_signals()` and `get_*_snapshot()` functions from Phases 7.1, 7.4, and 6.4. No re-computation, no yfinance calls, no direct DB queries inside `research_lab/`.

### 3. Route prefix rule (critical)
Routes are registered as `/research-lab/...` — **not** `/api/research-lab/...`. The Express app mounts the router with `app.use("/api", router)`, which strips the `/api` prefix before matching. Adding `/api/` inside the router causes permanent 404s.

### 4. Feature flag guard
`shared_services.py` wraps every public function with:
```python
if not RESEARCH_LAB_ENABLED:
    return {"status": "DISABLED"}
```

### 5. Cross-phase snapshot hook
`get_research_lab_snapshot()` returns a flat dict (`research_score`, `grade`, `trend`, `total_strategies`, `expected_drawdown`, `benchmark_alpha`) for the Executive Dashboard and review packages to consume without importing the full module.

### 6. AST safety test
`TestASTSafety` walks the entire `research_lab/` package using Python's `ast` module and asserts that no file imports any write-capable module (`paper_trades`, `portfolio_store`, `signals_store` write paths, `scan_state_store` write paths). This is enforced at CI level.

---

## Live Endpoint Verification

```
GET /api/research-lab/summary
→ {"status": "ENABLED", "research_score": 48.7, "grade": "D",
   "total_strategies": 7, "total_scenarios": 8, ...}

GET /api/research-lab/strategies
→ {"top_strategy": "TREND_FOLLOWING", "strategies": [...7 profiles...]}

GET /api/research-lab/reports
→ {"report": {"report_id": 85217948, "grade": "D", "recommendations": [...]}}
```

---

## Proposed Follow-up Tasks

| Task | Description |
|------|-------------|
| **#199** | Show the Research Lab score on the Executive Dashboard (uses `/api/research-lab/snapshot`) |
| **#200** | Confirm Research Lab score updates within 60 s after a new scan completes |
| **#201** | Add walk-forward optimisation to the Parameter Experiments tab |

---

*Generated: 2026-07-30 · ApexQuant AI Platform — Phase 7.5*
