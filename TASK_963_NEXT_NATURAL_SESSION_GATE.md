# Task 963 Next Natural Session Gate

## Eligible session

The next eligible NSE session after 31 August 2026 is 1 September 2026, subject to the authoritative NSE trading calendar.

## Before 08:43 IST

- Confirm the published build equals the approved Task 964 commit.
- Confirm revision 3/version 1 remains active with 23 members and the approved hash.
- Confirm no replacement session pin or manual pre-open evidence was manufactured.

## Natural observation windows

- 08:43–08:51: durable `init`
- 08:53–09:00: durable `readiness`
- 09:00–09:12: naturally scheduled collections
- 09:08–09:12: eligible final-proof batch
- 09:15–09:18: freeze
- 09:18–09:23: reconciliation

## Pass conditions

- One immutable current-session pin resolves revision 3/version 1.
- Phase 5A expected set is exactly 23 symbols with the approved hash.
- Provider outcomes account for 23/23 symbols.
- Verified and frozen batch IDs match.
- Final proof was captured naturally in the approved window.
- No scan, scheduler, or readiness status reports `revision_not_found`.
- No manual run, retry, replay, backfill, or fallback evidence is used.

The 31 August Task 930 failure remains immutable regardless of the next session's result.