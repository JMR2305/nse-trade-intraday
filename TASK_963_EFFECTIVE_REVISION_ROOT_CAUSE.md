# Task 963 Effective Revision Root Cause

## Verdict

The effective revision was not missing when the 31 August natural pre-open session failed. Production already held an immutable session pin for revision 3/version 1 before the failed phase window.

The first actionable failure was scheduler starvation:

1. The Node scheduler marked one whole tick in flight.
2. It awaited `scheduled_scan_tick` before launching Phase 5A/5B/5C.
3. The Python scan child had no bounded progress report and could run longer than a one-minute scheduler interval.
4. While that child remained open, later ticks returned immediately.
5. Time-gated pre-open phases were therefore suppressed even though durable universe authority was available.

The stale `revision_not_found` scanner status was an observed prior failure, not proof that revision 3 was absent at the time Phase 5A needed it.

## Production read-only evidence

- Revision: `id=3`, `version=1`, `status=ACTIVE`
- Effective from: `2026-08-31T03:30:00Z` (09:00 IST)
- Symbol count: `23`
- Exact-set hash: `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`
- Session pin created: `2026-08-31T02:55:12.015Z`
- Failed session: `preopen-2026-08-31-dee23c`
- Failed-session durable phases: `init` only
- No historical row was changed.

## Classification

`F. READINESS DEADLOCK` caused by scheduler orchestration, with stale scanner error reporting obscuring the available durable authority.