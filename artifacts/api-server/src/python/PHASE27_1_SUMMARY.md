# Phase 27.1 — Operational Intelligence Refinements

**Status: COMPLETE** · READ-ONLY · advisory only · PAPER TRADING / RESEARCH ONLY

## What was built

One new read-only aggregator, `phase27_1_operational_intelligence.py`, that
COMPOSES existing canonical stores — no new probes, no duplicate
calculations, no trading/strategy logic:

| Section | Canonical source |
|---|---|
| 1. Session Readiness Timeline | `phase27_readiness` KV history (`system_readiness_history`) — transitions with timestamp, reason, components, recovery time, operator action; clickable detail in UI |
| 2. Readiness History stats | Same history log — 7/30/90-day windows: verdict counts, avg score, longest READY streak, most common blocking failure, avg recovery, per-day trend chart. `insufficient_data` flag when the window is thin |
| 3. Pre-Market Checklist | 13 items mapped to readiness check ids + pipeline stage evidence (`pipeline_events.stage_summary` for the latest scan). PASS/WARNING/FAIL + remediation. No evidence ⇒ WARNING, never PASS |
| 4. Session Comparison | `replay_engine.get_replay_sessions()` grouped by IST day + `canonical_portfolio.canonical_trades(scope="all")` — stocks scanned, signals, trades, win rate, PnL, paper orders, scan duration. Historical rows with limited metadata stay `None` (shown as —), never fabricated |
| 5. Operator Insights | Deltas between comparison days + readiness BLOCKED checks + weekly most-common failure. Every insight carries `advisory_only: true` |
| 6. Pipeline Health Score | Presentation fold only: READY=100 / WARNING=60 / UNKNOWN=40 / BLOCKED=0 over readiness domains + pipeline stages; trend from history scores |
| 7. Investigation Shortcuts | Static link metadata (Investigation, Replay, Explainability, Strategy Optimization, Mission Control, Operator Analytics) rendered next to every warning/failure |
| 8. Executive Summary | Composition of the above: readiness/AI/trading/portfolio/system statuses, health score, checklist counts, today's session, alerts, recommendations, outstanding issues |

## Supporting changes

- `phase27_readiness.py`: history entries now include a compact `issues`
  list (id/domain/status/actual, capped 10) so the timeline can show
  reasons/components; `HISTORY_CAP` 50 → 500 to support 90-day statistics
  (report is honest about short windows via `insufficient_data`).
- `main.py`: command `operational_intelligence_report`.
- `routes/phase27.ts`: `GET /api/operational-intelligence/report`
  (30s cache + single-flight, `?force=true` bypass).
- `OperationalIntelligence.tsx` at `/operational-intelligence`, registered in
  App.tsx + AgentConfig.ts (Operations group). Mobile responsive (grids
  collapse, comparison table scrolls).

## Safety guarantees

- Read-only: module references no mutators (`kv_set`, `add_notification`,
  order execution, scan triggers) — enforced by an AST/source test.
- Fail-soft: each of the 5 sources loads independently; unavailable sources
  are surfaced in `sources` + a UI banner, never zeroed or hidden.
- No recalculation: every number is a regrouping/fold of a canonical value.

## Tests

`test_phase27_1_operational_intelligence.py` — 19 tests, all pure unit
(constructed inputs): timeline transitions + recovery time, history windows
/streaks/insufficient-data, checklist mapping + no-evidence-⇒-WARNING,
session grouping + win rate + never-fabricate, insight deltas + CRITICAL
surfacing, health-score folds + trend, executive composition, read-only
contract. Existing `test_phase27_readiness.py` (39) still passes.
