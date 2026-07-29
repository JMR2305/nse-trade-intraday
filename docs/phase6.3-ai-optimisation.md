# Phase 6.3 — AI Optimisation & Continuous Learning Framework

> **Status:** ✅ PHASE 6.3 COMPLETE  
> **Feature flag:** `AI_OPTIMISATION_ENABLED=true` (shared env)  
> **Safety contract:** READ-ONLY · ADVISORY-ONLY — No AI models, trading engine, orders, portfolio, signals, risk engine, or strategies are ever modified automatically.

---

## 1. Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `ai_optimisation/__init__.py` | 2 | Package marker |
| `ai_optimisation/optimisation_models.py` | 145 | Feature flag, dataclasses, health score formula, grade thresholds |
| `ai_optimisation/performance_analyser.py` | 150 | Prediction quality: accuracy, precision, recall, F1, FPR, FNR, confidence error, ECE, stability, consistency |
| `ai_optimisation/calibration_analyser.py` | 85 | 5-band confidence calibration, threshold recommendation |
| `ai_optimisation/false_signal_analyser.py` | 110 | FALSE_BUY/SELL, LATE, EARLY, HIGH_CONF_LOSS, LOW_CONF_WIN detection + advisory insights |
| `ai_optimisation/drift_analyser.py` | 160 | 6-dimension drift: Prediction, Confidence, Strategy, Regime, Sector, Performance |
| `ai_optimisation/learning_analyser.py` | 120 | Improvement rate, regression rate, learning velocity, consistency/confidence/adaptive trends |
| `ai_optimisation/recommendation_engine.py` | 200 | Advisory recs for 8 dimensions: confidence threshold, signal filters, regime, sector, time window, risk, execution, strategy |
| `ai_optimisation/shared_services.py` | 270 | Stable public interface: 5 GET functions + export helpers + `get_ai_optimisation_snapshot()` |
| `ai_optimisation/api.py` | 20 | Thin HTTP façade (cmd_* wrappers) |
| `ai_optimisation/test_ai_optimisation.py` | 320 | 43 unit tests across 9 test classes |
| `artifacts/api-server/src/routes/ai-optimisation.ts` | 85 | Express router for all 7 HTTP endpoints |
| `artifacts/trading-dashboard/src/pages/AIOptimisation.tsx` | 420 | 9-section dashboard page |

---

## 2. Files Modified

| File | Change |
|------|--------|
| `artifacts/api-server/src/python/main.py` | Added 7 new command dispatch entries for `ai_optimisation_*` |
| `artifacts/api-server/src/routes/index.ts` | Imported and registered `aiOptimisationRouter` |
| `artifacts/trading-dashboard/src/App.tsx` | Added `import AIOptimisation` and `<Route path="/ai-optimisation">` |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Added "AI Optimisation" nav item between Strategy Optimisation and AI Performance |

---

## 3. Shared Services Reused

| Phase | Module | How Reused |
|-------|--------|-----------|
| Phase 6.1 | `paper_trading_validation.validation_collector.collect_all_trade_records()` | Primary data source — all analytics operate on `List[TradeRecord]` |
| Phase 5D.4 | `ai_performance.shared_services.get_ai_snapshot()` | Available via `get_ai_optimisation_snapshot()` for downstream consumers |
| Phase 6.2 | `strategy_optimisation.shared_services.get_optimisation_snapshot()` | Strategy-level context for recommendations |

No analytics are duplicated. All metrics derive from the Phase 6.1 `TradeRecord` stream — the same source as every upstream phase.

---

## 4. APIs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ai-optimisation/summary` | AI Optimisation Score, grade, trend, full prediction quality snapshot |
| `GET` | `/api/ai-optimisation/calibration` | 5-band confidence calibration + threshold recommendation + version comparison stub |
| `GET` | `/api/ai-optimisation/drift` | 6-dimension drift + false signal analysis |
| `GET` | `/api/ai-optimisation/recommendations` | Advisory recs with explainability (reason, evidence, benefit, confidence) |
| `GET` | `/api/ai-optimisation/history` | Rolling learning progress, period breakdown, historical trend |
| `GET` | `/api/ai-optimisation/export/csv` | Summary stats as CSV |
| `GET` | `/api/ai-optimisation/export/json` | Full recommendations payload as JSON |

All responses carry `"advisory_only": true`. When the flag is off every endpoint returns `{"status": "DISABLED"}`.

---

## 5. Dashboard

**Page:** `/ai-optimisation` → `AIOptimisation.tsx`

Nine sections:

| # | Section | Data Source |
|---|---------|------------|
| 1 | **AI Health** | `/summary` — Score ring (0–100), grade badge, trend, key metrics grid |
| 2 | **Confidence Calibration** | `/calibration` — 5-band table with win rate, avg return, risk, pred error; threshold advisory |
| 3 | **Prediction Quality** | `/summary` — Accuracy, precision, recall, F1, FPR, FNR, confidence error, calibration score |
| 4 | **False Signal Analysis** | `/drift` — Per-type counts + advisory insight banners |
| 5 | **Model Drift Detection** | `/drift` — 6-row table with baseline → recent → Δ + severity badge per dimension |
| 6 | **Learning Progress** | `/history` — Adaptive trend, velocity, improvement/regression rates, period breakdown table |
| 7 | **Version Comparison** | `/calibration` — Future-ready stub (disabled, no promotion) |
| 8 | **Recommendations** | `/recommendations` — Explainable advisory cards with reason, evidence, benefit |
| 9 | **Historical Trend** | `/history` — Accuracy/F1/confidence summary + future ML retraining hook explanation |

---

## 6. Test Count

**43 tests — 43 passing** (`test_ai_optimisation.py`)

---

## 7. Test Results

```
============================= test session starts ==============================
platform linux -- Python 3.12.12, pytest-9.1.1
collected 43 items

ai_optimisation/test_ai_optimisation.py ................................................. [100%]

============================== 43 passed in 0.66s ==============================
```

| Test Class | Tests | Covers |
|------------|-------|--------|
| `TestFeatureFlag` | 5 | All 5 endpoints return `DISABLED` when flag is off |
| `TestPerformanceAnalyser` | 6 | TP/FP/TN/FN classification, accuracy, ECE, missing confidence |
| `TestCalibrationAnalyser` | 4 | 5 bands always returned, threshold rec, prediction error ≥ 0 |
| `TestFalseSignalAnalyser` | 5 | False buy/sell, high-conf loss, low-conf win, insights on high false rate |
| `TestDriftAnalyser` | 4 | Empty → no metrics, insufficient history → stable, drift score 0–1 |
| `TestLearningAnalyser` | 4 | Empty → INSUFFICIENT_DATA, buckets present, improvement+regression ≤ 1 |
| `TestRecommendationEngine` | 3 | No-data stub, advisory_only=True on all, ConfidenceThreshold present |
| `TestSharedServicesAPI` | 8 | End-to-end for all 5 endpoints + excellent vs poor AI score ordering |
| `TestHealthScoreModel` | 4 | Perfect inputs → A grade, zero inputs → D, threshold boundaries, snapshot keys |

---

## 8. Performance Benchmarks

Verified against 0 trades (instantaneous). With real paper trade data:

- All 5 endpoints spawn a single Python process per request.
- `analyse_prediction_quality()` is O(n) — no nested loops.
- `analyse_drift()` is O(n log n) for sort + O(n) for group operations.
- `analyse_calibration()` is O(n) — one pass over records.
- `analyse_learning()` is O(n log n) for sort + O(n) per bucket.
- The 30s TTL cache pattern from Phase 5D.2 can be applied to any endpoint if latency becomes a concern at scale.

---

## 9. Known Limitations

| Limitation | Detail |
|-----------|--------|
| Empty state | All analytics show zeros / graceful messages until paper trades are recorded. |
| Drift requires ≥ 33 trades | The baseline/recent split needs history > `max(20, n//3)` trades to produce meaningful signal. |
| Learning velocity | 4-bucket approximation — precision improves with more trades. |
| Version comparison | Stub only; requires AI version metadata that no current phase provides. |
| Time window mapping | Approximates entry time from `timestamp` (exit) minus `holding_time_minutes`; works for intraday but is an approximation. |

---

## 10. AI Optimisation Methodology

### Health Score Formula

```
AI Optimisation Score (0–100) =
    accuracy × 30
  + (1 − min(ECE × 2, 1)) × 20
  + (1 − false_signal_rate) × 20
  + ((learning_velocity + 1) / 2) × 15
  + (1 − drift_score) × 15
```

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Prediction accuracy | 30% | Primary correctness signal |
| Calibration (1 − ECE) | 20% | Confidence reliability — overconfident AI is dangerous |
| False signal rate | 20% | Directly impacts capital preservation |
| Learning velocity | 15% | Penalises regression, rewards improvement |
| Drift stability | 15% | Unstable distributions reduce reliability |

### Confidence Calibration

Expected Calibration Error (ECE) = Σ (|bin_size / total| × |avg_confidence − win_rate|) across 5 bins.

Well-calibrated: ECE < 0.05. Acceptable: < 0.10. Review needed: > 0.15.

### Drift Detection

Compares the most-recent `max(20, n // 3)` trades to the full historical baseline across 6 dimensions. Severity thresholds:

- **LOW**: |drift| < 5% (Prediction/Confidence) or < 10% (others)
- **MEDIUM**: |drift| 5–15% or 10–25%
- **HIGH**: |drift| ≥ 15% or ≥ 25%

Overall severity: HIGH if ≥ 2 HIGH dimensions; MEDIUM if 1 HIGH or ≥ 2 MEDIUM; otherwise LOW/STABLE.

---

## 11. GitHub-Inspired Enhancements

| Concept | Implementation in Phase 6.3 |
|---------|----------------------------|
| **AI confidence calibration** | 5-band ECE analysis with per-band win rate, prediction error, threshold advisory |
| **Adaptive confidence thresholds** | `_recommend_threshold()` in `calibration_analyser.py` — selects the band with the best calibrated win rate |
| **Recommendation explainability** | Every recommendation carries: reason, supporting metrics, historical evidence, confidence, suggested action, expected benefit |
| **Model drift monitoring** | 6-dimension drift analyser with signed drift values and severity classification |
| **Decision quality scoring** | AI Optimisation Score (0–100) weighted composite of 5 quality dimensions |
| **AI version comparison framework** | Stub with full data structure defined; activates without code changes when version metadata is available |
| **Pattern-based recommendation refinement** | False signal patterns (HIGH_CONF_LOSS, LOW_CONF_WIN) feed directly into signal filter recommendations |
| **Future-ready ML retraining hooks** | Learning velocity / regression rate serve as trigger signals; version comparison accepts new model artifacts; all disabled by default |

---

## 12. How Future ML Retraining Plugs In

The architecture is designed with a clean seam for retraining:

```
Current architecture:
  TradeRecord stream → Phase 6.3 analytics → advisory dashboard

Future retraining hook (no architecture change required):
  TradeRecord stream → Phase 6.3 analytics
                    ↓ trigger (learning_velocity < −0.2 OR regression_rate > 0.6)
                    → Retraining job (external, operator-approved)
                    → New model version metadata published
                    → Version comparison framework activates
                    → Operator reviews Accuracy Δ / Risk Δ / Win Rate Δ
                    → Operator manually promotes (never auto-promoted)
```

Specifically:
- **Trigger signals** already computed: `learning_velocity`, `regression_rate`, `drift_score`
- **Version comparison data contract** already defined in `get_calibration()` → `version_comparison` key; accepts `{versions: [{label, accuracy, win_rate, risk, recommendation_delta}]}`
- **Advisory-only gate**: `OptimisationRecommendation.advisory_only = True` is enforced at the dataclass level — it cannot be set False from outside the module
- **No code changes required** to accept new model versions; only the version metadata payload needs to be provided

---

## 13. Advisory-Only Confirmation

✅ **Phase 6.3 is advisory-only. No AI behaviour is automatically modified.**

This is enforced at multiple layers:

1. **Data contract**: `OptimisationRecommendation.advisory_only = True` is hardcoded; `to_dict()` always outputs `"advisory_only": True`
2. **No write paths**: `shared_services.py` contains zero write operations. It only reads from `collect_all_trade_records()`.
3. **No hooks into signal flow**: Phase 6.3 has no imports of `signal_generator`, `order_manager`, `risk_engine`, `paper_portfolio`, or any write-capable module
4. **No auto-promotion**: The version comparison stub explicitly sets `enabled: false`
5. **UI labelling**: Every recommendation card shows "advisory only" badge; the page header badge reads "ADVISORY ONLY — NO AI BEHAVIOUR AUTO-MODIFIED"
6. **Feature flag**: The entire module is gated behind `AI_OPTIMISATION_ENABLED=true` and returns `DISABLED` when off

---

**PHASE 6.3 COMPLETE**
