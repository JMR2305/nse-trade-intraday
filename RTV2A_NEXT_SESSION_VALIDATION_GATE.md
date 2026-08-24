# RTV-2A — Next natural-session validation gate

## Authorization boundary

Validate only the naturally scheduled NSE session. Do **not** run manual scans,
manual pre-open refreshes, lifecycle jobs, auto-entry/bootstrap activation, or
broker orders.

## Preconditions

- Published API build is healthy and identifies the approved application.
- Active universe is the 23-symbol custom low-price sector universe.
- Kite session/token and all 23 instrument mappings are healthy.
- Capital remains ₹100,000.
- Paper-only mode remains enabled.
- Automatic entries and bootstrap remain disabled.
- Automatic exits remain enabled.
- Live broker execution remains disabled.
- Portfolio has the expected parity and no unapproved open-position change.

## Required session evidence

Capture the following without triggering computation:

1. Phase 5A durable session created during its init window.
2. Durable readiness, collection, and freeze phase states.
3. A collection result where `provider_collected_count == persisted_count ==
   23`, with durable snapshots from the same immutable verified collection
   batch.
4. A frozen session only after that parity proof; otherwise an explicit
   `FREEZE_BLOCKED` outcome.
5. Reconciliation only after the durable frozen phase; 09:30 enrichment only
   after durable reconciliation. A blocked predecessor must block all
   downstream lifecycle advancement.
6. First canonical scan stamped `SCHEDULED`, with its scan ID and timestamp.
7. Readiness report showing `certifying_scheduled_scan: true` and a truthfully
   derived trading-data readiness verdict.
8. Repeated GET reads of recommendations/scan/pre-open status that do not
   create a new scan ID, lifecycle phase, paper trade, or broker order.
9. Ledger/portfolio reconciliation proving no unauthorized entry or broker
   activity occurred.
10. Any explicitly authorized API scan records `API_TRIGGERED` origin and a new
    scan result, while every frozen/reconciled Phase 5A record uses snapshots,
    watchlists, and reconciliation writes from the same durable session ID.
11. If collection retries occur, frozen evidence contains only the final
    verified batch—not newest rows carried over from an earlier attempt.

## Pass / fail rules

**PASS** only if every required evidence item is present and internally
consistent.  

**FAIL / retry next session** if provider data is unavailable, collection
counts diverge, a durable write fails, freeze is blocked, a scan origin is not
`SCHEDULED`, or any prohibited activity appears. A failure must be recorded as
an honest incomplete session, never filled with synthetic or manual evidence.