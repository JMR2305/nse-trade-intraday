# Task #930 — Batch and Freeze Evidence

## Certification session

| Field | Observed value |
| --- | --- |
| Session ID | `preopen-2026-08-27-2396e6` |
| Trading date | `2026-08-27` |
| Required origin | `SCHEDULED` |
| Observed collection source | `SCHEDULED` |
| Provider | `NSE Official` |
| Provider scope | `ALL` |

## Earlier natural collection evidence

At 09:00:24 IST, the natural collection reported:

| Measure | Value |
| --- | ---: |
| Expected symbols | 23 |
| Provider-returned symbols | 23 |
| Normalized symbols | 23 |
| Persisted symbols | 23 |
| Live snapshots | 23 |
| Immutable outcomes accounted | 23 |
| Missing | 0 |
| Duplicate | 0 |
| Malformed | 0 |
| Unexpected | 0 |
| Failed | 0 |
| Persistence status | `MATCH` |

This showed a healthy collection point, but it was not itself a freeze
certificate.

## Final pre-freeze evidence

The final observed status at 09:14:49 IST was:

| Field | Value |
| --- | --- |
| Session status | `PARTIAL_COVERAGE` |
| Current collection batch ID | `collection-6bbe038e85644fb7a42a364966691b88` |
| Expected symbols | 23 |
| Provider-returned symbols | 23 |
| Normalized symbols | 23 |
| Persisted symbols | 23 |
| Durable valid symbols | 0 |
| Visible valid symbols | 0 |
| Stale symbols | 23 |
| Live snapshot count | 0 |
| Missing / duplicate / malformed / unexpected | 0 / 0 / 0 / 0 |
| Outcome accounting | 23 expected; 23 accounted; aggregate status `LIVE_PREOPEN_DATA: 23` |
| Persistence status | `COVERAGE_INCOMPLETE` |
| Retry state | `RETRY_REQUIRED` |
| Certified | `false` |
| Verified collection batch | `collection-867b53a6ab4b48a58ae02582c4861c7e` |
| Frozen collection batch | `null` |
| Freeze timestamp | `null` |
| Collection error | `Provider response did not cover the active pre-open universe` |

The snapshot observation immediately after the status capture showed a
subsequent current batch ID,
`collection-9119a23b4bf541838ae578db1cf6a7da`, whose 23 persisted snapshots
were all `STALE`. This reinforces—not repairs—the coverage failure. It must not
be confused with the prior verified batch.

## Freeze proof

The required equality was not established:

```text
frozen_collection_batch = null
verified_collection_batch = collection-867b53a6ab4b48a58ae02582c4861c7e
current failed collection batch != verified collection batch
```

Because fresh live coverage was absent, freeze was correctly withheld. No
manual freeze or downstream lifecycle action was attempted.