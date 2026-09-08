---
name: Phase 5A universe coverage
description: Safety contract for custom-universe pre-open collection and certification.
---

Phase 5A collection must prove exact expected-universe coverage, not merely
provider-to-persistence count parity. A durable settings read failure is
indeterminate and must fail closed; environment defaults cannot establish
authority because operators may have selected a different durable universe.

**Why:** A scheduled custom-universe session requested a legacy ten-symbol
watchlist and recorded 10/10 persistence parity despite requiring 23 symbols.
Equal counts did not prove the requested or persisted set was authoritative.

**How to apply:** Resolve the durable mode and membership before provider
selection; cache providers by requested set; derive coverage from canonical
serialized rows; and require the persisted symbol set to equal the durable
expected set before verification, freeze, reconciliation, or certification.
Never use a manual retry to repair failed natural-session evidence.