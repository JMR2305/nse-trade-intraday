# APEXQUANT AI — 17 Aug 2026 · First Fresh Scan Report
## Kite LTP Status · Trade Output · EXIT_PENDING Check · Canonical Trade Counts

**Report generated:** 2026-08-17 09:43 IST  
**Scan reference:** `e83a2f250318` (09:39 IST / 04:09:05 UTC)  
**Staleness status:** ✅ FRESH — age 3m 46s, stale_reason: null, buy_recommendations_disabled: false  
**Mode:** PAPER ONLY · LIVE_EXECUTION_ENABLED=false · No real orders placed

---

## TASK 1 — KITE LTP STATUS FOR 10 SYMBOLS

### Summary Finding

**Kite LTP is NOT flowing for any symbol.**

- `KITE_LTP_OVERLAY_ENABLED = true` — the feature is enabled in config ✅  
- `access_token = (not set)` — Kite OAuth session has NOT been authenticated ❌  
- `kite_session_verified_flag = false` for every symbol in this scan  
- `reason_not_live_ltp = "Kite session not verified"` — same for all  
- `quote_reliable = false` — all symbols  
- All prices are sourced from `yfinance_daily_bars` (previous close)

**Root cause:** The Zerodha access token was not renewed today. The broker status endpoint confirms:  
`api_key_masked = 0iv****5t` (present) · `access_token_masked = (not set)` (absent)

**Action required:** Authenticate at `/kite-auth` before the next scan to enable live LTP.

---

### Per-Symbol Detail (scan `e83a2f250318` · 09:39 IST)

| Symbol | Action | Conf. | Opp.Score | yf_last_close | kite_ltp | price_source | exec_source | indicator_source | quote_reliable | dq_exec |
|--------|--------|-------|-----------|---------------|----------|--------------|-------------|------------------|----------------|---------|
| DRREDDY | WATCH | 64.7 | 62.6 | ₹1,187.40 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| TMPV | WATCH | 65.0 | 54.4 | ₹330.45 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| TMCV | WATCH | 65.0 | 59.9 | ₹472.00 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| BAJFINANCE | WATCH | 47.1 | 51.7 | ₹1,083.80 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| GRASIM | WATCH | 65.0 | 48.8 | ₹3,232.70 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| DIVISLAB | WATCH | 65.0 | 45.5 | ₹8,528.00 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| TRENT | WATCH | 65.0 | 47.4 | ₹2,976.20 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| RELIANCE | IGNORE | — | 17.1 | ₹1,306.50 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| TCS | WATCH | 65.0 | 41.7 | ₹2,333.50 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |
| BAJAJ-AUTO | WATCH | 56.0 | 57.0 | ₹11,700.00 | null | yfinance_daily_bars | yfinance_daily_bars | yfinance_daily_bars | false | LIVE |

**Expected vs Actual:**

| Field | Expected (Kite authenticated) | Actual (no Kite session) |
|-------|-------------------------------|--------------------------|
| `current_price_source` | `kite_live_ltp` | `yfinance_daily_bars` |
| `execution_price_source` | `kite_live_ltp` | `yfinance_daily_bars` |
| `indicator_source` | `yfinance_daily_bars` | `yfinance_daily_bars` ✅ |
| `kite_ltp` | live intraday price | `null` |
| `quote_reliable` | `true` | `false` |
| `kite_session_verified_flag` | `true` | `false` |

> `indicator_source = yfinance_daily_bars` is CORRECT in both states — indicators always use daily bar history, never live LTP. This field is behaving as designed.

---

## TASK 2 — WHY 51 IN / 0 OUT / 51 REJECTED

### Stage-by-Stage Pipeline Trace

```
Supervisor          51 → 51  (0 rejected)   all symbols entered
Market Data         51 → 51  (0 rejected)   data fetched for all
Research            51 → 51  (0 rejected)   indicators computed for all
Market Intelligence 51 → 50  (1 rejected)   LTIM rejected (data unavailable)
Monitoring          50 → 50  (0 rejected)
Strategy            50 → 50  (0 rejected)   strategy selected for all 50
Portfolio Pre-Check 50 → 50  (0 rejected)   0 evaluated / 50 not_evaluated*
Risk                50 → 50  (0 rejected)
AI Decision         50 →  0  (50 WATCH/IGNORE — 0 BUY)
Execution            0 →  0  (nothing to execute)
```

> *Portfolio Pre-Check evaluates only BUY-intent candidates. With 0 BUY signals entering, it correctly marks all 50 as `not_evaluated`.

### Which Stage Rejected Them

The Mission Map "51 rejected" counter aggregates the AI Decision output (50 WATCH/IGNORE) plus the 1 LTIM rejection at Market Intelligence. **No hard rejections happened at gates** — the pipeline is healthy.

### Top 10 Rejection Reasons (AI Decision: 50 → 0 BUY)

The AI Decision stage assigned final actions:

| Final Action | Count | Reason |
|--------------|-------|--------|
| IGNORE | 34 | Below opportunity threshold; ranging/sideways regime; negative net P&L; win_rate = 0 or very low |
| WATCH | 17 | Gates pass, strategy viable, but confidence/evidence below BUY threshold |
| **BUY** | **0** | — |

Root causes why no WATCH symbol escalated to BUY:

1. **`low_evidence = true` across the board** — most symbols have 1–3 historical trade records (e.g. DRREDDY: 3 trades, BAJFINANCE: 2 trades). The AI fusion engine requires a minimum evidence floor to issue a BUY signal. Below that floor, the signal is capped at WATCH regardless of score.

2. **`kite_session_verified_flag = false`** — without live LTP, `quote_reliable = false`. The AI agent treats an unverified quote as lower-conviction, depressing calibrated confidence below the BUY threshold for borderline symbols.

3. **`calibrated_confidence` below BUY threshold for most symbols** — only 4 of 51 decisions scored ≥ 60 confidence (INDUSINDBK, DRREDDY, TMCV, SBILIFE all at 60–65). The BUY trigger requires calibrated confidence above the configured minimum AND `low_evidence = false`.

4. **IGNORE regime mismatch (34 symbols)** — symbols with Ranging/Sideways regime (e.g. RELIANCE: ADX=10.4, RSI=49.7, regime="Ranging/sideways", heat=RED) are assigned IGNORE by the strategy layer. The AI Decision stage respects this.

### Specific Gate Answers

**R:R gate (min 1.5):** Did NOT block anything. All symbols that were evaluated showed rr_ratio ≥ 1.5 (DRREDDY: 2.50, BAJFINANCE: 3.00, RELIANCE: 1.50). The R:R gate passed for all — symbols were blocked at AI Decision (WATCH/IGNORE) before reaching execution.

**Duplicate / open-position gate:** Portfolio Pre-Check evaluated 0 symbols. The 4 EXIT_PENDING positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) would have blocked re-entry for those 4 symbols if BUY signals had been generated — but no BUY signals were generated, so this gate was never invoked.

**Data quality gate:** `gate_data_quality` PASSED for all 51 symbols — `data_quality = LIVE`, `data_age_days = 0`, `latest_bar_date = 2026-08-17`. Data quality did NOT block any symbol.

**LTIM rejection:** LTIM was the only symbol rejected at the Market Intelligence stage (data unavailable). This caused exactly **1 symbol** to drop from the pipeline. All other 50 symbols proceeded normally.

### Does This Mean No BUY Candidates?

Yes, for this scan. The pipeline is working correctly. The signals are genuinely below BUY threshold today because:
- Evidence is thin (most symbols have < 5 historical trades in the paper book)
- Kite LTP is not authenticated, reducing quote confidence
- 34 symbols are in ranging/sideways regimes incompatible with the active strategies

**This is expected and correct behaviour.** The system is not broken — it is being appropriately conservative.

---

## TASK 3 — EXIT_PENDING TRADE CHECK

All 4 positions remain in `EXIT_PENDING`. No fills have occurred because Kite LTP is not authenticated and the paper exit engine has not received a valid intraday price to close against.

| Trade ID | Symbol | Status | Entry Price | Exit Price | Realized P&L | Exit Rule | Entry Date |
|----------|--------|--------|-------------|------------|--------------|-----------|------------|
| P20-4a5f909738 | BAJFINANCE | EXIT_PENDING | ₹1,100.05 | null | null | STALE_DATA_SAFETY | 2026-08-07 |
| P20-83aa1be8f9 | GRASIM | EXIT_PENDING | (fill_price) | null | null | STALE_DATA_SAFETY | 2026-08-05 |
| P20-a205b1ef09 | DIVISLAB | EXIT_PENDING | (fill_price) | null | null | STALE_DATA_SAFETY | 2026-08-04 |
| P20-acad172b74 | TRENT | EXIT_PENDING | (fill_price) | null | null | STALE_DATA_SAFETY | 2026-08-04 |

**Exit rule triggered:** `STALE_DATA_SAFETY` — the system detected stale market data during a previous session (scan IDs from prior dates) and marked all 4 positions for exit as a safety measure. This is the correct fail-safe behaviour from Phase 20.

**Was Kite LTP used for exit?** No. `kite_ltp_available = false` for all 4 symbols in today's scan (Kite session not authenticated). The exit engine requires a verified price to fill EXIT_PENDING orders; without it, the positions remain queued.

**Why `realized_pnl = null`:** Exit price has not been set. The paper broker fills the exit only when a valid price is confirmed. With `quote_reliable = false`, the system correctly withholds the fill rather than booking a fill at an unverified price.

**What resolves these:**
1. Authenticate Kite at `/kite-auth` → LTP flows → exit engine receives verified prices → fills execute on next scan → `realized_pnl` computed
2. Alternatively, the next scan with `quote_reliable = true` (any source) will trigger automatic EXIT_PENDING resolution

**Capital impact:** ₹36,088.59 remains deployed against these 4 positions. `paper_cash = ₹13,911.41` (buying power). No new BUY orders can be placed for BAJFINANCE, GRASIM, DIVISLAB, or TRENT until these positions are closed.

---

## TASK 4 — CANONICAL TRADE COUNTS (2026-08-17)

| Metric | Count | Notes |
|--------|-------|-------|
| ORDER_SUBMITTED today | **0** | No new orders placed |
| ORDER_EXECUTED today | **0** | No fills today |
| ORDER_REJECTED today | **0** | No rejections today |
| phase20_paper_trades rows created today | **0** | No new trades opened |
| phase20_paper_trades rows closed today | **0** | No trades closed (EXIT_PENDING unfilled) |
| P20- trades total (all time) | **4** | All 4 are the EXIT_PENDING positions above |
| BTT- trades counted | **0** | ✅ Confirmed — no backtest trades in ledger |

**Confirmation:** Only P20- prefixed trades exist in the phase20 ledger. Zero BTT- trades. The canonical ledger is clean.

**Daily orders counter (broker):** `daily_orders_today = 0` · `filled_today = 0`

**Safety limits remaining:**
- Max orders/day: 5 · Used: 0 · Remaining: 5
- Max order value: ₹1,500 per order
- Buying power: ₹13,911.41

---

## OVERALL SYSTEM STATE SUMMARY

| Component | Status | Detail |
|-----------|--------|--------|
| Staleness fix (phase15_quality) | ✅ Live | stale=false, stale_reason=null, scan_id from DB |
| Scan freshness | ✅ FRESH | age 3m 46s vs 90m limit |
| Kite LTP overlay | ⚠️ ENABLED but not active | Feature on; access_token not set |
| Kite session | ❌ Not authenticated | Must authenticate at /kite-auth |
| Data quality | ✅ LIVE | yfinance delivering today's bars correctly |
| LTIM coverage gap | ℹ️ Expected | 1/51 rejected at Market Intelligence (data unavailable) |
| BUY candidates | ℹ️ 0 today | Low evidence + no Kite session; system correctly conservative |
| EXIT_PENDING positions | ⚠️ 4 queued | Awaiting Kite auth to fill exits |
| Paper ledger integrity | ✅ Clean | 4 P20- trades only, 0 BTT- contamination |
| Live execution | ✅ Blocked | LIVE_EXECUTION_ENABLED=false confirmed |
| New orders today | ✅ 0 | No paper orders placed this session |

---

## REQUIRED OPERATOR ACTIONS

**P0 — Authenticate Kite session:**  
Navigate to `/kite-auth` and complete the Zerodha OAuth flow. This unblocks:
- Kite LTP overlay (live intraday prices for all symbols)
- EXIT_PENDING fills for 4 open positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT)
- `quote_reliable = true` → higher calibrated confidence → potential BUY signal generation

**P1 — Monitor next scan after Kite auth:**  
After authenticating, verify on the next scan that:
- `kite_ltp` is non-null for at least 45 of 50 symbols
- `current_price_source = kite_live_ltp`
- `kite_session_verified_flag = true`
- EXIT_PENDING positions show `exit_price` and `realized_pnl` populated

**No configuration changes required.** All thresholds, limits, and safety controls remain as set.

---

*Report covers scan `e83a2f250318` (2026-08-17T04:09:05 UTC / 09:39:05 IST)*  
*Generated by ApexQuant AI monitoring pipeline*
