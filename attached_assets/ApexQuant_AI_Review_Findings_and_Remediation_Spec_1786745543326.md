# ApexQuant AI — Independent Review Findings & Remediation Spec

**Reviewed document:** ApexQuant AI Full Project SOP & Second-Opinion Pack (v1.0, generated 2026-08-15)
**Review type:** Independent second opinion, based on the document's own data — no direct code/DB access
**Prepared for:** Handoff to development (human developer or AI coding agent, e.g. Replit Agent)

---

## 1. Summary

The system is not failing to generate trading signals — it produced **19,034 `BUY_GENERATED` events** over the reviewed 14-day window. The failure is downstream: almost none of those signals survive the path from "signal" to "filled paper order." The one day that appears to show real execution (64 fills on 2026-08-11) coincides with a known scan-loop bug and cannot currently be verified against the canonical trade ledger.

This is not primarily a threshold-tuning problem. It is a combination of:

- One severe data-source gap (no live market data)
- Two concrete, fixable implementation bugs (position sizing, reason logging)
- At least two unresolved internal inconsistencies in the system's own instrumentation that should be answered in code before the rest of the roadmap is trusted

**Recommended approach:** resolve the open questions in Section 3, fix the P0/P1 items in priority order, then prove one symbol trades end-to-end (signal → fill → exit → correct P&L) before expanding scope further.

---

## 2. Root Cause Analysis (Priority Order)

### P0 — No live data feed

**File(s):** `market_data.py`, `kite_quote_provider.py`, `live_scan_engine.py`

**Problem:** Without an active Zerodha OAuth session, all quotes fall back to Yahoo Finance. The data-quality gate labels *any* Yahoo-sourced quote `STALE` — this is a source check, not a recency check. `STALE` hard-caps the resulting action at `WATCH`, and `WATCH` signals are never eligible for paper execution.

**Impact:** This is the ceiling the rest of the pipeline operates under. No downstream fix (sizing, thresholds, logging) can produce an executed trade while this is unresolved.

**Fix:** Restore and maintain an active Zerodha session during market hours. Consider replacing the source-based `STALE` label with an actual age-based check (quote timestamp older than N minutes), so a genuinely fresh Yahoo quote isn't penalized identically to a 20-minute-old one.

---

### P0 — Position sizer rejects instead of downsizing

**File(s):** `position_sizer.py`

**Problem:** For higher-priced symbols (DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV, TMPV), the sizer computes an "ideal" share count from risk parameters. When that count exceeds the 20%-of-capital hard cap, the order is rejected outright instead of being resized down to the largest quantity that fits.

**Example:** DRREDDY ~₹1,350/share. Ideal = 8 shares = 21.6% of ₹50,000 → rejected. 7 shares = 18.9% → would have passed every other gate.

**Impact:** 3,000+ `ORDER_REJECTED` events over the reviewed window — the single largest concrete, fixable cause of failed executions.

**Fix:**
```
qty = min(ideal_qty, floor(cap_amount / price))
if qty == 0:
    reject  # genuinely too expensive for the account
else:
    proceed with qty
```

**Definition of done:** DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV, and TMPV all produce a valid order size instead of a cap-rejection when signal conditions are otherwise met.

---

### P1 — Rejection reasons not logged

**File(s):** Risk agent / whichever module writes `RISK_REJECTED` and `EXECUTION_SKIPPED_WITH_REASON` events

**Problem:** 15,447 `RISK_REJECTED` events and 67 `EXECUTION_SKIPPED_WITH_REASON` events all have `payload->>'reason' = NULL`. The position-sizing bug above plausibly explains ~3,000 rejections; the other ~15,000+ are currently unexplainable from the data.

**Impact:** Impossible to audit or prioritize further fixes without this. Likely hiding additional bugs beyond the two above.

**Fix:** Every rejection/skip code path must write a structured reason string to the event payload. Do this *before* validating the P0-2 fix — you need it to confirm the fix actually worked and to see what's left afterward.

---

## 3. Open Questions to Verify in Code First

The source document contains two internal inconsistencies that should be resolved before trusting the rest of its own roadmap — the answers change how every count in the report should be interpreted.

**Q1 — Is `BUY_GENERATED` logged pre-gate or post-gate?**

The document states elsewhere that "ALL symbols receive STALE data… no BUY action can be generated." Yet DRREDDY, GRASIM, and BAJAJ-AUTO reach `BUY_GENERATED` and `RISK_APPROVED` on every single trading day in the window, failing only at the sizing gate. Both claims can't be true simultaneously. Most likely explanation: `BUY_GENERATED` is emitted from the raw signal computation *before* the STALE→WATCH downgrade is applied, not after. If so, the "no live data" problem and the "position sizing" problem are more entangled than they appear — fixing sizing alone, without live data, may still never produce a real fill for these symbols.

*Action:* Trace exactly where in `live_scan_engine.py` the `BUY_GENERATED` pipeline event is emitted relative to the data-quality gate coercion step.

**Q2 — Where exactly does `AI_MIN_RR_RATIO = 2.0` get enforced?**

Two documented gates require R:R ≥ 1.5 (`live_scan_engine.py` scan gate, `phase20_executor.py` execution gate) and are described as "Aligned." A third value, `AI_MIN_RR_RATIO = 2.0`, exists in the AI Decision Engine layer but isn't reconciled against the other two anywhere in the source document. A signal with R:R between 1.5 and 2.0 would pass both documented gates and could be dying silently at this third check — plausibly contributing to the unexplained rejections in P1.

*Action:* Confirm whether this threshold is actually applied at decision time, and if so, either align it to 1.5 or ensure its rejections carry a labeled reason.

**Q3 — Was Aug 11 a real success?**

64 `ORDER_EXECUTED` / `POSITION_OPENED` events exist in `pipeline_events` for 2026-08-11, but only 4 rows exist in the canonical `phase20_paper_trades` ledger, and none trace back to that day. The same day is separately flagged for a scan-loop anomaly (65,018 `SYMBOL_SCANNED` from 89 scan starts; one symbol — not even a NIFTY 50 constituent — scanned 282 times per cycle).

*Action:* Determine whether those 64 executions are real (e.g. stored in the legacy `paper_trades` table) or phantom events from the loop bug. Until resolved, treat the system as having **no verified instance** of a clean, end-to-end completed trade.

---

## 4. Additional Fixes Required for a Functioning System

### P1 — No sell/exit logic

**Problem:** The four existing open positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT — opened Aug 4) have no working exit path. Their only trigger to date is `STALE_DATA_SAFETY`, a safety net rather than a trading strategy, and it doesn't record an exit fill price — so `realized_pnl` is `NULL` on all of them.

**Fix:** Implement and test target-hit, stop-hit, and time-based exits as first-class exit reasons, each writing a fill price and computing `realized_pnl`.

**Definition of done:** A position opened by the system can be closed by the system under normal (non-safety-net) conditions, with a correct, non-null realized P&L.

### P2 — Duplicate trade ledger tables

**Problem:** `paper_trades` (legacy) and `phase20_paper_trades` (canonical) both exist. The Aug 11 executions can't be cleanly reconciled against either (see Q3).

**Fix:** Consolidate to one canonical table. Migrate or explicitly archive the legacy one.

### P2 — Capital sizing vs. instrument universe

**Problem:** Even after the P0-2 fix, a ₹50,000 bankroll with a 20% (₹10,000) per-trade cap produces very lumpy share counts for pricier NIFTY constituents (e.g., 1–2 shares for BAJAJ-AUTO at ~₹5,860). This won't block trades, but it limits how meaningfully risk-based sizing can operate.

**Fix:** Consider increasing simulated capital, or explicitly tiering the universe by price so risk-based sizing has room to work smoothly.

---

## 5. Scope Recommendation

The current system has 70+ registered routes, 10 formal agents, and 218 tracked tasks, but no verified instance of a complete, auditable trade (signal → fill → exit → correct P&L). Recommend freezing development outside the 5 pages the source document itself identifies as canonical — `/` (Trade Decisions), `/ai-paper-trader`, `/mission-control`, `/live-data-health`, `/market-intelligence` — until the P0/P1 items above are resolved and demonstrated on at least one real trade cycle. Additional dashboards and agents add surface area that makes existing bugs harder to find, not easier.

---

## 6. Suggested Sequence

1. Resolve Q1 and Q2 (code tracing — no behavior change yet)
2. Fix P0-2: position sizer floor-to-cap
3. Fix P1: reason logging on all rejection/skip paths
4. Restore Zerodha live session (P0-1); re-test P0-2 against live data
5. Resolve Q3 (Aug 11 audit) — do not treat those 64 fills as validated until resolved
6. Build and test exit logic (Section 4, P1)
7. Consolidate ledger tables (Section 4, P2)
8. Re-run backtests against the corrected logic to calibrate thresholds against real outcomes
9. Only then: resume work on non-canonical pages/dashboards

---

*Based on independent review of the ApexQuant AI Full Project SOP & Second-Opinion Pack (2026-08-15). This spec reflects analysis of that document only; items marked "Action" require direct code/DB verification that this review did not have access to.*
