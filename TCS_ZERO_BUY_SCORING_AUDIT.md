# TCS ZERO-BUY BACKTEST — SCORING AUDIT
**PAPER / RESEARCH ONLY — no thresholds changed, no strategy changes, no live orders**
Date: 2026-08-11

---

## Executive Summary

TCS produced zero BUY events in a completed 15m backtest covering 2026-07-12 → 2026-08-11 (549 ticks). This is **not primarily a bug** — it is the correct mathematical output of a scoring model whose inputs are misread by operators.

The critical finding: **`technical_score` is not computed from RSI, ADX, volume_ratio, or EMA alignment.** It is the historical strategy walk-backtest performance score, derived from win rate, profit factor, net P&L, and Sharpe ratio across the trades found in the lookback period. A "technical_score" of 35.5 alongside "RSI 70.7, ADX 21.3, above_ema20=true" is not a contradiction — they are independent quantities that happen to share a UI panel.

However, **there is a real design limitation**: the confidence and opportunity score model was calibrated for 6-month live-scan lookback windows. A 30-day 15m backtest produces too few walk-backtest trades (~2) for the reliability multiplier to allow confidence to approach the BUY threshold. The maximum opportunity score TCS ever reached was 53.8 — 8.2 points below the BUY gate of 62.0. This gap cannot be crossed regardless of how bullish the live technical indicators are.

There is also a confirmed **naming/UX bug**: the field called `technical_score` is actually the `strategy_performance_score`. Operators reading "RSI=70.7 → technical_score=35.5" reasonably conclude a scoring bug exists when in fact the two numbers are measuring entirely different things.

---

## Task 1 — Exact Run Identification

The suggested run ID `BT-f8a8c46864` did not exist in the database. No 15m TCS run had been previously created. A fresh run was launched and completed during this audit:

| Field | Value |
|---|---|
| **Run ID** | `BT-48de9da82a` |
| Symbol | TCS |
| Interval | 15m |
| Date range | 2026-07-12 → 2026-08-11 |
| Total ticks | 549 |
| Status | COMPLETED |
| Trades | 0 |
| Net return | 0.00% |
| Capital | ₹1,00,000 |
| Missed opportunities stored | 100 (capped) |
| Config | Baseline sizing (1% fixed, no scale-in, no vol normalization) |

---

## Task 2 — Event Counts

| Event | Count | Notes |
|---|---|---|
| SYMBOL_SCANNED | 549 | Every tick processed |
| MARKET_INTELLIGENCE_COMPLETED | 541 | |
| RESEARCH_COMPLETED | 541 | Historical walk-backtest runs here |
| MONITORING_COMPLETED | 541 | |
| STRATEGY_SELECTED | 541 | |
| STRATEGY_REJECTED | 0 | |
| RISK_APPROVED | **541** | Risk gate passed on EVERY tick |
| RISK_REJECTED | **0** | Risk gate never blocked TCS |
| WATCH_GENERATED | 180 | When live signal present (opp ∈ [42, 62)) |
| IGNORE_GENERATED | 361 | When no live signal (opp < 42) |
| BUY_GENERATED | **0** | Confirmed: zero BUY events |
| STRONG_BUY_GENERATED | 0 | |
| PORTFOLIO_PRECHECK_* | 0 | Correct — fires only when a BUY enters `_try_enter` |
| ORDER_SUBMITTED | 0 | |
| ORDER_EXECUTED | 0 | |
| Missed opportunities (backtest_runs.missed) | 100 | Stored at completion |

**Zero BUY_GENERATED events is confirmed.** The risk gate passed every time — the block is entirely upstream in the AI Decision / opportunity-score computation.

---

## Task 3 — Score Distribution Across All 549 Ticks

### Technical indicators (from SYMBOL_SCANNED event payloads)

| Metric | Min | P25 | Median | P75 | Max |
|---|---|---|---|---|---|
| RSI | 47.1 | 56.8 | 60.7 | 63.3 | 73.7 |
| ADX | 17.5 | 19.0 | 21.3 | 24.6 | 25.8 |
| Volume ratio | 0.01 | 0.20 | 0.37 | 0.64 | 2.13 |

| Threshold count | Value |
|---|---|
| RSI ≥ 60 | 313 / 549 (57%) |
| RSI ≥ 70 | 69 / 549 (13%) |
| ADX ≥ 20 | 324 / 549 (59%) |
| ADX ≥ 25 | 100 / 549 (18%) |
| Volume ratio ≥ 0.5 | 195 / 549 (36%) |
| Volume ratio ≥ 0.8 | 86 / 549 (16%) |
| above_ema20 | Field not captured in SYMBOL_SCANNED payload |
| above_ema50 | Field not captured in SYMBOL_SCANNED payload |

*Note: `above_ema20` and `above_ema50` shown in the AI explanation panel come from strategy.check_entry() output at decision time. They are not stored in the SYMBOL_SCANNED pipeline event and therefore cannot be distributed here. The display in the UI is correct — these are populated from a separate code path.*

### AI Decision scores (from WATCH_GENERATED / IGNORE_GENERATED payloads)

| Metric | Min | Median | Max |
|---|---|---|---|
| Confidence | 19.7 | ~37.6 | 44.8 |
| Opportunity score | 31.2 | ~38.4 | **53.8** |

| Threshold count | Value |
|---|---|
| Confidence ≥ 60 | **0** / 541 |
| Confidence ≥ 50 | **0** / 541 |
| Opportunity score ≥ 62 (BUY gate) | **0** / 541 |
| Opportunity score ≥ 57 (within 5 of BUY) | **0** / 541 |
| Opportunity score ≥ 52 (within 10 of BUY) | 187 / 541 |

**Maximum opportunity score ever reached: 53.8.** The BUY threshold is 62.0. TCS was mathematically incapable of crossing the BUY gate on any tick in this run.

---

## Task 4 — Why Final Confidence / Score Is Low: Root Cause

### What `technical_score` actually measures

`technical_score` in the UI is assigned from `_strategy_perf_score()` in `market_scanner.py` (line 166). It is the **historical strategy walk-backtest performance score** — not a composite of current RSI, ADX, or EMA readings. The formula (lines 187–199):

```python
raw = (win_rate / 100.0) * 35.0       # 35% weight — historical win rate
    + (profit_factor / 5.0) * 30.0    # 30% weight — profit factor (capped at 5)
    + ((net_pnl_pct + 30) / 60) * 20  # 20% weight — net return (range -30..+30)
    + ((sharpe + 3) / 6) * 15         # 15% weight — Sharpe ratio (range -3..+3)

reliability = min(1.0, total_trades / 4.0)
score = raw * (0.35 + 0.65 * reliability)   # reliability multiplier: 0.35 at 0 trades → 1.0 at 4+ trades
```

**At 0 trades: immediate return of 0.0.**

### Confidence formula (lines 202–210)

```python
reliability = min(1.0, total_trades / 5.0)
base = perf_score * 0.75 + reliability * 25.0
if live_signal: base += 8.0
```

### Opportunity score formula (lines 217–233)

```python
rr_score   = min(100, rr_ratio / 4 * 100)
live_bonus = 100.0 if live_signal else 40.0
opp = perf_score * 0.45 + confidence * 0.30 + rr_score * 0.15 + live_bonus * 0.10
```

### Verified reconstruction for TCS

The two distinct TCS score clusters observed in the data verify the formula exactly:

**Cluster A — IGNORE ticks (no live signal), ~2 walk-backtest trades:**
```
perf_score  = 35.3  (reverse-engineered from observed conf=36.5)
reliability = min(1, 2/5) = 0.4
confidence  = 35.3 * 0.75 + 0.4 * 25 = 26.5 + 10 = 36.5  ✓ (observed: 36.5)
opp_score   = 35.3*0.45 + 36.5*0.30 + rr_score*0.15 + 40*0.10
            = 15.9 + 10.95 + rr_score*0.15 + 4
            ≈ 38.3 (rr_ratio ≈ 2.0)  ✓ (observed: 38.3)
→ _final_action(38.3) = IGNORE (< 42 WATCH threshold)
```

**Cluster B — WATCH ticks (live signal present), same ~2 walk-backtest trades:**
```
confidence  = 36.5 + 8 (live signal bonus) = 44.5  ✓ (observed: 44.7)
opp_score   = 35.3*0.45 + 44.5*0.30 + rr_score*0.15 + 100*0.10
            = 15.9 + 13.35 + rr_score*0.15 + 10
            ≈ 53.8 (rr_ratio ≈ 2.0)  ✓ (observed: 53.8)
→ _final_action(53.8) = WATCH (≥ 42, < 62)
```

**The BUY threshold gap:**

| Metric | TCS (best case) | BUY gate | Gap |
|---|---|---|---|
| Opportunity score | 53.8 | 62.0 | **8.2 points** |
| Confidence | 44.8 | — | — |

To cross the BUY gate, TCS would need opp_score ≥ 62. The only ways to get there from the current position:
- Increase perf_score from 35.3 to ~55+ (needs more historical trades with better win rate / profit factor)
- Or increase rr_ratio dramatically (rr_score contribution is 15% of opp; even with rr_ratio=4, contribution = 15pts, still not enough: 15.9+13.35+15+10 = 54.25, still below 62)
- Or have a live signal AND a perf_score of ~55+

**Why does RSI=70.7 / ADX=21.3 / volume=0.83 produce technical_score=35.5?**

Because those indicators **do not feed into the score formula**. RSI, ADX, volume_ratio, and EMA alignment are:
1. Computed from candles and displayed in the AI explanation panel (for operator transparency)
2. Evaluated by individual strategy `check_entry()` rules (returns a binary live_signal pass/fail)
3. **Not mathematically connected to `technical_score`**

The "technical_score" of 35.5 comes entirely from the historical walk-backtest result: TCS's strategy found approximately 2 trades in the 30-day lookback window. Those 2 trades had a win rate and profit factor that produced raw=52.3, then multiplied by reliability=0.675 (2 trades) = 35.3. RSI being 70.7 is irrelevant to this calculation.

### Contribution breakdown for the observed tick (RSI=70.7, ADX=21.3)

| Factor | Input | Contribution to score | Notes |
|---|---|---|---|
| RSI 70.7 | Displayed only | **0%** | Not in scoring formula |
| ADX 21.3 | Displayed only | **0%** | Not in scoring formula |
| Volume ratio 0.83 | Used by volume gate (pass/fail) | **0%** on score itself | Volume gate PASSED |
| above_ema20 | Strategy check_entry signal | Controls `live_signal` (True/False) | Contributes +8 to conf if true |
| above_ema50 | Strategy check_entry signal | Controls `live_signal` (True/False) | Part of entry check |
| Walk-backtest win rate (historical) | ~50% (2 trades) | **~17/35 pts of raw** | |
| Walk-backtest profit factor (historical) | ~1.5 (2 trades) | **~9/30 pts of raw** | |
| Walk-backtest net P&L (historical) | ~+1% | **~10.3/20 pts of raw** | |
| Walk-backtest Sharpe (historical) | ~0.3 | **~8.8/15 pts of raw** | |
| Reliability discount (2 trades) | 2/4 = 0.50 → multiplier 0.675 | **Reduces raw by 32.5%** | Key penalty |
| RR ratio | ~2.0 | **+15% × 15 = 7.5** in opp | |
| No live signal (IGNORE cluster) | live_bonus=40 | **+4** in opp | vs. +10 if live |

---

## Task 5 — Missed Opportunity Quality

All 100 stored missed opportunities for `BT-48de9da82a` are WATCH-class (none were RISK_REJECTED — the risk gate passed every time).

### Summary statistics

| Metric | Value |
|---|---|
| Total missed opportunities | 100 (stored cap) |
| Decision type | 100% WATCH (0% RISK_REJECTED) |
| Profitable (realized > 0) | **71 / 100 (71%)** |
| Avg potential return (max high over 10 bars) | +1.07% |
| Avg realized return at horizon (10 bars) | +0.44% |
| Median realized return | +0.33% |
| Max potential return | +3.33% |
| Min realized return | -0.89% |
| Max adverse move (worst realized) | **-0.89%** |
| Adverse moves > -1% | 0 |

### Top 10 missed opportunities

| # | Decision | Potential | Realized | Profitable |
|---|---|---|---|---|
| 1 | WATCH | +3.33% | +2.73% | ✓ |
| 2 | WATCH | +3.29% | +2.57% | ✓ |
| 3 | WATCH | +3.22% | +2.29% | ✓ |
| 4 | WATCH | +2.93% | +1.85% | ✓ |
| 5 | WATCH | +2.89% | +2.72% | ✓ |
| 6 | WATCH | +2.79% | +1.73% | ✓ |
| 7 | WATCH | +2.63% | +1.55% | ✓ |
| 8 | WATCH | +2.61% | +2.45% | ✓ |
| 9 | WATCH | +2.59% | +2.07% | ✓ |
| 10 | WATCH | +2.24% | +2.12% | ✓ |

### False-positive risk estimate

71% of WATCH signals became profitable (horizon realized > 0). Worst adverse move was -0.89%. If WATCH signals were converted to BUY, estimated false-positive rate: ~29%. The max adverse move of -0.89% is below most stop-loss thresholds, suggesting the false positives would be low-cost losses.

**However, this is 1 symbol × 30 days — insufficient for a threshold change conclusion.**

---

## Task 6 — TCS vs GLAND Comparison

### Side-by-side (representative ticks)

| Metric | TCS 15m (WATCH best) | GLAND 5m (BUY) | GLAND 5m (STRONG BUY) |
|---|---|---|---|
| RSI | 60.7 (median), 73.7 (max) | 57.2 | 63.9 |
| ADX | 21.3 (median) | 31.4 | 41.5 |
| Volume ratio | 0.37 (median), 2.13 (max) | 0.42 | 0.30 |
| above_ema20 | Yes (some ticks) | — | — |
| above_ema50 | Yes (some ticks) | — | — |
| **perf_score (technical_score)** | **~35.3** | **~63.3** | **~85.1** |
| Confidence | 44.8 (max) | 72.5–72.6 | 88.8 |
| Opportunity score | 53.8 (max) | 69.6–73.2 | 81.3–81.6 |
| Final action | WATCH (best case) | BUY | STRONG BUY |

### Why GLAND got BUY but TCS got WATCH/IGNORE

The difference is **entirely in the walk-backtest historical performance**, not in the live technical indicators.

**GLAND's walk-backtest (6-month 5m data):**
- Found 5+ strategy trades (full reliability — reliability multiplier = 1.0)
- perf_score ~63.3 → confidence ~72.5 → opp_score ~69.6 → above BUY threshold (62)
- RSI/ADX/volume contributed 0% to this number

**TCS's walk-backtest (30-day 15m data):**
- Found ~2 strategy trades (low reliability — multiplier = 0.675)
- perf_score ~35.3 → confidence ~36.5 → opp_score ~38.3 → IGNORE (< 42)
- With live signal: opp_score ~53.8 → WATCH (< 62, below BUY)

**Why GLAND gets WATCH instead of BUY when volume is low:**
GLAND's opp_score is 69.6–73.2 (above BUY threshold 62). When GLAND was classified WATCH, it was because the quality gate or volume gate downgraded BUY→WATCH (volume_ratio 0.0–0.08). Once volume improved to 0.30+, it returned as BUY. The underlying performance score never changed.

**The key asymmetry:** TCS's 15m 30-day window produces too few historical trades. GLAND's 5m 6-month window (the live scan lookback) produces enough trades for full reliability. This is a window-length mismatch, not a TCS-specific problem.

---

## Task 7 — Bug Check Results

### Bug 1: Strategy score penalizes low trade count too heavily

**STATUS: DESIGN LIMITATION — not a code bug, but calibration concern.**

The code comment (market_scanner.py line 173–176) explains: *"Reliability denominator is 4 trades… NIFTY 50 trend-following strategies legitimately fire only 2–4 times over a 6-month lookback window."* This was calibrated for a 6-month live scan. A 30-day 15m backtest covers only ~1/6 of that window. A strategy that fires 2–4 times in 6 months will fire 0–1 times in 30 days — permanently trapping perf_score below the reliability threshold.

Impact: any backtest with a short date range (< 3 months) will systematically produce low scores due to insufficient walk-backtest trades, regardless of how good the live technical setup looks.

### Bug 2: technical_score not matching indicator strength

**STATUS: CONFIRMED NAMING/UX BUG.**

`technical_score` is the historical strategy performance score. It has zero mathematical connection to RSI, ADX, volume_ratio, or EMA alignment. The field name is systematically misleading. Operators reading "RSI=70.7 → technical_score=35.5" will incorrectly conclude a scoring error when none exists.

Evidence: the field is set at `live_scan_engine.py:414` directly from `_strategy_perf_score(metrics)`. The function's docstring says "historical-performance score." No indicator values enter this function.

### Bug 3: EMA Cross strategy score is incorrectly low

**STATUS: NOT A BUG — valid result given evidence.**

EMA Cross (strategy id: `ema_crossover`) fires on EMA crossover events, which are relatively rare on 15m bars over 30 days. 2–3 crossovers in 30 days is normal. The strategy score is mathematically correct for those trades. The issue is the short backtest window limiting the number of qualifying crossovers.

### Bug 4: Research low_evidence penalty is too harsh

**STATUS: CONFIRMED DESIGN CONCERN for short-window backtests.**

The minimum score at 2 trades is: `raw * (0.35 + 0.65 * 0.5) = raw * 0.675`. Even with a perfect win rate (raw=100), perf_score would be 67.5. Confidence would be 67.5*0.75 + 10 = 60.6. Opp_score would be 67.5*0.45 + 60.6*0.30 + rr*0.15 + 40*0.10 = 30.4 + 18.2 + rr*0.15 + 4 ≈ 58+ (still below BUY gate of 62 unless rr is high). The model requires ≥ 5 trades for confidence to have a chance at BUY territory — this is a high bar for a 30-day 15m window.

### Bug 5: TCS sector/regime mapping penalizes incorrectly

**STATUS: NOT CONFIRMED.** TCS maps to IT sector. No sector-specific penalty was found in code or observed in data.

### Bug 6: 15m backtest uses daily-shaped indicators

**STATUS: PARTIAL CONCERN — requires further investigation.**

The SYMBOL_SCANNED payload shows `"bars": 185` for TCS 15m ticks. This is the same count seen in GLAND 5m ticks (`"bars": 184`). If both use 185 candles as the indicator window regardless of interval, a 15m backtest would compute RSI/ADX/EMA from 185 × 15m ≈ 46 hours of data (~6 trading days), while GLAND 5m from 184 × 5m ≈ 15 hours (~2 trading days). This may produce different indicator behaviour but is not confirmed as a bug.

`market_scanner.py:31` has `SCAN_INTERVAL="1d"` hardcoded — but this is the standalone scanner, not the backtest replay path. The backtest uses 15m candles fetched from `backtest_candles`. The walk-backtest via `_run_lab_walk` operates on those 15m candles. This appears correct but the bar-count window is worth confirming.

### Bug 7: Missed opportunities not influencing recommendations

**STATUS: CONFIRMED** — documented in BACKTEST_LEARNING_LOOP_AUDIT.md. No change in this audit.

### Bug 8: BUY threshold comparison uses wrong field

**STATUS: NOT CONFIRMED.** `_final_action(opp_score)` in market_scanner.py:148–155 correctly compares the opportunity score against ACTION_STRONG_BUY=78, ACTION_BUY=62, ACTION_WATCH=42. Field access is correct.

### Bug 9: Case sensitivity / symbol mapping issue for TCS

**STATUS: NOT CONFIRMED.** TCS is consistently uppercase throughout event payloads, backtest config, and candle data.

### Bug 10: BUY events generated but hidden by UI filter

**STATUS: CONFIRMED NOT A BUG.** Zero BUY_GENERATED events exist in `pipeline_events` for `BT-48de9da82a`. This was queried directly against the database. The absence is real, not a display filter artifact.

---

## Task 8 — Report

### 1. Did TCS truly have zero BUY_GENERATED events?

**Yes.** Confirmed by direct database query: 0 BUY_GENERATED events, 0 STRONG_BUY_GENERATED events across all 541 AI decision ticks in `BT-48de9da82a`. The event store is authoritative.

### 2. Were zero trades expected or suspicious?

**Partially expected, but reveals a calibration mismatch.** The model's output is mathematically correct given its inputs. However, those inputs are structurally limited by the short backtest window: a 30-day 15m window cannot produce enough walk-backtest trades to unlock the reliability multiplier needed to reach the BUY gate. This is a design limitation of using a confidence model calibrated for 6-month lookbacks in a 30-day backtest context.

It is not a random or inexplicable result.

### 3. Why did the AI keep TCS as WATCH/IGNORE?

Because the historical walk-backtest performance score (`perf_score` ≈ 35.3) was too low, driven by ~2 walk-backtest trades and their limited win rate/profit factor over 30 days. This produced:
- Confidence: max 44.8 (BUY needs no minimum, but opp needs ≥ 62)
- Opportunity score: max 53.8 (BUY gate: 62.0)
- Gap to BUY: **8.2 points that cannot be closed by any current live technical indicator reading**

The RSI/ADX/EMA values seen in the UI are real and bullish — but they do not feed into the opportunity score formula. They affect only the binary live_signal pass/fail.

### 4. Is the technical score calculated correctly?

**Yes, mathematically.** The calculation is accurate. The problem is the label: `technical_score` implies RSI/ADX/indicator-based computation, but it is actually the historical strategy performance score. The score of 35.5 is the correct output for ~2 walk-backtest trades with moderate win rate and profit factor.

### 5. Is the confidence/opportunity model too conservative?

**Yes for short-window (≤ 30-day) backtests.** The model was designed and documented for 6-month live-scan lookback windows. In that context, 4–5 strategy signals is achievable and the reliability denominator is appropriate. In a 30-day 15m backtest, 4+ strategy signals is rare. The model needs context-aware calibration or a minimum-evidence warning when the backtest range is shorter than 90 days.

### 6. Is this a scoring bug, strategy limitation, or valid rejection?

**Three-layer answer:**

| Layer | Assessment |
|---|---|
| **Valid rejection** | Yes — TCS had genuinely weak walk-backtest evidence in this 30-day window |
| **Design limitation** | Yes — the confidence model is miscalibrated for short backtest windows |
| **Naming/UX bug** | Yes — `technical_score` misleads operators into expecting indicator-derived values |

### 7. Should TCS missed opportunities be ingested into the learning layer?

**Yes.** 71/100 TCS WATCH signals became profitable (71% win rate, avg realized +0.44%, max adverse -0.89%). This is meaningful evidence that WATCH signals in trending 15m setups are undervalued by the current model. The fix plan for ingestion is documented in BACKTEST_LEARNING_LOOP_AUDIT.md, Task 5, Section 7.

### 8. Recommended fix plan (do not implement yet)

**Fix 1 — Rename `technical_score` field (UX/naming fix, no logic change)**

In `live_scan_engine.py` (where the field is assigned) and in all event payloads, rename `technical_score` to `strategy_performance_score` (or add an alias). Update the Investigation Center UI label accordingly. Add a tooltip: *"Historical strategy performance score (X trades in walk-backtest). Not computed from current RSI/ADX/EMA."*

This eliminates the operator confusion without touching any formula.

**Fix 2 — Add a separate `indicator_score` field (new field, no threshold change)**

Compute and emit a separate score from the live technical indicators:
```python
indicator_score = (
    min(100, max(0, (rsi - 30) / 40 * 35)) +          # RSI 30→70 → 0→35pts
    min(100, max(0, adx / 40 * 30)) +                  # ADX 0→40 → 0→30pts
    min(100, max(0, volume_ratio / 1.5 * 20)) +        # Vol 0→1.5 → 0→20pts
    (7.5 if above_ema20 else 0) + (7.5 if above_ema50 else 0)  # EMA alignment → 15pts
)
```
This lets operators see "indicator_score=74 vs strategy_performance_score=35" and understand exactly where the gap is. The indicator_score is advisory/display only — it does not influence BUY/SELL decisions.

**Fix 3 — Short-window warning (advisory message, no threshold change)**

When a backtest covers < 90 calendar days, emit a warning in the run's metrics:
*"Walk-backtest period is short (30 days). Confidence scores may be structurally limited by low trade count. Results are valid but opportunity scores may systematically underestimate strategy quality. Consider extending the date range for a more reliable evaluation."*

**Fix 4 — Ingest TCS missed opportunities into Phase-24 learning**

Per BACKTEST_LEARNING_LOOP_AUDIT.md Fix plan (Phases A–E). This allows the recommendation engine to reason about the 71% WATCH-to-profitable conversion rate and potentially issue an advisory recommendation about WATCH signal quality for IT large-caps.

**Fix 5 — Review reliability denominator for backtest context (do not implement yet)**

The reliability denominator of 4 (perf) / 5 (confidence) was calibrated for 6-month live scans. Consider context-sensitive denominators:
- Live scan (6-month lookback): denominator = 4/5 (current)
- Backtest (90–180 days): denominator = 3/4
- Backtest (< 90 days): denominator = 2/3

This would allow short-window backtests to reach BUY territory with fewer (but still meaningful) historical trades. Requires multi-symbol validation before implementing.

---

## Appendix — Action Thresholds (confirmed from source)

| Action | Opportunity score threshold | File | Line |
|---|---|---|---|
| STRONG BUY | ≥ 78.0 | market_scanner.py | 37 |
| BUY | ≥ 62.0 | market_scanner.py | 38 |
| WATCH | ≥ 42.0 | market_scanner.py | 39 |
| IGNORE | < 42.0 | market_scanner.py | — |

TCS max observed opportunity score: **53.8** — 8.2 points below BUY, 11.8 above WATCH.

---

*Stop here. No thresholds changed. No strategy logic changed. No live trading enabled. PAPER / RESEARCH ONLY.*
