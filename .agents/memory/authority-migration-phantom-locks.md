---
name: Authority migration phantom locks
description: Concurrency rule for reconciling mutable authority into an immutable runtime revision.
---

An authority migration that asserts an exact mutable source set and zero open
positions must prevent phantom inserts/updates for both predicates through the
same transaction that publishes the immutable revision. Row locks on currently
matching rows are insufficient.

**Why:** A concurrent source refresh can add an active member, or a concurrent
ledger writer can create an OPEN row, after a predicate read but before commit.
The migration would otherwise audit evidence that was already false when the
new authority became visible.

**How to apply:** Hold table-level locks that conflict with source and ledger
writes (or use SERIALIZABLE isolation with retry) from the source/safety reads
through revision activation and audit commit. Keep runtime activation scheduled
at a natural session boundary rather than retroactively claiming a session.