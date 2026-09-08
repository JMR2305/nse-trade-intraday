# ApexQuant AI — Task #772 Bootstrap Activation Report
**Generated:** 2026-08-17T08:10 IST  
**Prepared by:** Replit Agent  
**Controlling document:** TASK_772_BOOTSTRAP_PAPER_TRADE_SUMMARY.md

---

## Executive Summary

Bootstrap paper mode has been **activated** (`bootstrap_paper_enabled` set to `true`). All
operator settings are correctly configured and the circuit breaker is clear. The scheduler is
running and the per-scan atomic guard (`kv_claim_once`) is working correctly.

**No bootstrap trade was created in the current session.** The single safety gate blocking entry
is an **inactive Kite session** — `kite_ltp_session_verified: false`. This is correct, expected,
and safe behaviour. The moment an operator authenticates a Zerodha session, the next scan will
produce bootstrap_eligible candidates and the first bootstrap trade will fire automatically.

No live broker API has been called. No real orders exist.

---

## TASK 1 — Settings Verification

| Setting | Expected | Actual | Status |
|---------|----------|--------|--------|
| `auto_paper_entries` | `true` | `true` | ✅ |
| `auto_paper_entries_confirmed_at` | set | `2026-08-04T04:18:08Z` | ✅ |
| `bootstrap_paper_enabled` | `true` | `true` (enabled this session) | ✅ |
| Circuit breaker tripped | `false` | `false` | ✅ |
| `KITE_LTP_OVERLAY_ENABLED` | `true` | `true` | ✅ |
| `kite_ltp_session_verified` | `true` | **`false`** | ❌ BLOCKER |
| `quote_reliable` (all symbols) | `true` | **`false`** | ❌ (depends on Kite) |
| `fill_model` | `SLIPPAGE_ADJUSTED` | `SLIPPAGE_ADJUSTED` | ✅ |
| `slippage_pct` | `0.15` | `0.15` | ✅ |

**Circuit breaker detail (from API):**
```
tripped: false
consecutive_losses: 0  (limit: 3)
daily_realized_pnl: 0  (limit: ₹1,500 loss)
closed_trades: 0
```

---

## TASK 2 — Bootstrap Setting Activation

`auto_paper_entries` is already confirmed (confirmed at `2026-08-04T04:18:08Z`) — no additional
confirmation was required.

`bootstrap_paper_enabled` was `false` (the safe-off default) and was set to `true` via:
```python
from phase20_store import update_settings
update_settings({'bootstrap_paper_enabled': True}, confirmation_text=None)
```

**Verified via API (`GET /api/phase20/settings`):**
```
bootstrap_paper_enabled: true
auto_paper_entries: true
auto_paper_entries_confirmed_at: 2026-08-04T04:18:08Z
```

---

## TASK 3 — Bootstrap Eligible Candidates (Latest Scan)

**Scan:** `ce9cc86b3d08` · `2026-08-17T08:02:17Z`  
**Universe:** 51 symbols · **WATCH:** 20 · **BUY:** 0 · **IGNORE/AVOID:** 30+1 error  
**paper_eligible_count:** 0 · **bootstrap_eligible_count:** 0

### Why 0 bootstrap_eligible?

The bootstrap eligibility flag is computed **post-overlay** in `live_scan_engine.py` and requires:
```
kite_session_verified_flag = True   ← FAILING for all 51 symbols
kite_ltp_available = True           ← FAILING for all 51 symbols
```

Because `kite_ltp_session_verified: false` in the snapshot safety block, neither condition can
be met. The Kite LTP overlay is enabled but falls back to yfinance daily-close prices when
no authenticated session exists.

### Top WATCH Candidates — Ready Once Kite Session Activates

These symbols pass all fundamental gates (`all_gates_passed=True`, `low_evidence=True`) and
will be bootstrap_eligible the moment `kite_ltp_session_verified` becomes `true`.

| Rank | Symbol | Conf | Opp Score | R:R | low_ev | agp | LTP (yf fallback) | Worst-fill | Bootstrap blocker |
|------|--------|------|-----------|-----|--------|-----|--------------------|------------|-------------------|
| 1 | **INDUSINDBK** | 64.8 | 64.6 | 3.0 | ✅ | ✅ | ₹1,014.00 | ₹1,015.52 | kite_ltp_available=False |
| 2 | **DRREDDY** | 64.7 | 62.6 | 2.5 | ✅ | ✅ | ₹1,192.80 | ₹1,194.59 | kite_ltp_available=False |
| 3 | SBILIFE | 59.7 | 55.5 | 1.5 | ✅ | ✅ | ₹1,787.20 | ₹1,789.88 | kite_ltp_available=False + conf<60 |
| 4 | GRASIM | 58.4 | 60.0 | 3.0 | ✅ | ✅ | ₹3,268.70 | ₹3,273.60 | kite_ltp_available=False + conf<60 |
| 5 | HINDUNILVR | 57.7 | 52.5 | 1.5 | ✅ | ✅ | ₹2,065.00 | ₹2,068.10 | kite_ltp_available=False + conf<60 |
| 6 | TMPV | 57.0 | 55.7 | 2.5 | ✅ | ✅ | ₹332.45 | ₹332.95 | kite_ltp_available=False + conf<60 |
| 7 | BAJAJ-AUTO | 56.7 | 57.3 | 3.0 | ✅ | ✅ | ₹11,735.00 | ₹11,752.60 | kite_ltp_available=False + conf<60 |
| 8 | BAJAJFINSV | 56.0 | 59.7 | 3.0 | ✅ | ✅ | ₹2,015.60 | ₹2,018.62 | kite_ltp_available=False + conf<60 |
| 9 | TECHM | 56.0 | 54.1 | 1.5 | ✅ | ✅ | ₹1,609.00 | ₹1,611.41 | kite_ltp_available=False + conf<60 |
| 10 | BHARTIARTL | 56.0 | 54.0 | 1.5 | ✅ | ✅ | ₹1,984.10 | ₹1,987.08 | kite_ltp_available=False + conf<60 |

**Predicted first bootstrap trade once Kite connects:** INDUSINDBK
- Confidence 64.8 ≥ BOOTSTRAP_MIN_CONF (60) ✅
- Opportunity score 64.6 ≥ BOOTSTRAP_MIN_OPP (50) ✅
- R:R 3.0 ≥ BOOTSTRAP_MIN_RR (1.5) ✅
- Worst-case fill ₹1,015.52 ≤ ₹1,500 cap ✅  
- Qty = floor(1500 ÷ 1015.52) = **1 share** · Notional = ₹1,015.52

> Note: SBILIFE, GRASIM, HINDUNILVR, BAJAJ-AUTO, BAJAJFINSV are also `all_gates_passed=True`
> and `low_evidence=True` but sit below BOOTSTRAP_MIN_CONF=60. They will gain eligibility if
> confidence rises on subsequent scans or if a higher-confidence WATCH symbol appears.

---

## TASK 4 — Scheduler Execution Trace

The bootstrap scheduler **did run** on the latest scan. Proof from the phase20_kv table:

```
key:         bootstrap_scan:ce9cc86b3d08
updated_at:  2026-08-17T08:03:12Z
```

This KV claim was made 1 minute after the scan snapshot (`08:02:17Z`). The per-scan
`kv_claim_once` guard fired correctly, consumed the scan_id, and then `run_bootstrap_auto_entry`
returned `ran=False` because there are 0 bootstrap_eligible candidates.

**Gate that returned false:**
```
Snapshot safety check:
  kite_ltp_session_verified: False
  → kite_session_verified_flag: False on all recs
  → bootstrap_eligible: False on all 51 symbols
  → "No bootstrap_eligible WATCH candidates in snapshot"
```

No paper trade was attempted. No DB write to `phase20_paper_trades`. Correct.

### Current phase20_paper_trades (4 rows, all pre-existing AUTO entries):

| Trade ID | Symbol | Status | Trigger | Fill Price | Qty | Created |
|----------|--------|--------|---------|-----------|-----|---------|
| P20-4a5f909738 | BAJFINANCE | EXIT_PENDING | AUTO | ₹1,100.05 | 8 | 2026-08-07 |
| P20-83aa1be8f9 | GRASIM | EXIT_PENDING | AUTO | ₹3,223.63 | 3 | 2026-08-05 |
| P20-a205b1ef09 | DIVISLAB | EXIT_PENDING | AUTO | ₹8,370.04 | 1 | 2026-08-04 |
| P20-acad172b74 | TRENT | EXIT_PENDING | AUTO | ₹3,082.42 | 3 | 2026-08-04 |

- All 4 are `trigger_source='AUTO'` (normal entries, not BOOTSTRAP_AUTO) ✅
- All 4 are `fill_model='SLIPPAGE_ADJUSTED'` (normal fill, not bootstrap_paper) ✅
- 0 BOOTSTRAP trades in DB ✅
- 0 CLOSED trades in DB (explains why bootstrap auto-disable threshold of 20 is far away)

---

## TASK 5 — Safety Confirmations

### 1. bootstrap_paper_enabled
```
true  (confirmed via GET /api/phase20/settings)
```

### 2. auto_paper_entries confirmed
```
auto_paper_entries: true
auto_paper_entries_confirmed_at: 2026-08-04T04:18:08Z
```
Both layers verified (scheduler gate + executor defense-in-depth).

### 3. Top eligible WATCH candidates
See Task 3 table above. INDUSINDBK and DRREDDY are the top two when Kite connects.

### 4. Bootstrap trade created?
**No.** The safety gate (Kite session not verified) correctly blocked all candidates.

### 5. Exact safety gate that blocked entry

```
Gate:     kite_ltp_session_verified
Value:    False  (in snapshot safety block)
Effect:   kite_ltp_available = False on all 51 recs
          kite_session_verified_flag = False on all 51 recs
          bootstrap_eligible = False on all 51 recs
Result:   "No bootstrap_eligible WATCH candidates in snapshot"
          → ran = False
```

This is the **correct and intended** safety behaviour. Bootstrap is explicitly designed to
require a live Kite LTP so the execution price is from the real market, not a stale daily close.

### 6. Live orders remain disabled

From snapshot safety block:
```json
{
  "no_real_orders": true,
  "paper_trading_only": true,
  "no_live_broker_calls": true,
  "kite_connected": false,
  "research_only": true
}
```

No real Zerodha orders have been placed. No broker order API has been called.

### 7. DB proof — trigger_source field

All 4 existing `phase20_paper_trades` rows have `trigger_source='AUTO'`.  
No row has `trigger_source='BOOTSTRAP_AUTO'` or `fill_model='bootstrap_paper'`.  

When the first bootstrap trade is created it will be distinguishable:
- DB column `trigger_source = 'BOOTSTRAP_AUTO'`
- DB column `fill_model = 'bootstrap_paper'`
- Dashboard: amber **BOOTSTRAP** badge in the Open Positions table

---

## What the Operator Must Do Next

Bootstrap is fully wired and enabled. The **only remaining action** to get the first trade:

### Step 1 — Authenticate Zerodha Kite Session

Complete the Zerodha OAuth flow (Kite Login → 2FA → access token). The system will detect
the session on the next scheduler tick and update:
- `kite_ltp_session_verified: true`
- `kite_connected: true`
- All WATCH symbols with Kite LTP will get `kite_ltp_available: true`

### Step 2 — Wait for Next Scan (≤ 4 minutes)

The scheduler runs every 4 minutes. On the next successful scan with a verified Kite session:

1. INDUSINDBK or DRREDDY will receive `bootstrap_eligible: true`
2. `run_bootstrap_auto_entry()` will pick the highest-confidence candidate
3. One paper trade will be created:
   ```
   symbol:         INDUSINDBK (or highest-confidence eligible)
   trigger_source: BOOTSTRAP_AUTO
   fill_model:     bootstrap_paper
   quantity:       1 share
   max notional:   ≤ ₹1,500
   ```
4. BOOTSTRAP badge will appear in the dashboard Open Positions table
5. `BOOTSTRAP_PAPER_TRADE_APPROVED` pipeline event will be emitted

### Step 3 — Watch the Trade Count

Bootstrap auto-disables when `phase20_paper_trades` reaches **20 CLOSED** rows. Currently at 0.
Normal AUTO entries closing will also count toward this threshold.

---

## System Health Summary

| Check | Status | Notes |
|-------|--------|-------|
| API server | ✅ Running | Port 8080 |
| Scanner scheduler | ✅ Running | 4-min interval, scans firing |
| Bootstrap code merged | ✅ | Task #772 merged |
| `bootstrap_paper_enabled` | ✅ | Enabled this session |
| `auto_paper_entries` confirmed | ✅ | 2026-08-04 |
| Circuit breaker | ✅ Clear | 0 consecutive losses |
| Per-scan kv_claim_once | ✅ Working | Claimed scan ce9cc86b3d08 |
| Kite session | ❌ Not active | **Action required** |
| Live orders | ✅ Disabled | paper_trading_only=true |
| Bootstrap trades in DB | — | 0 (none yet — expected) |
| EXIT_PENDING positions | ⚠️ 4 | Pre-existing AUTO entries since Aug 4–7 |
