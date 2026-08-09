# Phase 27E + 27F — Combined Summary

ApexQuant AI · NSE paper-trading platform · PAPER TRADING / RESEARCH ONLY
Both phases are **read-only, advisory-only** additions over the canonical stores — no new probes, no trading actions, no new thresholds.

---

## Phase 27E — Operator Analytics (`/operator-analytics`)

**Purpose:** give operators a single analytics page explaining *what the pipeline actually did* — funnel, timing, rejections, decision quality, risk posture, and trends — with honest evidence labels.

### What it delivers
- **Pipeline funnel** — per-stage in/out counts for the latest canonical scan.
- **Timing analysis** — stage durations and scan cadence.
- **Rejection analysis** — rejected **events** vs rejection-reason **occurrences** counted separately (one event can trip several gates), with `pct_of_occurrences` clearly labelled.
- **Decision quality** — final action mix, confidence distribution, blocked-vs-executed outcomes.
- **Risk posture & trends** — risk gate outcomes and multi-scan trend lines.
- **Evidence honesty** — every section carries a state: `OK`, `PARTIAL`, `SOURCE_UNAVAILABLE`, or `VERIFIED_EMPTY` (verified empty is real data, an unavailable source is never shown as zero). A sources-availability banner summarises what could/couldn't be read.
- Demo/replay sessions are filtered out of analytics.

### Implementation
- Backend: `phase27_operator_analytics.py` → `operator_analytics_report(scan_id=None)`.
- Command: `operator_analytics_report` in `main.py`; route `GET /api/operator-analytics/report` (30s cache + single-flight).
- Frontend: `OperatorAnalytics.tsx` with evidence badges and SourcesBanner.
- Tests: **21 unit tests** passing.

---

## Phase 27F — System Readiness Dashboard (`/system-readiness`)

**Purpose:** answer one question deterministically — **"Is the system ready to safely run the next/current paper trading session?"**

### What it delivers
- **Overall verdict** READY / WARNING / BLOCKED / UNKNOWN with a deterministic fold:
  any blocking BLOCKED → BLOCKED; else any blocking UNKNOWN → UNKNOWN (fail-safe — missing evidence never yields READY); else any non-READY → WARNING; else READY.
- **10 grouped domains**: Market & Data, Broker & Authentication, Pipeline, Strategy & Risk, Execution, Portfolio, Persistence & Recovery, Scheduling, Safety Controls, Configuration. Each check shows status, blocking flag, expected vs actual, evidence (expandable), last-checked time, and a remediation hint.
- **Safety card**: PAPER mode positively verified (explicit boolean required — absent/malformed → UNKNOWN); any live-execution flag set → blocking BLOCKED; circuit breaker tripped **or unreadable** → blocking BLOCKED; secrets presence-only.
- **Data freshness table** reusing existing platform thresholds only (scan staleness budgets, in-session heartbeat budget) — none defined by this phase.
- **"Run readiness check"** button — read-only cache bypass (`?force=true`), re-evaluates without new probes.
- **Check history** — compact snapshots (verdict + counts + blocking failures) in the existing KV store, capped at 50.
- Strictly **read-only collection** — portfolio health is read via a side-effect-free path (no alert/KV writes on poll).
- Data-contract correctness: provider coverage reads the canonical `symbols_requested` / `symbols_received` fields, with malformed metadata degrading to UNKNOWN instead of failing.

### Implementation
- Backend: `phase27_readiness.py` (fail-soft collectors, per-domain check builders, deterministic fold, freshness, KV history).
- Commands: `system_readiness_report`, `system_readiness_history`; routes `GET /api/system-readiness/report` (+`?force=true`) and `/history`.
- Frontend: `SystemReadiness.tsx`, registered in the Operations Agent nav group.
- Tests: **39 unit tests** passing, including missing-telemetry-never-READY per source, live-flag blocking, breaker fail-safe, staleness budgets open vs closed, scheduler enum mapping, and a producer-contract test against real scan metadata.

---

## Joint verification
| Check | Result |
|---|---|
| 27E unit tests | 21 passed |
| 27F unit tests | 39 passed |
| Dashboard typecheck (`tsc --noEmit`) | clean |
| API-server + lib typecheck (`tsc -b`) | clean |
| Live API + browser screenshots (both pages) | verified |

Detailed reports: `PHASE27E_SUMMARY.md`, `PHASE27E_VERIFICATION.md`, `PHASE27F_SUMMARY.md`, `PHASE27F_VERIFICATION.md`, `PHASE27_EF_FINAL_VERIFICATION.md`.
