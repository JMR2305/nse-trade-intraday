# Task 947 — Freeze Authority Design

## Authority selected

Freeze authority is a **naturally scheduled final-proof batch**, not the
latest arbitrary row set and not an arbitrary earlier verified pointer.

The scheduler may freeze only when one batch satisfies every condition below:

1. its source is `SCHEDULED`, never a direct/manual refresh;
2. it has a durable completion time on the current session trading date;
3. its completion time falls within 09:08–09:12 IST;
4. provider count equals persisted count equals expected count;
5. failed count is zero and persistence status is `MATCH`;
6. the durable snapshots are from the verified batch ID exactly, with no
   duplicate snapshots or symbols;
7. every snapshot was `LIVE` and `is_stale=false` at collection;
8. the immutable outcome matrix has one `LIVE_PREOPEN_DATA` outcome for every
   expected symbol; and
9. the freeze write records that same batch ID.

Any missing, malformed, future, cross-day, manual, late, older, stale,
partial, duplicate, mixed-batch, non-live, or unavailable evidence blocks
freeze and leaves the session in its safe error path.

## Why this is safe

The final-proof window preserves the strict provider freshness rule at
ingestion while preventing a matching-phase collection from overwriting good
evidence solely because auction data is appropriately static. The exact batch
ID and outcome matrix prevent the application from silently borrowing rows
from an earlier retry or using count parity as a substitute for symbol proof.

## Manual operation boundary

The public pre-open refresh path creates a distinct manual session and calls
collection with `MANUAL` origin. Manual data remains observable, but it cannot
be promoted to a 09:15 certificate. The legacy direct scheduler cycle also
collects as manual. Only the automatic intelligence tick passes the scheduled
origin, and it stops collection at 09:12.

This design does not change production universe membership, trade execution,
paper settings, broker behavior, or the immutable 2026-08-27 result.