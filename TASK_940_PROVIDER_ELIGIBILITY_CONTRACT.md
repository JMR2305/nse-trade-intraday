# Task 940 — NSE pre-open provider and eligibility contract

## Provider request scope

The Phase 5A custom-universe collector requests NSE pre-open data using:

```text
GET https://www.nseindia.com/api/market-data-pre-open?key=ALL
```

`ALL` is now forced for this custom-universe collection path; restricted keys
cannot override it. The old hard-coded `NIFTY` key was inappropriate for an
arbitrary 23-symbol custom universe.
Provider cache entries are now isolated by request key, preventing an old
NIFTY response from serving an `ALL` collection.

The NSE public pre-open UI describes separate capital-market pre-open
categories. A widely-used documented client for the same public endpoint lists
the above keys, including `ALL`. The next scheduled natural session is the
runtime proof point for this public-feed contract; no historical response has
been fabricated or inferred.

## Exact collection contract

For each collection batch:

1. Resolve the active universe before provider collection.
2. Send the full resolved symbol set to the provider adapter.
3. Record the provider query scope and the raw response row count before local
   symbol filtering.
4. Interpret NSE `lastUpdateTime` as an Asia/Kolkata wall-clock value before
   computing freshness. At five minutes or older, or if that timestamp is
   missing/invalid, or later than the collection time, the row is stale.
5. Normalize only real provider rows into `PreOpenSnapshot` records.
6. Persist exactly one immutable outcome row for each expected symbol.
7. Persist live snapshots separately from outcomes.
8. Require exact, explicitly proven non-stale live-snapshot coverage to reach
   `MATCH` and freeze. Each row must durably say `is_stale=false` and
   `source_status=LIVE`; a missing or unknown value is fail-closed.

## Outcome classes

| Outcome | Meaning | Creates a price snapshot? | Freeze effect |
|---|---|---:|---|
| `LIVE_PREOPEN_DATA` | Provider row was normalized and is ready for persistence. | Yes | Required for every expected symbol. |
| `NO_PREOPEN_DATA` | Provider result was empty or did not contain the requested symbol. | No | Blocks `MATCH`/freeze. |
| `NOT_ELIGIBLE` | Only allowed when a provider supplies explicit, auditable eligibility evidence. | No | Blocks unless a future formally approved policy changes the live-coverage contract. |
| `NORMALIZATION_FAILED` | A provider row existed but lacked required valid fields. | No | Blocks. |
| `PROVIDER_UNAVAILABLE` | Health or fetch failed before a usable row was available. | No | Blocks. |
| `COLLECTION_PROCESSING_FAILED` | A post-resolution processing, enrichment, serialization, or persistence exception occurred. | No | Blocks. |
| `DUPLICATE_RESPONSE` | A duplicate symbol/snapshot made the batch unusable. | No | Blocks. |
| `PROVIDER_OMITTED` | The adapter failed to classify an expected symbol. | No | Blocks. |

Current NSE parsing does not claim `NOT_ELIGIBLE`: an absent public-feed row is
recorded as `NO_PREOPEN_DATA`. This avoids incorrectly treating a provider
omission as an approved business rule.

Once the active universe has been resolved, every failure path retains the
original collection-batch ID and writes one explicit failure outcome for every
expected symbol. This includes provider initialization and health probing, as
well as post-provider processing.

## Safety invariants

- No missing outcome becomes a zero-price or synthetic live row.
- A complete outcome matrix is necessary for auditability but is not sufficient
  for a `MATCH`; every expected symbol must also have a valid live snapshot.
- Freeze rechecks the immutable outcome matrix for the exact collection batch,
  in addition to the existing count/set/persistence proof.
- The five-minute liveness boundary is inclusive: `age >= 300` is stale.
- Failed or partial batches remain isolated from verified/frozen batches.