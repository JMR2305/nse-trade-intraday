# Task 946 — Universe Versioning Design

## Scope and safety boundary

This release adds a PostgreSQL-backed, read-only resolution foundation and a
one-time baseline import. It does **not** switch any runtime consumer, add
management routes/UI, activate drafts, refresh market data, run scans, or
change trading settings. The currently selected runtime mode remains
untouched.

## Tables

* `trading_universe_sources` stores source table/reference, source snapshot,
  exact-set hash, importer, and JSON metadata.
* `trading_universes` stores one immutable membership snapshot per
  `(universe_key, version)`, lifecycle status, effective interval, provenance,
  exact-set hash, and enabled count.
* `trading_universe_members` stores one normalized symbol per revision,
  exchange/sector/token mapping metadata, enabled state, and removal metadata.
  Disabled historical rows are never physically deleted.
* `trading_universe_audit_events` is append-only and records actor, action,
  versions, symbol/change values, notes, correlation ID, and approval state.

The schema supports `DRAFT`, `PENDING_ACTIVATION`, `ACTIVE`, `SUPERSEDED`, and
`CANCELLED`. Version numbers are unique per universe. Symbols are normalized
uppercase and unique per revision. Enabled non-null instrument tokens have a
partial unique index per revision. PostgreSQL triggers enforce that sources,
members, and audit events cannot be updated or deleted; members can be added
only while their revision is `DRAFT`. Revision identity, hash, source, count,
and snapshot fields are immutable, while only lifecycle/effective-time approval
fields remain available for a future controlled activation flow.

## Baseline import

`seed_baseline()` reads active rows from the existing custom master, validates
the resolver-critical membership identity fields (symbol, sector, Yahoo symbol,
and Kite symbol), normalizes symbols, rejects duplicate symbols/tokens,
calculates SHA-256 over the sorted enabled set, inserts source, revision,
members, and a `BASELINE_IMPORTED` audit event in one transaction, then reads
the persisted enabled set back and requires exact equality before commit.
Descriptive `company_name` is retained where present but is intentionally not a
gate: three legacy approved rows lack it, and fabricating it or dropping those
members would corrupt the approved baseline.

The current rows have no instrument tokens. They are preserved as
`mapping_status = UNVERIFIED`, not falsely marked mapped. Future validation or
activation must require complete current Kite mappings and must not use Yahoo or
NSE as a mapping-validity fallback.

Repeated import is safe only when the existing revision hash **and** persisted
enabled member set both match. A conflicting or partial existing revision
fails closed without adding another revision.

## Read primitives

* `get_revision()` resolves by revision ID, version, current active status, or
  effective timestamp.
* `get_members()` returns complete or enabled-only historical member rows.
* `resolve_enabled_symbols()` returns the revision identity, exact enabled set,
  mapping coverage, count, and hash only after it rechecks normalized member
  order/set, stored enabled count, and stored exact-set hash; any drift fails
  closed.
* `compare_revisions()` returns added, removed, and unchanged normalized sets.
* `append_audit_event()` accepts only the allowlisted lifecycle actions and
  offers no update/delete operation.

These are internal primitives only and issue no schema DDL, so they work under
a read-only database role. Existing runtime consumers continue to use
their audited legacy paths until the downstream pinning/migration work is
explicitly implemented.

## Future lifecycle rules

Any add/remove operation must create a new draft revision. Activation must
revalidate every enabled member, require complete Kite mapping and provider
compatibility, require typed confirmation, and apply effective time at a
natural session boundary. The previous active revision is superseded only when
the new revision becomes effective. An open position remains manageable after
its symbol is removed; removal blocks only new entries after the effective
revision.

## Non-goals

No `DROP`, `TRUNCATE`, destructive replacement, historical rewrite, portfolio
mutation, ledger mutation, scan, Phase 5A/5B/5C trigger, or activation is part
of this foundation.