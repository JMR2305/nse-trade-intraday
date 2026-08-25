# RTV-3C — Next Natural Session Gate

## Current status

The clean Task #918 candidate is correctly isolated from unrelated runtime
changes, but it is **not deployable yet** because the daily-session test gate
has one failure. No release commit or production deployment exists.

The current time is after today's natural Phase 5A window. Do not run Task #920
today, manually simulate today's validation, or replay the failed RTV‑3 batch.

## Release prerequisite

First reconcile the untouched baseline daily-session test failure without
adding unrelated runtime changes. Then rerun all required RTV‑3C suites on the
same clean branch. Only after every required check passes may a release commit
be created with:

```text
APPROVED_DEPLOY_COMMIT = <full SHA>
EXPECTED_BUILD_ID = apexquant-<first 12 SHA chars>
```

## Next natural-session proof

After a clean scoped deployment, use
`RTV3A_NEXT_NATURAL_SESSION_GATE.md`. The next naturally scheduled NSE session
must prove:

```text
expected_symbol_count = 23
provider_collected_count = 23
persisted_count = 23
missing_count = 0
duplicate_count = 0
malformed_count = 0
unexpected_count = 0
failed_count = 0
persistence_status = MATCH
```

It must also show:

- no legacy `DEFAULT_WATCHLIST` substitution;
- exact persisted symbol identity before freeze;
- scheduled downstream lifecycle and scheduled canonical scan;
- pure observation GETs;
- automatic entries disabled and unconfirmed;
- bootstrap disabled;
- automatic exits enabled;
- live broker orders disabled;
- portfolio and ledger parity preserved.

## Prohibited actions

- no manual Phase 5A/5B/5C trigger;
- no manual scan, retry, or replay;
- no mutation of `preopen-2026-08-25-9b8340` or
  `collection-6073abbd096c44e7b4e4b51a205696ba`;
- no settings, universe, capital, strategy, threshold, portfolio, or ledger
  changes;
- no automatic-entry, bootstrap, broker-order, login, or credential action.

**Gate decision: WAIT.** Resolve the test gate, create a clean approved
release, deploy it, and then stop until the next naturally scheduled NSE
session.