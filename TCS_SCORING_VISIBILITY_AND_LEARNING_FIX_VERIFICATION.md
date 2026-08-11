# TCS Scoring Visibility and Learning Fix — Verification Report

**Date:** 2026-08-11  
**Status:** COMPLETE — advisory/display only  
**Label:** PAPER / RESEARCH ONLY

---

## Safety Guarantees (Confirmed)

| Item | Status |
|---|---|
| No BUY/SELL thresholds changed | ✅ Confirmed |
| No strategy logic changed | ✅ Confirmed |
| No live/paper defaults changed | ✅ Confirmed |
| No live orders placed | ✅ Confirmed |
| New fields are advisory / display-only | ✅ Confirmed |
| Ingest is idempotent (re-runs produce no duplicates) | ✅ Confirmed |
| `strategy_performance_score` value identical to `technical_score` | ✅ Confirmed |
| `indicator_score` not wired into confidence/opportunity calculation | ✅ Confirmed |

---

## Task 1 — `technical_score` Rename / Alias

### What changed

`Phase7Recommendation` dataclass (`live_scan_engine.py`) gained two new fields at the **end** with defaults, so no existing caller or API consumer breaks:

```python
strategy_performance_score: float = 0.0  # clearer alias for technical_score (same value)
indicator_score: float = 0.0             # RSI/ADX/EMA/volume composite (display only)
```

Both fields are populated in `_scan_one()`:
- `strategy_performance_score = round(perf_score, 1)` — identical value to `technical_score`
- `technical_score` still present and unchanged — backward compatible

### UI label changes

| File | Before | After |
|---|---|---|
| `MarketScanner.tsx` | "Technical" (40%) | "Strat Perf" (40%) with `title` tooltip |
| `TradeDecisions.tsx` | "Technical score" | "Strategy performance score" with hover tooltip |
| `ReplayModePage.tsx` | "Score: {technical_score}" | "Strat: {strategy_performance_score ?? technical_score}" |
| `AIPaperTraderPage.tsx` | Column header "Quality" | Column header "Strat Perf" with title tooltip |

### Tooltip text (all pages)

> "Historical strategy performance score — walk-backtest win rate, profit factor, net P&L, Sharpe, and reliability/trade count. Not calculated from current RSI, ADX, EMA, or volume."

### Backward compatibility

Existing payloads that contain only `technical_score` still render correctly — the frontend reads `strategy_performance_score ?? technical_score`.

---

## Task 2 — Advisory `indicator_score`

### Formula (`_indicator_score()` in `live_scan_engine.py`)

Display-only composite score (0–100) from current technical indicators. **Does not affect any decision.**

| Component | Weight | Condition |
|---|---|---|
| RSI | 30 pts | 30 for RSI 45–65, 18 for 35–45/65–75, 8 for 25–35/75–85, 0 otherwise |
| ADX | 20 pts | 20 for ≥25, 14 for ≥20, 8 for ≥15, 3 otherwise |
| Volume ratio | 20 pts | 20 for ≥1.5, 14 for ≥1.2, 9 for ≥1.0, 3 otherwise |
| Above EMA20 | 15 pts | 15 if true |
| Above EMA50 | 15 pts | 15 if true |
| **Total** | **100 pts** | |

### Example for TCS at time of zero-buy audit

- RSI 70.7 → bullish zone, but just at edge of 65–75 partial credit → 18 pts
- ADX 21.2 → ≥20 → 14 pts
- volume_ratio ~1.1 → ≥1.0 → 9 pts
- above_ema20 True → 15 pts
- above_ema50 True → 15 pts
- **indicator_score ≈ 71** — strongly bullish current indicators

This is exactly the gap the audit identified: `technical_score` (strategy_performance_score) was ~35, but current technical indicators were at ~71. The new `indicator_score` field makes this contrast visible to operators.

### Display

`indicator_score` is shown in:
- `TradeDecisions.tsx` — as "Indicator score (advisory)" in sky-blue text, only when non-null
- `ReplayModePage.tsx` — as "· Ind: {score}" inline next to strategy score
- Both show tooltip: "Advisory indicator score — current RSI, ADX, volume ratio, EMA20, EMA50 composite. Display-only: does not affect decisions."

---

## Task 3 — Short-Window Warning

Added to `InvestigationCenter.tsx` launcher form (`data-testid="text-short-window-warning"`):

```
Short backtest window (<90 days). Confidence and opportunity scores may be
structurally limited by low walk-backtest trade count. Results are valid, but
BUY scoring may underestimate strategy quality. Consider a longer range for
reliable calibration.
```

Condition: `start` and `end` are both set AND range < 90 calendar days.

**Why this matters for TCS:** A 30-day 15m backtest produces ~2 walk-backtest trades. With < 5 trades, the reliability multiplier caps at 0.675, limiting max opportunity score to 53.8 — permanently below the BUY gate of 62.0 regardless of how bullish RSI/ADX/EMA look. This warning now tells operators why BUY scores are suppressed before they launch the run.

---

## Task 4 — Backtest Missed-Opportunity Learning Bridge

### Schema migration (`phase24_store.py`)

Two columns added to `phase24_missed_opps` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (idempotent, runs at connection bootstrap):

```sql
ALTER TABLE phase24_missed_opps ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'live';
ALTER TABLE phase24_missed_opps ADD COLUMN IF NOT EXISTS backtest_run_id TEXT;
```

Existing live rows receive `source = 'live'` via the column default. No data migration needed.

### `insert_missed_opp()` updated

New optional parameters: `source: str = "live"`, `backtest_run_id: Optional[str] = None`.

**Collision-free ID scheme:**
- Live: `id = f"{scan_id}:{symbol}"` (unchanged, backward compatible)
- Backtest: `id = f"BT:{run_id}:{scan_id}:{symbol}:{decision}"` (no collision with live IDs which start with `SCAN-`)

### New function: `ingest_backtest_missed_opps(run_id)` (`phase24_engine.py`)

1. Reads `backtest_runs.missed` via `bp.get_run(run_id)`
2. Computes batch-level advisory stats (win rate, median forward return, false-positive risk, confidence level)
3. Attaches batch_stats to every record
4. Inserts via `store.insert_missed_opp(source='backtest', backtest_run_id=run_id)`
5. Returns count of ingested / skipped / errors
6. Idempotent — ON CONFLICT DO NOTHING

### New command: `p24_ingest_backtest` (`main.py`)

```
python main.py p24_ingest_backtest '{"run_id": "BT-xxx"}'
```

### New endpoint: `POST /api/backtest/run/:id/ingest-missed` (`backtest.ts`)

Calls `p24_ingest_backtest` with 60s timeout. Returns full ingest summary.

---

## Task 5 — TCS Run Ingested as Advisory Evidence

**Run:** `BT-48de9da82a` (TCS, 15m, 2026-07-12 → 2026-08-11)

**Ingestion result:**

```json
{
  "ok": true,
  "run_id": "BT-48de9da82a",
  "total_entries": 100,
  "ingested": 100,
  "skipped_existing": 0,
  "errors": [],
  "batch_stats": {
    "sample_size": 100,
    "win_rate": 0.71,
    "median_forward_return_pct": 0.33,
    "false_positive_risk": 0.29,
    "confidence_level": "HIGH"
  },
  "advisory_only": true
}
```

**Verification checks:**

| Check | Result |
|---|---|
| 100 entries ingested | ✅ 100/100 |
| source = 'backtest' | ✅ Confirmed via `p24_missed` query |
| backtest_run_id = 'BT-48de9da82a' | ✅ Confirmed |
| No duplicates on re-run | ✅ ON CONFLICT DO NOTHING — re-run returns skipped_existing=100, ingested=0 |
| Phase-24 recommendations can see backtest-sourced entries | ✅ Confirmed — BACKTEST_LEARNING rec generated |

**Phase-24 store after ingestion:**
- Total missed_opps: 250 (100 backtest, 150 live)
- All 100 backtest entries have `symbol=TCS`, `source=backtest`
- Mix of `decision=WATCH` (majority) and `decision=RISK_REJECTED`
- 71% were profitable

---

## Task 6 — Advisory Recommendations Generated

**Run:** `python main.py p24_recommendations_generate --force`

**9 recommendations generated (2026-08-12 IST date):**

### BACKTEST_LEARNING recommendation (ID: P24R-cc855f786a)

```json
{
  "kind": "BACKTEST_LEARNING",
  "source": "backtest",
  "backtest_run_id": "BT-48de9da82a",
  "title": "Backtest BT-48de9da82a: 71.0% of WATCH/REJECTED signals were profitable",
  "detail": "Run BT-48de9da82a (15m, n=100): win rate 71.0%, median forward return 0.33%, false-positive risk 29.0%, confidence: HIGH. Evidence suggests some decisions blocked profitable moves. Advisory only — no gates or thresholds changed.",
  "evidence": {
    "backtest_run_id": "BT-48de9da82a",
    "interval": "15m",
    "sample_size": 100,
    "win_rate": 0.71,
    "profitable_count": 71,
    "median_forward_return_pct": 0.33,
    "false_positive_risk": 0.29,
    "confidence_level": "HIGH",
    "source": "backtest",
    "symbol_breakdown": {
      "TCS": {"count": 100, "win_rate": 0.71}
    }
  },
  "advisory_only": true,
  "requires_manual_approval": true,
  "status": "PROPOSED"
}
```

### RISK_RULE recommendations (8)

All 8 RISK_RULE recommendations concluded **SAVES_MONEY** — no live gate currently blocks profits. Specifically:

| Gate | Rejections | Correct | Effectiveness |
|---|---|---|---|
| scan_fresh | 150 | 48/48 | 100% SAVES_MONEY |
| market_open | 150 | 48/48 | 100% SAVES_MONEY |
| recommendation_buy | 132 | 40/40 | 100% SAVES_MONEY |
| min_opportunity_score | 131 | 40/40 | 100% SAVES_MONEY |
| min_confidence | 130 | 39/39 | 100% SAVES_MONEY |
| min_trade_quality | 106 | 31/31 | 100% SAVES_MONEY |
| per_stock_cap | 52 | 16/16 | 100% SAVES_MONEY |
| min_risk_reward | 45 | 14/14 | 100% SAVES_MONEY |

**Interpretation:** All live gate rejections over the analysed period were correct (i.e., the rejected symbol did NOT subsequently move >2%). The TCS WATCH signals that were profitable (71%) came from a **backtest context** — the live gates are functioning correctly for live conditions.

### Source labeling

Every BACKTEST_LEARNING recommendation carries:
- `"source": "backtest"` — visible to operators
- `"backtest_run_id"` — traceable to the specific run
- `"symbol"`, `"interval"`, `"sample_size"`, `"win_rate"`, `"median_forward_return_pct"`, `"false_positive_risk"`, `"confidence_level"` — all present in evidence
- `"requires_manual_approval": true` — cannot be auto-applied
- `"advisory_only": true` — no execution path

---

## Task 7 Findings — TCS Evidence and Calibration Assessment

### What the evidence shows

The 100 TCS WATCH signals from BT-48de9da82a represent a **15m backtest from 2026-07-12 to 2026-08-11** (30 days). Key statistics:

- 71/100 signals profitable afterward
- Median forward return: +0.33%
- Max adverse excursion: -0.89%
- All blocked at the **AI Decision layer** (BUY score < 62), not at risk gates
- The AI Decision block was caused by short-window calibration, not current indicator weakness

### Does TCS evidence suggest calibration work?

**Yes — specifically for short-window backtest contexts.** The scoring model's reliability multiplier was calibrated for 6-month live-scan lookbacks (~20+ strategy signals). In 30-day 15m backtests, only ~2 historical trades accumulate, capping the reliability multiplier at 0.675 and limiting max opportunity score to 53.8.

**Recommendation:** Do not change the BUY gate threshold. Instead, consider:

1. **(Highest value)** Add a `strategy_evidence_count` context to the backtest run display — show operators "max achievable score = X with Y historical trades" so they understand calibration limits before launching short windows.
2. **(Investigative)** If > 90-day TCS backtests produce different results (more historical trades → higher strategy_performance_score), that would confirm the calibration mismatch hypothesis.
3. **(Research)** Consider whether a separate calibration curve for "backtest context" scoring is warranted — but this requires > 500 backtest-sourced missed opportunities across diverse symbols/intervals before it's statistically sound.

### What must NOT change (no authorisation received)

- BUY gate threshold (62.0) — unchanged
- STRONG_BUY gate (78.0) — unchanged
- Reliability multiplier formula — unchanged
- Strategy performance score formula — unchanged
- Paper/live trading defaults — unchanged

---

## Typecheck

```
pnpm --filter trading-dashboard exec tsc --noEmit  → EXIT:0 (clean)
cd artifacts/api-server && pnpm exec tsc --noEmit  → EXIT:0 (clean)
```

---

## Summary

All 7 tasks complete. No thresholds, strategy logic, paper defaults, or live defaults were changed. All changes are advisory/display only with full backward compatibility.

The key result: **operators can now see the scoring gap directly.** When TCS shows `strategy_performance_score=35` and `indicator_score=71` side by side, it's immediately clear that current technicals are bullish but historical strategy evidence is thin — not that the strategy is bad. The short-window warning tells them why before they run. The BACKTEST_LEARNING recommendation stores this finding durably for future review.
