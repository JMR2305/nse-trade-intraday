---
name: Python-managed schema parity
description: Prevent publish-time destructive diffs caused by runtime-only additions to Python-managed tables.
---

For Python-managed PostgreSQL tables, both the table itself and every durable
field must exist in the development schema before publication. Declare them in
the canonical `CREATE TABLE` definition before application use. Do not rely on
production-only runtime table creation or `ALTER TABLE ... ADD COLUMN`.

**Why:** Publishing compares the actual development and production schemas.
If production has runtime-created tables or columns that development never
received, the publish diff treats them as extra and proposes destructive
drops. Drizzle `tablesFilter` does not constrain Replit Publish's independent
development-versus-production comparison.

**How to apply:** Add new fields to the canonical table declaration, align the
development table with an additive-only change when necessary, verify the
publish schema diff is empty or additive, and include the Python-managed table
in the migration guard's protected registry. For established tables, add the
field with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` before creating an index
or query that references it. Never run schema DDL against production outside
the publish flow.