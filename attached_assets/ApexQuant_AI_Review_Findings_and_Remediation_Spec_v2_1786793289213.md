# ApexQuant AI — Independent Review Findings & Remediation Spec (v2)

**v1 source reviewed:** ApexQuant AI Full Project SOP & Second-Opinion Pack (2026-08-15) — document only
**v2 source reviewed:** ApexQuant AI Full Project SOP v2.0 + direct review of the `nse-trade-intraday` source code (two uploaded snapshots, diffed against each other)
**Review type:** v1 of this spec was document-based. Everything below is code-verified — findings come from reading the actual source, not from either SOP's description of it.

---

## What changed since v1 of this spec

- Two items marked P0 in v1 are **confirmed fixed** in code (position-sizing cap handling, rejection-reason logging) — verified end-to-end, including that the fix is actually adopted by the caller, not just computed and ignored.
- The root cause of the sizing bug was **misattributed** in the original SOP (and in v1 of this spec, which followed it). The actual bug lived in a different file.
- Open questions Q1 and Q2 from v1 are **resolved** by direct code inspection.
- A **new, more significant root cause** was found that neither SOP version identifies: the documented "Zerodha primary, Yahoo fallback" data architecture doesn't exist in code. This changes the recommended fix for the STALE/no-live-data problem.
- The v1 "no exit logic exists" finding is **corrected** — exit logic exists and is reasonably complete. It's gated by the same data problem as entries, not missing.
- Q3 (the Aug 11 anomaly) remains **unresolved** — it requires database access this review didn't have.

---

## 1. Confirmed Fixed

### Position-sizing cap rejection — FIXED, correctly wired end-to-end

**v1 diagnosis (from the SOP):** `position_sizer.py` computes an ideal quantity and rejects outright when it exceeds the 20% cap.

**Actual root cause, code-verified:** Both `position_sizer.py` implementations in the repo (`api-server/src/python/position_sizer.py` and `api-server/src/python/src/portfolio/position_sizer.py`) already correctly floor quantity to the cap — neither was ever the bug. The real fault was in `risk_validation/pre_trade.py`'s `_check_position_size()`, a separate, redundant cap check applied downstream, which re-validated the already-sized quantity and hard-rejected it with no attempt to resize.

**Fix verified ("Phase 1B"):** `_check_position_size()` now computes `cap_qty = floor(cap_amount / price)`. If `cap_qty >= 1`, the verdict downgrades from a hard rejection to `APPROVED_WARN` with a `SIZE_REDUCED_TO_CAP` warning, carrying the reduced quantity in `summary["capped_qty"]`. Only a genuine `cap_qty == 0` still rejects outright.

**Caller verified:** `phase20_executor.py` correctly adopts the reduction — reassigns `qty`, recomputes `charges` against the new quantity, records `original_qty` for the audit trail, and updates the `sizing` dict before the trade row is built. This is a complete fix, not a partial one.

### Rejection reasons not logged — FIXED

**Fix verified ("Phase 1C"):** `RISK_REJECTED` (in `live_scan_engine.py`), and `ORDER_REJECTED` / `EXECUTION_SKIPPED_WITH_REASON` (both in `phase20_executor.py`) now all populate `gate_name`, `actual_value`, and `human_readable_reason` in their event payloads, derived from the actual failed-gate data.

**Note:** this only fixes reasons for events going forward. The 15,447 historical `RISK_REJECTED` rows with `reason = NULL` cannot be retroactively recovered — treat pre-fix history as a lost audit trail, not as data worth continuing to analyze.

---

## 2. New Finding — Zerodha/Kite Is Not Wired Into the Data Path

*(This supersedes v1's "No live data feed" P0 — the problem is real, but the cause and fix are different from what's documented.)*

**What both SOP versions claim:** the pipeline tries Zerodha Kite first, falls back to Yahoo Finance when no session is active, and Zerodha session status determines whether data quality is LIVE or STALE. Both versions recommend authenticating Zerodha as the fix.

**What the code actually does:**

- `live_scan_engine.py` (~line 652) unconditionally instantiates `LiveDataProvider()`. No branch in the scan path selects Kite over Yahoo based on session state.
- `live_data_provider.py` uses `yfinance` exclusively. Data quality is computed purely from the calendar-day age of the latest OHLCV bar:
  ```
  age_days ≤ 3   → LIVE
  age_days ≤ 5   → NEAR_LIVE
  age_days ≤ 14  → STALE
  age_days > 14  → UNAVAILABLE
  ```
  Source (Yahoo vs. Kite) plays no role in this classification.
- The Kite/Zerodha references that do exist in `live_scan_engine.py` (~lines 783–810) are explicitly commented `"read-only overlay metadata"`. They populate a `kite_connected` boolean and a `live_quote_source` label for display only. `ohlcv_source` is hardcoded to `"yfinance (historical)"` regardless of session state — confirming the label has no effect on what's fetched or how it's graded.
- `SCAN_INTERVAL = "1d"` — the scanner works from daily bars, not intraday bars, anywhere in this path.

**Impact:** authenticating a Zerodha session — the fix currently documented in both SOP versions — will not change STALE-blocked BUY behavior, because nothing in the live scan path reads price or quality from Kite regardless of session status. If STALE really is occurring at the frequency the SOP describes, the cause is yfinance itself returning bars older than 3–5 calendar days for specific symbols — a data-availability problem, not a missing-credential problem.

**Action required, in order:**

1. Instrument a live scan to log `data_source`, `latest_date`, and `age_days` per symbol, and check what's actually being returned right now. This tells you whether STALE is a live, ongoing problem or something that's already resolved.
2. If genuinely stale bars are coming back from yfinance for specific symbols, treat that as its own bug (rate limiting, a fallback path serving cached data, a universe/context issue) — separate from any Zerodha work.
3. If real-time Kite data is wanted (reasonable, for a system named "intraday"), that's new integration work, not a re-auth: the scan engine's fetch call needs an actual conditional path to Kite for both OHLCV and quality when a session is verified, plus a decision on whether intraday bars get fetched at all. Update both SOPs' pipeline diagrams once this is scoped — they currently document a fallback architecture that doesn't exist in code.

---

## 3. Resolved Open Questions (from v1 spec)

**Q1 — Is `BUY_GENERATED` logged pre-gate or post-gate?**
**Resolved: post-gate.** The event type (`BUY_GENERATED` / `WATCH_GENERATED` / `IGNORE_GENERATED`) is derived from `r.final_action`, assigned only after the data-quality gate, R:R gate, and volume gate have all been applied and had the chance to downgrade the action. Consequence: the SOP's claim that "ALL symbols receive STALE data… no BUY action can be generated" is inaccurate for whichever symbols were observed reaching `BUY_GENERATED` regularly (DRREDDY, GRASIM, BAJAJ-AUTO per the v1 SOP) — those specific scans genuinely had LIVE or NEAR_LIVE quality at the time.

**Q2 — Where does `AI_MIN_RR_RATIO = 2.0` get enforced?**
**Resolved: nowhere.** Defined in `config.py`, referenced in exactly one other place (`phase21_baseline.py`), where it's copied into a reporting dict — never compared against a live R:R value. It's dead configuration, not an active gate. Rule it out as a cause of unexplained rejections. The only R:R gate enforced in the live pipeline is `MIN_RR_FOR_BUY = 1.5` in `live_scan_engine.py`.

**Q3 — Was Aug 11 a real success?**
**Still unresolved.** Requires querying the actual `pipeline_events` and `phase20_paper_trades` tables directly, which this review didn't have access to. Continue treating those 64 executions as unverified until checked against the database.

---

## 4. Corrected — Exit Logic Exists, Is Blocked by the Same Root Cause

**v1 claim:** no sell/exit logic exists; the only trigger seen was `STALE_DATA_SAFETY`.

**Correction:** `phase20_exits.py`'s `manage_open_positions()` implements a genuine waterfall, checked in this order: `STOP_LOSS_HIT`, `TARGET_HIT`, `RECOMMENDATION_EXIT` (signal flips to EXIT/AVOID/SELL), `TRAILING_STOP` (locks in ~1R once price reaches 2R above fill), `TIME_EXIT` (max holding days), `MARKET_CLOSE_EXIT` (square-off in the last 15 minutes of session), `PORTFOLIO_RISK_REDUCTION` (daily loss limit breached), `SECTOR_CAP_BREACH`, with `STALE_DATA_SAFETY` only as the last resort when a symbol is missing from the scan entirely.

**Why positions still get stuck:** the price-dependent rules require `quote_reliable` (LIVE/NEAR_LIVE quality), and even rules that don't depend on price (like `TIME_EXIT`) still can't produce an actual fill without a reliable quote — the system deliberately refuses to fabricate one. So a position on a symbol with genuinely stale data sits in `EXIT_PENDING` regardless of which rule wants to fire. This is the same root cause as Section 2, not a separate gap — fixing exits doesn't require new exit logic, it requires the data-freshness fix.

---

## 5. Still Open (not re-verified in this pass)

- **Duplicate ledger tables** (`paper_trades` legacy vs. `phase20_paper_trades` canonical) — flagged in v1, not re-checked against code this pass.
- **Capital sizing vs. instrument universe** (₹50,000 vs. NIFTY constituents priced well above ₹1,000) — still worth considering once sizing is confirmed working end-to-end on live data.

---

## 6. Scope Recommendation (unchanged, reinforced)

Still recommend limiting active development to the 5 canonical pages until a full signal → fill → exit → correct P&L cycle is demonstrated once, on real data. Navigating the codebase for this review reinforced rather than eased this: 60+ top-level modules under `api-server/src/python` alone, several with near-duplicate responsibilities (two `position_sizer.py` files, two `config.py` files with overlapping constants being the two found directly in the course of this review).

---

## 7. Updated Suggested Sequence

1. Log `data_source` / `latest_date` / `age_days` per symbol on a live scan — find out what's really happening with data freshness right now (Section 2, Action 1).
2. Based on that, fix the actual freshness problem on the yfinance side, or scope real Kite integration (Section 2, Action 3) — don't treat Zerodha re-auth as sufficient on its own.
3. Re-verify the Phase 1B/1C fixes produce real fills once live data is flowing, for at least one symbol, end-to-end, with a correct exit and P&L.
4. Resolve Q3 directly against the database — don't carry the Aug 11 numbers forward as validated.
5. Consolidate ledger tables (Section 5).
6. Revisit capital sizing (Section 5) once the above is stable.
7. Correct both SOP versions' pipeline diagrams to match what's actually in code — the Zerodha-fallback description in particular.

---

*This document supersedes the v1 remediation spec. Sections 1–4 are code-verified against the `nse-trade-intraday` source (two snapshots diffed against each other). Section 5 items are carried forward from v1 without re-verification in this pass.*
