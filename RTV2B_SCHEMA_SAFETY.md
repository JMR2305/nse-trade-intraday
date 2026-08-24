# RTV-2B — Schema Safety

**Date:** 2026-08-24  
**Verdict:** **SAFE ADDITIVE SOURCE SQL; publish not authorized because of a
separate settings safety regression**

## Publish-time schema diff

The publish schema check reported:

```text
hasDiff: false
hasStructuralDataLoss: false
tablesToRemove: []
columnsToRemove: []
tablesToTruncate: []
statementsToExecute: []
warnings: []
```

No destructive publish-time schema operation was detected.

## Runtime-managed schema statements

The pre-open database initializer contains the following relevant statements.
They are classified for safety review only; no production SQL was manually
executed during RTV-2B.

### SAFE ADDITIVE

```sql
CREATE TABLE IF NOT EXISTS preopen_sessions (...);

ALTER TABLE preopen_sessions
    ADD COLUMN IF NOT EXISTS provider_collected_count INTEGER,
    ADD COLUMN IF NOT EXISTS persisted_count INTEGER,
    ADD COLUMN IF NOT EXISTS failed_count INTEGER,
    ADD COLUMN IF NOT EXISTS collection_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS collection_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS collection_source TEXT,
    ADD COLUMN IF NOT EXISTS persistence_status TEXT,
    ADD COLUMN IF NOT EXISTS verified_collection_batch_id TEXT,
    ADD COLUMN IF NOT EXISTS frozen_collection_batch_id TEXT,
    ADD COLUMN IF NOT EXISTS retry_state TEXT,
    ADD COLUMN IF NOT EXISTS phase_state JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS preopen_snapshots (...);

ALTER TABLE preopen_snapshots
    ADD COLUMN IF NOT EXISTS collection_batch_id TEXT;
```

### SAFE INDEX

```sql
CREATE INDEX IF NOT EXISTS idx_preopen_sessions_date
    ON preopen_sessions (trading_date DESC);

CREATE INDEX IF NOT EXISTS idx_preopen_snaps_date_sym
    ON preopen_snapshots (trading_date, symbol);

CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session
    ON preopen_snapshots (session_id);

CREATE INDEX IF NOT EXISTS idx_preopen_snaps_session_batch
    ON preopen_snapshots (session_id, collection_batch_id);
```

The additive snapshot-column upgrade is ordered before the dependent batch
index, preserving compatibility with an existing production table.

### DESTRUCTIVE — NOT ALLOWED

None found.

## Historical-data safety

No delete, truncate, rewrite, backfill, type conversion, or table recreation
was authorized or executed during this attempt. Production historical reads
were read-only. Publication was stopped before any schema or application
runtime change could occur.
