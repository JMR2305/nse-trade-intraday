# Task #772 — Paper Bootstrap Mode: Low-Evidence Deadlock Fix

**Status:** ✅ Merged  
**Date:** 2026-08-17  
**Component:** Phase 20 Auto Paper Trading

---

## Problem

All 50 production symbols were permanently stuck at WATCH, making it impossible for the Phase 20 cycle to produce any closed trades or exit data.

### Root Cause Chain

```
6-month backtest window has 1–4 trades per symbol
  → low_evidence = True  (threshold: < 5 backtest trades)
  → confidence penalty applied
  → calibrated_confidence ≤ 65  (below BUY_CONF = 75.0)
  → all symbols → WATCH (never BUY)
  → paper_eligible = False
  → P20 cycle produces zero closed trades
  → low_evidence never clears (it needs backtest window to fill naturally)
  → deadlock
```

Paper trades **do not reduce** `low_evidence` — it clears only as the 6-month strategy walk-forward window accumulates ≥ 5 signals. Without any paper trades completing, the system had no path out.

---

## Solution: Parallel Bootstrap Track

A strictly parallel seeding mechanism that runs **alongside** the existing pipeline without modifying any confidence thresholds, gates, or the `paper_eligible` flag.

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| No threshold changes | `BUY_CONF` (75), `WATCH_CONF` (55), `paper_eligible` all untouched |
| Explicit opt-in | `bootstrap_paper_enabled` defaults **False** in `DEFAULT_SETTINGS` |
| Same confirmation invariant | Requires `auto_paper_entries` ON + `auto_paper_entries_confirmed_at` (two-layer: scheduler + executor) |
| Atomic per-scan guard | `kv_claim_once("bootstrap_scan:<scan_id>")` prevents concurrent/repeated ticks |
| Circuit breaker fail-closed | Errored or tripped breaker → bootstrap blocked |
| Slippage-aware sizing | Qty sized against worst-case fill: `price × (1 + slip_pct)` |
| Hard cap | Max ₹1,500 per trade, one trade per scan |
| Auto-disables | Stops when ledger reaches 20 closed trades |
| Full auditability | `trigger_source="BOOTSTRAP_AUTO"`, `fill_model="bootstrap_paper"` on every row |

---

## Safety Gates (in evaluation order)

```
bootstrap_paper_enabled = True  in settings?           → else: skip
auto_paper_entries + confirmed_at set?                 → else: skip (executor + scheduler both check)
circuit_breaker_tripped = False?                       → else: skip
kite_ltp verified in snapshot?                         → else: skip
scan has a scan_id?                                    → else: skip (can't guarantee idempotency)
kv_claim_once("bootstrap_scan:<id>") wins?             → else: skip (another process claimed it)
closed trades in ledger < 20?                          → else: auto-disabled
bootstrap OPEN trade already exists?                   → else: skip
candidates with bootstrap_eligible = True exist?       → else: skip
─── on selected best candidate (independent re-check) ──────────────────────────
low_evidence = True?                                   → else: normal BUY path unblocked
all_gates_passed = True?                               → else: hard risk gate failed
kite_ltp_available = True?                             → else: no live price
execution_price_source contains "kite"?                → else: non-Kite source rejected
worst-case fill ≤ ₹1,500?                              → else: skip stock
```

---

## Files Changed

### Python Backend (`artifacts/api-server/src/python/`)

| File | Change |
|------|--------|
| `phase20_store.py` | Registered `bootstrap_paper_enabled: False` in `DEFAULT_SETTINGS` (persistent via settings API) |
| `live_scan_engine.py` | Added `bootstrap_eligible` field (post-overlay), `BOOTSTRAP_MIN_*` constants, summary count, pipeline event payload |
| `market_scanner.py` | Added `bootstrap_eligible: bool = False` to `ScanItem` dataclass |
| `phase11_autonomous.py` | `get_open_positions_detail()` joins phase20 ledger for `trigger_source` + `fill_model` provenance |
| `phase20_executor.py` | `run_bootstrap_auto_entry()` — all safety gates, per-scan claim, independent gate re-verification, slippage-aware cap, pipeline event, notification |
| `phase20_scheduler.py` | `_manage_paper()` gates bootstrap on confirmed entries (first enforcement layer) |

### Frontend (`artifacts/trading-dashboard/`)

| File | Change |
|------|--------|
| `src/pages/AIPaperTraderPage.tsx` | Added `trigger_source?` and `fill_model?` to `OpenPosition` interface; amber **BOOTSTRAP** badge on open positions table when `trigger_source === "BOOTSTRAP_AUTO"` |

### Tests

| File | Count | Coverage |
|------|-------|----------|
| `tests/unit/test_bootstrap_paper_trade.py` | **37 tests, 37 passing** | Normal BUY→WATCH unchanged; eligible candidate creation; fill_model; qty cap (affordable + near-cap + slippage); highest-confidence selection; Kite LTP required; unauthenticated Kite refused; all-gates-passed required; circuit breaker blocked; P20 row with correct trigger_source; pipeline event emitted; exit engine compatibility; at-most-one-trade-per-scan; bypass regression (low_evidence/all_gates/kite_available/exec_source); per-scan kv_claim guard; concurrent tick blocked; no-scan-id skip; `DEFAULT_SETTINGS` default=False; executor-level confirmation refusal; scheduler gate logic |

---

## Operator Configuration

To enable bootstrap mode, operators must:

1. Enable and **confirm** auto paper entries (existing flow):
   ```
   Settings → Auto Paper Entries → Enable → confirm with text
   ```

2. Explicitly set `bootstrap_paper_enabled = True` via the settings API:
   ```json
   PATCH /phase20/settings
   { "bootstrap_paper_enabled": true }
   ```

Bootstrap automatically disables when the production ledger reaches **20 closed trades** — at that point the system has sufficient evidence for normal evidence-driven BUY signals.

---

## How to Identify Bootstrap Trades

- **API:** positions returned from `/phase11/portfolio/open-positions` include `trigger_source: "BOOTSTRAP_AUTO"` and `fill_model: "bootstrap_paper"` 
- **Dashboard:** amber **BOOTSTRAP** badge shown in the Open Positions table Stock column
- **Database:** all phase20 ledger rows carry `trigger_source = 'BOOTSTRAP_AUTO'`
- **Pipeline events:** `BOOTSTRAP_PAPER_TRADE_APPROVED` emitted before every trade creation

---

## Follow-Up Tasks Proposed

| Ref | Title | Category |
|-----|-------|----------|
| #775 | Show bootstrap-eligible WATCH symbols in the scan panel | next_steps |
| #776 | Confirm bootstrap auto-disables when ledger reaches 20 closed trades | incomplete_scope |
| #777 | Unify bootstrap and low_evidence thresholds into one config | tech_debt |
