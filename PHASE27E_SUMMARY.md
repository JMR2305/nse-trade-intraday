# Phase 27E — Operator Analytics: Summary

**Date:** 2026-08-15  
**Status:** COMPLETE  
**Mode:** PAPER TRADING / RESEARCH ONLY — read-only, advisory-only

---

## What Was Built

Phase 27E adds an Operator Analytics capability that helps the operator understand how ApexQuant AI has been behaving over time. It answers: pipeline funnel, rejection breakdown, decision distribution, risk interventions, cross-scan trends, session summary, and performance / time-of-day breakdowns.

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Python backend | `artifacts/api-server/src/python/phase27_operator_analytics.py` | 487 | Complete |
| React UI | `artifacts/trading-dashboard/src/pages/OperatorAnalytics.tsx` | 540 | Complete |
| Python tests | `artifacts/api-server/src/python/tests/unit/test_phase27e_operator_analytics.py` | 350+ | **NEW — 53/53 passing** |
| Frontend tests | `artifacts/trading-dashboard/src/pages/OperatorAnalytics.test.tsx` | 240+ | **NEW — 15/15 passing** |

---

## Canonical Data-Source Map

| Section | Canonical Source | Module |
|---------|-----------------|--------|
| Pipeline funnel (in/out/rejected/pending counts) | Unified replay snapshot | `replay_engine.build_replay()` |
| Stage timing (avg/median/p95) | Pipeline event timestamps | `pipeline_events.query_events()` |
| Rejection breakdown (reason codes) | Pipeline event store — `RISK_REJECTED`, `PRECHECK_REJECTED`, etc. | `pipeline_events.query_events()` |
| Decision distribution | Pipeline events (`BUY_GENERATED`, `WATCH_GENERATED`, …) + canonical snapshot | `pipeline_events` + `scan_state_store.load_latest_snapshot()` |
| Sector / regime splits | Canonical scan snapshot (`recommendations[]`) | `scan_state_store.load_latest_snapshot()` |
| Risk interventions | Pipeline events (`RISK_APPROVED`, `RISK_REJECTED`, `PRECHECK_APPROVED`, `PRECHECK_REJECTED`) | `pipeline_events.query_events()` |
| Cross-scan trends | Replay session list + per-scan event fetches (bounded) | `replay_engine.get_replay_sessions()` |
| Session summary | Replay sessions | `replay_engine.get_replay_sessions()` |
| Performance stats | Existing paper-analytics endpoints | `/paper-analytics/summary`, `/paper-analytics/snapshot` |
| Time-of-day analytics | Existing paper-analytics endpoints | `/paper-analytics/snapshot` (time_analytics field) |

---

## APIs Reused (No New Endpoints Created)

| main.py command | UI endpoint path | Description |
|-----------------|-----------------|-------------|
| `operator_analytics_report` | `/api` → `operator_analytics_report` | Full operator analytics report |
| `paper_analytics_summary` (existing) | `/paper-analytics/summary` | Performance KPIs |
| `paper_analytics_snapshot` (existing) | `/paper-analytics/snapshot` | Time-of-day analytics |

No new HTTP routes were added. All three were pre-existing dispatcher commands.

---

## Database Changes

**None.** Phase 27E is purely read-only. It queries existing tables (`pipeline_events`, scan state store, replay store) and never writes to any table.

---

## Test Results

| Suite | File | Tests | Result |
|-------|------|-------|--------|
| Python unit | `test_phase27e_operator_analytics.py` | **53** | ✅ 53/53 passed (0.41s) |
| Frontend (Vitest) | `OperatorAnalytics.test.tsx` | **15** | ✅ 15/15 passed (5.58s) |

### Python test coverage
- `TestFunnel` (7): conversion_pct, zero stocks_in, empty replay, source field, timing < 3 samples → insufficient, timing ≥ 3 samples, stage without timing
- `TestAggregateRejections` (8): empty events, non-rejection ignored, pct-of-occurrences vs events, PRECHECK reasons list, RISK failed_gates dict, RISK failed_gates list, SYMBOL error field, symbols sorted
- `TestDecisionDistribution` (7): BUY_GENERATED→BUY, WATCH→WATCH, IGNORE→IGNORE, pct sums to 100, regime extracted, snapshot splits when scan_id matches, splits omitted on mismatch
- `TestRiskInterventions` (5): approved/rejected split (risk), approved/rejected split (precheck), block_rate_pct, reasons populated, None candidates
- `TestEvidenceState` (7): OK, PARTIAL, SOURCE_UNAVAILABLE, VERIFIED_EMPTY — both direct and via aggregate_rejections
- `TestSessionIsolation` (3): demo source excluded, demo scan_id excluded, exception returns empty
- `TestDeterministicAggregation` (3): same input → same output for funnel, rejections, risk_interventions
- `TestOperatorAnalyticsReport` (13): ok=True, advisory_only/read_only=True, all required keys, funnel/rejections/decisions/risk_interventions/trends/session_summary structure, relay error graceful, sources map

### Frontend test coverage
15 tests: page title, loading state, error state, SourcesBanner (hidden / shown on unavailable / shown on truncated), funnel stage with data-testid, insufficient telemetry badge, rejection row render, rejection drill-down expand, EvidenceBadge SOURCE_UNAVAILABLE, EvidenceBadge PARTIAL, decisions BUY count, risk-risk blocked value, trends row render.

---

## UI Route

`/operator-analytics` — registered in `App.tsx:206` and `AgentConfig.ts:225` (Operations Agent group).

### Sections rendered
1. Header (scan id, snapshot ts, refresh button)
2. Sources banner (shown when any source is unavailable or truncated)
3. Pipeline Funnel & Stage Timing
4. Rejection Breakdown + Decision Distribution (side-by-side grid)
5. Risk Interventions
6. Cross-Scan Trends
7. Session Summary
8. Performance & Time of Day (from paper-analytics endpoints)
9. Footer (note, generated_at, event count)

---

## Known Limitations

| Limitation | Impact |
|------------|--------|
| Performance / time-of-day sections only populate after closed paper trades exist | Expected — paper trades take time to accumulate |
| Cross-scan trends require ≥2 real replay sessions; single-session installs show "INSUFFICIENT DATA" | Expected — label shown honestly |
| Stage timing requires ≥3 per-symbol gap samples per stage | Expected — stages with fewer samples show "INSUFFICIENT TELEMETRY" |
| Demo sessions (source="demo" or scan_id="demo") are excluded from trends | By design — synthetic demo data excluded |
| Bounded event fetch (2000/scan) — large scan runs may truncate; counts labeled PARTIAL | By design — bounded per scan to avoid full-history scans |
| Sector/regime splits only when snapshot belongs to the current scan | By design — avoids silently mixing data from different scans |

---

## Duplicate-Source Audit

**No duplicate calculations.** Phase 27E:
- Never recomputes portfolio metrics (delegates to paper-analytics endpoints)
- Never re-implements pipeline counters (reads from pipeline_events store directly)
- Never creates independent trading decisions (advisory_only=True enforced)
- Never re-implements timing logic (uses existing pipeline_events stage gap definition)
- Funnel counts come exclusively from `replay_engine.build_replay()` — the canonical single source

---

## Safety Verification

- `advisory_only: True` in every response
- `read_only: True` in every response
- No `INSERT`, `UPDATE`, or `DELETE` executed by this module
- No portfolio state modified
- No strategy parameters changed
- No trading decisions generated

## Tests
Backend — `tests/unit/test_phase27e_operator_analytics.py` — **31 tests**:
rejected-EVENTS vs reason-OCCURRENCES accounting (multi-gate events), pct =
share of occurrences, reason extraction per event type, all evidence states
(SOURCE_UNAVAILABLE / PARTIAL / VERIFIED_EMPTY / OK), decision normalisation +
different-scan snapshot omission, risk/precheck approved/blocked/no-evidence
(block rate None when no candidates), timing percentiles + insufficient
telemetry below MIN_TIMING_SAMPLES, funnel conversion (0-in → no fabricated %),
demo-session exclusion, trends scan isolation + bounded window, deterministic
aggregation, and `operator_analytics_report()` contract (ok=True + all
required keys; replay/event-store failures survive and surface).

Frontend — `src/pages/OperatorAnalytics.test.tsx` — **10 tests** (Vitest +
Testing Library, apiJson mocked): full-payload render, funnel stage
data-testids, SourcesBanner on unavailable/truncated sources, rejection row
expand/collapse drill-down, SOURCE_UNAVAILABLE / PARTIAL evidence badges,
risk-intervention blocks, trends partial flag, loading state, error state +
Retry.

(An earlier smoke suite `test_phase27_operator_analytics.py` — 21 tests —
remains alongside.) All pass; tsc clean.

