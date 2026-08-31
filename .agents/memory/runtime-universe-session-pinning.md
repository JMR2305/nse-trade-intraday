---
name: Runtime universe session pinning
description: Rules for resolving immutable scanner membership through an IST session.
---

Resolve the active universe once for each natural IST session against the 09:00 IST session boundary, then use the durable pin for all later work in that session. A readiness phase that runs before 09:00 must not permanently cache `revision_not_found` for a revision whose effective time is exactly 09:00; resolution must occur again at the collection boundary before the pin becomes final.

**Why:** A revision that becomes effective later in the day must not change the membership behind an in-flight collection, scan, decision, or entry record. Equal symbol counts are not proof of identity, so both the revision identity and exact-set hash matter. A natural session once initialized before the effective boundary, retained `revision_not_found`, and produced no 09:00 collection even though the durable revision became valid at 09:00.

**How to apply:** Runtime collection, canonical scans, coverage, and new decision/ledger provenance must consume the pinned envelope. Treat unavailable, malformed, ambiguous, or hash/count-mismatched authority as unavailable for new work; do not substitute a watchlist or static universe. Explicit symbol sets are test/replay overrides only. Test the pre-effective readiness → exact-boundary activation path separately from sessions whose revision was already effective at initialization.