# ApexQuant AI — Phase 4A Controlled Paper-Entry Framework (Disabled)

**Branch:** `phase4a-controlled-paper-entry-framework-disabled`
**Base branch:** `phase3a-advisory-integration-disabled`
**Mode:** PAPER ONLY / DRY RUN ONLY / DISABLED BY DEFAULT
**Implementation status:** Ready for Monday manual-test preparation only

## 1. Scope and branch state

This branch adds a controlled, review-only paper-entry framework before the
Monday market session. It is intentionally incapable of creating a paper
trade, position, ledger record, settings change, broker request, live order,
or scheduler action.

- The branch was created from `phase3a-advisory-integration-disabled`.
- No merge to `main` occurred.
- No production deployment or migration occurred.
- No production flags were enabled.
- No existing automatic-entry or bootstrap setting was changed.
- No new live-order capability was added.

## 2. Files created or modified

### New framework files

- `artifacts/api-server/src/python/controlled_paper_entry_flags.py`
- `artifacts/api-server/src/python/controlled_paper_entry_readiness.py`
- `artifacts/api-server/src/python/controlled_paper_entry_dry_run.py`
- `artifacts/api-server/src/python/controlled_paper_entry_bridge.py`
- `artifacts/api-server/src/lib/controlledPaperEntryFlags.ts`
- `artifacts/api-server/src/routes/controlledPaperEntry.ts`
- `artifacts/api-server/src/python/tests/unit/test_phase4a_controlled_paper_entry.py`
- `artifacts/api-server/src/routes/controlledPaperEntry.test.ts`

### Existing files updated

- `artifacts/api-server/src/routes/index.ts` registers the additive,
  disabled-by-default status router.
- `artifacts/api-server/src/python/review_package.py` includes the framework
  in implementation summary, feature matrix, test output, and an honest
  disabled-status data export.
- `docs/phase4a-summary.md` records implementation details, known gaps, and
  downstream dependencies.

## 3. Feature flags and safe defaults

The Python and Node resolvers use explicit boolean parsing. Unknown or missing
values use the safer default.

| Flag | Safe default | Effect |
| --- | --- | --- |
| `CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED` | `false` | The status route returns 404 and the bridge remains disabled. |
| `CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY` | `true` | Only non-persistent estimates are permitted. |
| `CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS` | `true` | Phase 1H PASS evidence is mandatory for any operator-review verdict. |
| `CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL` | `true` | Explicit operator approval evidence is mandatory. |
| `CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE` | `false` | The review gate blocks when this is set true; no automatic enablement exists. |
| `CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP` | `false` | The review gate blocks when this is set true; no bootstrap path exists. |

There is no code path in this framework that flips
`auto_paper_entries=true`, changes `bootstrap_paper_enabled`, or treats a
readiness result as an enablement action.

## 4. Read-only readiness checker

`controlled_paper_entry_readiness.py` is pure and dependency-injected. It
accepts caller-supplied evidence only; it has no production-state loader and no
write dependency.

Its public output is restricted to:

- `GO_FOR_OPERATOR_REVIEW`
- `NO_GO`
- `BLOCKED`

The checker requires all of the following exact evidence:

1. A Phase 1H report exists and has `PASS` status.
2. The scan universe is `CUSTOM_LOW_PRICE_SECTOR`.
3. `symbols_analysed=23` and `symbols_with_errors=0`.
4. `nifty_50_fallback=false`.
5. Custom-universe sector counts are exactly BANK=9, INFRA=13, IT=1 with
   `active_count=23`.
6. Settings show ₹100,000 capital, the active custom universe, auto entries
   off, and bootstrap off.
7. Positions are exactly `[]`.
8. The watch trade audit contains no `AUTO` or `BOOTSTRAP_AUTO` record.
9. EOD status and outcomes both pass.
10. Both advisory-core and advisory-integration reviews are present.
11. Operator approval is explicitly present.

The current Phase 1G report remains a pre-session **NO-GO** document, so the
framework cannot legitimately reach `GO_FOR_OPERATOR_REVIEW` until the Monday
watch and EOD evidence exist.

## 5. Dry-run simulation proof

`controlled_paper_entry_dry_run.py` accepts an advisory candidate and returns
only:

- candidate symbol;
- strategy source;
- advisory score;
- risk flags;
- theoretical notional;
- theoretical risk; and
- a rejection reason when unsafe.

Every result includes the exact marker:

```text
DRY RUN ONLY — NOT A TRADE — NOT AN ORDER
```

The output intentionally excludes quantity, executable quantity, order IDs,
broker fields, and any executable request payload. Unsafe advisory candidates,
risk flags, non-BUY actions, malformed inputs, and forbidden executable input
fields are rejected in memory. The module performs no file, database, ledger,
position, trade, broker, settings, or scheduler operation.

## 6. Advisory-to-paper bridge proof

`controlled_paper_entry_bridge.py` is a deliberately terminal bridge:

- With the framework disabled, it returns `BRIDGE_DISABLED` before simulation.
- With safe review controls explicitly enabled, it returns
  `DRY_RUN_ONLY` plus the dry-run simulation.
- If dry-run-only, auto-enable, or bootstrap controls are unsafe, it returns
  `BLOCKED`.
- Its `execution_allowed` value is always `false`.

The bridge has no import or call dependency on Phase 20, paper-trader,
broker/Kite, settings, or scheduler code. It cannot call an entry executor and
cannot create an executable request.

## 7. Optional status API proof

Only this additive, read-only route was added:

```text
GET /api/controlled-paper-entry/status
```

Rules verified:

- It returns HTTP 404 while
  `CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED` is unset or false.
- When explicitly enabled, it requires a valid operator `__session`.
- It reports `BLOCKED` readiness only because this route accepts no evidence
  and never reads production state.
- It exposes no run, execute, place-order, enable-auto-entry, create-trade,
  broker, settings, or scheduler endpoint.

After restarting the local development API workflow, a read-only request
returned:

```text
GET /api/controlled-paper-entry/status: HTTP 404
{"status":"DISABLED","controlled_paper_entry":true,
 "dry_run_only":true,"execution_allowed":false}
```

This was a local development-proxy verification, not a production request.

## 8. Test and validation results

| Validation | Result |
| --- | --- |
| New Phase 4A Python safety suite | 20 passed |
| Direct review-package test execution | 20 passed |
| New controlled-entry API route tests | 5 passed |
| Combined Phase 4A + Phase 3A + advisory + Phase 0C + custom-universe Python suites | 93 passed, 4 subtests passed |
| Existing warning | One pre-existing `datetime.utcnow()` deprecation warning in `phase3f_logging.py` |
| Advisory plus controlled-entry API tests | 15 passed |
| Python compilation for new modules and review package | Passed |
| API TypeScript typecheck | Passed |
| Repository configured typecheck | Passed |
| `git diff --check` | Passed |
| Diff check against `phase3a-advisory-integration-disabled` | Passed |
| Protected-file diff guard | Passed |
| Local default-disabled API check | HTTP 404 |

The test suite covers flag defaults, unsafe control combinations, every required
readiness blocker, empty positions, exact custom-universe counts, required EOD
proof, absent auto/bootstrap audit records, dry-run non-executable outputs,
bridge blocking, bootstrap blocking, no forbidden bridge imports, default API
absence, and API authentication.

## 9. Protected-file diff proof

The branch diff leaves these protected areas untouched:

- `phase20_executor.py`
- `phase20_scheduler.py`
- `phase20_exits.py`
- `phase20_eod_outcomes.py`
- `phase20_eod_status.py`
- `paper_trader.py`
- `broker_client.py`
- Kite and live-order modules
- settings write handlers
- deployment configuration
- workflows
- production execution configuration

No protected-file exception was needed.

## 10. Explicit safety confirmations

- **No merge:** confirmed.
- **No deployment:** confirmed.
- **No trades:** no trade was created.
- **No positions:** no position was opened, closed, or changed.
- **No live orders:** no broker or Kite order API was called.
- **No settings mutation:** no setting was changed by this framework.
- **Auto paper entries:** remain disabled.
- **Bootstrap:** remains disabled.
- **Paper only:** confirmed.
- **Dry run only:** confirmed.

## 11. Monday merge and testing recommendation

Keep every controlled-entry and advisory flag disabled in production.

On Monday, complete the Phase 1H market-session and EOD watch first. Supply the
resulting evidence to the pure readiness checker only in a separate, reviewed
operator process. A `GO_FOR_OPERATOR_REVIEW` verdict is not an enablement
action and must be followed by a separate explicit operator decision.

Do not merge this branch or deploy it solely because the framework exists.
Any future action that changes settings, enables automatic paper entries,
allows bootstrap, wires a scheduler, creates a trade, or adds an execution
surface requires an independent safety review and explicit operator approval.