# Task 964 Non-Destructive Schema Reconciliation

## Final verdict

**A. PASS — DESTRUCTIVE MIGRATION REMOVED, PRODUCTION AUTHORITY DATA PRESERVED, SAFE RELEASE READY**

Publishing remains subject to explicit user approval and inspection of the regenerated Publish SQL.

## Destructive migration status

The reported migration containing:

```sql
DROP TABLE "trading_universe_validations" CASCADE;
DROP TABLE "trading_universe_baseline_migrations" CASCADE;
DROP TABLE "trading_universe_member_details" CASCADE;
```

was not executed. Read-only production queries confirm all three tables and their rows remain present.

## Exact root cause

The three tables are created and consumed by Python universe-authority modules, not by the Drizzle schema. They existed in production after the guarded baseline-authority workflow but were absent from development.

Replit Publish independently compares the actual development and production databases. It therefore interpreted these production-only tables as deletions. Drizzle's `tablesFilter` protects Drizzle operations only and cannot constrain the Publish database comparison.

The local protected-table registry also omitted these three tables and the session-pin table, so the repository's own migration guard did not fully represent the authority boundary.

This drift was not required by the Task 963/964 runtime scheduler or effective-time fix.

## Table ownership

| Table | Purpose and runtime consumer | Foreign keys | Indexes | Production rows | Required |
|---|---|---|---|---:|---|
| `trading_universe_member_details` | Immutable per-revision metadata joined by `universe_management` when reading revision members | `universe_id → trading_universes.id` | PK `(universe_id, symbol)` | 23 | Yes; not superseded |
| `trading_universe_validations` | Append-only activation/readiness validation evidence written and read by `universe_management` | `universe_id → trading_universes.id` | PK `id`; `(universe_id, checked_at DESC)` | 1 | Yes; not superseded |
| `trading_universe_baseline_migrations` | Immutable one-shot baseline migration evidence used by baseline verification/status | `destination_universe_id → trading_universes.id` | PK `id`; unique correlation ID; unique `(universe_key, destination_version)` | 1 | Yes; not superseded |

All three have append-only UPDATE/DELETE rejection triggers. Development and production now have exact parity for columns, defaults, indexes, and trigger identities.

## Production authority preservation proof

Read-only before/after checks produced the same values:

- Universe ID: `3`
- Universe key: `CUSTOM_LOW_PRICE_SECTOR`
- Version: `1`
- Status: `ACTIVE`
- Effective from: `2026-08-31T03:30:00Z`
- Effective until: open
- Enabled members: `23`
- Mapped NSE members with instrument tokens: `23/23`
- Exact-set hash: `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`
- Baseline migration audits: `1` (PK 1)
- Validation records: `1` (PK 1)
- Member detail records: `23`
- Open or exit-pending Phase 20 ledger rows: `0`
- Phase 20 settings fingerprint: unchanged at `ef0b27cb270eadd2f8d3bd6db868deff`

No production DDL or DML was executed.

## Corrected migration

Complete reviewed SQL:

- File: `lib/db/migrations/0002_universe_authority_schema_parity.sql`
- SHA-256: `7f3e6fa19f6acf1613011b00ee63d4f4b52b5643afa0fdc20bc5cee0e1bc02fd`

The migration is self-contained for a fresh database. It establishes the full
eight-table authority dependency chain in order, then reconciles the three
production evidence tables. The SQL contains only:

- `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX IF NOT EXISTS`
- Create-only trigger-function bootstrap when the function is absent
- Trigger identity checks that fail closed
- Trigger creation only when the exact trigger is absent

It contains no executable `DROP`, `TRUNCATE`, `DELETE`, destructive `CASCADE`, `ALTER`, or `CREATE OR REPLACE`.

The development-only migration was dry-run, classified with `DATA-LOSS RISK: no`, applied, and then shown to produce exact catalog parity. Because production already has the exact structures, the corrected production Publish SQL for these three tables must be empty.

## Protection added

The migration guard now protects:

- `runtime_universe_session_pins`
- `trading_universe_audit_events`
- `trading_universe_baseline_migrations`
- `trading_universe_member_details`
- `trading_universe_members`
- `trading_universe_sources`
- `trading_universe_validations`
- `trading_universes`

For each table, automated checks require DROP, TRUNCATE, DELETE, and DROP COLUMN to classify as destructive and protected.

## Test gate

- Migration guard and exact clean-schema catalog parity: 56 passed
- Isolated Python universe/pre-open/Phase 20/Kite/market-data/portfolio/ledger files: 54 files, 1,332 passed
- API Vitest: 20 files, 169 passed
- TypeScript workspace checks: passed
- Python compilation: passed
- API production build: passed
- Dashboard production build: passed with existing non-fatal chunk/sourcemap warnings
- Development/production column parity: passed
- Development/production index parity: passed
- Development/production trigger parity: passed
- Independent architecture and data-safety review: passed

## Publish gate

Before approval, the Publish UI must regenerate the SQL diff from the reconciled development schema.

Required result:

```sql
-- No SQL statements affecting:
-- trading_universe_member_details
-- trading_universe_validations
-- trading_universe_baseline_migrations
-- runtime_universe_session_pins
-- or any other universe authority table.
```

If any DROP, TRUNCATE, DELETE, destructive ALTER, or CASCADE statement remains for those tables, cancel publishing.