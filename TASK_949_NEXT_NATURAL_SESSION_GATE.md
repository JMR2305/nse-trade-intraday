# Task 949 — Next Natural Session Gate

## Current status

The clean release was published and its exact runtime identity was confirmed.

The 28 August 2026 session must not be used as certification evidence.

The next natural session is **not ready** because production has no active versioned universe revision. Scanner coverage fails with `revision_not_found`, and pre-open fails closed with `UNIVERSE_UNAVAILABLE`.

## Mandatory entry gate

Before any future natural pre-open certification:

1. Keep production on commit `68f18b078fe9de37da175480d40d4d42ae727830` / build `apexquant-68f18b078fe9`.
2. Restore the intended immutable versioned universe only through a separately reviewed and approved remediation.
3. Confirm the versioned universe API returns one active revision.
4. Confirm the active custom universe contains exactly 23 symbols with 23/23 mappings.
5. Confirm scanner coverage resolves the same exact set without `revision_not_found`.
6. Confirm pre-open no longer reports `UNIVERSE_UNAVAILABLE`.
7. Reconfirm automatic entries and bootstrap remain false.
8. Reconfirm controlled execution and live broker orders remain disabled.
9. Reconfirm portfolio and ledger state are unchanged.

If any check fails, stop. Do not collect, scan, freeze, trade, alter settings, or modify the universe.

## Natural-session rules

- Collection must be scheduler-originated.
- The final-proof batch must be captured naturally from 09:08 IST until, but not including, 09:12 IST.
- Every accepted row must be fresh at ingestion using the strict 300-second boundary.
- Coverage and mappings must match the exact active universe.
- Provider scope must remain `ALL`.
- The 09:15 IST freeze must reuse the exact approved batch.
- No manual refresh, manual collection, replacement batch, or manual freeze may count as certification evidence.

## Verdict state

`F. SAFETY REGRESSION`

Release identity passed, but the authoritative universe and pre-open readiness gates failed. Verdict A is prohibited until a later read-only verification confirms the remediated active revision, exact 23/23 coverage, and all unchanged execution-safety controls.