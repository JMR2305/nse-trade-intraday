# Phase 27E — Operator Analytics

**Status: COMPLETE** · READ-ONLY · ADVISORY-ONLY · Paper trading / research only

One page answering *"How has the platform been behaving?"* — built strictly on
canonical stores; no new tables, no trading-logic changes, no recomputation of
existing analytics.

## What was built

### Backend — `phase27_operator_analytics.py`
Single entry `operator_analytics_report(scan_id=None)` (main.py command
`operator_analytics_report`), returning:

| Section | Canonical source |
|---|---|
| Session summary | `replay_engine.get_replay_sessions()` |
| Pipeline funnel (in/out/rejected/pending + conversion %) | unified replay snapshot (`build_replay`) — the ONLY count source |
| Stage timing avg/median/p95 | `pipeline_events` per-symbol gaps (same gap definition as `stage_summary`); `insufficient_telemetry` flag when < 3 samples |
| Rejection breakdown | rejection events — RAW canonical reason codes preserved (`payload.error`, `failed_gates` keys, `reasons` list); rejected EVENTS and reason-code OCCURRENCES counted separately (one event can fail several gates; % = share of occurrences); symbol/event-id drill-down |
| Decision distribution | decision events + canonical snapshot `final_action` ("STRONG BUY"/"STRONG_BUY" normalised); snapshot splits omitted (never mixed) if snapshot is from a different scan |
| Risk interventions | `PRECHECK_APPROVED/REJECTED`, `RISK_APPROVED/REJECTED` events with reasons; explicit evidence states instead of fabricated zeros |
| Cross-scan trends | last 5 replay sessions, bounded per-scan event fetches (≤1000 each) — never full-history scans |

### API — `routes/phase27.ts`
`GET /api/operator-analytics/report` — 30s in-process cache + single-flight
(same pattern as the strategy-optimization report).

### Frontend — `pages/OperatorAnalytics.tsx` at `/operator-analytics`
Registered in `App.tsx` + Operations group in `AgentConfig.ts`. Every card
shows its source label. Performance & Time-of-Day reuses the existing
`/paper-analytics/summary` + `/paper-analytics/snapshot` endpoints
client-side — **never recomputed**. 60s query timeout for the slow aggregate.

## Honesty guarantees
- Every canonical source reports availability in a `sources` map; read failures render as SOURCE UNAVAILABLE, truncated fetches as PARTIAL, and true empties as VERIFIED EMPTY — never conflated.
- Synthetic "demo" replay sessions are excluded from session summary and trends.
- Timing never inferred: `INSUFFICIENT TELEMETRY` badges when samples < 3.
- Rejection reason codes shown verbatim; unknown payloads fall back to the raw
  event type, never invented.
- Snapshot-based splits only when snapshot `scan_id` matches the replay scan.
- Empty sections say so explicitly (no zeros passed off as evidence).

## Tests
`test_phase27_operator_analytics.py` — 21 tests: reason extraction per event
type, aggregation counts/pcts/determinism, decision normalisation +
different-scan omission, risk approved/blocked/no-evidence, timing
percentiles + insufficient/unparseable-ts handling, funnel conversion (0-in →
no fabricated %), trends bounded fetches, hermetic end-to-end report +
replay-failure survival. All pass; full phase26/27 suites unaffected; tsc clean.

## Out of scope (as specified)
Phase 27F (task #592), new tables, changes to scoring/execution/risk logic.
