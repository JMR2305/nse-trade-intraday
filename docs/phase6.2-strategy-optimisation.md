# Phase 6.2 — Strategy Optimisation & Adaptive Learning

> **Status:** ✅ Complete & Live  
> **Feature flag:** `STRATEGY_OPTIMISATION_ENABLED=true` (shared env)  
> **Safety contract:** READ-ONLY · ADVISORY-ONLY — no strategy parameters, orders, portfolio state, signals, or risk engine are ever modified.

---

## Overview

Phase 6.2 adds a full strategy performance intelligence layer on top of Phase 6.1's validated paper-trade records. It analyses every closed trade by strategy, regime, sector, and time window; computes composite health scores; detects underperforming strategies; generates advisory parameter recommendations; discovers trade patterns; and tracks adaptive learning trends — all surfaced through a dedicated dashboard page.

---

## Architecture

```
paper_trading_validation.validation_collector   ← Phase 6.1 (FIFO-matched trade records)
            │
            ▼
strategy_optimisation/
├── strategy_analyser.py      per-strategy metrics, health score, grade, underperform detection
├── regime_analyser.py        performance breakdown by market regime
├── sector_analyser.py        performance breakdown by sector
├── time_analyser.py          performance breakdown by intraday time window
├── parameter_optimiser.py    advisory parameter recommendations per strategy
├── adaptive_learning.py      lifecycle states, trend directions, regression detection
├── pattern_discovery.py      WINNING / LOSING / HIGH_CONF / LOW_CONF cluster detection
├── optimisation_models.py    dataclasses, feature flag, grade/action helpers
├── shared_services.py        stable public interface (get_summary / get_strategies /
│                             get_recommendations / get_patterns / get_optimisation_snapshot)
└── api.py                    thin HTTP façade (cmd_* wrappers)
```

Data always flows **one way**: validated trade records in → analytics out. No writes back to any trading system.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/optimisation/summary` | Top 3 strategies, best regime/sector/window, overall advisory trend |
| `GET` | `/api/optimisation/strategies` | Full ranked strategy profiles with regime breakdown + parameter recs |
| `GET` | `/api/optimisation/recommendations` | All advisory recs: parameter, regime, time window, underperform actions, adaptive learning |
| `GET` | `/api/optimisation/patterns` | Pattern discovery: winning/losing/high-conf/low-conf clusters + sector/regime rankings |
| `GET` | `/api/optimisation/export/csv` | Strategy profiles as CSV (headers match `StrategyProfile.to_dict()`) |
| `GET` | `/api/optimisation/export/json` | Full recommendations payload as JSON |

All responses include `"advisory_only": true`. When the feature flag is off every endpoint returns `{"status": "DISABLED"}` — no computation runs.

---

## Health Score Model

The core ranking metric — a 0–100 composite score computed per strategy:

| Component | Weight | Notes |
|-----------|--------|-------|
| Win rate | 35% | Raw fraction of winning trades |
| Profit factor | 25% | Normalised to [0, 1] by capping at 3× |
| Consistency score | 20% | Proportion of rolling 5-trade windows with positive net P&L |
| Stability score | 10% | 1 − (2 × std of win-rate across time buckets); capped at [0, 1] |
| Recovery score | 10% | Proportion of losing trades followed by a win within the next 2 trades |

### Grade thresholds

| Score | Grade | Action |
|-------|-------|--------|
| ≥ 90 | A+ | Continue |
| ≥ 80 | A | Continue |
| ≥ 65 | B | Continue |
| ≥ 50 | C | Observe |
| ≥ 30 | D | Retune |
| < 30 | D | Pause |

---

## Underperforming Detection

A strategy is flagged `is_underperforming = true` (and shown an amber badge on the dashboard) when **any** of the following hold:

| Signal | Trigger |
|--------|---------|
| Falling Win Rate | Recent 10-trade win rate drops > 15 pp below all-time win rate |
| Increasing Drawdown | Recent 10-trade max drawdown > 1.5× overall max drawdown |
| Poor Execution | `avg_execution_score < 60` |
| Poor AI Confidence | `avg_confidence < 0.50` |
| Increasing Risk | Recent 10-trade avg risk score > 1.3× overall avg risk score |

Each active signal is listed as a `underperform_reasons` string on the strategy card.

---

## Adaptive Learning

Computed by `adaptive_learning.compute_adaptive_learning()` from the full trade set:

- **Lifecycle state** per strategy: `EMERGING` (< 5 trades) · `ACTIVE` · `DECLINING` · `DORMANT`
- **Trend direction** (IMPROVING / STABLE / DECLINING) computed with linear slope over the last 5 sampled win-rate points; threshold ±0.05
- **Overall trend** — composite of P&L trend + stability trend + regression detection
- **Regression trend** — flagged DECLINING when recent net P&L is < 80% of all-time average

---

## Pattern Discovery

`pattern_discovery.discover_patterns()` clusters trades into four pattern types using threshold rules (not ML):

| Type | Condition |
|------|-----------|
| `WINNING` | Cluster win rate ≥ 60% and avg return > 0 |
| `LOSING` | Cluster win rate < 40% and avg return < 0 |
| `HIGH_CONF` | Cluster avg AI confidence ≥ 0.75 |
| `LOW_CONF` | Cluster avg AI confidence < 0.50 |

Each pattern carries: `description`, `conditions` (the attributes that define membership), `trade_count`, `win_rate`, `avg_return_pct`, and up to 3 example trade IDs.

---

## Dashboard — StrategyOptimisation.tsx

Eight sections rendered in a single scrollable page:

1. **Overall Strategy Ranking** — health score card per strategy with grade badge, action badge, underperform reasons, and per-regime win-rate breakdown
2. **Market Regime Ranking** — tabular ranking of regimes by win rate and net P&L
3. **Sector Ranking** — tabular ranking of sectors by win rate, net P&L, consistency
4. **Time Window Ranking** — best-window advisory (Opening Hour / Morning / Mid Session / Afternoon / Closing Hour)
5. **Parameter Recommendations** — advisory-only tuning suggestions per strategy with HIGH/MEDIUM/LOW confidence
6. **Adaptive Learning** — overall/P&L/stability/regression trends + per-strategy lifecycle badge
7. **Pattern Discovery** — winning and losing pattern cards with conditions
8. **Historical Improvements** — underperforming action history (Pause/Retune/Observe/Continue)

**Export buttons:** CSV (strategy profiles) and JSON (full recommendations) — enabled only when the flag is on.  
**Auto-refresh:** every 120 s; manual Refresh button triggers all four queries simultaneously.  
**Empty state:** "No strategies yet — complete some paper trades first" shown per section; no crash on empty data.

---

## Key Data Models

### `StrategyProfile` fields

`strategy` · `total_trades` · `win_rate` · `avg_return_pct` · `profit_factor` · `max_drawdown` · `sharpe_ratio` · `avg_holding_time_minutes` · `avg_confidence` · `avg_execution_score` · `avg_risk_score` · `consistency_score` · `stability_score` · `recovery_score` · `health_score` · `grade` · `action` · `is_underperforming` · `underperform_reasons` · `advisory_only`

### `get_optimisation_snapshot()` — for downstream phases

```python
{
  "total_strategies": int,
  "best_strategy": str | None,
  "best_strategy_health": float,
  "best_strategy_grade": str,
  "underperforming_count": int,
}
```
This flat dict is the stable interface for Phase 5D.5 (Executive Dashboard) and any future aggregators. It never raises.

---

## Tests

**39 tests · 39 passing** (`test_strategy_optimisation.py`)

| Test class | Count | What it covers |
|------------|-------|----------------|
| `TestFeatureFlag` | 4 | All 4 endpoints return `DISABLED` when flag is off |
| `TestStrategyAnalyser` | 8 | Win rate, profit factor, Sharpe, drawdown, health score, grade, underperform triggers |
| `TestRegimeAnalyser` | 3 | Regime ranking order, win rate, multi-regime isolation |
| `TestSectorAnalyser` | 3 | Sector ranking, single sector, consistency calculation |
| `TestTimeAnalyser` | 3 | Time window bucketing, multi-window, empty trades |
| `TestParameterOptimiser` | 4 | Recommendation generation, confidence levels, advisory flag |
| `TestPatternDiscovery` | 4 | Winning/losing/high-conf/low-conf pattern detection |
| `TestSharedServicesAPI` | 7 | End-to-end response shape for all 4 endpoints + determinism |
| `TestAdaptiveLearning` | 5 | Lifecycle states, trend direction (improving/declining/stable) |
| `TestOptimisationSnapshot` | 2 | Required keys, zero-data fallback |

Run:
```bash
cd artifacts/api-server/src/python
python -m pytest strategy_optimisation/test_strategy_optimisation.py -v
```

---

## Files

| File | Lines | Role |
|------|-------|------|
| `strategy_optimisation/optimisation_models.py` | 240 | Dataclasses, feature flag, grade/action helpers |
| `strategy_optimisation/strategy_analyser.py` | 246 | Health score, underperform detection, `analyse_strategies()` |
| `strategy_optimisation/regime_analyser.py` | ~80 | `analyse_regimes()` |
| `strategy_optimisation/sector_analyser.py` | ~80 | `analyse_sectors()` |
| `strategy_optimisation/time_analyser.py` | ~100 | `analyse_time_windows()` — 5 intraday buckets |
| `strategy_optimisation/parameter_optimiser.py` | ~120 | `generate_recommendations()` |
| `strategy_optimisation/adaptive_learning.py` | ~140 | Lifecycle, trend, regression, `compute_adaptive_learning()` |
| `strategy_optimisation/pattern_discovery.py` | ~120 | `discover_patterns()` |
| `strategy_optimisation/shared_services.py` | 324 | Public API + export helpers + `get_optimisation_snapshot()` |
| `strategy_optimisation/api.py` | 22 | HTTP façade (`cmd_*` wrappers) |
| `strategy_optimisation/test_strategy_optimisation.py` | 466 | 39 unit tests |
| `artifacts/trading-dashboard/src/pages/StrategyOptimisation.tsx` | 560+ | Dashboard page (8 sections) |

---

## Dependency Map

```
Phase 6.2 (Strategy Optimisation)
    └── consumes → Phase 6.1 paper_trading_validation.validation_collector (FIFO-matched TradeRecord list)
    └── consumed by → Phase 5D.5 Executive Dashboard (get_optimisation_snapshot)
    └── consumed by → future phases via shared_services stable interface
```

Phase 6.2 never reads raw DB tables directly — it always operates on the `List[TradeRecord]` that Phase 6.1 has already validated and FIFO-matched.
