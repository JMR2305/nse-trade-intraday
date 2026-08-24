---
name: Python-managed schema parity
description: Prevent publish-time destructive diffs caused by runtime-only additions to Python-managed tables.
---

For Python-managed PostgreSQL tables, every durable field must be declared in
the canonical `CREATE TABLE` definition before it is used by application code.
Do not rely on a production-only runtime `ALTER TABLE ... ADD COLUMN` path to
introduce a field.

**Why:** Publishing compares the actual development and production schemas.
If production has runtime-added columns that development never received, the
publish diff treats them as extra and proposes destructive drops.

**How to apply:** Add new fields to the canonical table declaration, align the
development table with an additive-only change when necessary, verify the
publish schema diff is empty or additive, and include the Python-managed table
in the migration guard's protected registry. For established tables, add the
field with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` before creating an index
or query that references it. Never run schema DDL against production outside
the publish flow.