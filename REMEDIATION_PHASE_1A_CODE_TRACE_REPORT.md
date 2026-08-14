# Remediation Phase 1A — Code Trace Report
**ApexQuant AI | Generated: 2026-08-14 | Read-only analysis — no behaviour changes**

---

## Q1 — Where is `BUY_GENERATED` emitted, and is it pre-gate or post-gate?

### Answer: **POST-GATE — always after all data-quality, RR, and volume caps are applied**

### Evidence

`_scan_one()` in `live_scan_engine.py` evaluates one symbol. Gate application order:

| Step | Line(s) | Code | Effect |
|------|---------|------|--------|
| 1 | 377–379 | `capped_action, _ = _apply_quality_gate(action, quality)` then `action = capped_action` | STALE → WATCH, UNAVAILABLE → IGNORE; `action` mutated in-place |
| 2 | 383–386 | `rr_ok, _ = _rr_gate(rr_ratio, action)` then `if not rr_ok: action = "WATCH"` | RR < 1.5 and BUY → caps to WATCH |
| 3 | 404–413 | `vol_ok, _ = _volume_gate(vol_ratio, action)` then `if not vol_ok: action = "WATCH"` | vol_ratio < 0.3 and BUY → caps to WATCH |
| 4 | 463 | `final_action=action` (inside `Phase7Recommendation(...)`) | Records the post-gate value |

`derive_symbol_events()` (lines 520–592) emits the pipeline events from the already-finalised `Phase7Recommendation` list:

```python
act = r.final_action                               # line 584 — post-gate value
et = ("BUY_GENERATED" if act in ("BUY", "STRONG BUY")   # line 585
      else "WATCH_GENERATED" if act == "WATCH" else "IGNORE_GENERATED")
batch.append(_ev(et, "AI_DECISION", ...))          # line 587
```

**`BUY_GENERATED` can only fire when `final_action` is BUY or STRONG BUY after every gate.**  
A STALE symbol's action is already WATCH at this point — it will emit `WATCH_GENERATED`, never `BUY_GENERATED`.

### Implication for the "no live data" claim

The SOP stated "ALL symbols receive STALE data, no BUY action can be generated." The 19,034 `BUY_GENERATED` events over 14 days disprove this. Those symbols had LIVE or NEAR_LIVE data quality at scan time. Yahoo Finance data is **not** universally labelled STALE — the label reflects the provider's declared data freshness, not the provider name alone.

### Event order within one symbol (one scan tick)

```
SYMBOL_SCANNED          (stage: SCANNER)
RESEARCH_COMPLETED      (stage: RESEARCH)
MARKET_INTELLIGENCE_COMPLETED
MONITORING_COMPLETED
STRATEGY_SELECTED       (stage: STRATEGY)
RISK_APPROVED or RISK_REJECTED   (stage: RISK) — based on all_gates_passed
BUY_GENERATED / WATCH_GENERATED / IGNORE_GENERATED   (stage: AI_DECISION) — based on final_action
```

`RISK_REJECTED` and `BUY_GENERATED` **cannot** coexist for the same symbol in the same scan:
- If any gate fails → action is capped → `final_action` is WATCH or IGNORE → only `WATCH_GENERATED` or `IGNORE_GENERATED` fires.
- If `BUY_GENERATED` fires → all scan gates passed → `RISK_APPROVED` fires (not `RISK_REJECTED`).

---

## Q2 — Where is the R:R threshold enforced, and are the layers aligned?

### Answer: **Two different thresholds at scan (1.5) and execution (2.0). MISALIGNED. A verified gap exists in the live DB.**

### Full R:R gate map

| Layer | File | Constant / setting | Threshold | Enforcement | Effect if fails |
|-------|------|--------------------|-----------|-------------|-----------------|
| **Scan gate** | `live_scan_engine.py` line 64, 92–96 | `MIN_RR_FOR_BUY = 1.5` (module constant) | **≥ 1.5** | `_rr_gate()` caps action to WATCH | `WATCH_GENERATED` — no paper entry attempted |
| **Pre-trade validator** | `risk_validation/pre_trade.py` line 26, 158–162 | `_MIN_RR_RATIO = 1.5` (module constant) | **≥ 1.5** | `_check_rr_ratio()` raises CRITICAL | `ORDER_REJECTED` (stage: risk_agent_pre_trade) — trade blocked |
| **Phase20 execution gate** | `phase20_gates.py` line 257–259 | `settings["min_risk_reward"]` default **2.0** | **≥ 2.0** | `evaluate_entries()` marks candidate ineligible | `EXECUTION_SKIPPED_WITH_REASON` — auto-entry skipped |
| **AI Decision Engine** | `ai_decision.py` line 160–162 | `rr_ratio < 2.0` → `downgrade_reasons` | **≥ 2.0** | Advisory only — `AiDecision` result not consumed by phase20 executor | No paper trade effect |
| **config.py constant** | `config.py` line 61 | `AI_MIN_RR_RATIO: float = 2.0` | 2.0 | Advisory layer only | No paper trade effect |

### The gap — confirmed in live DB

`EXECUTION_SKIPPED_WITH_REASON` event payload for HDFCLIFE:
```json
{
  "failed_gates": ["min_risk_reward", "per_stock_cap"],
  "failed_gate_reasons": {
    "min_risk_reward": "R:R 1.5 vs minimum 2.0",
    "per_stock_cap": "Post-trade HDFCLIFE exposure 33.3% (cap 25.0%)"
  }
}
```

A signal with RR = 1.5 passes the scan gate (≥ 1.5 → `BUY_GENERATED`) and passes the pre-trade validator (≥ 1.5), then is blocked by the phase20 execution gate (< 2.0). This is a silent blocker for signals with RR between 1.5 and 1.99 — they show `BUY_GENERATED` in the pipeline but never produce an `ORDER_EXECUTED`.

**Note**: The scan gate and the pre-trade validator are aligned at 1.5. The phase20 execution gate (settings-driven, default 2.0) is the outlier.

---

## Q3 — Were the 64 Aug 11 `ORDER_EXECUTED` events real or phantom?

### Answer: **PHANTOM — emitted by an external bot, never committed to any canonical trade ledger**

### Evidence

**DB query results for 2026-08-11 IST window (2026-08-10T18:30Z → 2026-08-11T18:30Z):**

| Table | Aug 11 rows |
|-------|------------|
| `pipeline_events` WHERE event_type IN (ORDER_EXECUTED, POSITION_OPENED) | **64 each** |
| `phase20_paper_trades` (canonical ledger) | **0** |
| `paper_trades` (legacy ledger) | **0** |

**Trade ID prefix in ORDER_EXECUTED payloads:**

```
Sample 1: trade_id = "BTT-16d1f82f54"  symbol=TCS    fill_price=2367.37
Sample 2: trade_id = "BTT-a0f89753dd"  symbol=GLAND  fill_price=2248.49
Sample 3: trade_id = "BTT-ca8827662a"  symbol=GLAND  fill_price=2248.49  (same price, ~5s later)
Sample 4: trade_id = "BTT-24768e5d2a"  symbol=GLAND  fill_price=2248.49  (same price, same second)
```

The phase20 executor generates trade IDs as `f"P20-{uuid.uuid4().hex[:10]}"` (line 448 of `phase20_executor.py`). The "BTT-" prefix is from a separate external intraday_bot process that emits pipeline events but does NOT write to the canonical `phase20_paper_trades` table.

**Additional evidence of scan-loop anomaly:**

| Metric | Expected | Aug 11 actual |
|--------|----------|--------------|
| SCAN_STARTED | ~6 per day | **89** |
| SYMBOL_SCANNED | ~306 per day (51 × 6) | **65,018** (≈730/scan start) |
| BUY_GENERATED | ~100–200 per day | **18,460** |

The 89 scan starts with 65,018 SYMBOL_SCANNED (≈ 730 per scan vs 51-symbol universe) indicates the scanner looped over the universe ~14× per scan run. Multiple identical GLAND executions at the same fill price within seconds confirm the loop was multiplying execution signals, not symbols.

**Verdict: Aug 11 was NOT a clean execution day.**
- The 64 `ORDER_EXECUTED` events are from an external bot ("BTT-" prefix), not from `phase20_executor.py`.
- Zero rows in any canonical or legacy trade table confirm no actual positions were opened.
- The system has **no verified instance** of a clean end-to-end paper trade lifecycle (signal → fill → exit → correct P&L) from any date.

---

## Current DB counts (all-time as of 2026-08-14)

| Event type | Count |
|-----------|-------|
| WATCH_GENERATED | 36,737 |
| BUY_GENERATED | 19,034 |
| RISK_REJECTED | 15,447 |
| ORDER_REJECTED | 3,065 |
| EXECUTION_SKIPPED_WITH_REASON | 67 |
| ORDER_EXECUTED | 65 (all "BTT-" prefix, external bot) |
| POSITION_OPENED | 65 (same, external bot) |
| POSITION_CLOSED | 26 (external bot) |
| phase20_paper_trades rows | **4** (all status=EXIT_PENDING, all dates Aug 4) |

---

## Supplementary finding — Aug 14 ORDER_REJECTED breakdown

All 203 `ORDER_REJECTED` events on Aug 14 come from `stage_detail=risk_agent_pre_trade` for a single cause:

| Symbol | Rejection reason | Count |
|--------|-----------------|-------|
| DRREDDY | position size ~₹10,790 = 21.6% of portfolio (limit 20.0%) | **~170** |
| GRASIM | position size ~₹10,110 = 20.2% of portfolio (limit 20.0%) | ~20 |
| BAJAJ-AUTO | position size ~₹11,700 = 23.4% of portfolio (limit 20.0%) | ~10 |
| BAJAJFINSV | position size ~₹10,178 = 20.4% of portfolio (limit 20.0%) | ~5 |

Every single ORDER_REJECTED on the current day is the position-size cap bug.  
**Fix is unambiguous and safe to implement (Phase 1B).**

---

*This report was produced by direct code trace of `live_scan_engine.py`, `phase20_executor.py`, `phase20_gates.py`, `risk_validation/pre_trade.py`, `ai_decision.py`, and `config.py`, cross-referenced against live DB query results.*
