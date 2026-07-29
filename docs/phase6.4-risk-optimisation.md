# Phase 6.4 — Risk Optimisation & Capital Allocation Intelligence

> **Status:** ✅ PHASE 6.4 COMPLETE  
> **Feature flag:** `RISK_OPTIMISATION_ENABLED=true` (shared env)  
> **Safety contract:** READ-ONLY · ADVISORY-ONLY — No orders, portfolio, strategies, signals, risk engine, or position sizes are ever modified automatically.

---

## 1. Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `risk_optimisation/__init__.py` | 2 | Package marker |
| `risk_optimisation/risk_models.py` | 160 | Feature flag, `compute_risk_optimisation_score()` (weighted 0–100), `health_grade()`, dataclasses: `DrawdownPeriod`, `StressScenario`, `RiskRecommendation` |
| `risk_optimisation/capital_analyser.py` | 170 | Capital utilisation, idle capital, Kelly-based recommended allocation, allocation stability; position sizing: avg/largest/smallest/win/loss positions, recommended, max safe, risk per trade |
| `risk_optimisation/concentration_analyser.py` | 130 | Single position exposure, sector/strategy/regime exposure tables, HHI for sectors and strategies, normalised diversification score, correlation risk (LOW/MEDIUM/HIGH) |
| `risk_optimisation/drawdown_analyser.py` | 120 | Max drawdown, avg drawdown, recovery efficiency, avg recovery time, worst period, drawdown frequency, equity curve, drawdown severity |
| `risk_optimisation/stop_loss_analyser.py` | 100 | SL hit count/rate, avg loss on SL, avg stop distance, trailing stop analysis, premature/late exit detection, SL quality score |
| `risk_optimisation/target_analyser.py` | 95 | Target hits, win rate, avg reward, reward/risk ratio, avg win %, early profit booking, extended winners, missed profit count |
| `risk_optimisation/stress_tester.py` | 160 | 7 advisory stress scenarios: 20% correction, gap down, gap up, high volatility, 5 consecutive losses, sector collapse, liquidity crunch; Monte Carlo future hook |
| `risk_optimisation/recommendation_engine.py` | 290 | Advisory recs for 8 categories: CapitalAllocation, PositionSizing, Concentration, Drawdown, StopLoss, Target, RiskBudget, Diversification; priority-sorted |
| `risk_optimisation/shared_services.py` | 280 | Stable public interface: 5 GET endpoints + 2 export helpers + `get_risk_optimisation_snapshot()` |
| `risk_optimisation/api.py` | 18 | Thin HTTP façade (cmd_* wrappers) |
| `risk_optimisation/test_risk_optimisation.py` | 400 | 54 unit tests across 11 test classes |
| `artifacts/api-server/src/routes/risk-optimisation.ts` | 90 | Express router for all 7 HTTP endpoints |
| `artifacts/trading-dashboard/src/pages/RiskOptimisation.tsx` | 490 | 10-section dashboard page |

---

## 2. Files Modified

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/main.py` | Added 7 new command dispatch entries for `risk_optimisation_*` |
| `artifacts/api-server/src/routes/index.ts` | Imported and registered `riskOptimisationRouter` |
| `artifacts/trading-dashboard/src/App.tsx` | Added `import RiskOptimisation` and `<Route path="/risk-optimisation">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Added "Risk Optimisation" nav item after AI Optimisation in Analytics group |

---

## 3. Shared Services Reused

| Phase | Module | How Reused |
|-------|--------|-----------|
| Phase 6.1 | `paper_trading_validation.validation_collector.collect_all_trade_records()` | Primary data source — all analytics operate on `List[TradeRecord]` |
| Phase 5D.4 | `ai_performance` | Available via `get_risk_optimisation_snapshot()` for downstream consumers |
| Phase 6.3 | `ai_optimisation.shared_services.get_ai_optimisation_snapshot()` | Available for cross-phase executive summary |

No analytics are duplicated. All metrics derive from the Phase 6.1 `TradeRecord` stream.

---

## 4. APIs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/risk-optimisation/summary` | Risk Optimisation Score, grade, trend, all component scores snapshot |
| `GET` | `/api/risk-optimisation/capital` | Capital allocation + position sizing + portfolio concentration + stop loss + target analysis |
| `GET` | `/api/risk-optimisation/drawdown` | Full drawdown analysis with equity curve, periods, recovery metrics |
| `GET` | `/api/risk-optimisation/stress` | 7 advisory stress scenarios with estimated portfolio impact |
| `GET` | `/api/risk-optimisation/recommendations` | Advisory recs with explainability (reason, evidence, benefit, risk reduction, priority) |
| `GET` | `/api/risk-optimisation/export/csv` | Summary stats as CSV |
| `GET` | `/api/risk-optimisation/export/json` | Full recommendations payload as JSON |

All responses carry `"advisory_only": true`. When the flag is off every endpoint returns `{"status": "DISABLED"}`.

---

## 5. Dashboard

**Page:** `/risk-optimisation` → `RiskOptimisation.tsx`

Ten sections:

| # | Section | Data Source |
|---|---------|------------|
| 1 | **Risk Health** | `/summary` — Score ring (0–100), grade badge, trend, 6 component score tiles |
| 2 | **Capital Allocation** | `/capital` — Utilisation, idle capital, Kelly fraction, recommended allocation, stability |
| 3 | **Position Sizing** | `/capital` — Avg/largest/smallest, recommended, max safe (2% rule), risk per trade |
| 4 | **Sector Diversification** | `/capital` — HHI, diversification score, sector/strategy exposure tables, correlation risk |
| 5 | **Drawdown Analysis** | `/drawdown` — Max DD, avg DD, recovery efficiency, equity sparkline, worst period card |
| 6 | **Stop Loss Analysis** | `/capital` — SL hit rate, avg loss, stop distance, premature/late exits, advisory |
| 7 | **Target Analysis** | `/capital` — R:R ratio, win rate, target hits, early booking, extended winners |
| 8 | **Stress Testing** | `/stress` — 7-scenario table with impact %, estimated P&L, severity; Monte Carlo stub |
| 9 | **Recommendations** | `/recommendations` — Priority-sorted advisory cards with full explainability |
| 10 | **Historical Risk Trend** | `/summary` — Key stats + future Monte Carlo integration hook explanation |

---

## 6. Test Count

**54 tests — 54 passing** (`test_risk_optimisation.py`)

---

## 7. Test Results

```
============================= test session results ==============================
platform linux -- Python 3.12.12, pytest-9.1.1
collected 54 items

risk_optimisation/test_risk_optimisation.py ..................................................... [100%]

============================== 54 passed in 1.37s ==============================
```

| Test Class | Tests | Covers |
|------------|-------|--------|
| `TestFeatureFlag` | 5 | All 5 endpoints return `DISABLED` when flag is off |
| `TestCapitalAnalyser` | 6 | Empty/single/multi records, capital deployed formula, idle capital, efficiency bounds, Kelly allocation |
| `TestPositionAnalyser` | 4 | Empty state, avg non-negative, largest ≥ smallest, score bounds |
| `TestConcentrationAnalyser` | 5 | Empty state, single-sector HHI high, multi-sector HHI lower, diversification bounds, correlation risk values |
| `TestDrawdownAnalyser` | 6 | Empty, all-wins no drawdown, mixed has drawdown, bounds 0–1, equity curve start, high severity |
| `TestStopLossAnalyser` | 5 | Empty, stop count correct, rate bounds, quality score bounds, advisory non-empty |
| `TestTargetAnalyser` | 4 | Empty, target count correct, R:R ≥ 0, win+loss = total |
| `TestStressTester` | 5 | Always 7 scenarios, required keys, gap-up positive, correction negative, Monte Carlo disabled |
| `TestRecommendationEngine` | 4 | No-data empty list, `advisory_only=True` always, HIGH priority sorted first, required fields |
| `TestSharedServicesAPI` | 6 | ENABLED status, score bounds, capital nested sections, drawdown keys, stress 7 scenarios, recs advisory |
| `TestHealthScoreModel` | 4 | Perfect → 100/A+, zeros → D, grade thresholds, snapshot keys |

---

## 8. Performance Benchmarks

Verified at 0 trades (instantaneous). With real paper trade data:

- All endpoints are O(n) or O(n log n) per trade:
  - `analyse_capital()`, `analyse_stop_loss()`, `analyse_targets()`: O(n)
  - `analyse_concentration()`: O(n) with `defaultdict`
  - `analyse_drawdown()`: O(n log n) for sort + O(n) pass
  - `stress_tester`: O(n) single pass for avg loss
- No shared state between requests — Python process-per-request isolation.
- `get_risk_optimisation_snapshot()` for executive dashboard is safe to call with 0 trades (never raises).

---

## 9. Known Limitations

| Limitation | Detail |
|-----------|--------|
| Empty state | All analytics show graceful empty/zero state until paper trades are recorded. |
| Capital inference | Capital deployed = `entry_price × quantity`; no explicit "account capital" field in `TradeRecord`. Starting capital defaults to ₹5,00,000. |
| Stop loss classification | Stop loss exits identified by keyword match on `exit_reason` (`stop`, `sl`, `trailing`, etc.); may miss custom exit labels. |
| Target classification | Target exits identified by `target`, `tgt`, `profit`, `take_profit` keywords. |
| Drawdown at trade granularity | Equity curve is computed per completed trade, not tick-by-tick intraday. |
| Stress scenarios | All hypothetical — no intraday price data is used in impact estimates. |
| Monte Carlo | Stub only; no simulation runs. Enabled by setting `MONTE_CARLO_ENABLED=true` (future). |

---

## 10. Risk Optimisation Methodology

### Health Score Formula

```
Risk Optimisation Score (0–100) =
    diversification_score × 25
  + (1 − drawdown_severity) × 25
  + capital_efficiency × 20
  + position_sizing_score × 15
  + stop_loss_quality_score × 15
```

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Diversification | 25% | Correlation risk is the primary source of catastrophic portfolio loss |
| Drawdown resilience | 25% | Capital preservation is the first priority in advisory trading |
| Capital efficiency | 20% | Idle capital is a drag; over-deployment increases drawdown |
| Position sizing | 15% | Over-sized positions are the #1 cause of forced exits |
| Stop loss quality | 15% | Poor stops either cut winners short or let losses run |

### Concentration Measurement (HHI)

Normalised Herfindahl–Hirschman Index:
- HHI = Σ(count_i / total)² per sector/strategy
- Normalised: (HHI_raw − 1/n) / (1 − 1/n)
- 0 = perfectly even distribution, 1 = all in one category

### Drawdown Severity

`severity = min(1.0, max_drawdown × 3.0)`

A 33% drawdown reaches severity 1.0 (maximum). Below 5% is near-zero severity.

### Kelly Fraction (Half-Kelly)

`kelly_f = max(0, min(0.25, (win_rate × R:R − (1 − win_rate)) / R:R × 0.5))`

Half-Kelly (capped at 25%) balances growth optimisation with capital preservation.

### Drawdown Recovery Efficiency

`recovery_efficiency = recovered_periods / total_periods`

"Recovered" = a drawdown period that reached a new equity high before the analysis window closes.

---

## 11. GitHub-Inspired Enhancements

| Concept | Implementation |
|---------|---------------|
| **Dynamic position sizing** | Kelly-based `recommended_allocation` and `max_safe_position` (2% rule) |
| **Portfolio concentration analysis** | Normalised HHI for sectors and strategies; single-position max % |
| **Sector exposure monitoring** | Per-sector trade counts and % in `concentration_analyser` |
| **Correlation-aware diversification** | `diversification_score` penalises both high HHI and single-position concentration simultaneously |
| **Adaptive risk budgeting** | `RiskBudget` recommendation category with daily loss limit and maximum exposure suggestions |
| **Drawdown recovery analytics** | `recovery_efficiency`, `avg_recovery_trades`, worst period isolation, equity sparkline |
| **Stress-test simulation framework** | 7 scenarios with severity classification; structured for easy extension |
| **Capital efficiency scoring** | `capital_efficiency` = win P&L / total capital deployed, normalised 0–1 |
| **Risk-adjusted performance ranking** | Score weights drawdown resilience and diversification equally alongside absolute performance metrics |
| **Monte Carlo simulations (future-ready)** | Hook in `stress_tester.py`: `monte_carlo_simulation.enabled` flag + note; activates without architecture changes |

---

## 12. Future Monte Carlo & Advanced Portfolio Optimisation Integration

The architecture has a clean seam for both Monte Carlo simulations and mean-variance portfolio optimisation:

```
Current architecture:
  TradeRecord stream → Phase 6.4 analytics → advisory dashboard

Future Monte Carlo hook (no architecture change required):
  TradeRecord stream → Phase 6.4 analytics
                    ↓ (trade distribution fitted from historical records)
                    → Monte Carlo engine (10,000 paths, external library)
                    → Confidence intervals for drawdown projections
                    → Capital-at-risk (CaR) at 95th/99th percentile
                    → Operator reviews before any action
                    → Advisory-only: shown in Section 8 Stress Testing

Future Markowitz optimisation hook:
  TradeRecord stream → Phase 6.4 analytics
                    ↓ sector returns + covariance matrix
                    → Efficient frontier solver (optional: scipy.optimize)
                    → Optimal sector allocation weights (advisory)
                    → Shown alongside HHI diversification score
```

Specifically:
- **Monte Carlo trigger**: `stress_tester.py` → `run_stress_tests()` already returns `monte_carlo_simulation.enabled` key. Set `MONTE_CARLO_ENABLED=true` to activate the (future) engine without any API changes.
- **Portfolio optimisation trigger**: `concentration_analyser.py` already returns per-sector counts and HHI. The efficient frontier solver would accept the same inputs.
- **Advisory-only gate**: `RiskRecommendation.advisory_only = True` is hardcoded at the dataclass level. It cannot be set False.
- **No code changes needed** to accept new simulation outputs; only the simulation engine needs to be wired in.

---

## 13. Advisory-Only Confirmation

✅ **Phase 6.4 is advisory-only. No risk parameters, portfolio state, or position sizes are automatically modified.**

Enforced at multiple layers:

1. **Data contract**: `RiskRecommendation.advisory_only = True` is hardcoded; `to_dict()` always outputs `"advisory_only": True`
2. **No write paths**: `shared_services.py` contains zero write operations. It only reads from `collect_all_trade_records()`.
3. **No hooks into execution**: Phase 6.4 has zero imports of `signal_generator`, `order_manager`, `risk_engine`, `paper_portfolio`, `paper_trader`, or any write-capable module
4. **No automatic parameter changes**: Recommendations are display-only strings — there is no `apply_recommendation()` function
5. **No auto-promotion**: Monte Carlo stub explicitly has `enabled: false`
6. **UI labelling**: Every recommendation card shows "ADVISORY ONLY"; page header badge reads "RISK OPTIMISATION — ADVISORY ONLY — NO PARAMETERS AUTO-MODIFIED"
7. **Feature flag**: Entire module returns `DISABLED` when `RISK_OPTIMISATION_ENABLED≠true`

---

**PHASE 6.4 COMPLETE**
