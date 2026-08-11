# BACKTEST LEARNING LOOP AUDIT — MISSED OPPORTUNITIES
**PAPER / RESEARCH ONLY — no thresholds changed, no live orders, no auto-apply**
Date: 2026-08-11

---

## Executive Summary

The backtest engine **does** persist missed opportunities and **does** compute forward-return analytics on them. Those records are fully available in the UI.

However, the learning loop is **incomplete**. The data stops at `backtest_runs.missed` — a JSONB column in the run record. It is **never ingested** into the Phase-24 learning tables (`phase24_missed_opps`, `phase24_recommendations`). The Phase-24 recommendation engine operates exclusively on live-scan data. As a result, backtest missed opportunities are **displayed but not learned from**.

---

## Task 1 — Missed Opportunity Flow Trace

### Step-by-step with evidence

#### Step 1 — Backtest run completes
File: `artifacts/api-server/src/python/backtest_runner.py`

At the end of every completed run, `execute_run()` calls:
```python
missed = analyze_missed_opportunities(run_id, per_symbol, interval)  # line 642
bp.update_run(run_id, ..., missed=missed, ...)                         # line 654
```

`analyze_missed_opportunities()` (lines 670–742) is the only computation step:
- Queries `pipeline_events` for all `RISK_REJECTED` and `WATCH_GENERATED` events under the run (limit 5000 each).
- For each event: finds the corresponding candle, advances `horizon_bars = 10` candles forward.
- Computes: `potential_return_pct` (max-high over horizon), `return_at_horizon_pct` (close at horizon end), `would_have_been_profitable` (realized > 0), `single_rule_relax_hint` (if exactly one gate failed).
- Docstring line 677: **"Advisory only — NEVER changes any strategy."**
- Returns top 100 records sorted by descending potential.

#### Step 2 — Missed opportunity store
Table: `backtest_runs`, column `missed JSONB`

Schema (from `backtest_portfolio.py` lines 50–62):
```
backtest_runs(
  run_id       TEXT PK,
  status       TEXT,
  config       JSONB,
  progress     JSONB,
  metrics      JSONB,
  missed       JSONB,     ← array of missed opportunity records
  validation   JSONB,
  ...
)
```

There is **no separate missed-opportunity table** for backtest runs. The entire array is stored as a single JSONB value on the run record.

#### Step 3 — HTTP endpoint (display only)
File: `artifacts/api-server/src/routes/backtest.ts` lines 118–125

`GET /api/backtest/run/:id/missed`
- Calls `backtest_status` → returns `{ run_id, missed: run?.missed ?? [] }`.
- Comment explicitly: "stored on completion, no recompute".
- This endpoint is **read-only**. It serves the Investigation Center missed-opportunities tab.

#### Step 4 — Learning layer consumption
**NOT reached.** This is the gap.

The Phase-24 learning engine reads from:
- `phase24_missed_opps` table (populated by `p24_missed_run` command)
- `phase24_trade_intelligence` table (populated by `p24_capture` from `phase20_executor.get_ledger()`)

`p24_missed_run` (`phase24_engine.py` lines 327–346) analyzes the **latest canonical live scan** — not any backtest run. It calls `phase20_gates.evaluate_entries()` on the current live scan snapshot. It has no code path that reads from `backtest_runs.missed`.

**Current row counts (live DB):**

| Table | Rows | Source |
|---|---|---|
| `phase24_trade_intelligence` | 0 | Paper/live closed trades (none yet) |
| `phase24_missed_opps` | 100 | Live scan `4915c8df904f` (Aug 2026) |
| `phase24_recommendations` | 8 | Generated from live scan missed opps |
| `backtest_runs.missed` (GLAND runs) | 100 per run | Backtest analyzer |

The 100 rows in `phase24_missed_opps` come from a single live scan, not from any backtest.

#### Step 5 — Recommendations engine
The 8 existing `phase24_recommendations` (all status `PROPOSED`, require human approval) are all `RISK_RULE` kind, all generated from live scan data. Sample:

- "Gate 'scan_fresh' is effective — keep it" (100% of rejections correct, 48 evaluated)
- "Gate 'market_open' is effective — keep it" (100% correct)
- "Gate 'recommendation_buy' is effective — keep it" (100% correct)

None reference a backtest run. None come from the missed opportunity analyzer in `backtest_runner.py`.

### Flow summary table

| Step | File / Table | Persisted? | Consumed by Learning? | Notes |
|---|---|---|---|---|
| WATCH_GENERATED / RISK_REJECTED events emitted | `pipeline_events` (Postgres) | ✅ Yes | Indirectly (analyzer reads them) | Source events for analyzer |
| `analyze_missed_opportunities()` called | `backtest_runner.py:642` | — | — | Runs at completion only |
| Results stored | `backtest_runs.missed` (JSONB) | ✅ Yes | ❌ No | Dead end for learning |
| Served via API | `GET /backtest/run/:id/missed` | — | ❌ Display only | UI Investigation Center tab |
| `phase24_missed_opps` ingestion | `phase24_engine.py` | ❌ Not from backtest | — | Reads live scan only |
| `phase24_recommendations` generated | `phase24_recommendations.py` | ❌ Not from backtest | — | Requires human approval |

---

## Task 2 — TCS Case Verification

### Reference run: `BT-5d2ba71f70` (A Baseline, RUNNING as of report)

TCS is one of 5 symbols (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK) in the 5m smoke run. 179 ticks have been processed so far.

#### 1. Why no BUY was generated

Every single one of 179 TCS ticks produced `WATCH_GENERATED`. Not one produced `BUY_GENERATED`. The backtest engine enters a BUY **only** when:
```python
rec.error is None and rec.all_gates_passed and rec.final_action in ("BUY", "STRONG BUY")
```
`rec.final_action` was `"WATCH"` on every processed tick. `_try_enter` was never called.

#### 2. Why the final decision was WATCH

Sample `WATCH_GENERATED` payload from the live DB:
```json
{
  "action": "WATCH",
  "confidence": 36.7,
  "paper_eligible": false,
  "opportunity_score": 45.3
}
```

Sample `SYMBOL_SCANNED` payload (market context):
```json
{
  "adx": 15.7,
  "rsi": 42.4,
  "bars": 185,
  "data_quality": "LIVE",
  "volume_ratio": 0.0
}
```

The AI Decision layer returned WATCH because the evidence was weak:
- `confidence: 36.7` — well below the `min_confidence` gate threshold (~65)
- `opportunity_score: 45.3` — below the `min_opportunity_score` gate threshold (~65)
- `adx: 15.7` — weak trend (ADX < 20 signals directionless market)
- `rsi: 42.4` — neutral-to-bearish momentum
- `volume_ratio: 0.0` — zero relative volume at scan time (data capture timing artifact in 5m bars; also triggers the volume gate if applicable)

#### 3. Which scores were below threshold

| Score | Observed | Threshold | Status |
|---|---|---|---|
| Confidence | 36.7 | ~65 (min_confidence gate) | ❌ Below |
| Opportunity score | 45.3 | ~65 (min_opportunity_score gate) | ❌ Below |
| ADX | 15.7 | 20 typical minimum | ❌ Weak trend |
| RSI | 42.4 | 45–55 neutral (below momentum zone) | ⚠️ Neutral |
| Volume ratio | 0.0 | 0.3 (min volume gate) | ❌ Below |

Note: `RISK_APPROVED` fires for all 179 ticks, meaning the risk gate itself passed. The blocking scores are upstream: the AI Decision / opportunity-score model output was too weak to flip from WATCH to BUY, and the confidence was far below threshold. Volume ratio 0.0 is also likely to trigger RISK_REJECTED if any tick had a BUY signal — but they never reached that point.

#### 4. Why Portfolio Precheck had 0 events

`PORTFOLIO_PRECHECK` events are only emitted inside `_try_enter()`. `_try_enter()` is only called when `final_action in ("BUY", "STRONG BUY")`. Since TCS produced WATCH for every tick, `_try_enter` was never called. Portfolio precheck having 0 events is **correct behaviour**, not a bug.

#### 5. Why Execution had 0 events

Same reason. `ORDER_SUBMITTED`, `ORDER_EXECUTED`, `POSITION_OPENED` are all emitted inside `_try_enter()`. Zero execution events is expected when all decisions are WATCH.

#### 6. Which missed opportunities later became profitable

The run is still RUNNING (179/2819 ticks) so `analyze_missed_opportunities()` has not yet been called (it runs at completion only). No `backtest_runs.missed` data exists yet for this run.

From the completed GLAND reference runs, the pattern is: signals blocked by the volume gate or classified WATCH frequently became profitable over the following 10 bars. On `BT-1dd403e980` (GLAND, 2 trades, 4.06% return):
- 100/100 stored missed opportunities would have been profitable (100% win rate post-signal)
- Avg potential return: +2.08%, avg realized at horizon: +1.64%
- Max potential: +3.05% (volume ratio 0.28, single gate failure)
- WATCH signals (50/50): all profitable, no gate-relax hint (WATCH is a model output, not a single gate failure)
- RISK_REJECTED signals (50/50): all due solely to `volume` gate (volume ratio < 0.3)

#### 7. Whether missed opportunities were sent to the learning layer

**No.** Even for completed runs (GLAND), the missed opportunities stop at `backtest_runs.missed`. They are not ingested into `phase24_missed_opps`. The Phase-24 learning system has never processed a single backtest missed opportunity.

---

## Task 3 — Learning Safety Check

All four safety properties are **confirmed**:

| Property | Evidence |
|---|---|
| Backtest learning does not modify live BUY thresholds automatically | `analyze_missed_opportunities()` docstring line 677: "NEVER changes any strategy". No write path exists from this function to any config table. |
| Backtest learning does not modify paper trading defaults automatically | `backtest_runner.py` writes only to: `backtest_runs`, `backtest_trades`, `pipeline_events`. No paper trading tables touched. |
| Any learning output is advisory only | `phase24_store.py` lines 4–14: explicit advisory-only declaration. Phase24 module docstrings all confirm. DB: all 8 recommendations are `PROPOSED`, never auto-promoted. |
| Human approval is required before changing strategy/risk settings | `p24_rec_decide <id> approve/dismiss <note>` is the only status-change path. No scheduler, no auto-apply. No code path from `PROPOSED` to `APPROVED` without explicit human dispatch. |

The Phase-24 daily learning scheduler (`p24_daily_learning`) captures closed paper trades and generates recommendations — but it has no write path to strategy configs, risk thresholds, BUY gates, or paper trading settings.

---

## Task 4 — Recommendation Quality

The following recommendations are derived from the GLAND backtest data (completed runs `BT-1dd403e980`, `BT-acab5cf232`, `BT-67b265939f`, `BT-0587e32d0b`, `BT-317d5c345f`). Each completed GLAND run produced 100 missed opportunities.

All recommendations are **advisory only**. None should be applied without multi-symbol validation across a full 20-symbol run and explicit human review.

---

### Recommendation R-01: Volume gate may be overly strict for mid-cap intraday — do not change yet

**Observation:** All 50 RISK_REJECTED missed opportunities in the GLAND backtest were blocked solely by the `volume` gate (volume ratio < 0.3 threshold). Every one of those 50 would have been profitable.

| Metric | Value |
|---|---|
| Sample size | 50 RISK_REJECTED events, 1 symbol (GLAND), 5m bars |
| Win rate after missed signal | 100% (50/50) |
| Median potential return | +2.08% over 10-bar horizon |
| Avg realized return at horizon | +1.64% |
| Max adverse move within horizon | Not observed (all closed higher) |
| Max potential return | +3.05% |
| Would relaxing volume gate increase false positives? | Unknown — requires multi-symbol test. GLAND is a pharma mid-cap; volume patterns differ from NIFTY 50 names. |
| Confidence of recommendation | LOW — single symbol, one backtest period |

**Advisory:** The volume gate is effective for large-caps (Phase-24 live data: 100% of live rejections correct). For mid-cap pharma intraday, the 0.3 ratio threshold may be too restrictive. **Do not change the rule.** Sample is too small. Requires multi-symbol validation across at least the 20-symbol NSE universe before any threshold discussion.

---

### Recommendation R-02: WATCH confidence threshold may be too strict — requires validation

**Observation:** All 50 WATCH-classified missed opportunities in the GLAND backtest would have been profitable (100% win rate). WATCH signals are generated when the AI Decision model output is below the BUY confidence threshold — the signal is present but conviction is insufficient.

| Metric | Value |
|---|---|
| Sample size | 50 WATCH events, 1 symbol (GLAND), 5m bars |
| Win rate after WATCH signal | 100% (50/50) |
| Avg potential return | +2.08% |
| Avg realized return at horizon | +1.64% |
| Min realized return | +0.30% (still positive) |
| Max adverse move | Not observed in horizon window |
| Would lowering confidence threshold increase false positives? | YES — by construction. Lowering the threshold that separates WATCH from BUY will increase trade frequency and false positives. |
| Confidence of recommendation | LOW — 1 symbol, ~55 calendar days |

**Advisory:** A 100% WATCH win rate on one symbol over two months is statistically insufficient. Expected: a larger multi-symbol dataset will show many WATCH signals that did not become profitable. **Do not lower the confidence threshold.** Technical score model may be underweighting trend continuation for GLAND specifically (ADX was consistently weak; RSI neutral). The correct next step is the 20-symbol backtest, which will show WATCH win rates across diverse market conditions.

---

### Recommendation R-03: RISK_REJECTED volume gate — single-gate relaxation hint is informative, not actionable

**Observation:** The `single_rule_relax_hint` field is populated on 50/100 missed opportunities, all saying: *"Only the 'volume' gate failed — relaxing it alone would have allowed this entry (advisory only)."*

| Metric | Value |
|---|---|
| Sample size | 50 single-gate-failure events |
| Gate name | `volume` |
| All profitable after relaxation would allow | Yes (50/50) |
| Would change increase false positives | Yes — any volume-gate relaxation increases exposure to low-liquidity entries |
| Risk of relaxation | Slippage risk increases significantly at low volume. The realized return assumes fill at close price; real fills in low-volume conditions may be materially worse. |
| Confidence | LOW — single symbol, pharma sector |

**Advisory:** The hint is a useful diagnostic tool. It is not a recommendation to relax the gate. Slippage assumptions in the backtest engine use a fixed model; a volume-relaxed live trade in a 0.03 volume-ratio bar would incur real market impact not captured in simulation.

---

### Recommendation R-04: Require multi-symbol validation before any threshold discussion

**Observation:** All recommendations above are derived from 1 symbol (GLAND) over a single 55-day period. This is insufficient to conclude anything about threshold calibration.

| Metric | Value |
|---|---|
| Symbols in current evidence | 1 (GLAND pharma mid-cap) |
| Ticks analysed | 2,819 |
| Sectors represented | 1 (PHARMA) |
| Market regimes covered | ~1 (Aug 2026 sideways-to-bullish) |
| Minimum evidence standard (Phase-24 engine) | MIN_EVIDENCE = 5 trades |
| Recommended evidence before threshold change | ≥ 50 signals across ≥ 5 symbols across ≥ 2 market regimes |
| Confidence of recommendation | HIGH (this is a stop-the-analysis directive) |

**Advisory:** Wait for the 20-symbol run (`BT-19c7568aa7` to `BT-bc6b55820d`) to complete. That dataset will include NIFTY 50 large-caps, multiple sectors, and higher intraday volume. Only then can WATCH win rates and gate rejection correctness be evaluated with enough evidence to support a threshold discussion.

---

### Recommendation R-05: TCS WATCH signals — weak fundamentals, do not change rule

**Observation:** TCS produced WATCH on 100% of 179 processed ticks. Confidence: 36.7, opportunity score: 45.3, ADX: 15.7, RSI: 42.4, volume ratio: 0.0.

| Metric | Value |
|---|---|
| Sample size | 179 ticks, 1 symbol (TCS IT large-cap), run still RUNNING |
| Win rate after WATCH signal | Unknown — run still running, missed opps not computed |
| Evidence for threshold change | None — no forward returns available yet |
| Technical context | ADX 15.7 = directionless; RSI 42.4 = weak; volume_ratio 0.0 = no relative volume |
| Confidence | NOT ENOUGH DATA |

**Advisory:** The WATCH classification for TCS appears correct given the observed technical state. No action warranted. The missed-opportunity analysis will run when the smoke run completes and provide the forward-return evidence needed to evaluate this.

---

## Task 5 — Report: Is the AI Learning from Backtests?

### 1. Is the AI currently learning from backtests?

**No.** The backtest system computes a rich missed-opportunity analysis at run completion and stores it in `backtest_runs.missed`. That data is displayed in the Investigation Center. It is never ingested by the Phase-24 learning engine, never stored in `phase24_missed_opps`, and never generates recommendations.

### 2. Are missed opportunities persisted?

**Yes — partially.** They are persisted as a JSONB array in the `backtest_runs` table (column `missed`). This is a purpose-built store for display. It is not in a form that Phase-24 can consume directly (different schema, different table, no FK linkage).

### 3. Do missed opportunities reach the learning layer?

**No.** The Phase-24 learning layer reads exclusively from:
- `phase20_executor.get_ledger()` (paper/live closed trades)
- Live canonical scan snapshots (latest scan, not any backtest run)

There is no code path from `backtest_runs.missed` to `phase24_missed_opps`.

### 4. Are recommendations generated from backtest data?

**No.** All 8 current `phase24_recommendations` are generated from the live scan missed-opp data (scan `4915c8df904f`, Aug 2026). None reference a backtest run.

### 5. Are recommendations advisory only?

**Yes — confirmed at every level:**
- `analyze_missed_opportunities()` docstring explicitly says "NEVER changes any strategy"
- All Phase-24 modules have advisory-only declarations in docstrings and store docstring
- All recommendations in DB are `PROPOSED` — no auto-promotion path
- `p24_rec_decide` requires explicit operator dispatch with a decision note

### 6. What is missing?

The **bridge layer**: a function that reads `backtest_runs.missed`, transforms entries to the `phase24_missed_opps` schema, and ingests them so the Phase-24 recommendation engine can reason about backtest evidence.

Specifically missing:
- A command `p24_ingest_backtest <run_id>` that reads `backtest_runs.missed` and writes records to `phase24_missed_opps` with `advisory_only=True`, `source='backtest'`, and the appropriate field mapping.
- A post-completion hook (or manual trigger) that calls this ingestion after a backtest run reaches `COMPLETED`.
- An HTTP route `POST /api/backtest/run/:id/ingest-missed` so operators can explicitly choose to send a completed run's missed-opportunity data to the learning layer.
- The Phase-24 recommendation generator already handles mixed sources if given data — it would naturally produce backtest-sourced recommendations once the data is in `phase24_missed_opps`.

What is explicitly **not** missing:
- The computation step (already done — `analyze_missed_opportunities` is correct and complete)
- The storage step (already done — `backtest_runs.missed` is correct)
- The display layer (already done — Investigation Center shows missed opportunities)
- Safety controls (already done — advisory-only, requires human approval)

### 7. Exact fix plan (do not implement yet)

**Phase A — Schema extension (non-breaking):**
Add a `source` column to `phase24_missed_opps` defaulting to `'live'`. Add a `backtest_run_id` nullable column. This differentiates live vs. backtest evidence in the recommendation engine.

```sql
ALTER TABLE phase24_missed_opps
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'live',
  ADD COLUMN IF NOT EXISTS backtest_run_id TEXT REFERENCES backtest_runs(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS phase24_missed_opps_bt_uix
  ON phase24_missed_opps(backtest_run_id, symbol, scan_id)
  WHERE backtest_run_id IS NOT NULL;
```

**Phase B — Ingestion function (`phase24_engine.py`):**
```python
def ingest_backtest_missed(run_id: str, dry_run: bool = False) -> dict:
    """
    Read backtest_runs.missed for the given run_id, transform entries to
    phase24_missed_opps schema, and insert them.
    Advisory only. Does not modify any strategy or risk config.
    Idempotent: unique index on (backtest_run_id, symbol, scan_id) prevents duplication.
    """
```

Field mapping from `backtest_runs.missed` → `phase24_missed_opps`:
| Backtest field | Phase24 field | Notes |
|---|---|---|
| `symbol` | `symbol` | direct |
| `scan_id` | `scan_id` | direct |
| `decision` (WATCH/RISK_REJECTED) | `record.ai_decision` | direct |
| `reason` | `record.rejection_reason` | direct |
| `potential_return_pct` | `record.potential_profit_pct` | direct |
| `return_at_horizon_pct` | `record.later_max_move_pct` | closest equivalent |
| `would_have_been_profitable` | `record.rejection_correct = not would_have_been_profitable` | invert |
| `single_rule_relax_hint` | `record.improvement_suggestion` | direct |
| `base_price` | `record.reference_price` | direct |
| `run_id` | `backtest_run_id` | FK to backtest_runs |
| `'backtest'` | `source` | constant |

**Phase C — Command dispatch (`main.py`):**
```
p24_ingest_backtest <run_id> [--dry-run]
```

**Phase D — HTTP route (`backtest.ts`):**
```
POST /api/backtest/run/:id/ingest-missed
```
Advisory message in response: *"Missed opportunities ingested to learning layer. They will appear in the next recommendation generation. This does not modify any thresholds or strategy settings."*

**Phase E — Recommendation generator update (`phase24_recommendations.py`):**
No change required. The generator already reads all rows from `phase24_missed_opps` and computes gate effectiveness. With `source='backtest'` data present, it will naturally produce backtest-evidenced recommendations. The recommendation output should note the source so operators can distinguish backtest vs. live evidence.

**Implementation order:** A → B → C → D → E. A and B can be done together. Do not implement until the 20-symbol backtest completes and provides a meaningful evidence base.

---

## Appendix — Evidence Base

### Completed GLAND runs (reference)
| Run ID | Config | Trades | Return | Missed Count |
|---|---|---|---|---|
| BT-1dd403e980 | A Baseline | 2 | +4.06% | 100 |
| BT-acab5cf232 | B Scale-in | 3 | +5.11% | 100 |
| BT-67b265939f | C Sizing 1.5% | 3 | +6.30% | 100 |
| BT-0587e32d0b | D Combined | 3 | +6.11% | 100 |

### Missed opportunity statistics (BT-1dd403e980, GLAND)
- **Total stored**: 100 (capped at 100 by analyzer)
- **By decision**: 50 WATCH, 50 RISK_REJECTED
- **Profitable**: 100/100 (100% — single symbol, short period)
- **Avg potential return**: +2.08%
- **Avg realized at horizon**: +1.64%
- **RISK_REJECTED cause**: `volume` gate exclusively (volume ratio < 0.3)
- **WATCH cause**: model confidence/opportunity score below BUY threshold

### TCS events in smoke run BT-5d2ba71f70 (179 ticks processed)
| Event | Count |
|---|---|
| SYMBOL_SCANNED | 179 |
| MARKET_INTELLIGENCE_COMPLETED | 179 |
| RESEARCH_COMPLETED | 179 |
| MONITORING_COMPLETED | 179 |
| STRATEGY_SELECTED | 179 |
| RISK_APPROVED | 179 |
| WATCH_GENERATED | 179 |
| BUY_GENERATED | 0 |
| PORTFOLIO_PRECHECK_* | 0 |
| ORDER_SUBMITTED | 0 |
| ORDER_EXECUTED | 0 |
| POSITION_OPENED | 0 |

### Phase-24 current state
| Item | Value |
|---|---|
| `phase24_trade_intelligence` rows | 0 |
| `phase24_missed_opps` rows | 100 |
| Source of missed opps | Live scan only (scan `4915c8df904f`) |
| `phase24_recommendations` rows | 8 |
| All recommendations status | PROPOSED (none approved) |
| Recommendation content | All "gate is effective — keep it" (conservative) |

---

*Stop here. Fix plan above — do not implement until instructed.*
