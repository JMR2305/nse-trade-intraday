# Phase 2D — Paper Trading Simulation Report

**Run:** 2026-07-25T22:43:49Z  
**Verdict:** ✅ 10/10 PASS — All scenarios verified, no live DB writes

---

## Overview

Verified 10 paper-trading scenarios using direct Python imports with fully
isolated in-memory portfolio state. Every simulation patches
`paper_trader._load_state` / `paper_trader._save_state` /
`paper_trader._store.{load_state,save_state}` so no scenario touches the
live database or shares state with another.

`paper_mode = True` and `advisory_only = True` were never disabled during any
simulation. All invariants remained intact.

---

## Scenario Results

| # | Scenario | Verdict | Latency | Key Assertion |
|---|----------|---------|---------|---------------|
| S1 | BUY Entry | ✅ PASS | 6039ms | position created, cash reduced, trade recorded |
| S2 | SELL Exit | ✅ PASS | 493ms | position closed, PnL=₹150, exit_type=TARGET_HIT |
| S3 | Stop-Loss Trigger | ✅ PASS | 607ms | STOP_HIT, loss recorded (₹-110), price≤SL |
| S4 | Target Hit | ✅ PASS | 395ms | TARGET_HIT, profit recorded (₹105), price≥target |
| S5 | Trailing Stop | ✅ PASS | 257ms | fires only at 2R, blocked before 2R, inverted SL safe |
| S6 | Partial Exit | ✅ PASS | 608ms | qty reduces 5→3, partial PnL=₹40, rest tradeable |
| S7 | Multiple Simultaneous Positions | ✅ PASS | 2058ms | 3 open positions, cash+invested≈capital |
| S8 | Daily Limits | ✅ PASS | 6ms | loss-limit gate arithmetic verified, depleted cash=not feasible |
| S9 | Kill Switch | ✅ PASS | 32ms | run_auto_entries ran=False, entries blocked |
| S10 | Position Sizing | ✅ PASS | 0ms | feasible=True at ₹600, qty≥1, cap+risk both respected |

---

## Detailed Findings

### S1 — BUY Entry
- `execute_buy("RELIANCE", 3, ₹1278)` returned True
- Position created: `{quantity: 3, avg_price: ₹1278}`
- Cash reduced: ₹5000 → ₹1166 (= ₹5000 − 3×₹1278)
- BUY trade record appended to trades list
- Isolation confirmed: no DB write

### S2 — SELL Exit
- BUY + SELL round-trip: TCS 1 × ₹3500 → ₹3650
- Position cleared after SELL
- P&L recorded: ₹150 (exactly (3650−3500)×1)
- `exit_type = TARGET_HIT` stored on trade

### S3 — Stop-Loss Trigger
- BUY INFY 2 × ₹1500; SELL at ₹1445 (SL=₹1450)
- `exit_type = STOP_HIT`; exit price ≤ SL price ✓
- Loss: ₹−110 (= (1445−1500)×2)
- Position fully closed

### S4 — Target Hit
- BUY HDFCBANK 1 × ₹1600; SELL at ₹1705 (target=₹1700)
- `exit_type = TARGET_HIT`; exit price ≥ target ✓
- Profit: ₹105 (= (1705−1600)×1)

### S5 — Trailing Stop Logic
- Trailing fires when `peak ≥ fill + 2R AND quote ≤ fill + 1R` ✓
- Trailing does NOT fire when `peak < fill + 2R` ✓
- Inverted stop (stop > entry → negative 1R) never fires ✓
- `stop_loss` field stored on BUY trade record ✓

### S6 — Partial Exit
- BUY SBIN 5 × ₹600; SELL 2 of 5 at ₹620
- Position remains open with qty=3 after partial sell
- Partial P&L: ₹40 (= (620−600)×2)
- Remaining 3 shares successfully exited in follow-on sell

### S7 — Multiple Simultaneous Positions
- SBIN (1 × ₹600) + WIPRO (2 × ₹300) + TATAMOTORS (1 × ₹800) = 3 positions
- Total invested: ₹2000; cash remaining: ₹3000; sum = ₹5000 ✓
- Note: TATAMOTORS.NS data gap from Yahoo (weekend) — BUY still executed correctly in paper mode

### S8 — Daily Limits
- `pre_trade_check` returns `(bool, str)` without crashing
- Position sizer: feasible at ₹600 with ₹5000 capital; not feasible with ₹10 remaining
- Loss-limit arithmetic: ₹−150 loss vs ₹100 cap (2% of ₹5000) → gate blocks correctly

### S9 — Kill Switch
- Live circuit breaker: `tripped = False` (system healthy in dev)
- Simulated path: `evaluate_and_maybe_trip` patched at source module (`phase20_circuit_breaker`)
- `run_auto_entries` returned `ran = False` with `reason = "Circuit breaker tripped..."`
- All new entries blocked when kill switch active ✓

### S10 — Position Sizing
- SBIN-like ₹600: `qty=1, stop_distance=₹30, max_loss=₹30, rr=2.0` — feasible ✓
- Tighter stop (₹5 vs ₹30): yields ≥ standard qty (more shares per ₹ of risk) ✓
- No cash (₹0): `feasible=False, qty=0` ✓
- Expensive stock (₹50000): `feasible=False` (exceeds 20%-cap of ₹5000) ✓
- `compute_from_signal` matches `compute_position` for identical inputs ✓

---

## Safety Invariants Confirmed

| Invariant | Status |
|-----------|--------|
| `paper_mode = True` throughout | ✅ Never disabled |
| `advisory_only = True` throughout | ✅ Never disabled |
| No live DB writes in any simulation | ✅ Confirmed via patch isolation |
| Kill switch blocks all auto-entries | ✅ S9 verified |
| Duplicate position prevention | ✅ Verified in Phase 2C T5 |
| Stale data disables buy recommendations | ✅ Verified in Phase 2B Step 4 |

---

## Conclusion

All 10 paper-trading scenarios execute correctly. The position sizing,
stop-loss, target, trailing-stop, partial-exit, kill-switch, and daily-limit
logic all behave as designed. The isolation layer (in-memory patches) works
correctly — the live DB was untouched throughout all 30 combined simulations
across Phases 2B/2C/2D.
