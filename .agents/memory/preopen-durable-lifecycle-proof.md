---
name: Pre-open durable lifecycle proof
description: Rules for treating a pre-open lifecycle phase as safely complete across restarts.
---

**Rule:** Phase 5A progress must be durable and retryable. Collection succeeds
only when the provider's batch count equals the committed snapshot count; freeze
must refuse incomplete collection evidence.

**Why:** Process-local phase state and swallowed persistence failures allowed an
interrupted session to look complete, especially across restart/autoscale
handoffs. A frozen watchlist without durable parity is not a valid market
artifact.

**How to apply:** Persist every phase outcome with a completed flag, recover it
on every tick, and mark a phase done only after its own success signal and
durable phase-state write. Require durable predecessor completion before any
downstream reconciliation. Scope frozen snapshots, watchlists, and
reconciliation writes to that same session ID—not the date—so retries cannot
mix evidence. Each retry needs an immutable batch ID; pin the verified count
proof and the frozen inputs to that exact batch, never newest-per-symbol across
the session. Keep no-data/provider/persistence outcomes distinct so scheduler
retries remain honest. Treat the phase-window endpoint as owned by the later
phase only when using end-exclusive intervals.