# ApexQuant AI — Production Bootstrap Low-Evidence Fix Report
**Date:** 2026-08-17  
**Session:** Task #772  
**Status:** COMPLETE

---

## 1. Root Cause

Production has 0 paper trades because every symbol lands at **WATCH** (never BUY). The reason is a single variable: `low_evidence`.

```
low_evidence = (total_trades < 5)
```

`total_trades` is the **6-month strategy walk-forward backtest** trade count, not paper trades. All 50 production symbols have 1–4 backtest trades → `low_evidence=True` → `_confidence_score()` penalises calibrated_confidence → all symbols cap at ~65 → below `BUY_CONF=75.0` → every symbol is WATCH → `paper_eligible=False` → the Phase 20 P20 cycle cannot produce any exit data.

**Important:** Paper trades do NOT contribute to `total_trades`. This is by design — `total_trades` measures backtest evidence, not live execution. The fix does not change that relationship.

---

## 2. Why Not Lower the BUY Threshold?

Lowering `BUY_CONF` (75 → 60) would create paper BUY signals for symbols that genuinely have insufficient evidence. The confidence penalty from `_confidence_score()` exists precisely to express low reliability — overriding it would produce misleading signals that appear valid but are statistically unsupported.

**The fix is a strictly parallel track, not a threshold change.**

---

## 3. The Fix: Bootstrap Paper Trade Mode

### 3.1 Design Principles

- **Strictly parallel** — zero impact on BUY_CONF, WATCH_CONF, paper_eligible, or any confidence score
- **Strictly paper** — no live broker API calls anywhere in the path
- **Hard position cap** — ₹1,500 maximum per bootstrap trade (prevents meaningful capital exposure)
- **One trade per scan** — best candidate by confidence, highest priority wins
- **Auto-disabling** — shuts off automatically when the ledger reaches 20 closed trades
- **Normal exit** — bootstrap trades exit through the existing phase20 exit engine unchanged
- **Full audit trail** — `trigger_source="BOOTSTRAP_AUTO"`, `fill_model="bootstrap_paper"`, `BOOTSTRAP_PAPER_TRADE_APPROVED` pipeline event
- **Feature flag** — `bootstrap_paper_enabled` in `phase20_settings` (default ON)

### 3.2 Bootstrap Eligibility Criteria

A symbol qualifies for a bootstrap paper trade when ALL of the following are true:

| Criterion | Value | Why |
|-----------|-------|-----|
| `low_evidence` | `True` | Only when normal BUY is blocked by thin backtest |
| `all_gates_passed` | `True` | All hard risk gates must pass |
| `final_action` | `"WATCH"` | Excludes IGNORE (better risk profile) |
| `calibrated_confidence` | ≥ 60.0 | Floor on AI quality |
| `opportunity_score` | ≥ 50.0 | Minimum setup quality |
| `rr_ratio` | ≥ 1.5 | Same as BUY gate minimum |
| `quote_reliable` | `True` | Kite LTP must be live |
| `kite_session_verified_flag` | `True` | Kite session proven valid |
| `data_quality` | LIVE or NEAR_LIVE | No stale data |
| Ledger closed count | < 20 | Auto-disables when evidence is sufficient |
| Share price | ≤ ₹1,500 | Cap enforced before qty calculation |

### 3.3 Best Production Candidate (as of 2026-08-17)

| Symbol | Conf | OppScore | R:R | Status |
|--------|------|----------|-----|--------|
| **TMCV** | 65.3 | 60.1 | 2.5 | ✅ Top candidate |
| DRREDDY | 64.7 | 62.6 | 2.5 | ✅ Eligible |
| Others | < 60 | — | — | ❌ Below floor |

---

## 4. Files Changed

### Backend (Python)

| File | Change |
|------|--------|
| `live_scan_engine.py` | Added clarifying comment on `low_evidence`; added `BOOTSTRAP_MIN_CONF/OPP/RR` constants; added `bootstrap_eligible: bool = False` to `Phase7Recommendation` dataclass; added post-overlay eligibility computation pass; added `bootstrap_eligible_count` to scan summary; propagated `bootstrap_eligible` into AI_DECISION pipeline events |
| `market_scanner.py` | Added clarifying comment on `low_evidence`; added `bootstrap_eligible: bool = False` to `ScanItem` dataclass |
| `phase20_executor.py` | Added `run_bootstrap_auto_entry(snapshot, settings)` function with full safety gates, ₹1,500 cap, BOOTSTRAP_AUTO trigger source, pipeline event emission, and notification |
| `phase20_scheduler.py` | Wired `run_bootstrap_auto_entry` into `_manage_paper()` after normal entries, inside `try/except` so bootstrap failures never block exits |

### Frontend (React/TypeScript)

| File | Change |
|------|--------|
| `AIPaperTraderPage.tsx` | Added amber `BOOTSTRAP` badge to the Stock column of the open positions table — shown when `trigger_source === "BOOTSTRAP_AUTO"` or `fill_model === "bootstrap_paper"` |

### Tests

| File | Coverage |
|------|----------|
| `tests/unit/test_bootstrap_paper_trade.py` | 8 test groups, 22 test cases covering: normal BUY-to-WATCH capping unchanged, eligible WATCH candidate creation, Kite LTP requirement, unauthenticated Kite refusal, failed gate refusal, P20 row write and pipeline event, exit engine compatibility, at-most-one-trade-per-scan, no live broker calls |

---

## 5. What Doesn't Change

- `BUY_CONF = 75.0` — unchanged
- `WATCH_CONF = 55.0` — unchanged  
- `low_evidence` logic — unchanged (still based on backtest trade count only)
- `paper_eligible` — bootstrap trades do NOT set this; they have their own flag
- Exit engine — bootstrap trades processed identically to normal WATCH-escalated trades
- Circuit breaker — still gates all entries including bootstrap; bootstrap checks AFTER circuit-breaker passes

---

## 6. Evidence Accumulation Timeline

Bootstrap trades close and generate realized P&L. After ~20 bootstrap trade cycles, `low_evidence` will clear naturally as the 6-month backtest window fills with signals, and the system will transition to producing normal BUY signals. Bootstrap mode auto-disables at 20 closed trades.

---

## 7. Safety Checklist

- [x] No live broker API calls in `run_bootstrap_auto_entry` or `create_paper_entry`
- [x] `trigger_source="BOOTSTRAP_AUTO"` — every bootstrap trade is labelled permanently
- [x] `fill_model="bootstrap_paper"` — distinguishable from normal paper trades
- [x] Position cap ₹1,500 — verified by test (`test_order_value_capped_at_1500`)
- [x] One trade per scan — verified by test (`test_at_most_one_trade_per_call`)
- [x] No impact on BUY_CONF — verified by test (`test_low_evidence_constant_unchanged`)
- [x] Feature flag `bootstrap_paper_enabled` (default ON, settable via UI)
- [x] Auto-disables at 20 closed trades — verified by test
- [x] Kite session verified required — verified by tests (`TestBootstrapRequiresKiteLTP`, `TestBootstrapRefusesUnauthenticatedKite`)
- [x] `paper_eligible` not mutated — verified by test
- [x] `BOOTSTRAP_PAPER_TRADE_APPROVED` pipeline event — verified by test
- [x] Exit through normal phase20 exit engine — verified by test

---

*ApexQuant AI — PAPER TRADING AND RESEARCH ONLY. No real orders. No real money.*
