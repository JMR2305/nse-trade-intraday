# RTV-2E — Next Natural Session Gate

**Date:** 2026-08-25 (IST)  
**State:** **UNLOCKED FOR RESTRICTED NATURAL-SESSION VALIDATION**

RTV-2E reconciled the stale test expectations with stronger coverage and the
complete validation gate is green. This unlocks only the next naturally
scheduled NSE-session observation procedure; it does not authorize paper
entries, bootstrap, manual scans, lifecycle triggers, or broker orders.

## Required evidence

1. Phase 5A durable session and phase-state creation.
2. A single immutable collection batch with provider count = persisted count =
   23.
3. Freeze after durable parity proof only.
4. Durable predecessor ordering through reconciliation and enrichment.
5. A canonical `SCHEDULED` scan origin.
6. Repeated observation GETs with no new scan, lifecycle state, trade, or
   broker order.
7. Automatic entries false and unconfirmed; bootstrap false; exits enabled.
8. Canonical ledger and portfolio endpoint parity maintained.

## Still prohibited

- enabling automatic entries or bootstrap;
- triggering manual scans or manual lifecycle phases;
- changing universe, capital, strategies, or thresholds;
- resetting the portfolio or rewriting ledger history;
- placing live broker orders.

If any required evidence is missing or any prohibited action occurs, stop and
record a failed natural-session certification rather than retrying manually.
