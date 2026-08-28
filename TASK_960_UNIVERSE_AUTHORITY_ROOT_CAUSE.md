# Task 960 — Universe Authority Root Cause

## Root cause

`ROOT_CAUSE = Task #946 deployed the additive versioned-universe schema and a
one-shot baseline seed command, but no startup hook, deployment migration, or
authenticated operator route invoked the custom baseline import in production.`

The production `custom_universe_master` remained populated with the approved
23 active symbols, while `trading_universes` had no
`CUSTOM_LOW_PRICE_SECTOR` revision. Once runtime consumers were changed to
require immutable versioned authority, they correctly failed closed with
`revision_not_found` and `UNIVERSE_UNAVAILABLE`.

## Authority inventory

- Mutable source authority: `custom_universe_master`
- Durable destination: `trading_universes` and `trading_universe_members`
- Runtime resolver: immutable ACTIVE revision through `runtime_universe`
- Production state observed before this task:
  - 23 active custom-master rows
  - zero custom revisions
  - zero active custom revisions
  - zero runtime session pins
  - zero OPEN or EXIT_PENDING positions

Historical scan snapshots and cached health payloads are observations only.
They are not accepted as migration authority.

## Remediation

Task 960 adds a deliberate authenticated migration:

- `GET /api/universe/v1/baseline-migration` — read-only readiness
- `POST /api/universe/v1/baseline-migration` — exact-confirmation execution

There is no startup auto-seed and no runtime fallback.
