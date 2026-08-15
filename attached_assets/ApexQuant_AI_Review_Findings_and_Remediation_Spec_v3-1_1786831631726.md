# ApexQuant AI — Independent Review Findings & Remediation Spec (v3)

**Sources this round:** SOP v4.0 (self-reported Bug Audit + Kite LTP Overlay "Option A" implementation) and the one code snapshot actually reviewed since v2 (a diagnostic-logging-only change to `live_scan_engine.py`). No code has been supplied for anything from "Bug Audit Task 1" onward — that entire section of this document is based on the SOP's claims, not on code I've read myself.

---

## What changed since v2 of this spec

- **Correction:** v2 of this spec stated the position-sizer fix was "confirmed... correctly wired end-to-end." That was wrong. Their own Bug Audit (Task 1) found the wiring bug I missed.
- **Q3 (Aug 11) is now confirmed** — and reveals a detail worth its own follow-up: the phantom executions came from a process outside the reviewed codebase, not from a bug inside it.
- **A major architecture decision surfaced:** "Kite LTP Overlay — Option A" was built in direct response to this spec's Section 2. It does **not** make Zerodha the primary data source. It's narrower than that, and doesn't fulfill the explicit requirement given last round ("Zerodha primary, Yahoo fallback / backtesting only").
- New items: an internal contradiction in the SOP's own weakness tracking (R:R gate), an unidentified external process writing into the trade ledger, and a couple of still-open exploration-mode issues.
- Everything below Section 3 is self-reported in the SOP only, not independently verified against code in this pass — flagged explicitly where relevant.

---

## 1. Correction: Position-Sizer Fix Was Not Fully Verified Last Round

**What v2 of this spec said:** the sizer's "floor to cap" fix was traced end to end — `pre_trade.py` computes `capped_qty`, and `phase20_executor.py` reassigns `qty` to it — and called "a complete fix, not a partial one."

**What was actually wrong, per their own audit:** `phase20_executor.py` was reading the cap-reduction flag from the wrong level of the result dictionary — checking `_rv_result.get("size_reduced_to_cap")` at the top level, when the real value lived nested under `rv.to_dict()["summary"]`. That top-level key is always `None`, so the reassignment branch never actually executed — the "fix" computed the right answer and then silently discarded it. A second, related bug: a downstream validator kept comparing against the *original* oversized quantity even after a resize was intended, producing a false `CRITICAL` rejection on top of the first bug.

**Why I missed it:** I confirmed the right function names, the right variables, and the right intent were present in the diff, but didn't verify the exact shape of the dictionary being read against the exact shape of the dictionary being returned. Structurally-correct-looking code with a wrong data path is exactly the kind of bug that survives a read-through and only shows up when it's actually exercised.

**Both are now reported fixed** (Bug Audit Tasks 1 and 2, HIGH severity each) — self-reported, not re-verified by me against code this round.

---

## 2. Architecture Clarification: "Option A" Does Not Make Zerodha Primary

This is the most consequential finding this round, because it directly bears on the instruction from last message.

**What was implemented ("Option A"):** a `kite_ltp_overlay.py` module, gated by `KITE_LTP_OVERLAY_ENABLED` (reported as now set to `true` in the shared environment). When enabled and a Kite session is verified, it supplies the **live last-traded price** used to (a) fill a BUY once a trade has already been approved, and (b) get a valid quote to close a stuck `EXIT_PENDING` position.

**What it explicitly does not touch, per the SOP's own invariant table:**
- `ohlcv_source` — always `yfinance_daily_bars`, never changes
- `indicator_source` — always `yfinance_daily_bars`, never changes
- `data_quality_for_indicators` — always the yfinance age-based grade; **"Zerodha session state has no effect on quality grades"** (their words)
- Strategy signals and RSI/ADX/EMA computation — unchanged, still 100% daily-bar yfinance

**Net effect:** whether a signal is even eligible to become a BUY at scan time is entirely unaffected by this change — that gate is still 100% governed by yfinance daily-bar age, exactly as before. What changed is what happens *after* a signal already cleared that gate: it can now get a genuinely live fill price and a genuinely live exit quote, instead of a stale daily close. This is a real, useful improvement — it's why the four stuck `EXIT_PENDING` positions are expected to resolve — but it is not "Zerodha as primary provider." The SOP itself names the thing that would actually satisfy that requirement: **"Option B" — full intraday Kite candles feeding the indicators and signal generation directly — and explicitly scopes it as a separate, larger, not-yet-started project.**

**Recommendation:** if Zerodha-as-primary is a firm requirement rather than a nice-to-have, say so explicitly and treat it as Option B, scoped and sequenced on its own — don't let "Option A" close out that request in tracking, since it doesn't do the same thing.

---

## 3. Resolved: Q3 (Aug 11), With a New Follow-Up Item

**Now confirmed, per their DB-level audit:** the 63 `ORDER_EXECUTED` events on Aug 11 correspond to 0 rows in the canonical `phase20_paper_trades` ledger. Treat all of them as non-events — they never happened as real paper trades.

**New detail, not previously known:** the trade IDs on those phantom events carry a `BTT-` prefix, which the SOP attributes to "an external `intraday_bot` process" — distinct from the canonical executor this whole review has been examining. That process's writes to the trade ledger failed silently every time.

**Follow-up action (new, not currently tracked as a task anywhere I can see):** identify what this external process is, whether it's still running, and why it has write access to the same event stream as the canonical system. A watchdog on scan-loop *frequency* (the currently-open item) doesn't address a *different process* writing execution events at all — those are two separate problems being tracked as one.

---

## 4. Internal Contradiction to Resolve: the R:R "2.0 Execution Gate"

The SOP's own weakness table has two entries that can't both be true as written:

- One entry lists the scan-vs-execution R:R gap (1.5 vs. 2.0) as **open, deferred to Phase 2**, and the roadmap has a task to "lower the execution gate from 2.0 to 1.5."
- Another entry, in the same document, states `AI_MIN_RR_RATIO = 2.0` is **dead configuration, never enforced anywhere** — matching exactly what I found independently reading the code myself last round.

If the second is correct (and it matches my own independent finding), there is no live 2.0 gate to lower, and the roadmap task is solving a problem that doesn't exist as described. **Resolve this before spending engineering time on it:** either locate a real, enforced 2.0 check somewhere neither of us has found, or delete the unused config constant and close both the weakness entry and the roadmap task as moot.

---

## 5. Currently Open Items (self-reported, consolidated)

- **Daily bars, not intraday** — indicators and signal generation remain 100% daily-bar. This is "Option B," unscoped.
- **Scanner runs post-market** with no UI indication, risking operator confusion about signal freshness.
- **Scan-loop watchdog missing.** The Aug 11 runaway (88 scans, up to 5/minute) has a visibility fix (a dashboard gap-badge) but no root-cause fix or rate ceiling. Why the DB-durable lock failed to prevent it is an open question in their own document.
- **Exploration mode has a silent insert failure** — events are logged, but 0 rows land in its table. Unexplained.
- **Exploration-mode exits still price off stale daily close**, not the new Kite LTP path — only the main exit path was updated.
- **The external `BTT-` process** (Section 3) — not currently tracked as its own item anywhere visible.
- **The R:R contradiction** (Section 4) — not currently tracked as needing resolution, just carried forward as if settled.

---

## 6. Independent Reviewer's Take on the SOP's Open Architecture Questions

1. **Option A vs. Option B:** treat Option A as an interim step, not an end state, but decide on data rather than principle — let it run a couple of weeks producing real trades with real P&L. If a daily-bar-decided, live-priced strategy shows coherent expectancy, the edge is in stock-picking, not timing, and Option B may not be worth it. If fills consistently land far from what the daily-bar thesis assumed, that's the signal Option B is actually needed.
2. **Indicator/execution mismatch:** real and currently unaddressed. A cheap partial fix ahead of any Option B decision: at execution time, check how far live LTP has drifted from the daily-bar reference price and skip or flag trades past some threshold.
3. **R:R 2.0 → 1.5:** the question's premise doesn't hold — see Section 4. Nothing to lower; decide whether to wire a real gate (backed by backtest data) or delete the constant.
4. **Watchdog/lock failure:** can't be diagnosed without reading the actual lock code — not reviewed. Independent of root cause, pair the lock with a hard rate ceiling enforced at the scan entrypoint itself, so a lock failure isn't a single point of failure.
5. **Capital model:** should be persistent, not a daily reset. Positions are demonstrably carrying multiple days (Aug 4 through at least Aug 13); resetting notional capital daily either double-counts capital tied up in open positions or ignores real exposure when sizing new trades. Daily reset only makes sense once the system reliably flattens by end of session, which isn't true yet.

---

## 7. Verification Gap

Confirmed by direct code review (v1 → v2 zip diff, and the v2 → v3 diagnostic-logging diff): the position-sizer duplication, the original cap-rejection bug's real location, Q1 and Q2 resolutions, the Zerodha/Kite-not-wired finding, and the exit-logic waterfall in `phase20_exits.py`.

**Not verified by me — self-reported in SOP v4.0 only:** Bug Audit Tasks 1, 2, 4, 5; the entire Kite LTP Overlay implementation (`kite_ltp_overlay.py`, the 14 new fields, the 37 tests); `KITE_LTP_OVERLAY_ENABLED` actually being set in the live environment; Phase 27E/27F; and the claim that the four `EXIT_PENDING` positions will resolve automatically. If the same level of independent verification as earlier rounds is wanted, the current zip is needed.

---

## 8. Suggested Sequence

1. Get the current zip reviewed directly — confirm Bug Audit Tasks 1/2/5 and the Kite LTP Overlay are wired the way the SOP describes, given Section 1 of this document shows self-reported "fixed" isn't always reliable on the first pass.
2. Resolve the R:R contradiction (Section 4) before touching that roadmap task.
3. Identify the external `BTT-`/`intraday_bot` process (Section 3) — separate from, and in addition to, any scan-loop watchdog work.
4. Confirm at least one real `P20-` trade completes end to end (signal → fill → exit → correct P&L) now that the overlay is reportedly live — this is still the single most important unproven claim in the whole system.
5. Decide Option A vs. Option B using a few weeks of real trade data, not architecture debate (Section 6.1).
6. Make the capital model persistent (Section 6.5).
7. Address the remaining open items in Section 5 in whatever order fits — none of them block the core loop the way items 1–4 do.

---

*This document supersedes v2. Sections 1–4 combine SOP v4.0 claims with independent code findings from prior rounds; Sections 5–6 are primarily SOP-sourced and flagged accordingly; Section 7 states the verification boundary explicitly.*
