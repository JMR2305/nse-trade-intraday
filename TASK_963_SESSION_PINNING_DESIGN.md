# Task 963 Session Pinning Design

## Authority

`runtime_universe.resolve_active_universe()` remains the single runtime authority for scanners and Phase 5A collection.

The durable pin contains:

- Natural IST session date
- Universe key and immutable revision ID/version
- Exact normalized symbol set
- Exact symbol count
- Exact-set hash
- Effective-from timestamp
- Pin timestamp

## Invariants

- First claimant inserts once; conflicts load the existing row.
- Existing pins always win over later selector changes.
- Empty, count-mismatched, or hash-mismatched pins fail closed.
- Collection never falls back to a mutable watchlist.
- The scheduler fix does not create, update, replace, or retroactively attach a pin.

## Scheduler relationship

Session authority and scheduler progress are separate concerns. A scan child may remain legitimately active, but it no longer owns the Phase 5A/5B/5C scheduling lanes. Each advisory command has its own local single-flight guard and retains that guard until its child actually exits.