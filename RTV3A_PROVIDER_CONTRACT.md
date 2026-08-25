# RTV-3A — Phase 5A Provider Coverage Contract

## Scope

This contract governs scheduled Phase 5A collection for
`CUSTOM_LOW_PRICE_SECTOR`. It is advisory data collection only: it neither
creates orders nor relaxes paper-entry, bootstrap, broker, or portfolio gates.

## Authoritative requested set

1. The durable Phase 20 active-universe setting selects the mode.
2. When that mode is `CUSTOM_LOW_PRICE_SECTOR`, the durable active-symbol store
   supplies the requested set.
3. The set is upper-cased, de-duplicated, and passed unchanged to provider
   selection and construction.
4. An unreadable, malformed, or unavailable durable settings record is
   `UNIVERSE_UNAVAILABLE`, regardless of environment defaults. This prevents a
   prior custom selection from silently reverting to the legacy watchlist.
5. An empty or unreadable custom member set is `UNIVERSE_UNAVAILABLE`; it must
   not fall back to `DEFAULT_WATCHLIST`.
6. The legacy default-watchlist behavior remains available only when a readable
   durable setting explicitly selects a non-custom mode.

## Provider response semantics

The NSE pre-open endpoint is fetched once and parsed into a symbol-keyed map.
There is no provider pagination or response page size in this path. The NSE
provider then iterates its requested symbols and emits only rows requested for
that collection.

For an expected set `E`, the collection classifies a provider response as:

| Outcome | Meaning | Durable result |
| --- | --- | --- |
| `MATCH` | Every expected symbol has exactly one normalized, persisted row; no malformed, duplicate, or unexpected rows | Verified batch pointer may be written |
| `COVERAGE_INCOMPLETE` | A live/provider response is partial, duplicated, malformed, or contains unexpected rows | Retryable; no verified batch pointer; freeze blocked |
| `NO_DATA` | Provider returned zero rows | Retryable; missing symbols recorded; no synthetic snapshots |
| `PROVIDER_UNAVAILABLE` | Provider health is unavailable | Retryable; no snapshots fabricated |
| `UNIVERSE_UNAVAILABLE` | Required custom membership cannot be resolved | Fail closed; provider is not selected |
| `MISMATCH` / `PERSISTENCE_UNAVAILABLE` | Durable insert proof is incomplete or storage is unavailable | Retryable; no verified batch pointer |

## Durable coverage proof

Each collection records:

- expected, provider-returned, normalized, persisted, and failed counts;
- missing, duplicate, malformed, and unexpected counts;
- duplicate snapshot-ID evidence; and
- expected, normalized, missing, duplicate, and unexpected symbol lists in the
  session coverage record; and
- the immutable collection batch identifier.

`provider_collected_count == persisted_count` is necessary but not sufficient.
`MATCH` additionally requires:

```text
expected_count == normalized_count == persisted_count
missing_count == duplicate_count == malformed_count == unusable_count == 0
```

The scheduler freezes only a durable `MATCH` batch whose expected, collected,
and persisted counts are equal and whose failed count is zero. It repeats exact
batch row/snapshot-ID/symbol uniqueness checks and requires the canonical
persisted symbol set to equal the durable expected symbol set before freezing.

## Provider-cache isolation

The provider cache key contains the normalized ordered requested symbol tuple.
Calls with a different set, even during the cache TTL, construct/probe a
provider for that new set. A prior ten-symbol health probe therefore cannot
serve a later 23-symbol scheduled collection.

## No-data policy

Missing data is never padded with price, volume, or placeholder snapshots.
For a partial live response, only returned valid expected rows may be preserved
under the attempt batch; the coverage record explicitly lists missing and
unusable symbols. Such evidence is diagnostic only and cannot drive freeze or
downstream phases.