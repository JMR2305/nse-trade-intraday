# RTV-3C — Controlled Deployment Report

**Date:** 2026-08-25 (Asia/Kolkata)  
**Final verdict:** **C. TEST FAILURE**  
**Deployment:** **STOPPED — no publish performed**

## Test gate

| Check | Result |
| --- | --- |
| Phase 5A engine/lifecycle/provider/scheduler/persistence/coverage | 169 passed |
| Phase 20 safety | 62 passed |
| Daily session and pipeline | **26 passed, 1 failed** |
| Canonical portfolio | Not run after the required gate failed |
| Readiness / overnight-entry safety | 67 passed |
| Scan history/status and custom universe | 89 passed, 10 subtests |
| API build | Passed |
| API TypeScript | Passed |
| Workspace TypeScript | Passed |
| Python compilation | Passed |

### Blocking failure

```text
test_daily_session_and_pipeline_e2e.py::TestOpenAlert::test_run_tick_alerts_even_when_auto_scan_disabled
```

The untouched baseline test expects `kv_claim_once` to be called once for the
session-init alert. The current production-base runtime also claims the
system-heartbeat key, producing two calls:

```text
session_init_open_alert:2026-08-25
system_heartbeat:2026-08-25:09:3
```

This failure is outside the Task #918 scope and was not changed or weakened.
Because the release runbook requires no unexpected failures, the candidate
cannot be committed or published from this branch.

## Deployment decision

No `APPROVED_DEPLOY_COMMIT` was created. Consequently:

- no production publish was attempted;
- no production schema diff was applied or approved;
- no lifecycle job or scan was triggered;
- no manual Phase 5A/5B/5C action was performed;
- no broker, portfolio, ledger, capital, universe, strategy, or threshold
  mutation was performed.

## Production baseline observed before the stop

Read-only production identity remained:

- environment: `production`;
- git commit: `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832`;
- build ID: `apexquant-2e54e5e2f23f`;
- deployment ID: `0d018179-abe0-42c2-a554-dbb19d11341f`;
- runtime timestamp at observation:
  `2026-08-25T04:12:39.564Z`.

The current production deployment was not changed.

## Required next action

Resolve or explicitly reconcile the pre-existing daily-session test
expectation without changing Task #918 scope or weakening safety tests. Then
rerun the full RTV‑3C gate on this exact clean branch before creating an
approved release commit.