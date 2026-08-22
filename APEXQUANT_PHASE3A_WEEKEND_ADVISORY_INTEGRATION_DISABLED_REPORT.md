# ApexQuant AI — Phase 3A Weekend Advisory Integration (Disabled)

**Branch:** `phase3a-advisory-integration-disabled`
**Base branch:** `phase2a-advisory-multi-bot-logic`
**Controlling reports:** Phase 2D merge-readiness package, Phase 2C safety review, and Phase 1G post-publish upsert-hardening verification
**Operating posture:** PAPER ONLY / ADVISORY ONLY
**Verdict:** Prepared for Monday manual testing while disabled by default

## 1. Branch state

- The work is on `phase3a-advisory-integration-disabled`.
- `main` was not modified or merged.
- No production deployment was performed.
- No production migration was applied.

## 2. Files created or modified

- `artifacts/api-server/src/lib/advisoryFlags.ts`
- `artifacts/api-server/src/routes/advisory.ts`
- `artifacts/api-server/src/routes/advisory.test.ts`
- `artifacts/api-server/src/routes/index.ts`
- `artifacts/api-server/src/python/advisory_bots/flags.py`
- `artifacts/api-server/src/python/advisory_bots/manual_runner.py`
- `artifacts/api-server/src/python/tests/unit/test_phase3a_integration.py`
- `artifacts/trading-dashboard/src/lib/advisoryFlags.ts`
- `artifacts/trading-dashboard/src/lib/advisoryFlags.test.ts`
- `artifacts/trading-dashboard/src/pages/AdvisoryDashboard.tsx`
- `artifacts/trading-dashboard/src/pages/AdvisoryDashboard.test.tsx`
- `artifacts/trading-dashboard/src/App.tsx`
- `APEXQUANT_MONDAY_MARKET_TEST_AND_MERGE_CHECKLIST.md`
- `APEXQUANT_PHASE3A_WEEKEND_ADVISORY_INTEGRATION_DISABLED_REPORT.md`

## 3. Feature flags

All server and Python flag resolution is false when a flag is missing or is not
the literal value `true`.

| Flag | Default | Current use |
| --- | --- | --- |
| `ADVISORY_BOTS_ENABLED` | false | Required before a manual runner or preview can run. |
| `ADVISORY_BOTS_API_ENABLED` | false | Required before the optional status/preview API is available. |
| `ADVISORY_BOTS_UI_ENABLED` | false | The corresponding frontend build flag is false by default; the `/advisory` route is not registered. |
| `ADVISORY_BOTS_PERSIST_ENABLED` | false | Required, together with explicit `NODE_ENV=development` or `NODE_ENV=test` and no conflicting `ENVIRONMENT`, for an explicit persistence request. |
| `ADVISORY_BOTS_SCHEDULER_ENABLED` | false | Status-only future placeholder; it invokes nothing. |

The dashboard build reads `VITE_ADVISORY_BOTS_UI_ENABLED`, which is the
browser-safe build-time projection of the UI flag. It defaults to false and
must be explicitly set in a future non-production build before the hidden page
can be reached.

## 4. Manual runner proof

`advisory_bots/manual_runner.py` accepts only a caller-supplied JSON fixture
from a file or stdin. It has no production data loader and imports no broker,
Phase 20, scheduler, trade, position, or settings-write module.

- It requires `ADVISORY_BOTS_ENABLED=true`.
- `persist` defaults to false.
- It prints ranked advisory outputs and marks them `ADVISORY ONLY` /
  `NOT TRADE INSTRUCTIONS`.
- An explicit `--persist` request is rejected unless persistence is enabled and
  `NODE_ENV` is exactly `development` or `test`, with no conflicting
  `ENVIRONMENT` value.

## 5. Optional API proof

The registered optional API surface is:

- `GET /api/advisory/status`
- `POST /api/advisory/run-preview`

Both routes return HTTP 404 while `ADVISORY_BOTS_API_ENABLED=false`.
`/run-preview` additionally requires `ADVISORY_BOTS_ENABLED=true`, accepts
only a caller-supplied fixture payload, and does not load production data.

When the optional API is explicitly enabled, both routes require an existing,
validated operator session. Missing or invalid session cookies return HTTP 401
before a preview can spawn Python. This preserves the disabled-state 404 while
making the enabled surface operator-only.

Preview execution is bounded to one in-flight child process and a 15-second
cooldown after each preview begins. Additional authorized requests receive HTTP
429 rather than starting another analysis process.

Persistence is rejected unless the persistence flag is explicitly true and the
environment positively attests `NODE_ENV=development` or `NODE_ENV=test`,
without a conflicting `ENVIRONMENT` marker. Missing, unknown, production, and
conflicting environment values all fail closed. The API has no Phase 20, broker,
scheduler, or settings-write import or call path.

## 6. Optional UI proof

The dashboard `/advisory` route is registered only when the UI build flag is
true. With the default false value it resolves through the normal not-found
route and is not included in navigation.

When explicitly enabled in a future non-production build, the page is
read-only and labels itself:

> ADVISORY ONLY — NOT ORDER INSTRUCTIONS

It provides status, last manual-run availability, universe/data/candidate/
strategy/risk/supervisor evidence placeholders, and safety-boundary text. It
contains no buttons, mutations, execution, order, broker, position, settings,
or scheduler controls.

## 7. Disabled-by-default proof

- Python flag tests prove missing flags resolve to false.
- API HTTP tests prove disabled status and preview routes return 404 before a
  Python child process can start.
- API HTTP tests prove enabled endpoints reject missing and invalid operator
  sessions before Python can start.
- Preview-gate tests prove concurrent or rapid preview attempts are rejected
  rather than stacking subprocesses.
- Python and API tests prove persistence is rejected even with the persistence
  flag enabled when runtime environment evidence is missing, unknown, or
  conflicts with production.
- Dashboard tests prove the `/advisory` route is conditional on the UI flag and
  contains no action controls.
- The scheduler flag is not used to start or invoke any scheduler.

## 8. Test results

| Validation | Result |
| --- | --- |
| Phase 3A Python integration + advisory tests | 28 passed, 1 subtest passed |
| Full advisory + Phase 0C + custom-universe Python suites | 73 passed, 4 subtests passed, 1 expected deprecation warning |
| Advisory API authorization, rate-gate, and environment-allowlist tests | 10 passed |
| API TypeScript typecheck | Passed |
| Dashboard flag/page tests | 4 passed |
| Dashboard TypeScript typecheck | Passed |
| Live API check: `GET /api/advisory/status` | HTTP 404 with disabled payload |
| Live browser check: `/trading-dashboard/advisory` | Normal 404 page; advisory heading absent |
| Live browser console check | No console/page errors |
| Protected-path diff guard | Passed |

Python compilation passed. The repository typecheck is run again as the final
gate below.

## 9. Protected-file boundary

The final diff guard must confirm no changes to:

- Phase 20 executor, scheduler, exits, EOD outcome/status modules
- paper trader
- broker or Kite/live-order modules
- settings write handlers
- deployment configuration
- workflows
- production execution configuration

## 10. No merge or deployment confirmation

No merge to `main` was performed. No production deployment occurred.

## 11. No scheduler confirmation

No advisory scheduler hook exists. `ADVISORY_BOTS_SCHEDULER_ENABLED` is a
disabled future placeholder only.

## 12. No trade, position, settings, or broker path confirmation

No trade was created, no position was opened or closed, no broker order API was
called, no settings mutation was added, and no paper-entry or bootstrap path
was enabled.

## 13. Monday testing and merge recommendation

Use `APEXQUANT_MONDAY_MARKET_TEST_AND_MERGE_CHECKLIST.md` during the Monday
session. Hold any merge consideration until:

1. Phase 1H Monday market-session checks pass;
2. the operator approves a merge; and
3. the operator separately approves any future deployment.

The Phase 3A branch must remain disabled by default unless a later,
independently approved non-production manual test explicitly enables the
required flags.