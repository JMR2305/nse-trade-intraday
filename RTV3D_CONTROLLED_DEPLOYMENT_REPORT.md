# RTV-3D — Controlled Deployment Report

**Date:** 2026-08-25 (Asia/Kolkata)  
**Final verdict:** **A. RTV‑3D DEPLOYMENT PASS — TASK #920 READY**

## Approved release

```text
APPROVED_DEPLOY_COMMIT = 9f83f6764e3861e351e6334070d4031a85818876
EXPECTED_BUILD_ID = apexquant-9f83f6764e38
PRODUCTION_URL = https://nse-trade-intraday.replit.app
```

The production deployment is public autoscale with a successful build.

## Runtime identity gate

Read-only `/api/health/details` returned:

| Field | Observed value | Result |
|---|---|---|
| Environment | `production` | PASS |
| Git commit | `9f83f6764e3861e351e6334070d4031a85818876` | PASS |
| Build ID | `apexquant-9f83f6764e38` | PASS |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` | PASS |
| Runtime timestamp | `2026-08-25T04:37:06.962Z` | PASS |

The workspace later advanced with unrelated follow-up work, but production
identity proves that the deployed runtime is the approved clean release
commit.

## Deployment safety

No manual Phase 5A/5B/5C trigger, scan, retry, replay, entry, broker order,
login, credential creation, portfolio reset, ledger edit, or settings mutation
was performed during verification.

The only requests made to production were read-only GET requests. The
controlled-paper-entry status endpoint returned its intentional disabled
response:

```json
{
  "status": "DISABLED",
  "execution_allowed": false,
  "dry_run_only": true
}
```

## Verification summary

- Clean source scope: PASS
- RTV‑2E stale-test reconciliation: PASS
- Full test gate: PASS
- Schema safety: PASS
- Production runtime identity: PASS
- Production safety and portfolio parity: PASS
- Kite read-only status: PASS
- Failed RTV‑3 evidence preservation: PASS for preserved evidence hashes

## Historical pre-open observation

The read-only `/api/preopen/status` response is still a historical
10-symbol record for session `preopen-2026-08-25-9b8340`. It reports a later
collection batch in that same historical session, while the original failed
batch evidence remains preserved separately. This historical record is not
treated as a successful Task #920 validation.

Task #920 is therefore reserved for the next naturally scheduled NSE session;
no same-day manual validation is authorized.