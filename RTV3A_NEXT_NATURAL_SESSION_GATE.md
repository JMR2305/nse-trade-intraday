# RTV-3A — Next Natural Session Gate

## Purpose

This is the only permitted path to validate the Phase 5A coverage repair. It
requires a future naturally scheduled NSE pre-open session and does not
authorize any manual replay of the failed 2026-08-25 batch.

## Prohibited actions

Do not perform any of the following to obtain certification evidence:

- manual Phase 5A collection, refresh, scan, lifecycle trigger, or retry;
- simulated, mocked, cache-only, prior-session, or manually inserted quotes;
- universe/settings/threshold changes;
- automatic-entry enablement, bootstrap enablement, paper-order injection, or
  broker order placement;
- mutation of the failed session `preopen-2026-08-25-9b8340` or batch
  `collection-6073abbd096c44e7b4e4b51a205696ba`.

## Required Phase 5A evidence

For one future current-session row with source `SCHEDULED`:

| Requirement | Pass condition |
| --- | --- |
| Universe authority | `CUSTOM_LOW_PRICE_SECTOR`, exactly 23 active symbols and 23/23 valid mappings |
| Provider request | Durable coverage record lists exactly the 23 active symbols |
| Provider response | `provider_returned_count >= 23` and normalized symbols are exactly the expected 23 |
| No unusable rows | Missing, duplicate, malformed, and unexpected counts are all zero |
| Durable batch proof | `expected_count = provider_collected_count = persisted_count = 23`, `failed_count = 0`, `persistence_status = MATCH` |
| Identity proof | Exact batch contains 23 distinct snapshot IDs and 23 distinct expected symbols |
| Lifecycle gate | A verified batch pointer exists before freeze; freeze reads that same batch |
| Downstream integrity | Reconciliation/enrichment occur only after the durable frozen predecessor |
| Scan evidence | A new current-session canonical scan is `SCHEDULED`, has 23 symbols, and is not derived from a manual trigger |
| Safety state | Entries false/unconfirmed; bootstrap false; exits true; paper-only; live broker orders disabled |
| Portfolio parity | Canonical cash/equity/ledger parity remains intact with no unapproved orders |

## Fail conditions

Stop certification and preserve evidence if any count is null, differs from 23,
or if status is `COVERAGE_INCOMPLETE`, `NO_DATA`, `UNIVERSE_UNAVAILABLE`,
`PROVIDER_UNAVAILABLE`, `MISMATCH`, or persistence unavailable. A provider/
persisted parity such as 10/10 is explicitly a failure unless it also equals
the durable expected count and exact expected symbol set.

## Evidence to retain

Capture the session ID, immutable batch ID, source, provider status, all
coverage counts and symbol lists, phase-state transitions, freeze pointer,
canonical scan ID/origin/time, Kite quote provenance, settings safety state,
and portfolio/ledger parity. Record observations read-only and do not issue a
manual retry if the gate fails.