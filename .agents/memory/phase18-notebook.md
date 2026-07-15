---
name: Phase 18 notebook concurrency & guards
description: Durable lessons from the research-notebook state layer (JSON persistence, configurable targets)
---
- Every API route spawns a fresh Python process, so any read-modify-write of shared JSON state (notebook/issues/targets) must hold an exclusive fcntl flock for the whole cycle — atomic os.replace alone still loses updates.
  **Why:** architect review flagged lost-update corruption under concurrent requests.
  **How to apply:** decorate public mutator functions with the `_locked` wrapper in phase18_notebook.py; do the same for any future JSON-backed mutators.
- User-configurable numeric targets used as divisors must be validated (>=1) at write time AND guarded (<=0 → 0%) at read time; return `rejected` map instead of silently dropping bad values.
- Currency formatting of upstream values must be null-safe (fallback "Insufficient Data"), since portfolio payloads can be incomplete at finalize time.
