# ApexQuant AI — Phase 3B Disabled Advisory Integration Safety Review

**Review scope:** Phase 3A disabled integration, safe for Monday manual-test preparation only
**Reviewed branch:** `phase3a-advisory-integration-disabled`
**Base branch:** `phase2a-advisory-multi-bot-logic`
**Verdict:** **SAFE FOR MONDAY MANUAL TEST PREP**

## 1. Branch state

- The checked-out branch is `phase3a-advisory-integration-disabled`.
- Its direct base is `phase2a-advisory-multi-bot-logic`.
- The Phase 3A implementation is committed on the isolated branch.
- `main` was not modified or merged.
- The attached Phase 3B review instructions are user input only and are not
  part of the application diff.

## 2. Deployment and production confirmation

- No production deployment was performed for this review.
- No production migration was performed.
- No production flags were enabled.
- No published production URL was used.
- The live API check used the local Replit development proxy
  (`127.0.0.1:80`); the browser check used the local dashboard artifact
  preview. These checks were against the branch development services, not
  production.
- The API and dashboard workflows were restarted only to load the branch code.

## 3. Feature-flag review

The server and Python resolvers default every advisory flag to false and
recognize only the literal value `true`:

- `ADVISORY_BOTS_ENABLED=false`
- `ADVISORY_BOTS_API_ENABLED=false`
- `ADVISORY_BOTS_UI_ENABLED=false`
- `ADVISORY_BOTS_PERSIST_ENABLED=false`
- `ADVISORY_BOTS_SCHEDULER_ENABLED=false`
- `VITE_ADVISORY_BOTS_UI_ENABLED=false`

Verified behavior:

- Missing flags are false.
- Values such as `1`, `yes`, or other non-literal values are false.
- The scheduler flag is status-only and invokes no scheduler.
- Persistence requires the persistence flag plus positive
  `NODE_ENV=development` or `NODE_ENV=test` attestation.
- A missing, unknown, production, or conflicting `ENVIRONMENT` value fails
  closed.

## 4. API safety review

Reviewed:

- `artifacts/api-server/src/routes/advisory.ts`
- `artifacts/api-server/src/lib/advisoryFlags.ts`
- `artifacts/api-server/src/routes/index.ts`

Verified behavior:

- `GET /api/advisory/status` returns HTTP 404 when the API flag is disabled.
- `POST /api/advisory/run-preview` returns HTTP 404 when the API or master
  advisory flag is disabled.
- Disabled requests return before body validation or Python spawning.
- When explicitly enabled, both endpoints require a validated operator
  `__session`; missing or invalid sessions return HTTP 401.
- `run-preview` accepts an in-memory fixture payload only. It does not accept a
  file path and does not load production data.
- Preview work is bounded to one in-flight Python process with a 15-second
  start cooldown; additional requests return HTTP 429.
- Persistence requests are rejected unless all positive safety conditions are
  met.
- No Phase 20, paper-trader, broker/Kite, scheduler, trade, position, or
  settings-write import or call exists in the advisory route.

The live default-disabled check returned:

```text
GET /api/advisory/status: HTTP 404
{"status":"DISABLED","advisory_only":true,"paper_only":true,
 "error":"Advisory integration is unavailable."}
```

## 5. UI safety review

Reviewed:

- `artifacts/trading-dashboard/src/pages/AdvisoryDashboard.tsx`
- `artifacts/trading-dashboard/src/App.tsx`
- `artifacts/trading-dashboard/src/lib/advisoryFlags.ts`

Verified behavior:

- `/advisory` is conditionally registered only when the browser build flag is
  explicitly enabled.
- No navigation link is added for the disabled route.
- The enabled page is read-only and has no buttons, mutations, order/trade
  calls, position controls, broker controls, settings controls, auto-entry
  controls, or scheduler controls.
- The page includes the visible warning:
  `ADVISORY ONLY — NOT ORDER INSTRUCTIONS`.
- The browser check navigated directly to `/trading-dashboard/advisory` with
  defaults off and received the normal 404 page.
- The advisory heading and warning were absent, and browser/page errors were
  empty.

## 6. Manual-runner review

Reviewed:

- `artifacts/api-server/src/python/advisory_bots/manual_runner.py`
- `artifacts/api-server/src/python/advisory_bots/flags.py`

Verified behavior:

- The runner requires `ADVISORY_BOTS_ENABLED=true`.
- It accepts only a caller-supplied JSON fixture from a file or stdin.
- The API uses stdin and never passes a caller-supplied path.
- It has no production data loader, broker import, Phase 20 execution/position
  import, settings-write import, or scheduler hook.
- `persist=False` is the default.
- `--persist` requires the persistence flag and the positive development/test
  environment attestation.
- Output includes ranked advisory results and explicit advisory-only,
  paper-only, and not-trade-instructions markers.

## 7. Protected-file diff proof

The protected-path guard against `main` passed. No changes were found in:

- `phase20_executor.py`
- `phase20_scheduler.py`
- `phase20_exits.py`
- `phase20_eod_outcomes.py`
- `phase20_eod_status.py`
- `paper_trader.py`
- `broker_client.py`
- Kite/live-order modules
- settings write handlers
- deployment configuration
- workflows
- production execution configuration

## 8. Test results

The requested validation was rerun:

- `test_phase3a_integration.py`: 9 passed, 3 subtests.
- `test_advisory_bots.py`: included in the combined run; full relevant Python
  run completed with 73 passed, 4 subtests, and one pre-existing
  `datetime.utcnow()` deprecation warning.
- `test_phase0c_safety_fixes.py`: included in the combined run.
- `test_custom_universe_store.py`: included in the combined run.
- `python3 -m py_compile advisory_bots/*.py phase24_store.py`: passed.
- Advisory API route tests: 10 passed.
- Dashboard flag/page tests: 4 passed.
- API TypeScript typecheck: passed.
- Dashboard TypeScript typecheck: passed.
- Repository configured typecheck, including shared libraries and mobile:
  passed.
- `git diff --check`: passed after removing Markdown trailing whitespace.
- Protected-path diff guard: passed.
- Live default-disabled API check: HTTP 404.
- Live default-disabled browser check: normal 404 page, no console/page
  errors.

## 9. Merge confirmation

- No merge to `main` occurred.
- This review does not approve a merge.
- Any future merge requires a separate explicit operator decision after the
  Monday checklist passes.

## 10. Deployment confirmation

- No production deployment occurred.
- No deployment configuration was changed.
- Any future deployment requires separate explicit operator approval.

## 11. Scheduler-hook confirmation

- No advisory scheduler hook exists.
- `ADVISORY_BOTS_SCHEDULER_ENABLED` is a disabled future placeholder only.

## 12. Production-endpoint exposure confirmation

- The optional routes are registered behind the API flag, but return HTTP 404
  by default.
- The API route is also session-protected whenever explicitly enabled.
- No production flags were enabled, and no production endpoint was exercised.

## 13. Trade, position, settings, and broker-path confirmation

- No trades were created or closed.
- No positions were opened, closed, or mutated.
- No broker or Kite order API was called.
- No settings mutation path was added or called.
- No auto-entry or bootstrap path was enabled.

## 14. Final verdict

**SAFE FOR MONDAY MANUAL TEST PREP.**

Keep all advisory flags disabled in production. Use
`APEXQUANT_MONDAY_MARKET_TEST_AND_MERGE_CHECKLIST.md` for the first Monday
session. Do not merge or deploy until the Monday production checks pass and
the operator separately approves each action.