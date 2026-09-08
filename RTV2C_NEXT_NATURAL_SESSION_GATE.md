# RTV-2C Next Natural Session Gate

## Current gate status

**BLOCKED UNTIL THE SOURCE REPAIR IS PUBLISHED AND BOTH SOURCE + PRODUCTION
STATES ARE RECONFIRMED.**

The active production runtime setting has been corrected, but the source repair
has not yet been published. A natural-session certification must not be
unlocked until the published runtime identity contains the source repair and
the following checks pass.

## Mandatory pre-session checks

1. Verify the published build identity is the approved RTV-2C release.
2. Read production Phase 20 settings:
   - automatic entries `false`;
   - confirmation `null`;
   - bootstrap `false`;
   - automatic exits `true`;
   - custom 23-symbol universe and ₹100,000 capital unchanged.
3. Confirm no open or `EXIT_PENDING` ledger rows exist unless independently
   explained and acknowledged.
4. Confirm the scheduler consumes disabled automatic-entry settings and does
   not call an entry path.
5. Confirm daily session initialization reports automatic-entry state as
   unchanged.

## Natural-session boundaries

- Only normal scheduled NSE activity may be observed.
- Do not manually trigger a scan, pre-open lifecycle job, entry tick, bootstrap
  action, or broker order.
- Observation GET routes must remain read-only.
- Automatic exits may continue to operate under their existing safeguards.

## Certification evidence required after a natural session

- Scheduled scan origin and fresh timestamp evidence;
- no automatic-entry activation or confirmation transition;
- no new paper BUY from the disabled state;
- durable lifecycle collection/freeze/reconciliation evidence where applicable;
- portfolio and ledger parity;
- final production settings and runtime identity readback.

Any automatic-entry transition, missing durable evidence, stale scheduled scan,
or identity mismatch blocks certification and requires a new review.