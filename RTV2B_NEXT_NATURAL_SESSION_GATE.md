# RTV-2B — Next Natural-Session Gate

**Status:** Not unlocked — RTV-2B deployment stopped on source safety failure

The next natural scheduled NSE session remains the only permitted route to
certify the Phase 5A lifecycle. No manual validation activity is authorized.

## Preconditions before unlocking

1. Resolve the `auto_paper_entries: true` source regression.
2. Confirm the approved custom 23-symbol universe remains unchanged.
3. Confirm ₹100,000 capital, paper-only execution, automatic entries disabled,
   bootstrap disabled, automatic exits enabled, and live broker orders disabled.
4. Rerun the RTV-2B source, schema, test, and identity gates.
5. Publish only after all pre-deploy gates pass.

## Required natural-session evidence

During the next naturally scheduled NSE session, capture evidence without
manual scans, manual pre-open refreshes, lifecycle jobs, entry activation,
bootstrap activation, or broker orders:

1. Durable Phase 5A session created during its init window.
2. Durable readiness, collection, and freeze states.
3. `provider_collected_count == persisted_count == 23` from one immutable
   verified collection batch.
4. Freeze only after that parity proof.
5. Durable reconciliation ordering, followed by 09:30 enrichment only after
   `RECONCILED`.
6. Canonical scan origin `SCHEDULED`.
7. Truthful scheduled-scan readiness.
8. Repeated observation GETs with no new scans, phases, trades, or orders.
9. Portfolio and ledger parity with no unauthorized activity.
10. If collection retries occur, frozen evidence contains only the final
    verified batch.

## Verdict rule

Pass only when every evidence item is present and internally consistent.
Provider gaps, count mismatches, durable-write failures, blocked predecessors,
non-scheduled scan origin, prohibited activity, or stale/incomplete evidence
must produce an honest failure and defer certification to a later natural
session.
