# Task 960 — Production Authority Verification

## Current status

`PRODUCTION_MUTATION = NOT ATTEMPTED`

This is intentional. Task 960 requires a user-initiated publish followed by
explicit authenticated authorization. The development implementation must not
write to the separate production database.

## Pre-migration production evidence

- approved runtime commit:
  `68f18b078fe9de37da175480d40d4d42ae727830`
- expected build ID: `apexquant-68f18b078fe9`
- active custom-master rows: `23`
- valid NSE mappings and distinct positive tokens: `23`
- custom versioned revisions: `0`
- custom ACTIVE revisions: `0`
- runtime session pins: `0`
- OPEN positions: `0`
- EXIT_PENDING positions: `0`

## Required post-publish procedure

1. Verify the published commit/build identity.
2. Call authenticated read-only
   `GET /api/universe/v1/baseline-migration`.
3. Require exact count/hash, 23/23 current Kite mappings, zero positions, and
   the unchanged safety baseline.
4. Submit the exact confirmation once to
   `POST /api/universe/v1/baseline-migration`.
5. Perform read-only verification only.

## Required post-migration evidence

- ACTIVE revision present for `CUSTOM_LOW_PRICE_SECTOR`
- version `1`
- exact count `23`
- exact set and hash match
- mapping coverage `23/23`
- immutable `BASELINE_MIGRATION` audit present
- no portfolio, ledger, capital, or settings change
- next natural session resolves the same revision in scanner, pre-open,
  readiness, Mission Control, market-data coverage, strategy context, and
  execution eligibility

No scan or Phase 5A run is authorized by this report.

## Verdict

Production restoration verdict is pending publish and explicit migration.
Claiming **A — PASS** before those steps would fabricate production evidence.
