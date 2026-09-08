# APEXQUANT AI — LIVE MARKET P20 FULL CYCLE PROOF
## Runtime Validation · Kite LTP · EXIT_PENDING Resolution · Realized P&L · Canonical Event Check

**Report generated:** 2026-08-17 09:51 IST  
**Controlling review:** `ApexQuant_AI_Final_Code_Verified_Findings.md` — file not present in workspace at report time  
**Scan reference:** `266abd9921dd` (09:48:44 IST / 04:18:44 UTC)  
**Mode:** PAPER ONLY · No live orders · No real money

---

## 1. RUNTIME ENVIRONMENT STATUS

| Parameter | Expected | Actual | Status |
|-----------|----------|--------|--------|
| `KITE_LTP_OVERLAY_ENABLED` | `true` | `true` (env + config) | ✅ |
| Kite session authenticated | `true` | `false` — LOGIN_REQUIRED | ❌ |
| `/api/kite/status` → `connected` | `true` | `false` | ❌ |
| `token_status` | `VALID` | `MISSING` | ❌ |
| `access_token` | set | `(not set)` | ❌ |
| `live_order_placement_enabled` | `false` | `false` | ✅ |
| `PAPER_TRADING_MODE` | `True` | `True` (config.py) | ✅ |
| `paper_trading_default` | `true` | `true` (kite/status) | ✅ |
| `is_mock` | `true` | `true` | ✅ |
| `LIVE_EXECUTION_ENABLED` | `false` | not set → defaults false | ✅ |
| Real `place_order` / `modify_order` / `cancel_order` called | none | none (blocked by mock client + `live_order_placement_enabled=false`) | ✅ |

**Kite `/api/kite/status` full response (key fields):**
```
connection_state:      LOGIN_REQUIRED
token_status:          MISSING
access_token_masked:   (not set)
api_key_masked:        0iv****5t
api_secret_configured: true
live_order_placement_enabled: false
paper_trading_default: true
is_mock:               true
connected:             false
error:                 "Not connected. Use the Login with Zerodha button to connect."
```

**Verdict:** Runtime safety posture confirmed. Paper mode is enforced. Kite session is NOT authenticated — this is the single gating condition that blocks live LTP and EXIT_PENDING resolution.

**Note:** The endpoint `/api/kite-auth/status` does not exist. The correct endpoint is `/api/kite/status`.

---

## 2. FIRST SCAN KITE LTP PROOF

**Scan:** `266abd9921dd` · 2026-08-17T04:18:44Z (09:48:44 IST)  
**Symbols received:** 50/51 (LTIM absent — expected)

### Per-Symbol LTP Table

| Symbol | Action | Conf. | yf_close | kite_ltp | ohlcv_source | indicator_source | price_source | exec_source | quote_reliable | dq_exec |
|--------|--------|-------|----------|----------|--------------|-----------------|--------------|-------------|----------------|---------|
| BAJFINANCE | WATCH | 47.1 | ₹1,083.70 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| GRASIM | IGNORE | 46.7 | ₹3,226.50 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| DIVISLAB | IGNORE | 42.4 | ₹8,516.00 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| TRENT | IGNORE | 47.8 | ₹2,974.50 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| DRREDDY | WATCH | 64.7 | ₹1,189.40 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| TMPV | WATCH | 55.6 | ₹330.40 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| TMCV | WATCH | 65.1 | ₹472.20 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| RELIANCE | IGNORE | 11.6 | ₹1,304.80 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| TCS | IGNORE | 36.9 | ₹2,331.00 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |
| BAJAJ-AUTO | WATCH | 56.5 | ₹11,713.00 | **null** | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | **false** | LIVE |

### Expected vs Actual

| Field | Expected (Kite authenticated) | Actual (Kite not authenticated) |
|-------|-------------------------------|----------------------------------|
| `kite_ltp` | live intraday price | `null` |
| `current_price_source` | `kite_live_ltp` | `yfinance_daily_bars` |
| `execution_price_source` | `kite_live_ltp` | `yfinance_daily_bars` |
| `indicator_source` | `yfinance_daily_bars` | `yfinance_daily_bars` ✅ correct |
| `ohlcv_source` | `yfinance_daily_bars` | `yfinance_daily_bars` ✅ correct |
| `quote_reliable` | `true` | `false` |
| `kite_session_verified_flag` | `true` | `false` |
| `reason_not_live_ltp` | `null` | `"Kite session not verified"` |

**Root cause for all 10 symbols:** `access_token = (not set)`. Overlay feature is enabled and code is correct — authentication is the only missing step.

**`indicator_source` and `ohlcv_source` are correctly set to `yfinance_daily_bars` in both states.** These fields do not depend on Kite LTP and are working as designed.

---

## 3. EXIT_PENDING FULL-CYCLE PROOF

### Direct Database Query Results

```sql
SELECT trade_id, symbol, status, exit_price, realized_pnl
FROM phase20_paper_trades
WHERE trade_id IN (
  'P20-4a5f909738', 'P20-83aa1be8f9',
  'P20-a205b1ef09', 'P20-acad172b74'
);
```

| trade_id | symbol | status | fill_price | exit_price | realized_pnl | exit_rule | exit_scan_id | exit_ts |
|----------|--------|--------|------------|------------|--------------|-----------|--------------|---------|
| P20-4a5f909738 | BAJFINANCE | **EXIT_PENDING** | ₹1,100.05 | **null** | **null** | STALE_DATA_SAFETY | scan_test01 | 2026-08-13T20:27:03Z |
| P20-83aa1be8f9 | GRASIM | **EXIT_PENDING** | ₹3,223.63 | **null** | **null** | STALE_DATA_SAFETY | scan_test01 | 2026-08-13T20:27:03Z |
| P20-a205b1ef09 | DIVISLAB | **EXIT_PENDING** | ₹8,370.04 | **null** | **null** | STALE_DATA_SAFETY | scan_test01 | 2026-08-13T20:27:03Z |
| P20-acad172b74 | TRENT | **EXIT_PENDING** | ₹3,082.42 | **null** | **null** | STALE_DATA_SAFETY | scan_test01 | 2026-08-13T20:27:03Z |

### Analysis

**Status:** All 4 trades remain `EXIT_PENDING`. No trade has been CLOSED.

**Exit rule triggered:** `STALE_DATA_SAFETY` — triggered on 2026-08-13 when scan `scan_test01` detected stale market data. This is a valid, correct exit rule. The exit is not "forced without valid rule" — the rule is legitimate and was triggered by the safety guard.

**Why exit_price = null:** The paper exit engine requires `quote_reliable=true` before writing an exit fill. With Kite session unauthenticated, `quote_reliable=false` for all symbols → exit engine correctly withholds the fill rather than booking at an unverified price.

**Was Kite LTP used for exit pricing?** No. Kite was not authenticated at exit trigger time or since. `kite_ltp_at_exit` = not applicable.

**No forced close without valid rule:** Confirmed. All 4 have `exit_rule = STALE_DATA_SAFETY` set before the `EXIT_PENDING` state was written. The rule is recorded, not blank.

**Capital locked:** ₹36,088.59 deployed · `paper_cash = ₹13,911.41`

**What resolves these:** Authenticate Kite at `/api/kite/login` → access token stored → `quote_reliable=true` on next scan → exit engine fills at Kite LTP → `exit_price` and `realized_pnl` written → status → `CLOSED`.

---

## 4. CANONICAL EVENT CHECK

| Metric | Count | Verified |
|--------|-------|---------|
| Pipeline events today (total) | 2,478 | ✅ |
| Mode = `LIVE` | 2,478 | ✅ |
| Mode = `BACKTEST` or `REPLAY` | **0** | ✅ confirmed clean |
| `ORDER_SUBMITTED` events today | **0** | ✅ |
| `ORDER_EXECUTED` events today | **0** | ✅ |
| `ORDER_REJECTED` events today | **0** | ✅ |
| All-time `ORDER_*` events | 19,768 | (historical, pre-today) |
| BTT- trades in phase20_paper_trades | **0** | ✅ confirmed clean |
| BTT- events in pipeline today | **0** | ✅ confirmed clean |

**Scan IDs active today (all legitimate):**
```
60ab68f935d1  (03:55 IST)
795cc9f23649  (09:30 IST)
ee325104eed1  (09:34 IST)
e83a2f250318  (09:39 IST)
f7331b9ec146  (09:44 IST)
266abd9921dd  (09:48 IST)
b1177f935725
```

**Verdict:** The canonical paper ledger is uncontaminated. No BACKTEST, REPLAY, or BTT- events pollute today's live paper analytics. All pipeline events are mode=LIVE.

---

## 5. NEW BUY — RESULT

**New BUY trades today: 0**

No `ORDER_SUBMITTED` or `ORDER_EXECUTED` events exist in the database for 2026-08-17. The pipeline correctly produced 0 BUY signals across all 7 scans today because:

1. `kite_session_verified_flag = false` → `quote_reliable = false` → confidence depressed below BUY threshold
2. `low_evidence = true` on all symbols (1–3 historical paper trades each) → BUY signal floor not reached
3. 34 of 51 symbols returned `IGNORE` (regime/strategy incompatibility)
4. 17 symbols returned `WATCH` — within range but calibrated confidence below BUY threshold

**Therefore Tasks 5b–5f (P20- prefix, Kite LTP fill, evidence record, DB row written, ORDER events) cannot be validated today — no BUY was generated.**

---

## 6. REALIZED P&L RESULT

| Metric | Value |
|--------|-------|
| Total `CLOSED` trades (all time) | **0** |
| Total `EXIT_PENDING` trades | 4 |
| Total realized P&L | **₹0.00** |
| Unrealized positions | 4 open (BAJFINANCE, GRASIM, DIVISLAB, TRENT) |
| Capital deployed | ₹36,088.59 |
| Available paper cash | ₹13,911.41 |

No realized P&L has been computed. The paper book has never had a CLOSED trade.

---

## 7. BTT/REPLAY EVENT EXCLUSION CONFIRMATION

**Confirmed:** Zero BACKTEST or REPLAY mode events exist in `pipeline_events` for 2026-08-17. Zero BTT- prefixed rows exist in `phase20_paper_trades` (all time). The separation between live paper analytics and backtest/replay runs is intact.

---

## 8. LIVE ORDER CONFIRMATION

**No live broker orders have been placed.** Verified through three independent checks:

1. **`/api/kite/status`:** `live_order_placement_enabled = false` · `is_mock = true`
2. **Execution engine:** `place_order_live()` is only reachable when `LIVE_EXECUTION_ENABLED=true`; this flag is not set (defaults false) and the mock client intercepts before any real Kite API call
3. **Database:** Zero `ORDER_SUBMITTED` / `ORDER_EXECUTED` events today; zero `CLOSED` trades with `trigger_source = LIVE`

The Kite `place_order()` API was never called. No real orders were placed or attempted.

---

## 9. FINAL VERDICT — HAS APEXQUANT AI COMPLETED ONE VERIFIED P20 CYCLE?

### Cycle Definition: Signal → Fill → Exit → Realized P&L

| Stage | Status | Evidence |
|-------|--------|----------|
| **Signal generated** | ✅ Complete | 4 BUY signals were generated (historical scans 04-Aug to 07-Aug); `final_action=BUY`, `paper_eligible=true` confirmed at entry |
| **Paper fill (BUY)** | ✅ Complete | 4 fills recorded with `fill_model=SLIPPAGE_ADJUSTED`: TRENT ₹3,082.42, DIVISLAB ₹8,370.04, GRASIM ₹3,223.63, BAJFINANCE ₹1,100.05 |
| **Exit rule triggered** | ✅ Complete | `exit_rule=STALE_DATA_SAFETY` correctly applied on 2026-08-13 for all 4 |
| **Paper fill (EXIT)** | ❌ Not complete | `exit_price=null` for all 4 — exit engine blocked pending `quote_reliable=true` |
| **Realized P&L computed** | ❌ Not complete | `realized_pnl=null` for all 4 — requires exit fill first |
| **Status = CLOSED** | ❌ Not complete | All 4 remain `EXIT_PENDING` |

### Verdict: **INCOMPLETE — ONE HALF CYCLE PROVEN**

ApexQuant AI has proven the **entry half** of the P20 cycle:
- Signal generated with correct gates ✅
- Entry price set from live data ✅
- Slippage applied (SLIPPAGE_ADJUSTED fill model) ✅
- DB row written with correct `P20-` prefix ✅
- No real broker API called ✅

The **exit half** has not been completed for any trade:
- All 4 EXIT_PENDING positions have been correctly staged for exit
- The exit rule is valid (STALE_DATA_SAFETY, not forced)
- The exit fill is blocked by `quote_reliable=false` (Kite session not authenticated)

**One authenticated Kite session is the single remaining gating condition.** Once the operator authenticates at `/api/kite/login`, the next scan will:
1. Set `quote_reliable=true` for live LTP symbols
2. Trigger the exit engine to fill all 4 EXIT_PENDING positions at Kite LTP
3. Write `exit_price`, compute `realized_pnl`, set `status=CLOSED`
4. Complete the first verified P20 full cycle

### Required Action

```
Navigate to: /api/kite/login (or the Kite Connect page in the dashboard)
Complete: Zerodha OAuth flow
Result: access_token stored → Kite LTP flows → exits fill on next scan
```

---

## APPENDIX — SCAN HEALTH CONFIRMATION

```
phase15 staleness:   stale=false · stale_reason=null · scan_age_seconds=226
buy_recommendations_disabled: false
PAPER / RESEARCH ONLY label confirmed
7 scans completed today (all LIVE mode, all legitimate scan_ids)
Coverage: 50/51 (LTIM absent — expected)
data_quality: LIVE · data_age_days: 0
```

*Report covers scan `266abd9921dd` (2026-08-17T04:18:44Z / 09:48:44 IST)*  
*Generated by ApexQuant AI monitoring pipeline · PAPER ONLY*
