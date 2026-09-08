# Task 960 — Next Natural Session Gate

## Session policy

The migrated revision is ACTIVE but its `effective_from` is set to the next
natural trading session boundary at 09:00 IST. It cannot be attached
retroactively to the current session.

The implementation computes the next trading day at execution time, skipping
non-trading days. The development dry-run on Friday, 28 August 2026 reported:

`scheduled_effective_from = 2026-08-31T03:30:00+00:00`

which is Monday, 31 August 2026 at 09:00 IST.

## Prohibited actions

- do not certify the current session;
- do not replay or backfill failed pre-open evidence;
- do not relabel prior Task #930 sessions;
- do not attach the new revision to an existing session pin;
- do not trigger a scan or Phase 5A to manufacture evidence.

## Next-session gate

At the next natural session, read-only verification must establish:

1. the runtime session pin references custom universe version 1;
2. symbol count is 23 and the exact-set hash matches;
3. scanner expected denominator is derived from that revision;
4. pre-open resolves the same revision without `UNIVERSE_UNAVAILABLE`;
5. readiness no longer reports `revision_not_found`;
6. all exposed consumers report the same universe ID, version, count, and hash.

Until the user publishes and authorizes migration, this gate remains pending.
