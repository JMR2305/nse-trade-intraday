# RTV-3B — Next Natural Session Gate

## Current status

RTV‑3B did not produce an approved deployment. The source-scope gate failed
because the branch contains unrelated Mission Control, build/deployment, state,
database-initialization, and other runtime changes after the current
production commit.

Task #920 must not be performed against the current mixed-scope branch.
Additionally, the current observation was after the 09:15 NSE open, so no
manual or same-day Phase 5A action is permitted.

## Required release prerequisite

Before the next natural session, publish only a clean, independently validated
commit containing the Task #918 Phase 5A repair. The clean commit must include
only:

- durable active-universe resolution;
- exact requested-symbol propagation;
- provider-cache isolation by normalized symbol set;
- complete coverage evidence and `COVERAGE_INCOMPLETE` handling;
- exact persisted-vs-expected freeze validation;
- related status models and tests.

Do not include unrelated Mission Control, dashboard build identity,
deployment-script, state, database-initialization, or other runtime changes.

## Prohibited actions

- no manual Phase 5A/5B/5C trigger;
- no manual scan, retry, or replay;
- no mutation of the preserved RTV‑3 session or batch;
- no automatic entries, bootstrap, or live broker orders;
- no universe, capital, strategy, threshold, portfolio, or ledger changes;
- no credential creation or manual Kite login.

## Required next-session proof

Use the original `RTV3A_NEXT_NATURAL_SESSION_GATE.md` after a clean scoped
deployment. The next naturally scheduled NSE session must show:

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

The durable batch must contain exactly the 23 custom-universe symbols, freeze
must follow that exact proof, downstream phases must remain scheduled, and the
canonical scan must be current-session and `SCHEDULED`. Observation GETs must
remain pure, with safety and portfolio parity preserved.

## Gate decision

**WAIT.** No Task #920 natural-session validation is authorized today from the
current mixed-scope branch. First resolve the source-scope failure and obtain a
new approved deployment identity.