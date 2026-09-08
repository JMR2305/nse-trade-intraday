# Task 961 Release and Migration Scope

## Result

The approved Task 960 release was published successfully. The guarded
production migration was not executed because the authenticated production
readiness gate failed on the Kite instrument reference.

## Production identity

- Environment: `production`
- Approved release commit: `17ff7ca46b900f4adb25fad550fab6ca8fea1623`
- Production API commit: `17ff7ca46b900f4adb25fad550fab6ca8fea1623`
- Expected build ID: `apexquant-17ff7ca46b90`
- Production API build ID: `apexquant-17ff7ca46b90`
- Production UI build ID: `apexquant-17ff7ca46b90`
- UI embedded commit: `17ff7ca46b900f4adb25fad550fab6ca8fea1623`
- UI/API identity: `MATCH`
- Deployment ID: `0d018179-abe0-42c2-a554-dbb19d11341f`
- Runtime identity timestamp observed: `2026-08-28T04:47:14.162Z`
- Workspace HEAD after Publish: `ee8f3fd0f621d6ffb5318fde5f3c3a11592cb8b3`
- Workspace HEAD subject: `Published your App`
- Workspace HEAD parent: `17ff7ca46b900f4adb25fad550fab6ca8fea1623`

The generated Publish checkpoint contains the approved release commit as its
direct parent. Production itself reports the approved source commit and
commit-derived build identity.

## Runtime files changed from the previous production commit

Compared with production commit
`68f18b078fe9de37da175480d40d4d42ae727830`, the approved release changed:

1. `artifacts/api-server/src/python/custom_universe_baseline_migration.py`
2. `artifacts/api-server/src/python/main.py`
3. `artifacts/api-server/src/python/tests/unit/test_custom_universe_baseline_migration.py`
4. `artifacts/api-server/src/python/universe_management.py`
5. `artifacts/api-server/src/routes/universe-management.test.ts`
6. `artifacts/api-server/src/routes/universe-management.ts`

No strategy, broker-execution, portfolio, ledger, scan, mobile, or video
runtime file was part of this release delta.

## Operations performed

- Manual Publish: completed by the user
- Production identity checks: read-only, passed
- Unauthenticated readiness check: returned `401`, as required
- Authenticated migration readiness: read-only, failed closed
- Migration POST: not sent
- Manual scan or Phase 5A/5B/5C invocation: not performed
- Portfolio, ledger, settings, or historical evidence mutation: not performed
