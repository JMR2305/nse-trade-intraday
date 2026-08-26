# Task #944 — Next Natural Session Gate

## Purpose

This document defines the read-only certification criteria for the next
**naturally scheduled** NSE Phase 5A pre-open collection after the approved
Task #941/#942 deployment is confirmed.

No manual collection, manual market scan, replay, retry, backfill, data
fabrication, or historical repair is permitted to satisfy this gate.

## Precondition: deployment identity

The post-publish verification confirmed that production reports:

```text
git_commit = 06ff8327ed35b4ab298f15e7b8f7cdef8ad02191
build_id   = apexquant-06ff8327ed35
environment = production
```

The additive `preopen_collection_outcomes` table and its required indexes are
present in the production schema.

## Required natural scheduled evidence

For the natural `SCHEDULED` Phase 5A collection:

1. The active universe resolves to `CUSTOM_LOW_PRICE_SECTOR`.
2. The expected universe contains exactly 23 approved symbols.
3. The NSE provider collection query uses scope `ALL`.
4. The provider cache is not reused across a different query scope.
5. One immutable outcome exists for every expected symbol in the same
   collection batch.
6. A real snapshot row exists only for a real normalized provider row.
7. Every persisted live row carries explicit:
   - `is_stale = false`
   - `source_status = LIVE`
8. Expected, live, and persisted live symbol sets match exactly.
9. All matching evidence points to one collection batch ID.

## Certification and freeze decision

`MATCH` and freeze are allowed only when:

```text
expected live symbol set
  = persisted live symbol set
  = exact expected universe
```

and the exact batch has:

- complete durable outcome coverage;
- explicit non-stale liveness;
- explicit `LIVE` source status;
- no missing or unknown liveness metadata; and
- matching verified/frozen batch pointers.

The freeze process must independently re-read the exact batch evidence. It
must not rely only on an earlier aggregate count or a later snapshot from
another batch.

## Mandatory blockers

Any of the following must block `MATCH` and freeze:

- a missing expected symbol;
- duplicate or unexpected symbol evidence;
- a missing outcome;
- an unclassified outcome;
- provider unavailability;
- normalization failure;
- no-data evidence;
- an incomplete outcome matrix;
- a missing, malformed, stale, or future-dated NSE timestamp;
- `age >= 300` seconds;
- `source_status` other than `LIVE`;
- `is_stale` other than explicit `false`;
- an inconsistent collection batch ID; or
- an incomplete persisted live set.

## Preservation rule

The next natural session is new evidence only. It must not modify the
historical session:

```text
preopen-2026-08-26-ccb21a
```

That session remains partial, uncertified historical evidence.

## Final post-publish verdict rule

After the completed controlled publish and read-only runtime identity
verification:

```text
PASS — TASK #941/#942 DEPLOYED, NEXT NATURAL SESSION READY
```

is permitted only if production identity, additive schema, source/runtime
presence, and safety checks all pass. The natural session itself remains the
only permitted source of new Phase 5A certification evidence.