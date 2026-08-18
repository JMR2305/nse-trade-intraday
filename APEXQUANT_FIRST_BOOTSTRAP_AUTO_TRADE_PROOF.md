# APEXQUANT_FIRST_BOOTSTRAP_AUTO_TRADE_PROOF

**Generated:** 2026-08-18 ~09:30 IST  
**Controlling document:** APEXQUANT_AI_SOP_v5.0.html  
**Production URL verified:** https://nse-trade-intraday.replit.app  

---

## VERDICT SUMMARY

> **NO BOOTSTRAP_AUTO TRADE HAS BEEN CREATED YET.**

The bootstrap pipeline is alive and selecting candidates. HDFCLIFE has been
selected, approved, and then rejected 3 times since market open. The rejection
is caused by a known architectural gap: slippage applied to the fill price
compresses HDFCLIFE's R:R below the 1.5 minimum at the pre-trade re-check
stage. DRREDDY (R:R 2.5, ample headroom) is also eligible but is not attempted
after HDFCLIFE fails — only one candidate is tried per bootstrap run.

No live orders were placed. All safety gates are intact.

---

## 1. PRODUCTION ENVIRONMENT PROOF

| Item | Value |
|---|---|
| Database | Neon PostgreSQL 16.14 (`neondb`) |
| Production URL | https://nse-trade-intraday.replit.app |
| Dev domain | NOT used (*.replit.dev excluded) |
| IST time at check | 2026-08-18 09:29:57 IST |
| Market status | OPEN (NSE regular session) |
| Phase20 settings source | `phase20_settings` table, row id=1, production Neon DB |
| Paper trades source | `phase20_paper_trades` table, production Neon DB |
| Latest production scan_id | `e070bac6fcbc` (completed 09:27:56 IST) |

**CONFIRMED: All queries run against the production Neon database, not a dev
replica or local port.**

---

## 2. SAFETY PROOF — NO LIVE ORDERS

| Check | Evidence |
|---|---|
| Execution mode default | `ExecutionMode.PAPER_TRADING` (execution_engine.py line 154) |
| Live path | `place_order_live()` is only reachable when mode = `LIVE_ASSISTED` — never reached in PAPER_TRADING |
| Bootstrap orders | Write to `phase20_paper_trades` only — confirmed by 0 rows in table |
| Kite usage | Quotes/LTP only (`kite_ltp`, `kite_live_ltp` price source) — no `place_order` / `modify_order` / `cancel_order` calls |
| BOOTSTRAP_PAPER_TRADE_APPROVED payload | Explicitly states: *"No live broker API called."* |
| ORDER_REJECTED payload | Rejected at `risk_agent_pre_trade` stage — never reached broker API |
| phase20_paper_trades row count | **0** — no trades created, no fills simulated, no broker calls made |

**CONFIRMED: PAPER TRADING ONLY. No live broker orders placed or attempted.**

---

## 3. BOOTSTRAP SETTINGS PROOF (PRODUCTION)

Settings from `phase20_settings` table (production DB), row id=1:

| Setting | Value | Expected | Pass? |
|---|---|---|---|
| `bootstrap_paper_enabled` | **true** | true | ✅ |
| `auto_paper_entries` | **true** | true | ✅ |
| `auto_paper_entries_confirmed_at` | **2026-08-10T03:31:14Z** | set | ✅ |
| `_BOOTSTRAP_MAX_CLOSED_TRADES` (code constant) | **20** | — | ✅ |
| Current CLOSED trade count | **0** | < 20 | ✅ |
| Current OPEN trade count | **0** | 0 | ✅ |
| `circuit_breaker_tripped` | **no KV entry** (= not tripped) | false | ✅ |
| `daily_realized_pnl` | **₹0.00** | — | ✅ |
| `consecutive_losses` | **no KV entry** (= 0) | 0 | ✅ |
| `_BOOTSTRAP_MAX_ORDER_VALUE` (code constant) | **₹1,500** | ≤ ₹1,500 | ✅ |
| `_BOOTSTRAP_MIN_RR` (code constant) | **1.5** | ≥ 1.5 at scan | ✅ |
| `scan_interval_minutes` | **5** | — | ✅ |
| `min_confidence` (settings gate) | 75.0 | — | (bootstrap bypasses) |
| `min_risk_reward` (settings gate) | 2.0 | — | (bootstrap uses 1.5) |

Starting capital: ₹50,000 (cash column in `paper_portfolio`, pnl_history has 1 point = initial seed).

---

## 4. KITE LTP OVERLAY PROOF

From latest scan snapshot `e070bac6fcbc` (09:27:56 IST):

| Item | Value |
|---|---|
| `KITE_LTP_OVERLAY_ENABLED` | true (all 11 requested symbols show `kite_live_ltp`) |
| `execution_price_source` | `kite_live_ltp` for all symbols |
| `current_price_source` | `kite_live_ltp` for all symbols |
| `indicator_source` | `yfinance_daily_bars` (scan uses daily candles — correct) |
| `quote_reliable` | **true** for all 11 symbols |
| `kite_ltp_available` | **true** for all 11 symbols |

**CONFIRMED: Kite LTP overlay is live. Prices are from Kite direct quotes, not yfinance.**

### Requested Symbol Detail (scan e070bac6fcbc, 09:27:56 IST)

| Symbol | Action | Confidence | Opp Score | R:R | yf Close | Kite LTP | Price Src | Quote Reliable | Bootstrap Eligible |
|---|---|---|---|---|---|---|---|---|---|
| HDFCLIFE | WATCH | 73.6* | 63.9 | 1.50 | 539.10 | 539.20 | kite_live_ltp | ✅ true | ✅ **true** |
| DRREDDY | WATCH | 62.6* | 62.6 | 2.50 | 1187.00 | 1186.40 | kite_live_ltp | ✅ true | ✅ **true** |
| INDUSINDBK | WATCH | — | 58.4 | 3.00 | 1018.20 | 1017.70 | kite_live_ltp | ✅ true | ❌ false |
| BAJAJ-AUTO | WATCH | — | 57.4 | 3.00 | 11752.00 | 11751.00 | kite_live_ltp | ✅ true | ❌ false |
| TMCV | WATCH | — | 51.9 | 3.00 | 468.40 | 468.60 | kite_live_ltp | ✅ true | ❌ false |
| TMPV | WATCH | — | 54.2 | 2.50 | 330.40 | 330.25 | kite_live_ltp | ✅ true | ❌ false |
| GRASIM | WATCH | — | 57.2 | 3.00 | 3273.00 | 3272.70 | kite_live_ltp | ✅ true | ❌ false |
| BAJFINANCE | WATCH | — | 51.7 | 3.00 | 1091.80 | 1092.10 | kite_live_ltp | ✅ true | ❌ false |
| TCS | WATCH | — | 52.5 | 1.50 | 2299.00 | 2297.80 | kite_live_ltp | ✅ true | ❌ false |
| HEROMOTOCO | IGNORE | — | 46.7 | 2.50 | 5766.50 | 5766.50 | kite_live_ltp | ✅ true | ❌ false |
| RELIANCE | IGNORE | — | 30.8 | 2.50 | 1325.60 | 1324.80 | kite_live_ltp | ✅ true | ❌ false |

\* Calibrated confidence from BOOTSTRAP_PAPER_TRADE_APPROVED event payload (scan snapshot stores raw confidence without calibration).

Non-bootstrap-eligible symbols have `low_evidence=true` but fail other bootstrap gates (likely `min_confidence` or `min_opportunity_score`). INDUSINDBK, previously a candidate, is now confidence-gated.

`indicator_source = yfinance_daily_bars` ✅ (technical indicators always from yfinance — correct per design).

---

## 5. BOOTSTRAP CANDIDATES (LATEST SCAN)

Two bootstrap_eligible candidates in scan `e070bac6fcbc`:

| Rank | Symbol | Confidence | Opp Score | R:R | low_evidence | bootstrap_eligible | Kite LTP | Stop Loss | Target | Est. Fill (+ 0.15% slip) | Qty | Notional |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **HDFCLIFE** | 73.6 | 63.9 | 1.50 | true | ✅ | 539.20 | 524.87 | — | 540.01 | 2 | **₹1,080.02** |
| 2 | DRREDDY | 62.6 | 62.6 | 2.50 | true | ✅ | 1186.40 | 1138.16 | — | 1188.18 | 1 | **₹1,188.18** |

Both within ₹1,500 cap. Both have live Kite LTP. HDFCLIFE ranked first by opportunity_score (63.9 > 62.6).

---

## 6. WHETHER A BOOTSTRAP_AUTO TRADE WAS CREATED

**NO.**

```
SELECT COUNT(*) FROM phase20_paper_trades
→ 0
```

`phase20_paper_trades` has **zero rows** in production. No BOOTSTRAP_AUTO trade
(or any other paper trade) exists.

---

## 7. EXACT GATE THAT BLOCKED IT

The bootstrap pipeline ran 3 times today (09:16, 09:22, 09:28 IST). Each time
HDFCLIFE was selected, approved, and then rejected at the same gate.

### Gate Chain for HDFCLIFE (all 3 scans — identical result)

| Gate | Check | Expected | Actual | Pass? |
|---|---|---|---|---|
| 1 | `bootstrap_paper_enabled` | true | **true** | ✅ |
| 2 | `auto_paper_entries` confirmed | set | **2026-08-10T03:31:14Z** | ✅ |
| 3 | circuit_breaker clear | not tripped | **not tripped** | ✅ |
| 4 | Kite verified / overlay live | true | **true** | ✅ |
| 5 | valid scan_id | non-null | **e070bac6fcbc** | ✅ |
| 6 | `kv_claim_once` | claim succeeds | **claimed** (APPROVED event emitted) | ✅ |
| 7 | closed trades < threshold | < 20 | **0** | ✅ |
| 8 | no existing OPEN bootstrap trade | 0 positions | **0 open trades** | ✅ |
| 9 | bootstrap_eligible candidates exist | ≥ 1 | **2 (HDFCLIFE, DRREDDY)** | ✅ |
| 10 | top candidate re-check (scan-level R:R ≥ BOOTSTRAP_MIN_RR) | ≥ 1.5 | **1.50** (exactly) | ✅ |
| 11 | max notional cap | ≤ ₹1,500 | **₹1,080** | ✅ |
| 12 | duplicate position check | no existing HDFCLIFE position | **none** | ✅ |
| 13 | **pre-trade risk_agent re-check** (slippage-adjusted R:R) | ≥ 1.5 | **1.35–1.44** ❌ | **FAILED** |

### Gate 13 — Root Cause Explained

The bootstrap executor uses the Kite LTP as the entry reference. Before placing
the simulated order, the execution engine's pre-trade risk agent recomputes R:R
using the **slippage-adjusted fill price**:

```
slippage_pct = 0.15%
worst_fill   = kite_ltp × (1 + 0.0015)

Scan 90485405f6c5 (09:16):  kite_ltp=539.30 → fill=540.11 → R:R=1.44  (rejected: < 1.5)
Scan 5b9ddd5fbb4c (09:22):  kite_ltp=539.75 → fill=540.56 → R:R=1.36  (rejected: < 1.5)
Scan e070bac6fcbc (09:28):  kite_ltp=539.20 → fill=540.01 → R:R=1.35  (rejected: < 1.5)
```

HDFCLIFE's stop loss (524.87) is close enough to the entry that any positive
slippage compresses R:R below 1.5. At scan time R:R = exactly 1.50 (borderline).
A 0.15% price move upward is sufficient to fail the gate.

**This is correct safety behavior** — the risk agent should always re-check with
the actual fill price. The problem is architectural:

1. `_BOOTSTRAP_MIN_RR = 1.5` is applied at both scan selection AND pre-trade
   check, with no slippage budget built into the scan-level filter.
2. Only one candidate is tried per bootstrap run. After HDFCLIFE fails, DRREDDY
   (R:R 2.5 — would easily survive slippage) is **not attempted**.

### Evidence from Pipeline Events

```
BOOTSTRAP_PAPER_TRADE_APPROVED @ 09:16:35 — HDFCLIFE — rr_ratio=1.5, kite_ltp=539.30, notional=₹1,080.22
ORDER_REJECTED              @ 09:16:35 — HDFCLIFE — "reward:risk 1.44 is below minimum 1.5" (gate: RR_RATIO_INSUFFICIENT)

BOOTSTRAP_PAPER_TRADE_APPROVED @ 09:22:14 — HDFCLIFE — rr_ratio=1.5, kite_ltp=539.75, notional=₹1,081.12
ORDER_REJECTED              @ 09:22:14 — HDFCLIFE — "reward:risk 1.36 is below minimum 1.5" (gate: RR_RATIO_INSUFFICIENT)

BOOTSTRAP_PAPER_TRADE_APPROVED @ 09:28:10 — HDFCLIFE — rr_ratio=1.5, kite_ltp=539.20, notional=₹1,080.02
ORDER_REJECTED              @ 09:28:10 — HDFCLIFE — "reward:risk 1.35 is below minimum 1.5" (gate: RR_RATIO_INSUFFICIENT)
```

No ORDER_SUBMITTED, ORDER_EXECUTED, or PAPER_TRADE_CREATED events exist today.

---

## 8. DASHBOARD VISIBILITY

**Not applicable** — no BOOTSTRAP_AUTO trade was created.
The dashboard correctly shows 0 open positions, 0 holdings, no BOOTSTRAP badge.

---

## 9. EXIT READINESS

**Not applicable** — no trade was created, so no exit management is active.

---

## 10. FIRST PRODUCTION P20 SIGNAL → PAPER FILL CYCLE STATUS

| Stage | Status |
|---|---|
| Signal generation (scan) | ✅ **Working** — 3 scans completed today, 50+ symbols each |
| Bootstrap candidate selection | ✅ **Working** — HDFCLIFE + DRREDDY identified correctly |
| Bootstrap approval event | ✅ **Working** — BOOTSTRAP_PAPER_TRADE_APPROVED fires correctly |
| Pre-trade risk re-check | ⚠️ **Blocking** — slippage-adjusted R:R drops below 1.5 |
| Fallback to next candidate | ❌ **Missing** — DRREDDY not attempted after HDFCLIFE fails |
| Paper fill → ledger write | ⏳ Pending |
| Exit management → realized P&L | ⏳ Pending |

**The first production P20 paper fill cycle is NOT yet complete.**

---

## 11. NEXT REQUIRED OPERATOR ACTION

### Option A — Fix the bootstrap executor to try the next candidate (RECOMMENDED)

In `phase20_executor.py`, function `run_bootstrap_auto_entry`, after an
`ORDER_REJECTED` result from `create_paper_entry`, iterate to the next
`bootstrap_eligible` candidate instead of returning. DRREDDY (R:R 2.5) would
pass immediately — its slippage budget is ~₹1.78 per share on a ₹1,186 price,
compressing R:R to ~2.47, well above 1.5.

**This is a one-line logic change and the correct fix.**

### Option B — Lower the scan-level bootstrap R:R filter to account for slippage

Change `_BOOTSTRAP_MIN_RR = 1.5` at the scan selection stage to `~1.35`, while
keeping the pre-trade re-check at 1.5. This would let HDFCLIFE pass the full
cycle on days when its R:R is exactly at the boundary — but HDFCLIFE's R:R
appears to be structurally borderline; it will likely keep failing.

**Less robust than Option A.**

### Option C — No code change, wait for market movement

If HDFCLIFE's price drops or its stop loss widens, R:R may rise above 1.5
post-slippage. DRREDDY could also appear as the top-ranked candidate in a future
scan if its opp_score overtakes HDFCLIFE's.

**Highest risk of no trade firing today.**

---

### Immediate steps for operator:

1. **Do not change thresholds, risk rules, or strategy settings** — the system
   is working correctly; only the single-candidate-per-run limitation needs fixing.
2. **Option A is safe to implement now** — no settings change, no threshold change,
   just a fallback loop in the bootstrap executor.
3. After the fix is deployed, the next scheduled scan (~09:33 IST) will select
   DRREDDY as fallback and create the first BOOTSTRAP_AUTO paper trade.
4. Monitor `phase20_paper_trades` and the Live Activity Feed for the
   `BOOTSTRAP_TRADE_CREATED` notification confirming the first fill.
5. Kite subscription renewal still required before 2026-08-28.

---

*Document generated by automated production DB queries. All data is read-only.
No settings, thresholds, or trade records were modified during this verification.*
