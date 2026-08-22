# ApexQuant AI — Phase 4C Weekend Freeze and Monday Merge Plan

**Current branch:** `phase4a-controlled-paper-entry-framework-disabled`
**Current branch tip at review start:** `14280329`
**Phase 4A base:** `phase3a-advisory-integration-disabled`
**Mode:** PAPER ONLY / NO PRODUCTION ENABLEMENT  
**Freeze status:** **FROZEN — NO NEW FEATURE CODING BEFORE MONDAY**

This document is the final weekend freeze package. It defines a conditional
Monday review and merge sequence; it does not authorize a merge, deployment,
flag enablement, trade, position change, or broker action.

## 1. Branch map

The following branch refs were verified in the repository:

| Branch | Current status | Merge/deployment status |
| --- | --- | --- |
| `main` | Production-safe baseline; custom universe active; auto entries disabled; bootstrap disabled. | No Phase 2–4 feature merge is present on `main`; no deployment was performed by this freeze review. |
| `phase2a-advisory-multi-bot-logic` | Advisory core; eligible for a later, separately reviewed merge. | Not merged into `main`; not deployed. |
| `phase3a-advisory-integration-disabled` | Disabled advisory API/UI/manual-runner integration; safe for Monday manual-test preparation. | Not merged into `main`; not deployed. |
| `phase4a-controlled-paper-entry-framework-disabled` | Disabled controlled-entry readiness/dry-run framework; Phase 4B reviewed it as safe for Monday review. | Not merged into `main`; not deployed. |

Verified branch ancestry is linear for the feature work:

```text
phase2a-advisory-multi-bot-logic
  -> phase3a-advisory-integration-disabled
  -> phase4a-controlled-paper-entry-framework-disabled
```

The current working tree contains only the user-provided Phase 4C instruction
file as an untracked item. It is not application code and must not be committed
as part of this package.

## 2. Weekend freeze confirmation

No further feature coding is required before Monday. The weekend freeze is:

- No new features.
- No refactors of trading or execution paths.
- No merge to `main`.
- No production deployment.
- No production migration.
- No advisory flag enablement.
- No controlled-entry flag enablement.
- No auto paper-entry enablement.
- No bootstrap enablement.
- No trades.
- No position closures.
- No broker order API calls.
- No scheduler hooks.
- No execution endpoints.

The repository defaults and controlling reports confirm:

- All advisory flags default disabled.
- All controlled-entry framework flags default disabled, with dry-run and
  evidence requirements defaulting to the safer values.
- `auto_paper_entries=false`.
- `bootstrap_paper_enabled=false`.
- No new scheduler hook exists in the advisory or controlled-entry additions.
- No new execution endpoint exists.
- No production deployment or migration was performed during this freeze review.

The current development status route remains disabled by default:

```text
GET /api/controlled-paper-entry/status
HTTP 404
{"status":"DISABLED","controlled_paper_entry":true,
 "dry_run_only":true,"execution_allowed":false}
```

## 3. Exact Monday sequence

All times below are India Standard Time (IST). The operator must record the
timestamp, source, result, and evidence artifact for each step.

### A. Before market open

1. Confirm production health with a read-only health check.
2. Confirm settings with a read-only request:
   - capital is ₹100,000;
   - active intraday universe is `CUSTOM_LOW_PRICE_SECTOR`;
   - `auto_paper_entries=false`;
   - `bootstrap_paper_enabled=false`;
   - all advisory flags are disabled; and
   - all controlled-entry flags are disabled.
3. Confirm the portfolio has exactly `positions=[]`.
4. Confirm the active custom universe is the approved 23-symbol universe.
5. Confirm the production branch/deployment identity and ensure no unapproved
   branch or build is serving production.
6. Record the pre-open evidence before proceeding.

If any pre-open item is unavailable, contradictory, or not independently
traceable, stop with **NO-GO**. Do not substitute cached or inferred values.

### B. After the first scan, around 09:30 IST

1. Wait for the first completed custom-universe scan.
2. Run the Phase 1H first-custom-universe scan checks.
3. Confirm:
   - `universe_mode=CUSTOM_LOW_PRICE_SECTOR`;
   - `symbols_analysed=23`;
   - `symbols_with_errors=0`;
   - no NIFTY_50 fallback;
   - sector counts are BANK=9, INFRA=13, IT=1;
   - active count is 23; and
   - no stale, missing, or contradictory evidence is silently treated as a
     pass.
4. Record the complete Phase 1H evidence and verdict.

No controlled-entry, advisory, auto-entry, bootstrap, scheduler, or broker
flag may be enabled for this check. This is observation and evidence
collection only.

### C. After 15:20 IST

1. Run the EOD status checks.
2. Run the EOD outcomes checks.
3. Confirm every expected candidate has a durable outcome or an explicit
   blocked/exit-pending outcome according to the existing safety rules.
4. Confirm positions and settings remain unchanged.
5. Record the EOD evidence for the same Monday watch.

If EOD evidence is incomplete, inconsistent, or cannot be tied to the same
watch, the result is **NO-GO**.

### D. If Phase 1H and EOD pass

1. The operator reviews all evidence and the four controlling reports.
2. The operator reviews the proposed merge order and protected-file diff.
3. A separate explicit approval is recorded for each merge.
4. Merge advisory core first.
5. Re-run the full guard suite and inspect the diff.
6. Merge the disabled advisory integration second.
7. Re-run the full guard suite and inspect the diff.
8. Merge the disabled controlled-entry framework third.
9. Re-run the full guard suite and inspect the diff.
10. Keep deployment as a separate approval and separate action.
11. Keep every advisory, controlled-entry, auto-entry, and bootstrap flag
    disabled after each merge.

Passing Phase 1H is a prerequisite for operator review. It is not itself a
merge authorization or an execution authorization.

### E. If Phase 1H or EOD fails

Immediately:

- Do not merge.
- Do not deploy.
- Do not enable anything.
- Do not create trades.
- Do not close positions.
- Do not call broker order APIs.
- Produce a blocker report containing the failed evidence, timestamp, source,
  and exact remediation.
- Keep the feature branches isolated and preserve the production-safe baseline.

## 4. Safe merge order and guards

The only permitted conditional merge order is:

1. `phase2a-advisory-multi-bot-logic`
2. `phase3a-advisory-integration-disabled`
3. `phase4a-controlled-paper-entry-framework-disabled`

Do not merge out of order. Do not combine a merge with a deployment or a
settings change.

Before **each** merge, run:

```bash
cd artifacts/api-server/src/python
python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v
python3 -m pytest tests/unit/test_custom_universe_store.py -v
python3 -m pytest tests/unit/test_advisory_bots.py -v
python3 -m pytest tests/unit/test_phase3a_integration.py -v
python3 -m pytest tests/unit/test_phase4a_controlled_paper_entry.py -v
python3 -m py_compile advisory_bots/*.py phase24_store.py controlled_paper_entry_*.py
cd ../../..
pnpm --filter @workspace/api-server exec vitest run \
  src/routes/advisory.test.ts \
  src/routes/controlledPaperEntry.test.ts
pnpm --filter @workspace/api-server exec tsc --noEmit
pnpm exec tsc -b lib/api-client-react lib/api-zod lib/db artifacts/api-server
pnpm --filter @workspace/trading-dashboard exec tsc --noEmit
pnpm --filter @workspace/trading-mobile exec tsc --noEmit
git diff --check
git diff --name-only main...HEAD
```

For the dashboard UI test layer, also run the existing focused tests when the
merge includes dashboard files:

```bash
pnpm --filter @workspace/trading-dashboard exec vitest run \
  src/lib/advisoryFlags.test.ts \
  src/pages/AdvisoryDashboard.test.tsx
```

The protected-file guard must reject any diff touching:

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
- workflow configuration
- production execution configuration

After **each** merge, confirm:

- no production deployment occurred;
- advisory flags remain disabled;
- controlled-entry flags remain disabled;
- no scheduler hook exists;
- no execution endpoint exists;
- `auto_paper_entries` remains false;
- `bootstrap_paper_enabled` remains false;
- no trades or positions were created or changed; and
- the branch diff still passes the protected-file guard.

## 5. Rollback plan

### Before any merge

The safest rollback is to stop. Leave `main` unchanged and retain the feature
branches for review. Do not reset or rewrite `main`.

### After a conditional merge

If a guard, test, settings check, or runtime safety check fails:

1. Stop the merge sequence immediately.
2. Do not deploy and do not enable flags.
3. Record the failing commit, command, output, and branch.
4. Revert only the most recently merged feature commit or merge commit on the
   integration branch, using the normal reviewed Git process.
5. Re-run the protected-file guard and full safety suite.
6. Confirm `main` remains production-safe before any further decision.

Do not use a rollback to conceal a production data mutation. This Phase 4C
package performs no data migration, trade, position, broker, or scheduler
operation, so no data rollback is required for the current review.

### If production unexpectedly changes

Treat any unexpected production change as an incident: stop all planned merge
and deployment activity, keep all flags disabled, preserve logs and evidence,
and obtain an independent operator decision before any remediation. No
production change is authorized by this plan.

## 6. Conditions for GO

The Monday sequence may reach **GO FOR OPERATOR REVIEW** only when every
condition below is true:

- pre-open production health is confirmed;
- production settings are read and match the approved values;
- positions are exactly `[]`;
- the active universe is exactly `CUSTOM_LOW_PRICE_SECTOR`;
- the first scan completes with the approved 23-symbol universe;
- Phase 1H report exists and has `PASS` status;
- `symbols_analysed=23`;
- `symbols_with_errors=0`;
- NIFTY_50 fallback is false;
- sector counts are BANK=9, INFRA=13, IT=1;
- EOD status and outcomes both pass;
- no `AUTO` or `BOOTSTRAP_AUTO` trade occurred during the watch;
- advisory core and advisory integration reviews are present;
- the operator explicitly approves the review;
- all pre-merge tests and typechecks pass;
- the protected-file diff guard passes;
- no deployment is bundled with the merge; and
- all flags remain disabled.

This GO state authorizes only an operator review of the proposed merge order.
It does not authorize automatic paper entries, bootstrap, execution, broker
access, or deployment.

## 7. Conditions for NO-GO

The result is **NO-GO** if any one of these occurs:

- Phase 1H is missing, incomplete, WARN, or FAIL;
- EOD status or outcomes are missing or fail;
- production health is unavailable or contradictory;
- capital is not ₹100,000;
- the active universe is not `CUSTOM_LOW_PRICE_SECTOR`;
- the active count is not 23;
- symbols analysed are not 23;
- any scan error exists;
- NIFTY_50 fallback is true or unknown;
- sector counts differ from BANK=9, INFRA=13, IT=1;
- positions are not exactly `[]`;
- an `AUTO` or `BOOTSTRAP_AUTO` watch trade exists;
- any advisory or controlled-entry flag is enabled;
- auto entries or bootstrap are enabled;
- a scheduler hook or execution endpoint appears;
- a protected file is changed;
- any required test, compile, typecheck, or UI check fails;
- deployment is requested as part of the merge;
- evidence cannot be tied to the same Monday watch; or
- operator approval is absent or ambiguous.

On NO-GO, preserve the freeze and create a blocker report. Do not attempt to
make the evidence pass by changing settings, deleting records, retrying with a
different universe, or enabling a feature flag.

## 8. Explicit freeze confirmations

- **No new feature coding:** confirmed. This package adds documentation only.
- **No merge done now:** confirmed. `main` remains unchanged by this review.
- **No deployment done now:** confirmed. No production deployment was invoked.
- **No enablement done now:** confirmed. Advisory, controlled-entry,
  auto-entry, and bootstrap flags remain disabled.
- **No scheduler hook:** confirmed.
- **No execution endpoint:** confirmed for the Phase 4A additions.
- **No trades or position changes:** confirmed.
- **No settings mutation:** confirmed.
- **No broker order API call:** confirmed.
- **PAPER ONLY:** confirmed.

The weekend state is frozen. Monday activity may collect evidence and, only if
all gates pass, conduct the separately approved merge sequence. Deployment and
any future enablement remain separate approvals and are outside this plan.