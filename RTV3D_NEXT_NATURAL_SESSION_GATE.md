# RTV-3D — Next Natural NSE Session Gate

**Current status:** Deployment and read-only safety verification passed.  
**Task #920 status:** **READY for the next natural scheduled NSE session only.**

## No same-day validation

The current verification occurred after today’s natural Phase 5A window. Do
not manually trigger, simulate, retry, replay, or backfill Task #920 today.

The historical production pre-open status remains a 10-symbol record for
`preopen-2026-08-25-9b8340`; it is not evidence of a repaired next-session
collection. The original failed batch remains immutable evidence:

```text
collection-6073abbd096c44e7b4e4b51a205696ba
```

## Required next-session proof

During the next naturally scheduled NSE pre-open session, require one new
scheduled Phase 5A collection with:

```text
expected_symbol_count = 23
provider_collected_count = 23
persisted_count = 23
missing_count = 0
duplicate_count = 0
malformed_count = 0
unexpected_count = 0
failed_count = 0
persistence_status = MATCH
```

The persisted symbol set must equal exactly:

```text
BANKBARODA BANKINDIA CANBK COALINDIA FEDERALBNK GAIL HUDCO IDFCFIRSTB
IRCON IRFC KTKBANK MAHABANK MRPL NBCC NMDC NTPC PFC PNB RECLTD RVNL SAIL
UNIONBANK WIPRO
```

## Certification requirements

- origin must be `SCHEDULED`;
- active universe must remain `CUSTOM_LOW_PRICE_SECTOR`;
- provider selection must receive the exact 23-symbol set;
- no `DEFAULT_WATCHLIST` substitution may occur;
- coverage must be complete before verification or freeze;
- freeze must compare exact symbol identity, not count alone;
- downstream phases may proceed only after the complete persisted proof;
- observation GETs must remain side-effect free;
- automatic entries must remain disabled and unconfirmed;
- bootstrap must remain disabled;
- automatic exits must remain enabled;
- live broker orders must remain disabled;
- open and `EXIT_PENDING` positions must remain zero;
- six historical closed ledger rows and −₹278.74 realized P&L must remain
  preserved;
- canonical portfolio parity must remain intact.

## Prohibited actions

- no manual Phase 5A/5B/5C trigger;
- no manual scan, retry, replay, or simulated market data;
- no portfolio, ledger, capital, universe, strategy, or settings change;
- no broker order, manual login, token refresh, or credential creation;
- no modification of the original RTV‑3 failed session or batch evidence.

**Gate decision: WAIT until the next natural scheduled NSE session.**