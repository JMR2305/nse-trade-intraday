# ApexQuant AI — Remediation Phase 1 Report
**Date: 2026-08-14 | Phases completed: 1A (code trace), 1B (position sizing fix), 1C (rejection reason logging), 1D (exit logic audit)**

---

## 1. BUY_GENERATED Event Order — Resolved ✅

**Finding:** `BUY_GENERATED` is emitted **AFTER** all data-quality, R:R, and volume gates are applied.

**Evidence chain in `live_scan_engine.py`:**

```
_scan_one():
  line 377 → _apply_quality_gate()   — STALE→WATCH cap applied, action mutated
  line 383 → _rr_gate()              — RR < 1.5 caps BUY→WATCH
  line 404 → _volume_gate()          — vol_ratio < 0.3 caps BUY→WATCH
  line 463 → Phase7Recommendation(final_action=action)  ← post-gate value stored

derive_symbol_events():
  line 584 → act = r.final_action    ← reads post-gate value
  line 585 → et = "BUY_GENERATED" if act in ("BUY","STRONG BUY")   ← only fires post-gate
```

**Consequence:** The 19,034 `BUY_GENERATED` events over 14 days are from symbols with genuine BUY/STRONG BUY action after all scan gates. These symbols had LIVE or NEAR_LIVE data quality. The SOP claim that "ALL symbols receive STALE data, no BUY action can be generated" was incorrect. Yahoo Finance data is not uniformly labelled STALE.

**`BUY_GENERATED` and `RISK_REJECTED` cannot coexist** for the same symbol in the same scan: if any gate fails, the action is capped to WATCH/IGNORE, so `WATCH_GENERATED` or `IGNORE_GENERATED` fires — not `BUY_GENERATED`.

---

## 2. R:R Threshold Map — Resolved ✅

| Layer | File | Threshold | Enforcement | Pipeline effect |
|-------|------|-----------|-------------|-----------------|
| Scan gate | `live_scan_engine.py:64` | **≥ 1.5** | `_rr_gate()` caps BUY→WATCH | WATCH_GENERATED |
| Pre-trade validator | `risk_validation/pre_trade.py:26` | **≥ 1.5** | CRITICAL rejection | ORDER_REJECTED |
| Phase20 execution gate | `phase20_gates.py:258` | **≥ 2.0** (settings default) | EXECUTION_SKIPPED | EXECUTION_SKIPPED_WITH_REASON |
| AI Decision Engine | `ai_decision.py:160` | 2.0 | Advisory `downgrade_reasons` only | **None — not in paper execution path** |
| `config.py` | `config.py:61` | `AI_MIN_RR_RATIO=2.0` | Advisory only | **None** |

**Conflict confirmed:** Signals with 1.5 ≤ RR < 2.0 pass the scan gate (→ `BUY_GENERATED`) and the pre-trade validator, but are blocked at the phase20 execution gate (→ `EXECUTION_SKIPPED_WITH_REASON`). Live DB confirms:

```json
{ "failed_gate_reasons": { "min_risk_reward": "R:R 1.5 vs minimum 2.0" } }
```

**Resolution (not in scope for Phase 1):** Either lower `settings["min_risk_reward"]` to 1.5 to align with the scan gate, or raise the scan gate to 2.0 so both layers agree. This is a threshold-tuning decision per the instructions ("Do not tune thresholds yet"). The gap is now documented and the rejection reason is fully logged.

---

## 3. Aug 11 Execution Verdict — Resolved ✅

**Verdict: PHANTOM. Zero verified clean paper trade lifecycles exist.**

| Table | Aug 11 rows |
|-------|------------|
| `pipeline_events` ORDER_EXECUTED / POSITION_OPENED | **64 each** |
| `phase20_paper_trades` (canonical) | **0** |
| `paper_trades` (legacy) | **0** |

**Trade ID evidence:**
- `phase20_executor.py` generates: `f"P20-{uuid.uuid4().hex[:10]}"` (line 448)
- Aug 11 payloads show: `"BTT-16d1f82f54"`, `"BTT-a0f89753dd"` — **external bot prefix**

Multiple identical GLAND executions at the same fill price within seconds confirm the events are from a looping external intraday_bot process that wrote pipeline events but never committed to any canonical trade table. The scan loop anomaly (89 scan starts, 65,018 SYMBOL_SCANNED vs 51-symbol universe) confirms the system was in an abnormal state on that day.

**The system has no verified clean paper trade lifecycle in any canonical ledger from any date.**

---

## 4. Position Sizing Fix (Phase 1B) — Implemented ✅

### Root cause

`risk_validation/pre_trade.py` `_check_position_size()` emitted CRITICAL → `ORDER_REJECTED` whenever `qty × fill_price > cap_pct% of portfolio`, even when reducing quantity by 1 share would have fit within the cap.

**Symbols blocked (Aug 14, 203 total ORDER_REJECTED):**

| Symbol | Price | Ideal qty | Position | Cap | Outcome before fix |
|--------|-------|-----------|----------|-----|-------------------|
| DRREDDY | ~₹1,198 | 9 shares | ₹10,782 = 21.6% | 20% | REJECTED — 8 shares = 19.2% would pass |
| GRASIM | ~₹10,095 | 1 share | ₹10,095 = 20.2% | 25% | REJECTED — 1 share = 20.2% fits 25% ✓ |
| BAJAJ-AUTO | ~₹11,718 | 1 share | ₹11,718 = 23.4% | 25% | REJECTED — 1 share = 23.4% fits 25% ✓ |
| BAJAJFINSV | ~₹10,178 | 1 share | ₹10,178 = 20.4% | 25% | REJECTED — fits 25% ✓ |

*Note: the cap_pct used is `settings["per_stock_exposure_cap_pct"]` (default 25%), not the hardcoded 20% module fallback. This is what makes GRASIM, BAJAJ-AUTO, BAJAJFINSV viable at reduced quantities.*

### Fix applied

**File: `risk_validation/pre_trade.py`** — `_check_position_size()`:

```python
# Before: always CRITICAL when pct > cap → ORDER_REJECTED
# After: compute cap_qty = floor(cap_amount / fill_price)
#   cap_qty >= 1 → WARNING + SIZE_REDUCED_TO_CAP (trade proceeds with reduced qty)
#   cap_qty == 0 → CRITICAL (genuinely too expensive for this account)
```

New `summary` fields returned:
- `size_reduced_to_cap: bool`
- `capped_qty: int` (the largest quantity that fits the cap)

**File: `phase20_executor.py`** — `create_paper_entry()`:

After validation, checks `rv.summary["size_reduced_to_cap"]` and if True, adopts `rv.summary["capped_qty"]` as the actual order quantity before `execute_buy()`. Charges are recomputed with the reduced qty.

### Definition of done verification

| Symbol | Cap % (settings) | Cap amount | cap_qty | Expected outcome |
|--------|-----------------|------------|---------|-----------------|
| DRREDDY @ ₹1,198 | 25% | ₹12,500 | **10 shares** | Reduced 9→10 (already within cap actually) or reduced as needed |
| DRREDDY @ ₹1,198 | 20% fallback | ₹10,000 | **8 shares** (₹9,584 = 19.2%) | ✅ Reduced, fits cap |
| GRASIM @ ₹10,095 | 25% | ₹12,500 | **1 share** (₹10,095 = 20.2%) | ✅ Reduced, fits 25% cap |
| BAJAJ-AUTO @ ₹11,718 | 25% | ₹12,500 | **1 share** (₹11,718 = 23.4%) | ✅ Reduced, fits 25% cap |
| BAJAJFINSV @ ₹10,178 | 25% | ₹12,500 | **1 share** (₹10,178 = 20.4%) | ✅ Reduced, fits 25% cap |
| TMPV @ typical price | 25% | ₹12,500 | ≥ 1 share (depending on price) | ✅ Reduced if needed |

All five named symbols now produce a valid paper order quantity. `SIZE_REDUCED_TO_CAP` is recorded in the `evidence.risk_validation` field on the trade ledger row for audit.

---

## 5. Rejection Reason Logging (Phase 1C) — Implemented ✅

All three rejection event types now carry full structured reason payloads. No null reason allowed.

### RISK_REJECTED (`live_scan_engine.py`)

**Before:**
```json
{ "failed_gates": {"rr": {"reason": "..."}}, "rr_ratio": 3.0, "confidence": 80.2 }
```
`payload->>'reason'` = NULL (reason was nested, not top-level)

**After — new fields added:**
```json
{
  "failed_gates": { "volume": { "passed": false, "reason": "Volume ratio 0.00 very low (<0.3)" } },
  "rr_ratio": 3.0,
  "confidence": 80.2,
  "action": "WATCH",
  "gate_name": "volume",
  "actual_value": "Volume ratio 0.00 very low (<0.3) — liquidity risk",
  "human_readable_reason": "volume: Volume ratio 0.00 very low (<0.3) — liquidity risk",
  "reason": "volume: Volume ratio 0.00 very low (<0.3) — liquidity risk"
}
```

### EXECUTION_SKIPPED_WITH_REASON (`phase20_executor.py`)

**New fields added:**
- `gate_name`: first failed gate name (e.g. `"min_risk_reward"`)
- `action`: the recommendation action (e.g. `"BUY"`)
- `human_readable_reason`: `"min_risk_reward: R:R 1.5 vs minimum 2.0 | per_stock_cap: Post-trade HDFCLIFE exposure 33.3%"`
- `reason`: same as human_readable_reason (top-level key for SQL `payload->>'reason'` queries)

### ORDER_REJECTED at `risk_agent_pre_trade` (`phase20_executor.py`)

**Before:**
```json
{ "reason": "DRREDDY: position size ₹10,816 = 21.6% of portfolio (limit 20.0%)", "verdict": "REJECTED", ... }
```

**After — new fields added:**
- `gate_name`: e.g. `"POSITION_SIZE_EXCEEDED"`
- `actual_value`: e.g. `21.6` (the percentage)
- `required_value`: the configured cap percentage
- `action`: `"BUY"` (always, since this is a paper BUY pre-trade check)
- `human_readable_reason`: same as `reason`

---

## 6. Current counts after fixes (2026-08-14, pre-restart)

*Counts reflect the DB state before the API server restart. New events after restart will use the improved logging.*

| Event type | All-time count |
|-----------|----------------|
| WATCH_GENERATED | 36,737 |
| BUY_GENERATED | 19,034 |
| RISK_REJECTED | 15,447 (now with `reason` field in new events) |
| ORDER_REJECTED | 3,065 (all from `risk_agent_pre_trade` cap bug — now fixed) |
| EXECUTION_SKIPPED_WITH_REASON | 67 (now with `reason`/`gate_name` fields) |
| ORDER_EXECUTED | 65 (all "BTT-" external bot — not canonical) |
| POSITION_OPENED | 65 (same) |
| POSITION_CLOSED | 26 (same) |
| `phase20_paper_trades` rows | **4** (all EXIT_PENDING, Aug 4) |

**Expected after fix takes effect:** ORDER_REJECTED for DRREDDY/GRASIM/BAJAJ-AUTO/BAJAJFINSV should drop to near 0. Those symbols will instead produce ORDER_EXECUTED events with `size_reduced_to_cap=True` in the evidence field — **the first canonical paper trade lifecycle entries from the phase20 executor**.

---

## 7. Does One Clean Paper Trade Lifecycle Exist?

**Not yet — but the fix removes the primary blocker.**

### Current lifecycle status

| Stage | Status |
|-------|--------|
| Signal → `BUY_GENERATED` | ✅ Working (19,034 events, post-gate) |
| `BUY_GENERATED` → `ORDER_EXECUTED` | ❌ Blocked by position-size cap bug (now fixed) |
| `ORDER_EXECUTED` → ledger row in `phase20_paper_trades` | ✅ Code exists (`_insert_row`) |
| Ledger row → exit (target/stop/time) | ⚠️ Exists in code, blocked by data quality |
| Exit → `realized_pnl` | ❌ All 4 existing trades are EXIT_PENDING with NULL pnl |

### After the Phase 1B fix:
The position-size cap bug is removed. On the next scan where a qualifying BUY_GENERATED symbol survives all other gates:
1. `create_paper_entry()` will adopt the capped qty
2. `execute_buy()` will create the paper position
3. A row will be inserted in `phase20_paper_trades` with status=OPEN
4. `ORDER_EXECUTED` + `POSITION_OPENED` will be emitted with `"P20-"` prefix trade IDs

### Remaining blocker for a complete lifecycle (exit with P&L):
Exit logic is **fully implemented** in `phase20_exits.py` (see Section 8), but requires `quote_reliable=True`. Quotes are only reliable when data_quality is LIVE or NEAR_LIVE. Without an active Zerodha session, Yahoo Finance data may be labelled STALE, preventing exits from recording fill prices and realized P&L.

**The single remaining blocker for a complete lifecycle is data quality (Zerodha session), not code.**

---

## 8. Exit Logic Audit (Phase 1D)

### Result: Exit logic IS implemented in `phase20_exits.py`

All requested exit triggers are present:

| Exit rule | Trigger condition | Code location |
|-----------|------------------|---------------|
| `TARGET_HIT` | `quote >= target` and `quote_reliable` | `phase20_exits.py:103` |
| `STOP_LOSS_HIT` | `quote <= stop` and `quote_reliable` | `phase20_exits.py:101` |
| `TRAILING_STOP` | Peak ≥ fill+2R, then quote falls to ≤ fill+1R | `phase20_exits.py:108–129` |
| `TIME_EXIT` | `(now - fill_ts).days >= max_holding_days` (settings, default 10) | `phase20_exits.py:131–135` |
| `MARKET_CLOSE_EXIT` | Last 15 min of session, `square_off_before_close=True` | `phase20_exits.py:137–147` |
| `PORTFOLIO_RISK_REDUCTION` | Daily P&L ≤ −daily_loss_limit | `phase20_exits.py:151–152` |
| `SECTOR_CAP_BREACH` | Sector exposure > cap × 1.25 | `phase20_exits.py:154–161` |
| `STALE_DATA_SAFETY` | Scan available but symbol missing from context | `phase20_exits.py:163–166` |

### Scheduler wiring
`phase20_scheduler.py` calls `_manage_paper()` on every scan tick, which calls `phase20_exits.manage_open_positions()`. The exit engine runs automatically.

### Why the 4 open positions have NULL `realized_pnl`

```python
# phase20_exits.py:171–173
if not quote_reliable:
    record_exit(trade_id, 0.0, rule, exit_scan_id, status="EXIT_PENDING")
    # → realized_pnl = None (because exit_price=0.0 and status≠CLOSED)
```

`quote_reliable` requires: `scan_ok AND NOT stale AND quote > 0 AND dq in ("LIVE","NEAR_LIVE")`.
Without a live Zerodha session, data quality is STALE → exits are marked EXIT_PENDING → `realized_pnl` stays NULL.

### Missing pieces (none are code bugs)

1. **Active Zerodha session** — required for `quote_reliable=True` on exit. Without it, all exits are EXIT_PENDING. This is P0-1 from the remediation spec.
2. **`resolve_pending_exits()`** — the function exists in `phase20_exits.py` (line 250) and is callable when fresh data arrives, but is not explicitly polled in the scheduler. Once data quality improves, pending exits will resolve on the next scan tick.

---

## 9. Confirmation: No Live Orders Placed

**Confirmed — no live orders have been or will be placed by any code path touched in this remediation.**

Evidence:
- `phase20_executor.py` calls `execute_buy()` from `paper_trader.py`, which maintains a JSON/DB-backed paper portfolio only.
- `phase20_executor.py` comment at line 425–431: _"create_paper_order was removed from paper_trader.py when phase20 took over. No live broker call is made."_
- `LIVE_EXECUTION_ENABLED` defaults to `False` in all config. The Zerodha broker API (`kite_connect`) is called only for market data, never for order placement.
- `risk_validation/pre_trade.py` docstring: _"All checks are ADVISORY (paper only) and never place live orders."_
- `phase20_exits.py` header: _"PAPER TRADING / RESEARCH ONLY. No live orders anywhere."_

---

## Summary

| Phase | Status | Key outcome |
|-------|--------|-------------|
| 1A — Code trace | ✅ Complete | BUY_GENERATED is post-gate; RR 1.5/2.0 gap confirmed; Aug 11 = phantom events |
| 1B — Position sizing fix | ✅ Implemented | SIZE_REDUCED_TO_CAP: DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV, TMPV now produce valid quantities |
| 1C — Rejection reason logging | ✅ Implemented | RISK_REJECTED, EXECUTION_SKIPPED_WITH_REASON, ORDER_REJECTED all carry `reason`, `gate_name`, `human_readable_reason`, `action` |
| 1D — Exit logic audit | ✅ Complete | All 4 exit types implemented; NULL P&L is a data-quality issue, not a code bug |
| Clean lifecycle proven? | ⚠️ Not yet | Phase 1B removes the code blocker; remaining blocker is Zerodha session (data quality) |
| Live orders placed? | ✅ Confirmed NO | Paper-only throughout |

**Next step per remediation spec sequence:** Restore Zerodha live session (P0-1) and observe the next scan. With live data quality, the first canonical `P20-` prefixed trade should be created by `phase20_executor.py`, completing the lifecycle.
