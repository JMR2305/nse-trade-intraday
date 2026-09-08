# Phase 4A — Controlled Paper-Entry Framework (Disabled)

## What was built

Phase 4A adds a pre-Monday, disabled-by-default framework for evaluating
whether paper-entry controls could later be reviewed. It is not an entry
system, an order system, or an activation mechanism.

### Components

| Component | Purpose |
| --- | --- |
| Controlled-entry flags | Resolve six safety controls with fail-closed defaults. |
| Readiness checker | Pure caller-supplied-evidence checker returning only GO_FOR_OPERATOR_REVIEW, NO_GO, or BLOCKED. |
| Dry-run simulation | Calculates non-persistent theoretical notional and risk for an advisory candidate. |
| Disabled bridge | Stops at dry run and has no execution dependency. |
| Status API | Optional authenticated read-only route; HTTP 404 by default. |
| Review package metadata | Adds implementation summary, feature-matrix entry, test row, and honest disabled-status export. |

### API endpoint

- `GET /api/controlled-paper-entry/status`
  - HTTP 404 by default.
  - Requires an operator session if the framework is explicitly enabled.
  - Always reports `BLOCKED` until separately supplied review evidence exists.
  - Has no mutation, execution, order, or trade action.

### Framework behavior

The readiness checker requires an exact Phase 1H PASS, approved
23-symbol custom universe, zero scan errors, no NIFTY fallback, correct
9/13/1 sector counts, ₹100,000 settings with entries/bootstrap disabled,
no positions, no AUTO/BOOTSTRAP_AUTO watch trades, EOD proof, advisory review
proof, and explicit operator approval.

The dry-run output visibly states:

```text
DRY RUN ONLY — NOT A TRADE — NOT AN ORDER
```

It intentionally omits executable quantity and order data.

## Files created or modified

- `artifacts/api-server/src/python/controlled_paper_entry_flags.py`
- `artifacts/api-server/src/python/controlled_paper_entry_readiness.py`
- `artifacts/api-server/src/python/controlled_paper_entry_dry_run.py`
- `artifacts/api-server/src/python/controlled_paper_entry_bridge.py`
- `artifacts/api-server/src/python/tests/unit/test_phase4a_controlled_paper_entry.py`
- `artifacts/api-server/src/lib/controlledPaperEntryFlags.ts`
- `artifacts/api-server/src/routes/controlledPaperEntry.ts`
- `artifacts/api-server/src/routes/controlledPaperEntry.test.ts`
- `artifacts/api-server/src/routes/index.ts`
- `artifacts/api-server/src/python/review_package.py`
- `APEXQUANT_PHASE4A_CONTROLLED_PAPER_ENTRY_FRAMEWORK_DISABLED_REPORT.md`

## Test results

| Test | Result |
| --- | --- |
| Phase 4A controlled-entry Python safety suite | 20 passed |
| Combined required Python regression suite | 93 passed, 4 subtests passed |
| Advisory and controlled-entry API tests | 15 passed |
| API and repository typechecks | Passed |
| Protected-file diff guard | Passed |
| Local default-disabled API endpoint | HTTP 404 |

The combined Python regression suite emits one existing
`datetime.utcnow()` deprecation warning from `phase3f_logging.py`.

## Issues and known gaps

| Area | Description | Severity | Resolution path |
| --- | --- | --- |
| Monday market evidence | The Phase 1H full-session scan and EOD evidence do not exist yet. | Blocking | Complete Monday watch and submit read-only evidence to the checker. |
| Operator approval | No approval is embedded or inferred by code. | Blocking | A future operator must supply explicit approval after checks pass. |
| Runtime evidence loader | The status route never loads production data by design. | Intentional | Any future evidence loader requires its own safety review. |
| Entry activation | There is no entry activation path. | Intentional | A separate approved phase would be required; this phase must not be extended implicitly. |

## What to enable

Nothing should be enabled for this phase.

Keep all of these disabled in production:

- `CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED`
- all advisory integration flags
- `auto_paper_entries`
- `bootstrap_paper_enabled`

`CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY`,
`CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS`, and
`CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL` retain their safe defaults
if configuration is absent.

## Downstream dependencies

1. A complete Monday Phase 1H market-session report with PASS status.
2. Verified EOD status and outcome proof for the same watch.
3. An independent operator review of the complete evidence.
4. A separate explicit decision before any merge or deployment.
5. A new independent safety review before introducing settings changes,
   automatic entries, bootstrap, scheduler integration, trade creation,
   persistence, or any execution capability.