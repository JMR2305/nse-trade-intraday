# RTV-3B — Controlled Production Deployment Report

**Date:** 2026-08-25 (Asia/Kolkata)  
**Final verdict:** **B. SOURCE SCOPE FAILURE**  
**Deployment action:** **STOPPED — no publish performed**

## Task #1 — Source scope

| Field | Value |
| --- | --- |
| Branch | `rtv1-market-data-portfolio-truth` |
| HEAD | `8317ae3cfad0f907d76cf903d90ee444d7cf9ebe` |
| Git status | Clean before this report was created |
| Current production commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Current production build | `apexquant-2e54e5e2f23f` |
| Current production deployment | `0d018179-abe0-42c2-a554-dbb19d11341f` |

The branch contains these commits after the current production commit:

1. `3e435c92a16be168f227fe55bc5d200ffecadade` — RTV‑2D deployment
   documentation and portfolio reconciliation
2. `f87602717d78a81f948564db719cee84a9a2f115` — RTV‑2E test gates and
   validation updates
3. `b937ea90ccf77e0881a14e4590669936e3dc7e02` — RTV‑3 compliance evidence
4. `62d19e39ce242f311929da69959544b1a88c5858` — RTV‑3 readiness evidence
5. `563a7004373a23b1e9916083034435b05b3eeade` — state-file/gitignore changes
6. `f6a0cd94feddd9049714752c5de05789940c5ec3` — Mission Control build identity
   changes
7. `41402b0bcb75267f76867065cbafbc1223496791` — provider-coverage evidence
8. `fc550ff3b728574fdfbd8f6326955e62312fbff4` — Task #918 repair and related
   evidence
9. `1cdadef039fd4ead5e0c47a799ea5215c0143a85` — dashboard build identity
   evidence
10. `8317ae3cfad0f907d76cf903d90ee444d7cf9ebe` — Task #918 summary

## Changed runtime scope

The post-production tree contains the Task #918 Phase 5A runtime files:

- `artifacts/api-server/src/python/config.py`
- `artifacts/api-server/src/python/preopen_db.py`
- `artifacts/api-server/src/python/preopen_engine.py`
- `artifacts/api-server/src/python/preopen_intelligence_tick.py`
- `artifacts/api-server/src/python/preopen_provider_manager.py`
- `artifacts/api-server/src/python/preopen_scheduler.py`

It also contains unrelated runtime/build changes, including:

- `artifacts/api-server/build.mjs`
- `artifacts/api-server/src/python/state.json` deletion
- `artifacts/trading-dashboard/src/pages/MissionControl.tsx`
- `artifacts/trading-dashboard/src/pages/MissionControl.freshness.test.tsx`
- `artifacts/trading-dashboard/buildIdentity.mjs`
- `artifacts/trading-dashboard/scripts/check-build-identity.mjs`
- `artifacts/trading-dashboard/vite.config.ts`
- `artifacts/trading-dashboard/package.json`
- `artifacts/trading-dashboard/.replit-artifact/artifact.toml`
- `scripts/deploy-build.sh`

The full `2e54e5e2..8317ae3c` comparison contains **63 changed files** and
approximately **4,697 additions / 200 deletions**, including unrelated
Mission Control, build/deployment, database-initialization, state/config, and
prior RTV evidence changes.

Because unrelated runtime changes exist, the requested scope confirmation
fails. No commit can be approved from this mixed branch under the stated
deployment rules.

## Approved deploy commit

```text
APPROVED_DEPLOY_COMMIT = NOT DEFINED — SOURCE SCOPE FAILURE
EXPECTED_BUILD_ID = NOT DEFINED
```

The current HEAD must not be published as a Task #918-only deployment.

## Gate execution

Per the explicit stop rule, the following were **not run** after the scope
failure:

- the RTV‑3B test gate;
- production schema-diff inspection;
- controlled publish;
- post-deploy identity verification;
- post-deploy safety and Kite checks.

This prevents a mixed-scope build from being validated or deployed under the
Task #918 approval.

## Production state observed before the stop

The read-only production identity endpoint returned:

- environment: `production`
- git commit: `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832`
- build ID: `apexquant-2e54e5e2f23f`
- deployment ID: `0d018179-abe0-42c2-a554-dbb19d11341f`
- runtime timestamp: `2026-08-25T04:12:39.564Z`

The production service remains on the prior build. No lifecycle job, scan,
retry, order, settings mutation, or deployment was triggered.

## Required remediation before deployment

Create or select a clean commit containing only the verified Task #918
runtime/evidence scope, or otherwise obtain explicit approval for the
additional runtime changes. Re-run all release gates against that exact commit
before publishing.