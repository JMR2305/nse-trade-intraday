---
name: Static architecture audit boundary
description: Constraints for using the repository architecture and lineage audit artifacts.
---

The root-level architecture, page-lineage, API, database, business-logic, and data-quality audit artifacts are static source inventories, not a representation of current production state.

**Why:** The audit intentionally made no database connections, broker calls, deployment checks, or workflow starts. Route declarations, code-defined tables, caches, and fallback paths can exist without being mounted, populated, reachable, or current in a running environment.

**How to apply:** Use the documents to locate and scope work, then prove any production claim with the appropriate live endpoint, workflow, deployment, or database evidence. Preserve `UNKNOWN` values in the inventories until source or runtime inspection establishes the missing lineage.