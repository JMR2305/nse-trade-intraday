# Phase 5D.4 — AI Performance Intelligence

**Status:** COMPLETE  
**Feature flag:** `AI_PERFORMANCE_ENABLED=true`  
**Module:** `artifacts/api-server/src/python/ai_performance/`  
**Dashboard:** `artifacts/trading-dashboard/src/pages/AIPerformanceIntelligence.tsx` → `/ai-performance`

---

## What was built

A read-only analytics module that evaluates how well the AI performs over time using historical paper-trading data. It never recalculates anything already computed by Phase 5D.1–5D.3 — all strategy profiles, regime/sector matrices, and closed trades flow in from `strategy_intelligence.shared_services`. New analytics added exclusively here: confidence analysis, calibration quality, binary classification metrics (precision/recall/F1/MCC), recommendation analysis, learning trend analysis, and a composite AI Health Score (0–100).

---

## Files created

| File | Purpose |
|---|---|
| `ai_performance/__init__.py` | Package docstring — advisory-only contract, reuse contract |
| `ai_performance/ai_models.py` | `AISignalRecord`, `CalibrationPoint`, `PredictionMetrics`, `CalibrationMetrics`, `AIHealthScore`; feature flag helpers; confidence bucket constants |
| `ai_performance/ai_engine.py` | Converts 5D.3 `ClosedTrade` → `AISignalRecord`; assigns TP/FP/TN/FN classification; builds date fields for learning analysis |
| `ai_performance/confidence_analysis.py` | Confidence distribution, per-bucket stats, confidence vs regime/sector cross-analyses |
| `ai_performance/calibration.py` | ECE, reliability score, confidence bias, overconfidence %, underconfidence %, calibration curve |
| `ai_performance/prediction_analysis.py` | Precision, Recall, Accuracy, FPR, FNR, TPR, TNR, F1, MCC, Balanced Accuracy |
| `ai_performance/recommendation_analysis.py` | Accepted/flagged/neutral strategy win rates; per-recommendation breakdown |
| `ai_performance/learning_analysis.py` | Daily/weekly/monthly accuracy; rolling 30-day window; trend direction (Improving/Stable/Declining) |
| `ai_performance/shared_services.py` | **Stable interface for Phase 5D.5** — see Deliverable #10 |
| `ai_performance/api.py` | 6 HTTP façade functions |
| `ai_performance/test_ai_performance.py` | 32 unit tests — all passing |

**Files modified:**

| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` | +6 ai_* commands |
| `artifacts/api-server/src/routes/index.ts` | Added `aiPerformanceRouter` |
| `artifacts/api-server/src/routes/ai-performance.ts` | 6 Express GET endpoints |
| `artifacts/trading-dashboard/src/App.tsx` | Added `/ai-performance` route |
| `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx` | Added `AI Performance` sidebar entry (Brain icon) |

---

## Shared services reused from earlier phases

| Module | What was reused |
|---|---|
| `strategy_intelligence.strategy_engine.load_all_data()` | FIFO-matched `ClosedTrade` list — no re-implementation of FIFO matching |
| `strategy_intelligence.shared_services.get_all_strategy_profiles()` | Ranked+recommended strategy profiles for recommendation context |
| `strategy_intelligence.shared_services.get_recommendations()` | Recommendation labels to tag each `AISignalRecord` |

Nothing from Phase 5D.1–5D.2 was recalculated: execution quality scores flow in through the `ClosedTrade.quality_score` field already populated by 5D.3's engine.

---

## API endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/ai/summary` | Health score, all KPIs, prediction metrics, confidence distribution, trend |
| `GET /api/ai/confidence` | Confidence buckets + vs-regime + vs-sector cross-analyses |
| `GET /api/ai/calibration` | ECE, reliability, bias, overconfidence, calibration curve |
| `GET /api/ai/predictions` | Full binary classification matrix (TP/FP/TN/FN + all derived metrics) |
| `GET /api/ai/recommendations` | Accepted/flagged/neutral win rates, per-recommendation breakdown |
| `GET /api/ai/learning` | Daily/weekly/monthly accuracy, rolling 30d, trend direction |

---

## Classification methodology

**Positive class** = "AI predicts this trade will win" → `signal_confidence >= 60%`  
**Negative class** = "AI is uncertain" → `signal_confidence < 60%`  
**Actual positive** = trade won (`pnl > 0`)  
**Actual negative** = trade lost (`pnl ≤ 0`)

| Quadrant | Definition |
|---|---|
| **TP** | High confidence + winner |
| **FP** | High confidence + loser |
| **TN** | Low confidence + loser |
| **FN** | Low confidence + winner |

All four quadrants are fully observable from executed trade history. TN/FN do not require counterfactual "what would have happened" data because lower-confidence trades that were still executed provide the negative-class samples.

---

## AI Health Score (0–100)

| Component | Weight | Source |
|---|---|---|
| Prediction Accuracy | 25% | Balanced Accuracy × 100 |
| Calibration Quality | 20% | `reliability_score` = (1 – ECE) × 100 |
| Consistency | 20% | 100 − (stdev of daily accuracies × 2) |
| Execution Outcome | 15% | Avg execution quality score (already 0–100 from 5D.1) |
| Risk Awareness | 10% | % of trades exiting via TARGET_HIT |
| Recommendation Quality | 10% | Accepted strategies' win rate |

Labels: Excellent (≥90), Good (≥75), Fair (≥60), Poor (≥40), Critical (<40).

---

## Deliverable #10 — How Phase 5D.5 will reuse this module

Phase 5D.5 (Executive Dashboard) **must not recalculate AI metrics**. It imports from `ai_performance.shared_services` only:

```python
from ai_performance.shared_services import (
    get_ai_snapshot,        # ← primary call for executive tile (flat dict, one call)
    get_ai_summary,         # full KPI dict if executive view needs a deep-link panel
    get_health_score,       # just the health score and component breakdown
    get_confidence_data,    # if executive view wants a mini-chart
    get_learning_data,      # for trend direction tile
)
```

`get_ai_snapshot()` is designed specifically for the executive dashboard tile:
```python
{
    "health_score":        94.2,
    "health_label":        "Excellent",
    "prediction_accuracy": 73.5,
    "balanced_accuracy":   71.8,
    "precision":           80.0,
    "recall":              68.4,
    "f1_score":            0.7370,
    "avg_confidence":      77.3,
    "calibration_ece":     0.0412,
    "trend_direction":     "Improving",
    "accuracy_delta":      +6.2,
    "total_signals":       142,
}
```

One call to `get_ai_snapshot()` gives the executive view all KPIs for its AI tile without touching any sub-module. The stable function signatures in `shared_services.py` must not be renamed without versioning — 5D.5 depends on them.

---

## Deliverable #11 — Metrics that require minimum sample sizes

| Metric | Minimum reliable sample | Rationale |
|---|---|---|
| **Calibration ECE** | ≥ 20 trades per occupied bucket | ECE is a weighted average across buckets; a bucket with 1–3 trades produces unreliable win-rate estimates that dominate the error |
| **MCC (Matthews Correlation Coefficient)** | ≥ 30 total trades with representation in all 4 quadrants (TP, FP, TN, FN) | MCC = 0 when any quadrant is zero; the denominator contains a product of all four marginals |
| **Rolling 30-day trend direction** | ≥ 10 trades in each of the "old" and "new" halves of the rolling window | Trend with n < 5 in either half returns `Stable` by design |
| **Overconfidence / underconfidence score** | ≥ 3 occupied buckets | Percentage-of-buckets statistics with only 1–2 buckets are binary and misleading |
| **Precision / Recall split** | ≥ 20 signals in positive class (high confidence) | Precision from 3–5 FPs swings ±25 pp per trade |
| **F1 Score** | Same as precision/recall — ≥ 20 high-confidence signals | Harmonic mean amplifies instability from either metric |
| **Monthly accuracy trend** | ≥ 3 calendar months | One month's data cannot show improvement vs. decline |
| **Consistency score (stdev of daily accuracies)** | ≥ 5 distinct trading days | Stdev from 2 days is uninformative; anything < 2 days returns 50.0 (neutral) |

All `get_*` functions remain usable below these thresholds — they return mathematically correct values from available data. The table describes when results should be treated as **statistically meaningful** by operators reviewing the dashboard.

---

## Test results

**32/32 passing (0.65 s)**

| Test class | Tests | Covers |
|---|---|---|
| `TestFeatureFlag` | 2 | Disabled flag blocks all 6 endpoints + shared services |
| `TestZeroSignals` | 3 | Empty trade store → graceful zeros everywhere |
| `TestOneSignal` | 2 | Single winner / single loser |
| `TestHighConfidencePredictions` | 2 | High-confidence winners = TP; high-confidence losers = FP |
| `TestLowConfidencePredictions` | 2 | Low-confidence losers = TN; low-confidence winners = FN |
| `TestPrecisionRecall` | 4 | Known values; balanced accuracy; perfect MCC; full API response |
| `TestCalibrationCalculations` | 3 | Perfect calibration; overconfident model; API response structure |
| `TestAIHealthScore` | 4 | Score in range; all 6 components present; zero-trades; label mapping |
| `TestRecommendationAnalysis` | 2 | Success %; accepted vs flagged win rates |
| `TestLearningAnalysis` | 2 | API structure; trend detection |
| `TestSharedServiceReuse` | 2 | 5D.3 reuse verified; `get_ai_snapshot()` keys for 5D.5 |
| `TestAPIResponses` | 2 | All endpoints return ENABLED; confidence endpoint structure |
| `TestMultipleSignals` | 1 | All 5 confidence buckets correctly assigned |
| `TestRestartPersistence` | 1 | Two sequential calls return identical results |

---

## Dashboard tabs

1. **Overview** — Health gauge (SVG ring), 5 KPI cards, health component bar chart, confidence win-rate chart, calibration curve, rolling-30d line chart
2. **Predictions** — Confusion matrix (colour-coded 2×2), all 9 classification metrics, methodology note
3. **Calibration** — 5 calibration KPIs, predicted vs actual grouped bar chart, detail table with well-calibrated/acceptable/poorly-calibrated status
4. **Confidence** — Distribution count chart, vs-regime and vs-sector charts, detail table
5. **Learning** — Trend KPIs, daily accuracy line chart, monthly accuracy bar chart
6. **Recommendations** — 4 headline metrics, per-recommendation table with accepted/flagged/neutral category badges

---

## Issues & known gaps

| # | Area | Description | Severity | Resolution path |
|---|---|---|---|---|
| 1 | Feature flag off by default | `AI_PERFORMANCE_ENABLED` shows disabled banner until set | Low — intentional | Set `AI_PERFORMANCE_ENABLED=true` in environment secrets |
| 2 | `signal_confidence=0` for old trades | Trades created before confidence was stored show 0.0, which buckets into "Below 60" and classifies as TN/FN | Low | Resolved naturally as new trades are recorded; historical data is sparse by design |
| 3 | `ignored_signals` always 0 | The trade store only has executed signals; unexecuted signals aren't stored, so `ignored_signals` and `recommendation_acceptance_rate` can't be computed | Medium | Requires a new `signals_log` table (separate from `paper_trades`) that persists every AI signal before execution decision — future work |
| 4 | TN/FN interpretability caveat | Lower-confidence trades that still executed provide the negative class — this isn't a "truly unexecuted" signal, it's just lower confidence. Operators should understand the classification threshold is confidence-based, not execution-based | Medium | Methodology note on the Predictions tab explains this; add tooltip in a future UI polish pass |
| 5 | Consistency score degrades with high day-count | `stdev × 2` penalty can push consistency below 0 if daily accuracy is extremely volatile; clamped at 0 | Low — already handled via `max(0, ...)` | No action needed |
| 6 | Rolling 30-day window does a full O(n×d) scan | For large trade histories (thousands of trades), the nested loop in `_rolling_30d` is O(n × unique_dates). At 500 trades this is ~2–3 ms — acceptable now. | Medium | Refactor to a sliding sorted list when trade count exceeds 1000 |
| 7 | `Brain` icon was already imported in AppLayout | TypeScript caught a duplicate identifier; fixed before ship | Cosmetic — fixed | Noted to avoid re-introducing the duplicate |
| 8 | `avg_pnl` missing from `RecResponse` TypeScript interface | TypeScript strict mode caught missing field; added before ship | Cosmetic — fixed | Already resolved |

---

## What to enable before using in a live session

1. `AI_PERFORMANCE_ENABLED=true` — in environment secrets
2. `STRATEGY_INTELLIGENCE_ENABLED=true` — required; AI module reads from 5D.3's shared services
3. Minimum ~10 closed round-trip trades with `signal_confidence` > 0 before classification metrics are meaningful
4. Minimum ~3 trading days before trend direction and consistency scores are meaningful

---

## Dependencies for downstream phases

| Phase | What it needs from 5D.4 |
|---|---|
| **5D.5 Executive Dashboard** | `get_ai_snapshot()` — single-call flat dict with health score, accuracy, calibration ECE, confidence, and trend for the AI performance tile |
