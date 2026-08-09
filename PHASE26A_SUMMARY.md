# Phase 26A — Portfolio Pre-Check Visibility: Summary

**Status:** ✅ Implemented, verified, and merged (Task #520) — August 9, 2026

## Goal
Make the Portfolio Pre-Check gate fully visible across the trading pipeline: events, dashboard UI stage, replay reconstruction, and tests — without changing any gating logic (the Portfolio Engine remains the single source of validation decisions).

## What was delivered

### 1. Events with exact engine reasons
- Every BUY candidate evaluated by Portfolio Pre-Check emits an `PRECHECK_APPROVED` or `PRECHECK_REJECTED` event carrying the engine's exact reason list — never recomputed or paraphrased.
- Events are emitted at the true decision point in `execute_buy`, covering **both** production paths (phase20 auto executor and intelligence path).
- Emission is fail-safe and append-only: an event failure never blocks or alters a trade decision.
- Every event is attributed to the canonical scan id (resolved from the latest scan snapshot, fail-safe to `None`).

### 2. Pipeline stage everywhere
- New `PORTFOLIO_PRECHECK` stage sits between **Strategy** and **Risk** in the 11-stage pipeline vocabulary.
- Reflected consistently in: pipeline summary API, replay stage list (order 6), Ops Centre trace/bottleneck pairs, Mission Control funnel, Live Command Centre rejection views (with reason rendering), Ops V2/V3 sections, and the AI Investigation Centre.

### 3. Honest counts
- The stage reports `approved_count` (event-derived approvals only), `evaluated_count`, and `not_evaluated` (pass-through) separately.
- Anything labeled "Approved" in any UI shows **only** event-derived approvals — pass-through symbols are never counted as approved.
- Conservation holds: `in = out + rejected`.
- Per-symbol journeys mark downstream stages (Risk, AI Decision, Execution) as **SKIPPED** with blocking reasons when pre-check rejected the symbol.

### 4. Replay from events alone
- Replay reconstructs pre-check decisions purely from stored events — no re-evaluation.
- Verified live: `/api/replay/sessions/latest` shows `portfolio_precheck` at order 6, correctly chained; counts honest (e.g. approved 0 / not_evaluated 48 on a session with no BUY attempts).

### 5. Tests & verification
- ~24 backend tests (`test_portfolio_precheck_events.py`, `test_pipeline_events.py`), including per-rule event tests, scan-attribution end-to-end (event → replay), and a regression test ensuring unevaluated symbols are never counted as approved.
- Dashboard component tests updated (SessionWidgets funnel proves only `approved_count` renders as "Pre-Check Approved"); 45+ frontend tests passing.
- Full monorepo typecheck clean; complete Python test sweep passing.
- Architect code review passed (3 findings fixed); completion validation passed.
- Detailed verification report: `artifacts/api-server/src/python/PHASE26A_PRECHECK_VISIBILITY.md`.

## Out of scope
- Gate rewiring (Task #15) — pre-check ordering/wiring changes were explicitly excluded.

## Follow-up
- Task #539: guard test keeping dashboard stage lists in sync with the backend `pipeline_events.STAGES` vocabulary.
