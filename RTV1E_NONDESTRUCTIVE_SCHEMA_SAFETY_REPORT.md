# RTV-1E Non-Destructive Schema Safety Report

**Status: SAFE TO APPROVE — schema diff only.**

This report authorizes no production operation by itself. Publishing, metadata
hydration, universe refresh, scans, orders, portfolio changes, ledger changes,
and safety-setting changes remain outside this remediation and require their
own approved control flow.

## Root cause

`custom_universe_master` is Python-managed and is not part of the Drizzle
managed-table schema. Its base `CREATE TABLE` definition omitted four
instrument-reference fields:

- `instrument_exchange`
- `instrument_tradingsymbol`
- `instrument_cache_date`
- `instrument_mapping_at`

Runtime code subsequently added those fields with `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS`. Production had executed that runtime path, while development
did not have the fields. The publishing service correctly compared the
development and production schemas and proposed dropping the four
production-only columns.

The source of truth now declares all four fields in the original table
definition, removes the runtime schema mutation, and marks the current master
and its membership history as protected from routine destructive migration
scripts.

## Corrected schema contract

| Field | Development | Production | Hydration behavior | Retain? |
|---|---|---|---|---|
| `instrument_token` | present, nullable bigint | present, nullable bigint | written by hydration and read in active metadata | Yes |
| `instrument_exchange` | present, nullable text | present, nullable text | written by hydration and returned in serialized metadata | Yes |
| `instrument_tradingsymbol` | present, nullable text | present, nullable text | written by hydration and returned in serialized metadata | Yes |
| `instrument_cache_date` | present, nullable date | present, nullable date | written by hydration and returned in serialized metadata | Yes |
| `instrument_mapping_at` | present, nullable timestamp with time zone | present, nullable timestamp with time zone | written by hydration and returned in serialized metadata | Yes |

The four non-token fields are the intended persistence fields for the
metadata-only hydration provenance and must not be dropped.

## Development-only alignment SQL

The following statement was applied to the development database only after
the canonical source definition was corrected:

```sql
ALTER TABLE public.custom_universe_master
  ADD COLUMN IF NOT EXISTS instrument_exchange TEXT,
  ADD COLUMN IF NOT EXISTS instrument_tradingsymbol TEXT,
  ADD COLUMN IF NOT EXISTS instrument_cache_date DATE,
  ADD COLUMN IF NOT EXISTS instrument_mapping_at TIMESTAMPTZ;
```

Classification: **SAFE ADDITIVE**. All four fields are nullable. This statement
does not remove, overwrite, backfill, reset, recreate, or otherwise change
existing data.

No SQL statement was run against production.

## Regenerated publishing migration

**NO DATABASE MIGRATION REQUIRED**

The platform schema-diff result after development alignment:

```text
hasDiff: false
statementsToExecute: []
columnsToRemove: []
tablesToRemove: []
tablesToTruncate: []
hasStructuralDataLoss: false
maybeNonBackwardsCompatible: false
```

Exact regenerated publishing SQL: **none**.

Statement review: there are no publish-time statements to classify; therefore
there are zero `SAFE ADDITIVE`, `SAFE INDEX`, `DATA BACKFILL`, or
`DESTRUCTIVE — NOT ALLOWED` statements in the regenerated plan.

## Read-only production verification

Production was queried read-only before and after the development-only change.
It remains unchanged:

| Check | Result |
|---|---|
| Total custom-universe rows | 26 |
| Active rows | 23 |
| Inactive rows | 3 |
| Active BANK rows | 9 |
| Active INFRA rows | 13 |
| Active IT rows | 1 |
| `instrument_token` non-null / null | 1 / 25 |
| `instrument_exchange` non-null / null | 0 / 26 |
| `instrument_tradingsymbol` non-null / null | 0 / 26 |
| `instrument_cache_date` non-null / null | 0 / 26 |
| `instrument_mapping_at` non-null / null | 0 / 26 |

The null counts are expected before the separately controlled, metadata-only
hydration action. No sample field values were exposed.

## Validation

- Custom-universe Python unit suite: 24 passed.
- Migration safety guard suite: 20 passed.
- API-server TypeScript typecheck: passed.
- API build: passed.
- API workflow restarted successfully.
- Read-only development checks for `/api/health/details` and
  `/api/universe/custom/status`: HTTP 200.
- No isolated preview-deployment control is available in this workspace; the
  restarted development API workflow was used for the required non-mutating
  preview check instead.

## Approval gate

No production data would be deleted by the regenerated schema plan because
the plan contains no production SQL. All 23 active custom-universe memberships
and their 9 BANK / 13 INFRA / 1 IT sector distribution remain unchanged.

The previous destructive migration is not approved. Only the regenerated
zero-statement schema plan is safe to approve. Any subsequent publishing or
RTV-1E production verification must stop again if runtime identity does not
match the approved source candidate.

## Instrument mapping refresh review — 2026-08-25 (read-only)

Production was queried with `SELECT` statements only. No cache refresh,
metadata hydration, membership refresh, scan, or order action was run.

| Check | Result |
|---|---:|
| Total custom-universe rows | 26 |
| Active rows | 23 |
| Inactive rows | 3 |
| Active BANK / INFRA / IT | 9 / 13 / 1 |
| Active rows with all instrument-reference fields | 23 / 23 |
| Mapping exchange | NSE for all active rows |
| Stored instrument cache date | 2026-08-23 for all active rows |
| Stored mapping timestamp | 2026-08-23T22:07:53.315696Z for all active rows |

The mappings are complete and their stored provenance is internally
consistent. They are nevertheless two calendar days old, while the instrument
cache has a one-day freshness policy. A metadata-only refresh is therefore
appropriate **only after an operator gives a separate, explicit approval**.

The approved control is intentionally separate from an instrument-cache
refresh and requires both the universe admin credential and the exact
confirmation `HYDRATE_INSTRUMENT_METADATA_ONLY`. It updates only
`instrument_exchange`, `instrument_tradingsymbol`, `instrument_token`,
`instrument_cache_date`, and `instrument_mapping_at` for existing active rows.
It does not update membership, active status, sector, selection criteria, or
the membership-history table. The 23-row active membership and 9 BANK / 13
INFRA / 1 IT split are therefore preserved by the metadata-only operation.