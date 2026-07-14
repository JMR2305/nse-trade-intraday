---
name: Evolution registry write safety
description: Rules for writing to the strategy evolution registry (drafts/mutations) from any module.
---
Rule: any code appending to the strategy-evolution registry must (1) take an exclusive flock on `<REGISTRY_PATH>.lock` around the read-modify-write, and (2) dedupe on (parent_id, mutation.parameter, mutation.to, status != Archived), returning the existing entry with `already_exists: true`.

**Why:** Concurrent POSTs lose updates and duplicate version numbers; an architect review flagged real duplicate test entries polluting the registry.

**How to apply:** Reuse the pattern in meta_learning.cmd_create_mutation. Tests must never write to the real registry — copy it to a temp dir and patch the module's REGISTRY_PATH, restoring it in a finally block.
