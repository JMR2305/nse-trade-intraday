# Today's Paper Trade Exit Quality Audit

**Trading session audited:** 20 August 2026 (IST)  
**Scope:** Paper trades only. Read-only audit of the production `phase20_paper_trades` ledger, production pipeline events, notifications, stored trade evidence, and daily OHLCV cache.  
**No strategy, gate, setting, or order-placement changes were made. No live orders were placed.**

## Executive conclusion

1. The authoritative Phase 20 ledger **does persist quantities**. The two completed trades were:
   - **DRREDDY: 20 shares**
   - **DIVISLAB: 1 share**
2. Both completed trades were closed by the mandatory **`MARKET_CLOSE_EXIT`**, not by a fixed target, stop-loss, trailing stop, or recommendation reversal.
3. The late DRREDDY and TRENT entries were permitted because the only time gate was **market state = `OPEN`** through 15:30 IST. There is **no no-new-entry cutoff** before the mandatory 15:20 IST square-off window.
4. The two late entries remained open after the close. The expected `POST_CLOSE_FORCE_EXIT` is absent from the ledger and event trail. The audit can prove it did not produce a recorded close; it cannot prove from persisted evidence whether the scheduler failed to tick, skipped the routine, or failed before emitting its audit event.
5. A precise intraday MFE/MAE calculation is **not recoverable**: the production database retained daily OHLCV bars, but no 1-minute/tick bars and no timestamped per-trade high-water/low-water history. Daily high/low figures below are therefore session-level bounds, not a claim about the exact post-entry high or low.

---

## Canonical completed-trade table

| Symbol | Entry Time (IST) | Entry Price | Qty | Exit Time (IST) | Exit Price | Realized P&L | Highest Price After Entry | Time of High | Max Profit Available | Profit Captured | Missed Profit | Exit Reason | Should Have Exited Earlier? |
|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---|
| DRREDDY | 09:16:09 | ₹1,193.79 | 20 | 15:24:01 | ₹1,180.10 | **−₹273.80** | No recorded intraday high. Session high was ₹1,183.80, below entry. | Not retained | ₹0.00 | −₹273.80 | ₹0.00 | `MARKET_CLOSE_EXIT` | **No earlier profitable exit is evidenced.** |
| DIVISLAB | 09:24:14 | ₹8,570.34 | 1 | 15:22:36 | ₹8,578.00 | **+₹7.66** | No recorded intraday high. Session high was ₹8,597.50 (upper bound only). | Not retained | **≤ ₹27.16** | ₹7.66 | **≤ ₹19.50** | `MARKET_CLOSE_EXIT` | **Not provable.** A session-high-only upper bound suggests up to ₹19.50 more could have been available, but the high may have occurred before entry. |

### Timestamp reconciliation

The UI observations are directionally consistent with the canonical ledger, but the ledger carries the authoritative timestamps:

- UI observation: DIVISLAB sold around 15:21; ledger: **15:22:36 IST**.
- UI observation: DRREDDY sold around 15:22; ledger: **15:24:01 IST**.
- UI observation: DRREDDY re-entered at 15:25; ledger: **15:25:10 IST**.
- UI observation: TRENT entered at 15:26; ledger: **15:26:22 IST**.

---

## Quantity audit and P&L verification

### Quantity is present in the canonical ledger

| Trade ID | Symbol | Ledger Qty | Status |
|---|---|---:|---|
| `P20-cfd2e587aa` | DRREDDY | **20** | Closed |
| `P20-1c52c79d84` | DIVISLAB | **1** | Closed |
| `P20-8fc829b8c3` | DRREDDY | **20** | Open |
| `P20-315e824378` | TRENT | **5** | Open |

The API mapping for Phase 20 closed trades also returns `quantity`, and the dashboard's closed-trade table renders that field directly. Therefore, a **“Not available”** quantity display is not caused by missing quantity in the authoritative production ledger for these trades.

### Why quantity may still display as “Not available”

The most likely causes are a source/build mismatch rather than missing ledger data:

1. The visible page may be reading a non-canonical fallback/legacy record instead of the production Phase 20 ledger.
2. The browser may be serving an older dashboard build or a stale endpoint response.
3. A historical legacy record may lack quantity, but that does **not** apply to the 20 August Phase 20 trades above.

The display should be checked against the `phase11_closed_positions` response in the running environment. It must expose the ledger's `quantity` values of **20** and **1**, rather than a placeholder.

### P&L formula

The exit writer currently records:

```text
realized_pnl = (exit_price - fill_price) × quantity
```

For these two trades, the values match exactly:

| Symbol | Calculation | Ledger P&L | Result |
|---|---|---:|---|
| DRREDDY | (₹1,180.10 − ₹1,193.79) × 20 | −₹273.80 | Matches |
| DIVISLAB | (₹8,578.00 − ₹8,570.34) × 1 | +₹7.66 | Matches |

The entry rows also store estimated charges and slippage. The realized-P&L writer does **not** subtract a separate exit-cost amount; entry slippage is already reflected in the stored fill price. Consequently, the recorded realized P&L is a gross price-difference result from the stored fill onward, not a fully net round-trip P&L after separately modelled exit charges.

---

## DRREDDY exit audit

### Recorded entry and exit

| Field | Value |
|---|---:|
| Entry | 09:16:09 IST at ₹1,193.79 |
| Quantity | 20 |
| Stop-loss at entry | ₹1,141.05 |
| Fixed target at entry | ₹1,319.38 |
| Exit | 15:24:01 IST at ₹1,180.10 |
| Realized P&L | −₹273.80 |
| Exit reason | `MARKET_CLOSE_EXIT` |
| Entry slippage stored | ₹1.788 total-per-share adjustment field |
| Estimated entry charges stored | ₹28.65 |

### Did DRREDDY trade above entry?

**No evidence supports that it did.** The retained full-session daily high was **₹1,183.80**, which is already **₹9.99 below** the actual fill price of ₹1,193.79. Since the full-session high is below entry, DRREDDY could not have traded above the actual fill at any later moment if that daily bar is accurate.

### Target, trailing stop, and profit lock

- **Target hit?** No. The recorded target was ₹1,319.38; the retained session high was ₹1,183.80.
- **Stop-loss hit?** No recorded `STOP_LOSS_HIT` exit. The retained session low was ₹1,171.20, still above the ₹1,141.05 stop. Exact post-entry low time is not retained.
- **Trailing stop configured?** The engine has a rule-based trailing stop, but it is not a per-trade configured percentage and does not store a durable per-trade trail history in the ledger.
- **Could the trailing stop have activated?** No. With a one-R distance of ₹52.74:
  - Trail activation: `fill + 2R` = **₹1,299.27**
  - Profit-lock exit threshold after activation: `fill + 1R` = **₹1,246.53**
  - Retained session high: ₹1,183.80
- **Did trailing fail?** No. It never had a chance to activate from the retained price evidence.
- **Was this only an end-of-day square-off?** Yes. The canonical exit rule is `MARKET_CLOSE_EXIT`.

### Excursion findings

No true post-entry high/low series is retained. Based on the full-session daily bar only:

- Maximum favourable excursion / maximum profit available: **₹0.00** (the daily high remained below entry).
- Maximum adverse excursion bound: `(₹1,193.79 − ₹1,171.20) × 20 = ₹451.80`.
- Actual loss captured: **−₹273.80**.

The ₹451.80 adverse figure is a **session-low bound**, not a verified post-entry MAE. It must not be interpreted as proof that the trade reached that adverse level after 09:16.

---

## DIVISLAB exit audit

### Recorded entry and exit

| Field | Value |
|---|---:|
| Entry | 09:24:14 IST at ₹8,570.34 |
| Quantity | 1 |
| Stop-loss at entry | ₹8,121.78 |
| Fixed target at entry | ₹9,380.80 |
| Exit | 15:22:36 IST at ₹8,578.00 |
| Realized P&L | +₹7.66 |
| Exit reason | `MARKET_CLOSE_EXIT` |
| Fill model | `bootstrap_paper` |
| Entry slippage stored | ₹12.8362 total-per-share adjustment field |
| Estimated entry charges stored | ₹10.28 |

### Did AI miss a larger profit?

The retained session high was **₹8,597.50**, which would imply:

```text
(₹8,597.50 − ₹8,570.34) × 1 = ₹27.16
```

The actual captured profit was ₹7.66. This creates a **maximum possible missed-profit bound of ₹19.50**.

However, there is no retained intraday high timestamp. The high may have occurred before the 09:24 entry, so the audit cannot honestly label ₹19.50 as an actual missed profit. It is a session-level upper bound only.

### Target, trailing stop, and exit reason

- **Target hit?** No. Target was ₹9,380.80; daily high was ₹8,597.50.
- **Stop-loss hit?** No recorded stop exit. The daily low was ₹8,532.00, above the ₹8,121.78 stop.
- **Trailing stop active?** No evidence it could activate. One R was ₹448.56:
  - Trail activation: **₹9,467.46**
  - Profit-lock threshold after activation: **₹9,018.90**
  - These are above both the fixed target and the retained daily high.
- **Why only +₹7.66?** The position was closed by the mandatory `MARKET_CLOSE_EXIT`, using the available exit quote, before any fixed target or trailing condition was reached.

### Excursion findings

No true post-entry high/low series is retained. Based on the full-session daily bar only:

- MFE / maximum profit available: **at most ₹27.16**
- Profit captured: **₹7.66**
- Potential missed amount: **at most ₹19.50**
- MAE bound: `(₹8,570.34 − ₹8,532.00) × 1 = ₹38.34`

The MFE, MAE, and missed-profit values are bounded estimates, not exact intraday measurements.

---

## Late-entry audit

### Recorded late entries

| Symbol | Entry Time (IST) | Entry Price | Qty | Status at audit |
|---|---:|---:|---:|---|
| DRREDDY | 15:25:10 | ₹1,181.87 | 20 | Open |
| TRENT | 15:26:22 | ₹2,971.45 | 5 | Open |

### Why they were allowed

They occurred before the configured official market close at **15:30 IST**, so the `market_open` gate passed. The stored DRREDDY evidence explicitly says:

```text
market_open: passed — Market state is OPEN
```

The entry gates do not include an intraday “no new entries after 15:20” cutoff. The current setting `square_off_before_close` is `false`, but the exit code independently mandates square-off from 15:20 onward; that setting does not create an entry cutoff.

### Are fresh entries after 15:20 acceptable in intraday mode?

**No.** They conflict with the system's declared intraday invariant: after the 15:20 IST square-off threshold, the system should be reducing exposure, not creating new exposure. In the current sequence:

1. Existing positions were closed via `MARKET_CLOSE_EXIT`.
2. The same scan then admitted fresh DRREDDY and TRENT buys at 15:25/15:26.
3. The post-close force-close safety net did not leave a corresponding close or blocked-exit record for them.

### Current cutoff and recommended cutoff

| Item | Value |
|---|---|
| Current no-new-entry cutoff | **None** |
| Current market-open entry boundary | 15:30 IST |
| Mandatory exit threshold | 15:20 IST |
| Recommended intraday no-new-entry cutoff | **15:15 IST** |

The recommended cutoff gives a five-minute buffer before the 15:20 mandatory exit window. It should be enforced as an authoritative admission gate in the paper-entry path, not merely as a scheduler convention.

---

## Exit-capability confirmation

| Capability | Present in code | Recorded for today's completed trades | Audit conclusion |
|---|---|---|---|
| Fixed target exits | Yes | No target hit | Available, not triggered |
| Stop-loss exits | Yes | No stop hit | Available, not triggered |
| Trailing-stop exits | Yes: dynamic 2R high-water mark then 1R lock | No trail activation or history recorded | Exists, but is not auditable enough for post-trade analysis |
| Time-based exits | Yes: maximum holding days | Not applicable intraday | Available |
| End-of-day square-off | Yes: `MARKET_CLOSE_EXIT` from 15:20 | Yes, both completed trades | Worked for positions open before the late-entry sequence |
| Post-close force-close | Yes: `POST_CLOSE_FORCE_EXIT` | No recorded action for late entries | Did not produce a traceable close for DRREDDY/TRENT |
| Profit-protection logic | Only through the conditional trailing rule | Not triggered | No separate break-even or staged-profit-lock rule |

---

## Recommendations — do not implement as part of this audit

### Required reliability fixes

1. **No-new-entry-after cutoff — required.**  
   Enforce a 15:15 IST entry cutoff for intraday paper trades. From that point onward, allow exits and safety actions only.

2. **Quantity display verification/fix — required.**  
   Make the visible closed-trades response use the canonical Phase 20 ledger when it exists, and add a browser-level check that the production page renders `20` for DRREDDY and `1` for DIVISLAB rather than a placeholder.

3. **Post-close force-exit auditability — required.**  
   Every open position at 15:30 must result in exactly one traceable outcome: `POST_CLOSE_FORCE_EXIT`, `MARKET_CLOSE_EXIT_BLOCKED`, or an explicit operator-approved carry. The missing DRREDDY/TRENT outcome is not acceptable for an intraday paper system.

### Exit-quality improvements to evaluate after the reliability fixes

4. **Persist intraday excursion data — required before judging “missed profit.”**  
   Store 1-minute/tick bars or at least a timestamped per-trade high-water/low-water series. Without it, MFE, MAE, high time, and missed-profit claims are not auditable.

5. **Profit lock — recommended.**  
   Add a separately auditable break-even/profit-lock policy only after collecting enough intraday evidence. The existing trailing rule activates only at 2R and does not preserve a ledger-level trail history.

6. **Trailing stop — refine, do not loosen.**  
   Keep the existing safety intent, but make its activation level, locked stop, and high-water mark persist with the trade so each exit can be reproduced and explained.

7. **Better exit agent — later, evidence-driven.**  
   The completed trades did not demonstrate a target or trailing failure. First correct the close-window admission defect and preserve intraday evidence; then assess whether a separate exit agent adds value.

---

## Audit limitations and evidence integrity

- The production `phase20_paper_trades` ledger is the source of truth for quantity, fills, targets, stops, status, exit rule, and realized P&L.
- Pipeline events confirm `MARKET_CLOSE_EXIT` for the two completed trades and entry creation for the two late trades.
- The production OHLCV cache contains one daily bar for each symbol. It contains no intraday timestamps, and the database has no minute-bar table.
- Scanner events stored daily-bar values rather than a reliable intraday sequence for these symbols, so they cannot be used to calculate true MFE/MAE.
- All “maximum available” and “missed profit” values in this report are therefore explicitly marked as **bounds** where they depend on the daily bar.