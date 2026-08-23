# RTV-1 Pre-open and Lifecycle Verification

## Confirmed root cause

The Phase 5A and Phase 5B session upserts treated every omitted field as a default value. A lifecycle-only write such as freeze, reconciliation, or checkpoint therefore replaced previously collected counts with zero and provider status with `UNAVAILABLE`. The collection tick also reported the obsolete `symbols_captured` field while collection emitted `symbol_count`.

## Fixes

1. Partial Phase 5A and Phase 5B session updates now preserve omitted count, provider, timestamp, error, and linkage fields.
2. The Phase 5A collection tick reports the authoritative `symbol_count`, retains a compatibility alias, and returns persisted count plus `MATCH`, `MISMATCH`, or `UNCONFIRMED` persistence status.
3. Lifecycle guards prevent collection/checkpoint updates from regressing frozen, reconciled, complete, or no-candidate sessions back to collecting/pending states. Valid forward 5A reconciliation transitions remain allowed.
4. A 5B EOD run with no candidates records `NO_CANDIDATES` instead of leaving a collecting session behind.
5. 5C EOD finalization reports `EOD_RETRY_REQUIRED` when records are still non-terminal or lack a reliable close; it only records `COMPLETE` after terminal resolution.

## Verification

- Focused lifecycle truth tests cover count persistence, mismatch visibility, post-freeze/reconcile rejection, allowed forward transition, and post-terminal update protection.
- The consolidated RTV-1 focused suite passed: **92 passed**.
- No pre-open collection, scheduler trigger, or historical-row rewrite was performed as part of verification.

## Runtime interpretation

The historical Friday provider-count versus persisted-zero finding is repaired prospectively by preservation and mismatch detection. It is not backfilled or rewritten. Monday's scheduled pre-open run must confirm provider collected count equals persisted snapshot count before it is considered live-session verified.