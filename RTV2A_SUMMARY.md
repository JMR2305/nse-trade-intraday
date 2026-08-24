# RTV-2A Summary — Phase 5A Persistence and Read Safety

**Date:** 2026-08-24  
**Status:** Complete — source validation passed  
**Scope:** Durable Phase 5A pre-open lifecycle state, collection evidence,
session scoping, and read-only observation behavior.

## Executive summary

RTV-2A closes the paths that could make an incomplete pre-open lifecycle look
successful. Phase 5A state is now durable and restart-safe, collection success
requires same-batch provider/snapshot parity, and downstream phases cannot
advance without durable predecessor evidence.

The repair does **not** reconstruct the incomplete RTV-2 session or certify a
new production trading session. Certification still requires the next natural
scheduled NSE session to satisfy the validation gate.

## Delivered controls

- Phase 5A session and phase state is persisted in PostgreSQL and reloaded on
  every lifecycle tick; the JSON sidecar is only a warm cache.
- Collection succeeds only when:
  - the provider count equals the persisted snapshot count,
  - the counts are proven from the same collection batch, and
  - the durable write succeeds.
- Every collection attempt receives an immutable batch ID.
- The verified batch pointer is committed with the successful parity proof.
- Freeze reads only the verified batch and checks exact row, snapshot-ID, and
  symbol parity before pinning it for downstream use.
- A later retry cannot mix symbols from an earlier collection attempt.
- Existing `preopen_snapshots` tables receive the new batch column through an
  additive migration before the dependent batch index is created.
- Failed persistence, unavailable providers, no-data results, and retryable
  lifecycle failures remain explicit rather than being reported as success.
- Freeze requires durable collection parity.
- Reconciliation requires durable `FROZEN` state.
- 09:30 enrichment requires durable `RECONCILED` state.
- Failed phase writes remain retryable; a local sidecar cannot unlock a phase.
- Phase windows use end-exclusive boundaries.
- Freeze, reconciliation, watchlists, and 09:30 updates are scoped to the
  exact durable session, not merely the trading date.
- API-triggered scans preserve `API_TRIGGERED` origin and accept `force`
  regardless of argument position.
- GET routes for recommendations and scan data remain observation-only; they
  do not trigger scans or create new lifecycle state.
- Provider-health telemetry writes were removed from the pre-open health GET.

## Safety posture preserved

RTV-2A did not change the approved trading configuration:

- Custom 23-symbol low-price sector universe
- ₹100,000 capital
- Paper-only execution
- Automatic entries disabled
- Bootstrap disabled
- Automatic exits enabled
- Live broker execution disabled

No manual scan, manual pre-open refresh, lifecycle job, paper entry, bootstrap
activation, or broker order was used as production validation.

## Validation evidence

| Check | Result |
| --- | --- |
| Phase 5A, scan, and readiness Python suite | 156 passed |
| Batch persistence, exact-batch read, and schema-upgrade tests | Passed |
| Scan route regression suite | 10 passed |
| Push notification regression suite | 25 passed |
| API server build | Passed |
| API server TypeScript check | Passed |
| Workspace typecheck: API, dashboard, mobile, shared libraries | Passed |
| Changed Python syntax compilation | Passed |
| Diff whitespace check | Passed |
| API workflow restart | Passed; listening on port 8080 |
| `/api/health/live` smoke request | HTTP 200 |

## Natural-session certification gate

The next natural scheduled NSE session must independently demonstrate:

1. Durable session creation during the Phase 5A init window.
2. Durable readiness, collection, and freeze phase states.
3. `provider_collected_count == persisted_count == 23` for one immutable
   verified collection batch.
4. Freeze only after that parity proof.
5. Durable predecessor ordering through reconciliation and 09:30 enrichment.
6. A canonical scan with `SCHEDULED` origin.
7. Truthful scheduled-scan trading-data readiness.
8. Repeated observation GETs without new scans, lifecycle phases, trades, or
   broker orders.
9. Portfolio/ledger evidence showing no unauthorized activity.

If collection retries occur, frozen evidence must contain only the final
verified batch.

See [`RTV2A_NEXT_SESSION_VALIDATION_GATE.md`](RTV2A_NEXT_SESSION_VALIDATION_GATE.md)
for the complete pass/fail procedure.

## Known non-blocking observations

- The API build retains its existing bundle-size warning.
- Deployment logs contain independent backtest queue timeout warnings; RTV-2A
  neither changes nor depends on that queue.
- The broad API Vitest run has a timing-sensitive push fan-out assertion that
  can observe 104 instead of 105 sends under concurrent load. The isolated
  25-test notification suite passes.

## Related documents

- [`RTV2A_FIX_AND_TEST_REPORT.md`](RTV2A_FIX_AND_TEST_REPORT.md) — detailed
  controls and validation results
- [`RTV2A_PREOPEN_PERSISTENCE_ROOT_CAUSE.md`](RTV2A_PREOPEN_PERSISTENCE_ROOT_CAUSE.md)
  — root-cause chain and corrective controls
- [`RTV2A_NEXT_SESSION_VALIDATION_GATE.md`](RTV2A_NEXT_SESSION_VALIDATION_GATE.md)
  — restricted natural-session evidence gate