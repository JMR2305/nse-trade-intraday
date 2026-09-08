# RTV-2D — Next Natural Session Gate

**Date:** 2026-08-25 (IST)  
**State:** **LOCKED**

## Why certification is locked

The deployed source repair, runtime identity, safety settings, Kite session,
custom-universe mapping, ledger preservation, and canonical portfolio parity
all verify correctly.

However, RTV-2D requires the complete unmodified test gate to pass. Two
pre-existing expectations are currently red, so the permitted verdict is:

```text
E. TEST FAILURE
```

Natural-session certification must not be unlocked until those tests are
reconciled without weakening coverage and the full gate is rerun successfully.

## Required next-session evidence

After the test gate is green, use only a natural scheduled NSE session. Do not
use a manual scan, manual lifecycle trigger, bootstrap action, paper entry, or
broker order to obtain this evidence.

The session must demonstrate:

1. Phase 5A creates durable session state.
2. Provider-collected and persisted counts are both 23 for the same immutable
   verified batch.
3. Freeze follows only that durable parity proof.
4. Reconciliation and enrichment preserve durable predecessor ordering.
5. The canonical scan is scheduled and its origin remains `SCHEDULED`.
6. Repeated observation GETs create no scan, lifecycle state, trade, or broker
   order.
7. Automatic entries remain false and unconfirmed; bootstrap remains false;
   exits remain enabled.
8. The ledger remains reconcilable and both portfolio endpoints remain
   canonical-parity equal.

## Prohibited actions while locked

- enabling automatic entries or bootstrap;
- changing the universe, capital, strategy, or thresholds;
- resetting the portfolio or rewriting ledger history;
- triggering scans or pre-open lifecycle phases;
- placing broker orders.
