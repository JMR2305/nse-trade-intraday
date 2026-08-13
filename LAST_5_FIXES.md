# Last 5 Fixes — ApexQuant AI

_All changes are in the `artifacts/api-server` (Python) and `artifacts/trading-dashboard` (React) layers unless noted._

---

## Fix 1 — Task #670: Morning stale data no longer shown as active
**Problem:** Post-market scans (fired by the scheduler after 15:30 IST) carried `data_quality: LIVE` from yfinance returning last-close bars. Operators seeing a scan timestamped 23:57 IST assumed live prices were flowing.

**Resolution:** The scan-level regime and market-phase metadata now carries an explicit `market_closed_mode` flag when the scan runs outside the 09:15–15:30 IST window. The Agent Journey and scan-detail views surface this so operators cannot mistake a post-close research scan for a live intraday one.

---

## Fix 2 — Task #671: Last scan of every session sealed against orphan BUY labels
**Problem:** The final scan before 15:30 IST sometimes completed its pipeline stages but the executor tick never ran (session ended). Those symbols remained in a half-resolved state with `paper_eligible=True` in the snapshot but no `pipeline_events` row — causing the Agent Journey to show "Paper order placed" with no ledger entry.

**Resolution:** A post-scan reconciliation pass now emits an `EXECUTION_SKIPPED_WITH_REASON` event for every BUY-eligible symbol that has no terminal execution event 60 seconds after the pipeline completes. These orphan events seal the journey so operators see a clear "Skipped — session ended" label instead of a misleading positive.

---

## Fix 3 — Task #672: Dual R:R threshold gap now surfaces an operator alert
**Problem:** The Risk Agent uses a minimum R:R of 1.5 (scan-time gate); the Execution layer uses 2.0 (order-time gate). Symbols that cleared the Risk Agent showed `RISK_APPROVED + BUY` in the journey, then silently disappeared. There was no indication that a second, stricter threshold existed.

**Resolution:**
- `replay_engine._build_symbol_journey()` now detects when `event_type=EXECUTION_SKIPPED_WITH_REASON`, `min_risk_reward` is in `failed_gates`, and `all_gates_passed=True` (Risk Agent approved). It adds a `dual_threshold_warning` string to the execution step's `detail` payload, reading the thresholds directly from the event — never hardcoded.
- `AIInvestigationCentre.tsx` renders an amber `AlertTriangle` callout when `dual_threshold_warning` is present on the journey step.

---

## Fix 4 — Task #667: Local backtesting setup guide added
**Problem:** Developers setting up paper-analytics backtesting locally had no reference document. Environment variables, DB prerequisites, and the correct pytest command were undiscovered or guessed from CI configs.

**Resolution:** `LOCAL_DEVELOPMENT_BACKTESTING_SETUP.md` added to the repo root covering:
- Required environment variables and where to set them
- DB schema prerequisites (paper_trades, paper_portfolio, pipeline_events tables)
- Step-by-step command sequence to run `paper-analytics-smoke` locally
- Common failure modes and how to diagnose them

---

## Fix 5 — Task #673: Regression test guard for Agent Journey execution labels _(just merged)_
**Problem:** The "Paper order placed" mislabelling bug (#665) was fixed in `_build_symbol_journey()`, but with no tests the fix could silently revert in a future edit.

**Resolution:** `tests/test_journey_execution_labels.py` — 12 unit tests, no DB required:

| Case | Execution outcome | Expected result | Key assertion |
|---|---|---|---|
| 1 | `EXECUTION_SKIPPED_WITH_REASON` (R:R failed) | `SKIPPED` | "Paper order placed" absent; gate text in reason |
| 2 | `ORDER_REJECTED` | `REJECTED` | "Paper order placed" absent |
| 3 | `ORDER_SUBMITTED` or `ORDER_EXECUTED` | `PAPER BUY` | reason = "Paper order placed and recorded" |
| 4 | No event, `paper_eligible=True` | `ELIGIBLE` | reason contains "not recorded"; "Paper order placed" absent |
| 5 | No event, `paper_eligible=False` | `SKIPPED` or `REJECTED` | "Paper order placed" absent |
| 6–9 | Dual-threshold warning logic | `dual_threshold_warning` fires/not | Only fires for SKIPPED + RR + Risk-approved; not for REJECTED, not for non-RR gates, not when Risk also blocked |

Also tightened the `paper_eligible=True/no-event` reason from `"Paper eligible"` to `"Paper eligible — execution outcome not recorded for this scan"` so it is unambiguous in the UI.

---

_Generated: 2026-08-13_
