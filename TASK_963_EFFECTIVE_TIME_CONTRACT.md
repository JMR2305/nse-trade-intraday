# Task 963 Effective-Time Contract

## Canonical rule

The first runtime resolver for an IST trading date selects the revision effective at that date's natural 09:00 IST boundary, not at process startup time and not at the caller's current wall-clock time.

For 31 August 2026:

- Natural boundary: `2026-08-31 09:00:00 IST`
- UTC boundary: `2026-08-31T03:30:00Z`
- Selected authority: revision 3/version 1
- Interval: open-ended from the boundary

## Deterministic proof

Tests cover calls at:

- `08:59:59 IST`
- `09:00:00 IST`
- `09:00:01 IST`

Every first claim resolves with `effective_at=09:00:00 IST`. Once a session pin exists, all three times return that immutable pin without consulting a later configuration change.

No revision interval, membership, hash, or stored activation record was changed by Task 964.