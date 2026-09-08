# Task 940 — next natural NSE pre-open session gate

## Purpose

This is an observation-only certification gate for the next natural eligible
NSE pre-open session. Do not manually trigger a scan, collection, retry,
replay, backfill, or freeze.

## Required evidence for a pass

For one scheduled collection batch, verify:

1. The active-universe record has a non-empty exact expected symbol set.
2. The collection coverage records:
   - `provider_scope=ALL`;
   - a raw response count before filtering;
   - `outcome_complete=true`;
   - exactly one outcome for each expected symbol.
3. Every immutable outcome row belongs to that session and batch, and its
   symbol set exactly equals the expected set.
4. Each symbol outcome is classified explicitly. No `PROVIDER_OMITTED`,
   unclassified, or duplicate outcome is permitted.
5. The live snapshot symbol set exactly equals the expected set:
   `provider_collected_count = persisted_count = expected_count`,
   `failed_count = 0`, and `persistence_status=MATCH`. Every persisted row
   must explicitly record `is_stale=false` and `source_status=LIVE`.
6. The verified collection batch pointer names that same batch.
7. Freeze only succeeds for that same batch and records a frozen batch pointer.
8. Watchlist/persistence consumers use only real live snapshots. No missing
   symbol may appear as a zero-price, stale, or fabricated placeholder.

## Fail-closed outcomes

Any of the following is a fail:

- a provider response covers only part of the active universe;
- missing or duplicate outcome rows;
- `NO_PREOPEN_DATA`, `NORMALIZATION_FAILED`, `PROVIDER_UNAVAILABLE`, or
  `PROVIDER_OMITTED` for any expected symbol;
- mismatch between expected, outcome, provider, and persisted symbol sets;
- an unverified or unfrozen batch;
- evidence from a different session or collection batch.

Record the batch ID, expected set, raw response count, outcome matrix,
persisted symbol set, and freeze decision. Do not amend the August 26
historical session to make it look complete.