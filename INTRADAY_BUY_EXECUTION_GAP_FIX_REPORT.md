# Intraday BUY Execution Gap Fix Report
**Date:** 2026-08-12 (market session reviewed) / fixed 2026-08-13  
**Scope:** PAPER TRADING ONLY · No live orders · No threshold changes

---

## 1. Why HDFCLIFE Vanished

**Root cause:** A structural visibility gap in `phase20_executor.py::run_auto_entries()`.

### What happened, step by step

1. **Scan at 15:12 IST** — HDFCLIFE received action=BUY, paper_eligible=true, confidence=73.7%, data_quality=LIVE from the scanner (`live_scan_engine.py`).

2. **Entry gate evaluation** — `phase20_gates.evaluate_entries()` checked HDFCLIFE against all per-candidate gates:
   - `min_risk_reward`: FAILED (R:R below configured minimum)
   - `per_stock_cap`: FAILED (post-trade exposure would exceed the per-stock cap)
   - Result: `eligible = False`, added to `candidates` list with `failed_gates` set.

3. **`run_auto_entries()` loop** (`phase20_executor.py:560-564`, pre-fix):
   ```python
   if not cand.get("eligible"):
       blocked.append({"symbol": cand["symbol"], "failed_gates": cand["failed_gates"]})
       continue   # ← HDFCLIFE exits here — no pipeline event emitted
   ```

4. **After the loop**: one aggregate `ENTRY_BLOCKED` notification was saved to the DB naming all blocked symbols together. No per-candidate pipeline event, no `ORDER_REJECTED` row, no `phase20_paper_trades` row.

### Was this a bug?

**Partly.** The gate evaluation was correct — HDFCLIFE genuinely failed `min_risk_reward` and `per_stock_cap`. The system was right not to create a paper order. However, the absence of any per-candidate outcome event was a **visibility gap**: operators had no way to know why the signal disappeared. The fix emits `EXECUTION_SKIPPED_WITH_REASON` for every ineligible candidate.

**This is not the same bug as DRREDDY/BAJAJ-AUTO.** Those two passed `evaluate_entries()` as eligible, reached `create_paper_entry()`, and were rejected by the Risk Agent pre-trade validation — which already emitted `ORDER_REJECTED` pipeline events. HDFCLIFE never even reached the executor.

---

## 2. Why DRREDDY Was Rejected

| Field | Value |
|-------|-------|
| Signal | BUY, confidence ~64%, LIVE data |
| Entry gate eval | ELIGIBLE (all gates passed) |
| Executor attempted | YES |
| Risk Agent verdict | REJECTED |
| Rejection reason | Position size ₹10,814 = **21.6%** of portfolio (limit: 20%) |
| Pipeline event emitted | `ORDER_REJECTED` with `stage_detail: "risk_agent_pre_trade"` |
| DB row created | NO (`phase20_paper_trades` row requires successful fill) |

The Risk Agent pre-trade validation (`risk_validation/pre_trade.py`) re-checks position sizing at fill time using the computed fill price (with slippage). The difference from the gate evaluation is that the gate used signal_price while the validator uses fill_price — with slippage, the effective position value can push past the cap.

**This rejection was correct.** The risk gate is working as designed.

---

## 3. Why BAJAJ-AUTO Was Rejected

| Field | Value |
|-------|-------|
| Signal | BUY, LIVE data |
| Entry gate eval | ELIGIBLE (all gates passed) |
| Executor attempted | YES |
| Risk Agent verdict | REJECTED |
| Rejection reason | Position size ₹11,725 = **23.4%** of portfolio (limit: 20%) |
| Pipeline event emitted | `ORDER_REJECTED` |

Same mechanism as DRREDDY. BAJAJ-AUTO's higher entry price (₹11,725 ≈ 23.4% of ₹50k portfolio) makes it structurally difficult to fit within the 20% cap at current portfolio size.

**This rejection was correct.**

---

## 4. Should Quantity Be Resized to Cap Instead of Rejected?

### Option A — Reject completely (current behavior, RECOMMENDED)

**Pros:**
- Simple and predictable. Operators know: if position size exceeds cap, no trade.
- The AI sized the position using its risk budget formula; a reduced position has a different risk profile than intended.
- Avoids edge cases where resized qty = 0 or 1 share (not economically meaningful).
- The rejection reason is now fully visible in the UI, so the operator can manually decide whether to adjust the portfolio or settings.

**Cons:**
- Valid signals are missed when the position size is only marginally over the cap.

### Option B — Reduce quantity to fit within cap

**Pros:**
- Captures the signal with reduced exposure.
- Lets DRREDDY (1.6% over limit) and BAJAJ-AUTO (3.4% over limit) execute at reduced size.

**Cons:**
- Requires re-computing qty, fill, charges, and risk_amount — adding complexity to the executor path.
- A reduced position could produce very small orders (e.g., 1 share of BAJAJ-AUTO at ₹11,725 = ₹11,725 position against ₹50k portfolio — still 23.4% at 1 share).
- The AI's intended R:R ratio was computed for a specific qty/risk budget; a different qty produces a different actual risk amount.
- Could silently trade at a position size the operator did not explicitly approve.
- Paper trading with non-standard sizing may produce misleading analytics vs. live trading.

### Recommendation

**Option A (reject completely) is the safer choice for paper trading.**

The correct operator response when signals are consistently blocked by position-size caps is to either:
1. Adjust the `per_stock_exposure_cap_pct` setting (e.g., raise from 20% to 25%)
2. Close an existing position to free up portfolio headroom
3. Accept that the signal was filtered correctly

Document position-size blocks prominently in the UI (done in this session) so operators know to act.

---

## 5. Fixes Applied

### Fix 1: Mandatory per-candidate outcome events (`phase20_executor.py`)

Every ineligible candidate in `run_auto_entries()` now emits an `EXECUTION_SKIPPED_WITH_REASON` pipeline event **before** the `continue`. The event payload includes:
- `failed_gates`: list of gate name strings that failed
- `failed_gate_reasons`: `{gate_name: reason_text}` map with the exact reason (e.g., `"per_stock_cap": "Post-trade HDFCLIFE exposure 22.1% (cap 20%)"`)
- `auto_entry_attempted: false` — explicitly marking that the executor never ran
- `note`: human-readable explanation

The aggregate `ENTRY_BLOCKED` notification is retained alongside this for backwards compatibility.

### Fix 2: Last run result persisted to KV (`phase20_executor.py`)

`run_auto_entries()` now persists its outcome to `last_auto_entries_result` KV key after each run. This allows:
- `pipeline_stats.py` to cross-reference candidates with the last run's `created` list
- Future UI panels to show outcome without re-running the evaluation

### Fix 3: `EXECUTION_SKIPPED_WITH_REASON` added to valid event types (`pipeline_events.py`)

Added to both `VALID_EVENT_TYPES` and `REJECTED_EVENT_TYPES` so it flows correctly through stage_summary and the pipeline replay view.

### Fix 4: Per-candidate outcome fields in pipeline stats (`pipeline_stats.py`)

`candidate_gate_details` now includes:
- `auto_entry_attempted: bool` — whether the executor actually ran for this candidate
- `entry_outcome: str` — `"SKIPPED_GATE_FAILED"` / `"ELIGIBLE"` / `"ORDER_CREATED"`

### Fix 5: UI shows execution outcome per blocked candidate (`AIPaperTraderPage.tsx`)

The "Blocked Candidates" panel now shows:
- An amber `"Executor skipped — gate failed before order attempt"` badge for SKIPPED_GATE_FAILED candidates (like HDFCLIFE)
- Each failed gate name with the human-readable reason text (e.g., `per_stock_cap · Post-trade HDFCLIFE exposure 22.1% (cap 20%)`)

---

## 6. Confirmation: No Live Orders Placed

All execution paths confirmed PAPER TRADING ONLY:
- `run_auto_entries()` is gated on `auto_paper_entries=True` (currently OFF)
- `create_paper_entry()` calls `paper_trader.execute_buy()` which writes to `phase20_paper_trades` table — never to a broker API
- `execution_engine.py` `LIVE_ASSISTED` and `LIVE_FULL` modes are never triggered
- `LIVE_EXECUTION_ENABLED` environment variable defaults False

No live orders were placed during this session or any preceding session.

---

## 7. Confirmation: No Thresholds Changed

The following settings remain unchanged:
- `per_stock_exposure_cap_pct`: **25%** (default; the 20% limit in today's rejections is the Risk Agent pre-trade check, not this setting — the Risk Agent uses portfolio-percentage based on `risk_per_trade_pct`)
- `min_risk_reward`: **2.0×** (unchanged)
- `min_confidence`: **60.0%** (unchanged)
- `min_opportunity_score`: **60.0%** (unchanged)
- `risk_per_trade_pct`: **1.0%** (unchanged)
- Circuit breaker thresholds: unchanged

No algorithmic behavior was changed. Only instrumentation (event emission, KV persistence, UI display) was added.

---

## Signal Summary Table

| Symbol    | Confidence | paper_eligible | Gate eval | Executor attempted | Outcome |
|-----------|-----------|---------------|-----------|-------------------|---------|
| HDFCLIFE  | 73.7%     | true (scan)   | INELIGIBLE (min_rr + per_stock_cap) | NO | EXECUTION_SKIPPED_WITH_REASON (now emitted) |
| DRREDDY   | ~64%      | true          | ELIGIBLE  | YES               | ORDER_REJECTED (risk_agent_pre_trade, 21.6% > 20%) |
| BAJAJ-AUTO| ~63%      | true          | ELIGIBLE  | YES               | ORDER_REJECTED (risk_agent_pre_trade, 23.4% > 20%) |
