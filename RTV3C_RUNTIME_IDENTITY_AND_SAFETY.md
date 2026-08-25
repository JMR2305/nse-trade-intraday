# RTV-3C — Runtime Identity and Safety

**Status:** Pre-deployment baseline only  
**Reason:** The clean candidate failed the required test gate, so no candidate
was committed or deployed.

## Current production identity

The live production endpoint was read without mutation:

| Field | Value |
| --- | --- |
| Environment | `production` |
| Git commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Build ID | `apexquant-2e54e5e2f23f` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime timestamp | `2026-08-25T04:12:39.564Z` |
| Identity endpoint | HTTP 200 |

No post-deployment identity gate exists because no deployment occurred.

## Read-only baseline observations

The production health response reported:

- active universe: `CUSTOM_LOW_PRICE_SECTOR`;
- active count: `23`;
- valid token count: `23/23`;
- missing token count: `0`;
- latest scheduled scan symbol count: `23`;
- token stored: `true`;
- token expired: `false`;
- current Kite connection flag: `false`;
- current-session Kite quote freshness: not proven.

The existing RTV‑3 records remain the source of the previously verified
settings and portfolio baseline: automatic entries disabled, confirmation
absent, bootstrap disabled, automatic exits enabled, paper-only execution,
live broker orders disabled, zero open positions, zero `EXIT_PENDING` rows, six
historical closed ledger rows, and realized P&L of −₹278.74. These values were
not mutated or re-certified during the blocked release attempt.

## Historical evidence preservation

The failed RTV‑3 session and collection batch remain untouched:

```text
session = preopen-2026-08-25-9b8340
batch   = collection-6073abbd096c44e7b4e4b51a205696ba
```

The preserved evidence hashes observed before the clean-branch work were:

- `RTV3_NATURAL_SESSION_CERTIFICATION.md`
  - `8339f6a48a4f2eac2f172868e35759511ed66f060ddd956dfff931019999f7cf`
- `RTV3_PREOPEN_BATCH_EVIDENCE.csv`
  - `c7e06a59cacd17b0b552365e753948db0b2bdecbab6df4d5fbccfb29fb699270`

No replay, update, normalization, replacement, deletion, lifecycle trigger,
scan, retry, login, credential creation, or broker operation was performed.