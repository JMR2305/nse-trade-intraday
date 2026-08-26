# Task #944 — Historical 3-Symbol Reconciliation

## Scope and immutability

This reconciliation is read-only. It does not modify, retry, replay, backfill,
freeze, or relabel the historical session:

```text
preopen-2026-08-26-ccb21a
```

## Authoritative historical truth

The authoritative source is the immutable persisted production batch evidence:

```text
SESSION_ID              = preopen-2026-08-26-ccb21a
COLLECTION_BATCH_ID     = collection-3a70e162d5f146a3b8514974ee6a780e
AUTHORITATIVE_COLLECTED_3 = COALINDIA, NTPC, WIPRO
```

The persisted session row reports:

| Field | Value |
|---|---:|
| Status | `PARTIAL_COVERAGE` |
| Expected count | 23 |
| Provider-returned count | 3 |
| Normalized count | 3 |
| Persisted count | 3 |
| Missing count | 20 |
| Verified batch | none |
| Frozen batch | none |
| Persistence status | `COVERAGE_INCOMPLETE` |

The session's immutable coverage payload names the normalized symbols as:

```text
COALINDIA, NTPC, WIPRO
```

The matching persisted `preopen_snapshots` rows under the authoritative batch
also contain exactly those three symbols.

## Why earlier reports differed

Two earlier static reports stated that the three persisted symbols were:

```text
COALINDIA, GAIL, NTPC
```

That is not consistent with the immutable production session row, the
collection-coverage JSON, or the persisted snapshot rows, all of which identify
`WIPRO` rather than `GAIL`.

The historical `preopen_collection_outcomes` table did not exist at the time of
the failed session, and the session did not retain the raw provider request,
raw provider row set, or per-symbol normalization evidence. Therefore, this
audit does **not** claim to reconstruct raw provider behavior.

It does establish the narrower, durable truth:

1. The historical batch was incomplete and uncertified.
2. The immutable persisted result was `COALINDIA`, `NTPC`, and `WIPRO`.
3. `GAIL` was expected but appears in the historical coverage payload's missing
   symbol set.
4. The conflicting `GAIL` narrative is a stale documentation/reporting error,
   not a reason to mutate the historical database evidence.

## Historical evidence status

| Claim | Result |
|---|---|
| The active universe contained 23 expected symbols | Proven |
| Three symbols were normalized and persisted | Proven |
| The exact three persisted symbols are known | Proven: `COALINDIA`, `NTPC`, `WIPRO` |
| Raw provider response set can be reconstructed | Not proven |
| Per-symbol omission versus normalization failure can be reconstructed | Not proven |
| Historical batch was certified or frozen | False — neither batch pointer exists |

## Preservation statement

The August 26 session remains incomplete historical evidence. It is not a
valid certification record and must not be retried, replayed, backfilled,
rewritten, or relabeled as certified.