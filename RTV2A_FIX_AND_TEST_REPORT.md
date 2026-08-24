# RTV-2A — Fix and test report

**Date:** 2026-08-24  
**Result:** PASS — source validation complete; publication remains a
user-initiated action.

## Delivered controls

- Durable Phase 5A session/phase state with restart recovery.
- Atomic collection outcome with provider/persisted count proof.
- Explicit `PERSISTENCE_UNAVAILABLE`, `PERSISTENCE_FAILED`,
  `PROVIDER_UNAVAILABLE`, and `NO_DATA` outcomes.
- Freeze denial when durable collection parity is incomplete.
- Retryable failed lifecycle phases; only successful phases are once-complete.
- Durable predecessor gates: reconciliation requires freeze and the 09:30
  enrichment requires reconciliation. A failed durable phase-state write cannot
  become a local one-shot completion.
- Forced `POST /live-data/scan/run` sends `force` before
  `origin=API_TRIGGERED`, with route coverage of that command contract.
- Freeze, reconciliation, frozen watchlists, and 09:30 reconciliation updates
  are session-scoped, preventing same-date session evidence from being mixed.
- Collection retries have immutable batch IDs. Snapshot rows, the successful
  parity proof, and the session's verified-batch pointer are written together;
  freeze pins that exact batch after matching its rows, snapshot IDs, and
  symbols to the persisted proof.
- Existing snapshot tables receive the batch column through an additive upgrade
  before the dependent batch index is created; a schema-order test protects the
  production rollout path.
- End-exclusive Phase 5A window boundaries.
- Canonical scan trigger-origin persistence and scheduled-only readiness
  authority.
- Read-only GET behavior for `/live-data/recommendations` and
  `/live-data/scan`, including explicit no-snapshot and force-rejection
  responses.
- Provider-health telemetry write removed from `GET /api/preopen/health`.

## Validation evidence

| Check | Result |
| --- | --- |
| Final Phase 5A/scan/readiness Python suite | 156 passed |
| API route regression suite | 10 passed |
| Scan read-safety and force-command API routes | 10 passed |
| Push notification regression suite | 25 passed |
| API server build | Passed |
| API server TypeScript check | Passed |
| Workspace typecheck (API, dashboard, mobile, shared libraries) | Passed |
| Python syntax compilation for changed modules | Passed |
| Diff whitespace check | Passed |
| API workflow restart | Passed; service listening on port 8080 |
| Read-only browser smoke test | Passed; populated dashboard rendered without browser error or action clicks |

## Safety review

The diff did not change the approved custom universe, capital amount,
execution mode, automatic-entry setting, bootstrap setting, strategy
thresholds, paper ledger, or broker-order behavior. Scan execution remains
explicitly separated from observation GETs.

## Known non-blocking observations

The API build reports its existing bundle-size warning. It does not affect
this change. Production deployment logs previously contained independent
backtest queue timeout warnings; RTV-2A neither changes nor relies on that
queue.

The broad API Vitest command has an unrelated timing-sensitive push-delivery
fan-out assertion that intermittently observes 104 of 105 sends under
concurrent suite load. The isolated 25-test notification suite and the changed
10-test route suite both passed.