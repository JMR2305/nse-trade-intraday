---
name: Portfolio snapshot restart recovery
description: Rules for the Postgres-backed portfolio snapshot repo and bridge recovery ordering
---

# Portfolio snapshot restart recovery

- The snapshot endpoint's primary source is PortfolioService (via portfolio_bridge); aggregates (cash/invested/unrealised) must come from the SAME service snapshot as the positions — never mix service positions with canonical/legacy accounting.
- A valid EMPTY service book is authoritative: fall back to canonical/legacy only when the service call *raises*, never when it returns zero positions.
- **Attach the snapshot repo to the service only AFTER startup seeding.** `initialise()` persists an empty v1 snapshot; with per-request processes those empty rows become the newest by timestamp and poison `get_latest_valid()` recovery. Bridge attaches the repo post-seed, then `persist_snapshot_if_changed()` (version-deduped) runs after every fill/mark.
- Bridge startup: canonical phase20 ledger is the authoritative seed; `recover()` from the persisted snapshot is used only when the canonical ledger is unreadable.
- Repo corrupt semantics: undecodable persisted rows are corruption candidates — when ALL rows for a portfolio are undecodable, `get_latest_valid()` must raise CorruptSnapshotError (so recovery alerts + rebuilds), not return None.
- Hermetic tests: `PORTFOLIO_SNAPSHOT_DB_DISABLED=1` (set in tests/unit/portfolio/conftest.py); DB integration tests lift it in setUp and restore in tearDown, using a unique portfolio_id with cleanup.
