---
name: Simulation Lab design rules
description: Durable design rules for cross-run comparison and stress-test consistency proofs
---
- **Unlimited comparison rule:** any "compare N stored runs" feature must fetch requested runs directly by id (chunked ANY-query; full-file scan on fallback), never through a limited/paged history list, and the UI must let operators select runs beyond its history page (direct-ID add / load-more) and POST ids to the compare endpoint. **Why:** paged history windows silently cap comparison once history grows. **How to apply:** any cross-run comparison or bulk-fetch feature.
- **Consistency proofs must cover the whole store:** read-only "store untouched" checks need a deterministic fingerprint of the FULL store content (e.g. sha256 over canonically-serialized rows), not counts or a truncated id list; report unknown (null) rather than pass when the store can't be read. **Why:** partial fingerprints report false-green after out-of-window or same-id content mutations.
