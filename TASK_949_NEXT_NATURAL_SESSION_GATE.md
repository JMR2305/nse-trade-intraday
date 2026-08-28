# Task 949 — Next Natural Session Gate

## Current status

The clean release is ready for controlled publish, but no deployment has been performed by release preparation.

The 28 August 2026 session must not be used as certification evidence.

## Mandatory entry gate

Before any future natural pre-open certification:

1. Publish only `68f18b078fe9de37da175480d40d4d42ae727830`.
2. Confirm production reports `apexquant-68f18b078fe9`.
3. Confirm the deployment ID is present.
4. Confirm the Task 947 timing/freeze source and Task 938 cache-race source are present.
5. Confirm the active custom universe remains 23 symbols with 23/23 mappings.
6. Confirm automatic entries and bootstrap remain false.
7. Confirm controlled execution and live broker orders remain disabled.
8. Confirm portfolio and ledger state are unchanged.

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

PRE-PUBLISH PASS — clean release and test gates are complete.

Final verdict `A. PASS — CLEAN RELEASE DEPLOYED, NEXT NATURAL SESSION READY` is permitted only after the post-publish read-only identity and safety checks pass. Identity failure maps to verdict E; any safety-state regression maps to verdict F.