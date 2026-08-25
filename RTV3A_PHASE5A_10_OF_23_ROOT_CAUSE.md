# RTV-3A — Phase 5A 10-of-23 Root Cause

**Date:** 2026-08-25 (Asia/Kolkata)  
**Scope:** Source analysis and development-only repair validation  
**Production posture:** Read-only; the failed production session and batch remain unchanged.

## Immutable production evidence

The preserved scheduled production session was:

- Session: `preopen-2026-08-25-9b8340`
- Batch: `collection-6073abbd096c44e7b4e4b51a205696ba`
- Source: `SCHEDULED`
- Provider: `NSE Official`, status `LIVE`
- Durable recorded counts: provider `10`, persisted `10`, failed `0`
- Authoritative active universe: `CUSTOM_LOW_PRICE_SECTOR`, `23` active symbols

The original `MATCH` value proved only that every one of the ten supplied rows
persisted. It did not prove that the provider had been asked for, returned, or
persisted the required active universe.

## Exact set reconstruction

The authoritative custom set contains 23 symbols. The immutable batch contains
these ten legacy default-watchlist symbols:

`BAJFINANCE`, `HDFCBANK`, `ICICIBANK`, `INFY`, `LT`, `MARUTI`, `RELIANCE`,
`SBIN`, `TCS`, `WIPRO`.

The headline numerical shortfall is **13** (`23 required - 10 persisted`).
However, identity comparison is stricter and exposes the underlying defect:

- Only `WIPRO` is shared by the custom universe and the collected batch.
- **22** required custom symbols have no collected row.
- **9** persisted rows are outside the active custom universe.

Therefore “missing 13” is a count shortfall, not an exact symbol-set
reconciliation. The exact per-symbol evidence is in
`RTV3A_SYMBOL_COVERAGE_MATRIX.csv`.

## First 23-to-10 transition

The active custom universe and all 23 Kite mappings were healthy before Phase
5A. The first narrowing happened before the provider request:

1. Scheduled collection called the Phase 5A engine without an explicit symbol
   list.
2. Provider selection received no symbols and defaulted to the ten-item
   `DEFAULT_WATCHLIST`.
3. The NSE provider filtered its otherwise broader response by that supplied
   ten-symbol list.
4. Persistence truthfully stored the same ten rows and reported 10/10 parity.
5. The old persistence proof had no expected-universe denominator, so it
   incorrectly marked the ten-row collection `MATCH`.

There is no evidence of NSE pagination, a top-ten provider response, custom
symbol alias failure, or a Kite mapping failure. The NSE endpoint response is
loaded into an in-memory symbol map and the provider iterates the requested
symbol list; the truncation occurred upstream in provider construction.

## Secondary cache risk

Provider instances retain their requested symbol list. The previous cache was
keyed only by time, so a provider built by an earlier default-watchlist health
check could have been reused for a later custom-universe collection. This was
an independent path for the same 10-symbol behavior.

## Corrective outcome

The repair now:

- resolves the active custom universe before health, status, and collection
  provider selection;
- fails closed if durable universe settings or custom membership are empty,
  malformed, or unavailable; environment defaults are not authority during a
  settings outage;
- keys provider reuse by the normalized requested symbol set;
- records expected, returned, normalized, missing, duplicate, malformed,
  unexpected, and per-symbol coverage facts from the exact serialized rows
  that will be stored; and
- accepts `MATCH` only when one exact, normalized, durable row exists for every
  expected symbol, with no missing, duplicate, malformed, or unexpected rows.

A partial collection is retained as truthful evidence where applicable, marked
`COVERAGE_INCOMPLETE`, retryable, and denied a verified-batch pointer. It
cannot freeze, reconcile, enrich, or certify a natural session.
Freeze independently confirms that the immutable batch's normalized persisted
symbol set is exactly the durable expected symbol set, not merely the same size.

## Safety boundary

No manual retry, scan, lifecycle trigger, production settings change, broker
operation, portfolio/ledger write, universe change, or deployment was performed
for this diagnosis or repair. The next valid certification input remains a
future naturally scheduled NSE session.