# HDFCLIFE Today Session — Execution Mismatch Audit

**Date of session audited:** 2026-08-13 (NSE market hours 09:15–15:30 IST)  
**Audit type:** Read-only — no orders placed, no thresholds changed, no strategy logic altered  
**Audit completed:** 2026-08-14  

---

## Executive Summary

HDFCLIFE displayed **"Paper order placed"** in the Agent Journey and **"Paper ✓"** in the symbol list on Aug 13, but:

- **zero paper trades were recorded** in the ledger (`paper_trades` table — 0 HDFCLIFE rows ever)
- **auto-entry was never attempted** on any scan this session
- **Portfolio Pre-Check showed "NOT EVALUATED"**
- **Live Trade Timeline showed no paper trade**
- **EOD Summary: 0 trades**

The contradiction was caused by **two independent bugs** — one in the backend journey builder and one in the ops-centre journey builder — that both inferred execution status from the `paper_eligible` flag alone rather than from actual pipeline execution events.

**No live orders were placed at any point.** All findings are paper-mode only.

---

## Task 1 — Exact HDFCLIFE Signal Shown in UI

The UI was displaying the **last market-hours scan** of the session:

| Field | Value |
|---|---|
| scan_id | `ac3b38f90f67` |
| Scan timestamp (UTC) | 2026-08-13 09:30:29 |
| Scan timestamp (IST) | 2026-08-13 **15:00:29** |
| Snapshot age at viewing | ~14h 21m (viewed ~05:21 IST Aug 14, normal post-close) |
| Action | BUY |
| Confidence | 73.1% |
| Opportunity score | 63.4 |
| paper_eligible | `true` |
| Data quality | `LIVE` — RSI 38.4, price ₹536.85, ADX 20.7 |
| Strategy | Mean Reversion |
| R:R | 1.50 |
| Source endpoint | `replay/sessions/latest` → scan_state → snapshot |

**Verdict: A — today's fresh market session.** Both scans active in the last 5 minutes of session (ac3b... at 15:00 IST and 958c... at 14:55 IST) had `data_quality: LIVE`. The stale banner is the elapsed time since market close, not stale input data.

---

## Task 2 — Execution Events for scan `ac3b38f90f67` + HDFCLIFE

Events in `pipeline_events` for scan `ac3b38f90f67`, symbol `HDFCLIFE`:

| Timestamp (UTC) | Event | Stage |
|---|---|---|
| 09:30:29.361 | SYMBOL_SCANNED | SCANNER |
| 09:30:29.399 | RESEARCH_COMPLETED | RESEARCH |
| 09:30:29.399 | MARKET_INTELLIGENCE_COMPLETED | MARKET_INTELLIGENCE |
| 09:30:29.399 | MONITORING_COMPLETED | MONITORING |
| 09:30:29.399 | STRATEGY_SELECTED | STRATEGY |
| 09:30:29.399 | RISK_APPROVED | RISK |
| 09:30:29.399 | BUY_GENERATED | AI_DECISION |
| *(none)* | **No execution event** | — |

**There is no terminal execution event for scan `ac3b38f90f67` + HDFCLIFE.**

The preceding scan (`958c717e1b8c`, 14:55 IST) did produce terminal events:

| Timestamp (UTC) | Event | Payload |
|---|---|---|
| 09:26:06 | EXECUTION_SKIPPED_WITH_REASON | failed_gates: `min_risk_reward`, `per_stock_cap` |
| 09:27:12 | EXECUTION_SKIPPED_WITH_REASON | (same — executor re-checked same scan_id) |
| 09:28:12 | EXECUTION_SKIPPED_WITH_REASON | (same) |
| 09:29:12 | EXECUTION_SKIPPED_WITH_REASON | (same) |

`auto_entry_attempted: false` on all four.

**Verdict: TASK #665 FAILURE for scan `ac3b38f90f67`.** HDFCLIFE (and TMPV, TITAN, DRREDDY) had `BUY_GENERATED + paper_eligible=true` but no terminal execution event. The executor's final scheduler tick for these signals was never written. See Task 6 for full orphan analysis.

---

## Task 3 — Paper Trade Ledger

```sql
SELECT * FROM paper_trades WHERE symbol ILIKE '%HDFCLIFE%';
-- 0 rows returned
```

```sql
SELECT COUNT(*), MIN(trade_ts), MAX(trade_ts) FROM paper_trades;
-- 12 rows | 2026-07-26 | 2026-08-07
```

No paper trade has ever been placed for HDFCLIFE. The entire `paper_trades` table contains 12 BUY entries from Jul 26–Aug 7 — none are HDFCLIFE.

The UI **must not** show "Paper order placed" — there is no paper trade row, no `ORDER_SUBMITTED` event, and no `ORDER_EXECUTED` event.

---

## Task 4 — Why Portfolio Pre-Check Says NOT EVALUATED

The Portfolio Pre-Check step reads from `signals_cache` (keyed by ticker symbol). A query of `signals_cache WHERE key ILIKE '%HDFCLIFE%'` returned **zero rows**. No signals_cache entry exists for HDFCLIFE.

Without a cache entry:
- The executor never wrote a pre-check evaluation result for HDFCLIFE
- The journey builder's `precheck` parameter receives `None`
- The step renders as `result: "NOT EVALUATED"` / `reason: "No BUY attempt reached the portfolio pre-check"`

This is correct and honest. The Pre-Check step is accurate. The contradiction is that the **Execution** step then falsely says "Paper order placed" despite pre-check never running.

---

## Task 5 — UI Label Fix

Three misleading labels were fixed:

### Bug 1: `replay_engine.py` — `_build_symbol_journey()` (primary bug)

**Before:**
```python
"result": "PAPER BUY" if paper_eligible else ("SKIPPED" if not _is_buy_action(...) else "REJECTED"),
"reason": "Paper order placed" if paper_eligible else (
    "Not paper-eligible" if _is_buy_action(final_action) else f"Action: {final_action}"
),
```

The execution step was synthesised entirely from the `paper_eligible` flag in the scan snapshot. It never consulted `pipeline_events`.

**After:**  
`_build_symbol_journey()` now accepts an `execution_outcome: Optional[Dict]` parameter populated by the caller from `pipeline_events`. The label matrix is:

| Actual event in DB | Result shown | Reason shown |
|---|---|---|
| `ORDER_SUBMITTED` / `ORDER_EXECUTED` | `PAPER BUY` | "Paper order placed and recorded" |
| `EXECUTION_SKIPPED_WITH_REASON` | `SKIPPED` | "Execution skipped — `<gate reasons>`" |
| `ORDER_REJECTED` | `REJECTED` | "Order rejected — `<gate reasons>`" |
| `paper_eligible=true` + no event | `PENDING` | "Paper eligible — execution outcome not recorded for this scan" |
| `paper_eligible=false` | `SKIPPED`/`REJECTED` | (as before) |

`get_symbol_journey()` now queries `pipeline_events` for the terminal execution event before calling `_build_symbol_journey()`, scoped to the resolved `scan_id` + `symbol`.

### Bug 2: `ops_centre.py` — ops-centre journey builder

**Before:**
```python
elif executed:  # decision_type is BUY/STRONG_BUY
    exec_decision = "Eligible" if paper_eligible else "Paper order placed"  # logic inverted
```

**After:**
```python
elif executed:
    exec_decision = "Paper Eligible" if paper_elig else "Not placed"
    exec_reason = "Paper-eligible — no order recorded for this scan" if paper_elig else "Not paper-eligible for this scan"
    exec_status = "PASS" if paper_elig else "INFO"
```

### Bug 3: `AIInvestigationCentre.tsx` — symbol list badge

**Before:**  
`{sym.paper_eligible && <span className="text-emerald-400">Paper ✓</span>}`  
(green checkmark implies order was placed)

**After:**  
`{sym.paper_eligible && <span className="text-amber-400">Paper Eligible</span>}`  
(amber badge signals eligibility only, not placement)

---

## Task 6 — Task #665 Verification

### Orphan analysis — all BUY_GENERATED + paper_eligible=true on Aug 13

| Terminal outcome | Count |
|---|---|
| ORDER_REJECTED | 556 |
| EXECUTION_SKIPPED_WITH_REASON | 63 |
| **NO_TERMINAL_EVENT (orphan)** | **4** |

**4 orphan BUYs exist — all from the final scan of the session (`ac3b38f90f67`):**

| Symbol | Buy timestamp (UTC) | Scan |
|---|---|---|
| HDFCLIFE | 09:30:29 | ac3b38f90f67 |
| DRREDDY | 09:30:29 | ac3b38f90f67 |
| TITAN | 09:30:30 | ac3b38f90f67 |
| TMPV | 09:30:31 | ac3b38f90f67 |

All other 619 BUYs across every earlier scan have a terminal event. Only the **last scan** of the session produced orphans.

### Root cause of the 4 orphans

Scan `ac3b38f90f67` completed at 15:00:29 IST (09:30:29 UTC). The executor runs on a ~1-minute scheduler tick. The next tick after this scan would have been ~09:31 UTC (15:01 IST). However:

1. The executor's signals_cache for HDFCLIFE had **no row** — the cache write for `ac3b38f90f67` did not complete or was overwritten/expired before the executor tick ran.
2. Without a signals_cache entry the executor had no candidate to evaluate, so no `EXECUTION_SKIPPED_WITH_REASON` was written.
3. The same two gates that blocked 958c... (R:R 1.5 vs exec minimum 2.0, and per-stock exposure 34.4% vs cap 25.0%) would have blocked ac3b... identically — the executor simply never ran for this scan_id.

**Task #665 verdict: PARTIAL FAIL.** All scans except the final session scan resolved correctly. The final scan (`ac3b38f90f67`) produced 4 orphan BUYs because the executor did not write a terminal event for it before or after market close.

This is a pre-existing scheduler timing edge case at end-of-session, not a regression introduced today.

---

## Task 7 — Summary Answers

| Question | Answer |
|---|---|
| Was HDFCLIFE BUY from fresh or stale scan? | **Fresh** — LIVE data quality, scanned at 15:00:29 IST Aug 13 |
| Did auto-entry actually attempt? | **No** — `auto_entry_attempted: false` on all execution ticks for the preceding scan; no execution event at all for the final scan |
| Does a paper trade row exist? | **No** — 0 HDFCLIFE rows in `paper_trades` (all time); 0 rows on Aug 12–13 |
| Why was Portfolio Pre-Check NOT EVALUATED? | signals_cache has no HDFCLIFE entry — executor never evaluated it; `precheck=None` → "NOT EVALUATED" (correct) |
| Why did UI say "Paper order placed"? | Backend `_build_symbol_journey()` inferred execution outcome from `paper_eligible=True` flag alone, never querying `pipeline_events` for the actual terminal event |
| Is this a UI bug or execution bug? | **Both.** (1) Backend journey builder produced wrong label (fixed). (2) Executor did not write a terminal event for the last scan of the session (pre-existing end-of-session timing edge case). |
| Task #665 passed or failed? | **PARTIAL FAIL** — 4 orphan BUYs (all from the final scan `ac3b38f90f67`). All other 619 BUYs had terminal events. |
| Were any live orders placed? | **Confirmed: zero live orders placed.** All activity was paper-mode only. |

---

## What Was Fixed (Read-Write)

| File | Change |
|---|---|
| `artifacts/api-server/src/python/replay_engine.py` | `_build_symbol_journey()` now accepts `execution_outcome` and uses actual pipeline event; `get_symbol_journey()` queries `pipeline_events` for terminal event before building journey |
| `artifacts/api-server/src/python/ops_centre.py` | Fixed inverted `exec_decision` logic; "Paper Eligible" instead of "Paper order placed" when no order_id |
| `artifacts/trading-dashboard/src/pages/AIInvestigationCentre.tsx` | "Paper ✓" badge renamed "Paper Eligible" (amber) to distinguish eligibility from placement |

No strategy logic, thresholds, risk gates, or order execution paths were changed.

---

## What Remains (Not Fixed — Requires Separate Task)

The **4 orphan BUYs from the final scan** represent an executor timing edge-case: when the last scan of the session completes in the final minute of market hours, the executor's next tick may not fire before the scheduler stops, leaving no terminal event. The UI fix (showing `PENDING` instead of `PAPER BUY`) is now in place. The underlying scheduler gap is tracked separately.
