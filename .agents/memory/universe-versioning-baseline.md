---
name: Versioned universe baseline imports
description: Safety rules for importing the existing custom master into immutable versioned revisions.
---

Baseline imports must lock the current master during the transaction, normalize
the enabled set, verify the persisted member set/count/hash before commit, and
make repeat imports idempotent under a transaction advisory lock.

**Why:** A simple select-then-insert can race a current-master refresh or
another seed process, producing a partial revision or a duplicate-key error
instead of a safe idempotent outcome.

**How to apply:** Treat descriptive legacy gaps such as a missing company name
as provenance, not a reason to fabricate or drop an approved symbol. Require
resolver-critical identity fields and reject malformed symbols, incomplete
provider identifiers, duplicate normalized symbols, and duplicate enabled
tokens. Read resolvers must not run schema DDL and must fail closed if members,
count, or exact-set hash drift.