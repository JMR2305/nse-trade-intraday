# Task #930 — Versioned Universe Evidence

## Durable revision

The authenticated production authority endpoint returned:

- Universe key: `CUSTOM_LOW_PRICE_SECTOR`
- Durable universe ID: `3`
- Version: `1`
- Revision status: `ACTIVE`
- Effective from: `2026-08-31T03:30:00+00:00`
- Effective until: null
- Enabled symbol count: `23`
- Exact set hash:
  `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`
- Mapping coverage: `23/23`
- Mapping percent: `100`
- Unmapped symbols: none

The durable revision itself was present and matched the approved baseline.

## Runtime resolution failure

The natural runtime did not bind that revision to the pre-open session:

- Session universe ID: null
- Session universe version: null
- Session set hash: null
- Scheduler error:
  `Effective universe CUSTOM_LOW_PRICE_SECTOR is unavailable: revision_not_found`
- Scanner coverage warning:
  `Latest scan was produced by a different pinned universe version`

The failure is therefore not reported as a missing durable revision. It is a
runtime scanner/readiness resolution failure: the persisted revision existed,
but the natural session did not resolve and pin it.

## Exact approved set

Approved version-1 symbols:

1. BANKBARODA
2. BANKINDIA
3. CANBK
4. FEDERALBNK
5. IDFCFIRSTB
6. KTKBANK
7. MAHABANK
8. PNB
9. UNIONBANK
10. COALINDIA
11. GAIL
12. HUDCO
13. IRCON
14. IRFC
15. MRPL
16. NBCC
17. NMDC
18. NTPC
19. PFC
20. RECLTD
21. RVNL
22. SAIL
23. WIPRO

No universe mutation or alternative revision activation was performed.
