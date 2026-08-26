# Task 946 — Implementation Report

## Delivered

* Audited current authority and documented precedence, fallbacks, fixed
  denominators, and retirement path.
* Added additive PostgreSQL schema for universe sources, revisions, members,
  and append-only audit events.
* Added normalized symbol handling and deterministic exact-set hashing.
* Added atomic baseline import with before/after set verification, duplicate
  protection, and fail-closed malformed/incomplete input handling.
* Added internal resolution and revision comparison primitives.
* Added internal Python command hooks for schema setup, baseline import,
  resolution, and comparison; no HTTP management API was added.
* Added hermetic tests for schema safety, normalization, exact 23-symbol
  preservation, duplicate/malformed rejection, import atomicity, conflicting
  revision protection, and audit action validation.

## Baseline result

The baseline source is the active `custom_universe_master` membership for
`CUSTOM_LOW_PRICE_SECTOR`. It contains 23 enabled symbols. Three legacy rows
are missing only descriptive `company_name`; they retain complete membership
identity fields and are imported without fabricated names. Mapping fields are
preserved as observed; the current development rows have no Kite tokens, so
the imported revision reports `UNVERIFIED` mappings rather than claiming
23/23 coverage.

The development baseline is revision `1`, with exact-set hash
`22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`.
The second guarded seed returned `already_seeded: true`; resolving revision 1
returned the same 23 symbols and a version-1 self-diff had no changes.

After the additive schema bootstrap, direct development-database attempts to
update an audit event, member row, revision hash, or source provenance row were
all blocked by the database guards and rolled back.

## Explicitly unchanged

No active mode/settings, Task #930 evidence, portfolio, capital, paper ledger,
schedules, execution flags, scan, market-data refresh, historical table, or
runtime universe consumer was changed.