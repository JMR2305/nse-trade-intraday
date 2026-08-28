# Task 960 — Versioned Universe Migration Report

## Implemented migration

The guarded operation creates exactly one immutable baseline:

- universe key: `CUSTOM_LOW_PRICE_SECTOR`
- version: `1`
- status after atomic transition: `ACTIVE`
- enabled members: `23`
- exact-set hash:
  `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`
- source authority: `custom_universe_master`
- effective policy: next natural trading session at 09:00 IST

Source, revision, members, member details, validation evidence, ACTIVE
transition, and migration audit are committed in one transaction.

## Concurrency and safety

- An advisory transaction lock serializes migration attempts.
- `custom_universe_master` is table-locked against concurrent membership writes.
- `phase20_paper_trades` is table-locked against concurrent OPEN or
  EXIT_PENDING ledger writes.
- The Phase 20 settings row is locked and its full digest is compared before
  commit.
- Any exception while inspecting controlled-entry flags blocks migration.
- No scan, pre-open collection, replay, backfill, portfolio, ledger, or
  settings mutation is performed.

## Audit

The migration records an immutable `BASELINE_MIGRATION` row in the dedicated
append-only `trading_universe_baseline_migrations` table. This avoids weakening
or rewriting the existing audit-action check constraint.

The audit includes actor, timestamp, source authority, destination revision,
count, hash, mapping completeness, configured universe key, reason, correlation
ID, and safety evidence.

`REASON = MIGRATE_EXISTING_PRODUCTION_BASELINE_TO_VERSIONED_AUTHORITY`

## Idempotency

A repeated request returns `ALREADY_MIGRATED` only when all of these hold:

- exactly one custom revision exists;
- it is ACTIVE version 1;
- count and hash are exact;
- all 23 persisted members and unique mappings are exact;
- its effective interval is runtime-usable;
- its immutable migration audit exists.

Any partial, conflicting, expired, or malformed revision fails closed as
`conflicting_revision`.

## Production mutation status

`NOT EXECUTED`

Production mutation is intentionally deferred until the reviewed code is
published and the authenticated operator submits the exact confirmation:

`MIGRATE CUSTOM_LOW_PRICE_SECTOR BASELINE 23`
