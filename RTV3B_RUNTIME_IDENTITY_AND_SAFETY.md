# RTV-3B — Runtime Identity and Safety

**Final status:** Not a post-deployment certification  
**Reason:** RTV‑3B stopped at the source-scope gate; no deployment occurred.

## Current production identity

Read-only `/api/health/details` observed the production runtime as:

| Field | Observed value |
| --- | --- |
| Environment | `production` |
| Git commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Build ID | `apexquant-2e54e5e2f23f` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime timestamp | `2026-08-25T04:12:39.564Z` |
| Service response | HTTP 200 |

This is the pre-Task #918 production build, not an approved RTV‑3B build.

## Read-only production observations

The same response reported:

- active universe: `CUSTOM_LOW_PRICE_SECTOR`;
- active universe count: `23`;
- valid token count: `23`;
- missing token count: `0`;
- symbols on Kite: `23`;
- symbols fallback: `0`;
- symbols synthetic: `0`;
- latest scan origin: `SCHEDULED`;
- latest scan symbol count: `23`;
- live broker execution mode: paper/research-only;
- Kite token stored: `true`;
- Kite token expired: `false`;
- current Kite connection flag: `false`;
- current-session quote freshness: not proven (`latest_quote_timestamp: null`).

The current connection flag is recorded exactly as observed. No manual login,
credential creation, token refresh, or broker action was attempted.

The existing RTV‑3 baseline remains the source of the previously verified
settings and portfolio facts, including automatic entries disabled, bootstrap
disabled, automatic exits enabled, paper-only execution, live broker orders
disabled, ₹100,000 capital, zero open/exit-pending positions, six closed
ledger rows, and realized P&L of −₹278.74. RTV‑3B did not mutate or revalidate
those records because the scope gate stopped the procedure.

## Preservation evidence

The preserved files remain present and were only hashed/read:

- `RTV3_NATURAL_SESSION_CERTIFICATION.md`
  - SHA-256: `8339f6a48a4f2eac2f172868e35759511ed66f060ddd956dfff931019999f7cf`
- `RTV3_PREOPEN_BATCH_EVIDENCE.csv`
  - SHA-256: `c7e06a59cacd17b0b552365e753948db0b2bdecbab6df4d5fbccfb29fb699270`

Preserved identifiers:

- session: `preopen-2026-08-25-9b8340`
- collection batch: `collection-6073abbd096c44e7b4e4b51a205696ba`

No replay, delete, update, normalization, replacement, scan, retry, lifecycle
trigger, portfolio reset, ledger modification, settings change, or publish was
performed.