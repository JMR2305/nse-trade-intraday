# Phase 6.2 — Strategy Optimisation & Adaptive Learning Framework

**Status:** COMPLETE  
**Date:** 2026-07-29  
**Advisory-only — no strategy parameters auto-modified**

---

## Deliverables

| # | Deliverable | Status |
|---|-------------|--------|
| 1 | `strategy_optimisation/__init__.py` — package docstring | ✅ |
| 2 | `strategy_optimisation/optimisation_models.py` — dataclasses, feature flag, grade/action helpers | ✅ |
| 3 | `strategy_optimisation/strategy_analyser.py` — per-strategy metrics, health score (0–100), grade (A+/A/B/C/D), 5 underperform signals | ✅ |
| 4 | `strategy_optimisation/regime_analyser.py` — 8 regimes (Bull/Bear/Sideways/High Vol/Low Vol/Trending/Gap Days/Expiry Days) | ✅ |
| 5 | `strategy_optimisation/time_analyser.py` — 5 IST windows (Opening Hour/Morning/Mid Session/Afternoon/Closing Hour) | ✅ |
| 6 | `strategy_optimisation/sector_analyser.py` — composite sector ranking (win rate × 0.4 + PnL × 0.3 + consistency × 0.3) | ✅ |
| 7 | `strategy_optimisation/parameter_optimiser.py` — advisory recs for 7 parameters; all carry `advisory_only=True` | ✅ |
| 8 | `strategy_optimisation/pattern_discovery.py` — winning/losing patterns, high/low confidence setups, best strategy×sector | ✅ |
| 9 | `strategy_optimisation/adaptive_learning.py` — EMERGING/ACTIVE/DECLINING/DORMANT lifecycle; IMPROVING/DECLINING/STABLE trend | ✅ |
| 10 | `strategy_optimisation/shared_services.py` — stable API: `get_summary()`, `get_strategies()`, `get_recommendations()`, `get_patterns()`, `get_optimisation_snapshot()`, `export_strategies_csv()`, `export_recommendations_json()` | ✅ |
| 11 | `strategy_optimisation/api.py` — 4 HTTP façades: `cmd_summary`, `cmd_strategies`, `cmd_recommendations`, `cmd_patterns` | ✅ |
| 12 | `strategy_optimisation/test_strategy_optimisation.py` — **39/39 passing** | ✅ |

---

## Express Route

`artifacts/api-server/src/routes/optimisation.ts` — 6 endpoints:
- `GET /optimisation/summary`
- `GET /optimisation/strategies`
- `GET /optimisation/recommendations`
- `GET /optimisation/patterns`
- `GET /optimisation/export/csv`
- `GET /optimisation/export/json`

---

## React Page

`artifacts/trading-dashboard/src/pages/StrategyOptimisation.tsx`

Eight sections:
1. **Overall Strategy Ranking** — health score, grade, action, win rate, P&L, Sharpe, regime breakdown per strategy
2. **Market Regime Ranking** — regime × win rate × net P&L table
3. **Sector Ranking** — composite sector scoring table
4. **Time Window Ranking** — best window advisory + window descriptions
5. **Parameter Recommendations** — advisory-only recs with confidence badge and rationale
6. **Adaptive Learning** — lifecycle states per strategy, overall/improvement/stability/regression trends
7. **Pattern Discovery** — winning/losing/high-conf/low-conf patterns with conditions
8. **Historical Improvements** — underperforming action list + regime advisory

---

## Wiring

- `main.py` — 6 commands: `optimisation_summary`, `optimisation_strategies`, `optimisation_recommendations`, `optimisation_patterns`, `optimisation_export_csv`, `optimisation_export_json`
- `routes/index.ts` — `optimisationRouter` added after `validationRouter`
- `App.tsx` — `<Route path="/strategy-optimisation" component={StrategyOptimisation} />`
- `AppLayout.tsx` — "Strategy Optimisation" entry with `Sparkles` icon in Analytics section

---

## Feature Flag

`STRATEGY_OPTIMISATION_ENABLED=true`

---

## Key Design Decisions

- Reads exclusively from `paper_trading_validation.validation_collector.collect_all_trade_records()` — no separate DB reads
- All `ParameterRec` objects carry `advisory_only=True` enforced at model level
- Underperform detection uses 5 independent signals (falling win rate, increasing drawdown, poor execution, poor confidence, increasing risk); ≥10 trades required for trend-based checks, <10 uses execution/confidence thresholds
- Adaptive Learning uses GitHub-style lifecycle states; EMERGING = <5 trades, ACTIVE = consistent ≥5, DECLINING/DORMANT based on recency
- TypeScript: clean (0 errors)
