---
name: AI Operations Centre import pattern
description: How to call multiple Python agent snapshot functions in parallel without deadlocking on the import lock
---

# AI Operations Centre — parallel snapshot collection

## The rule
When collecting agent snapshots in parallel (ThreadPoolExecutor), threads must NEVER call `__import__()` or `importlib.import_module()`. Instead:
1. Call `_preload_modules()` in the **main thread** to populate `sys.modules`.
2. Use `_get_fn(mod, fn)` — a pure `sys.modules` dict lookup — inside thread workers.

## Why
Python's import lock is reentrant for the same thread but NOT across threads. When 12 threads simultaneously call `__import__("market_data_agent.shared_services", ...)`, some acquire the lock, others block indefinitely → 15-20s timeouts even though the underlying function completes in <4s.

`sys.modules[mod]` is a plain dict read — no lock, fully thread-safe.

## How to apply
- `ops_centre.py`: `_preload_modules()` lists every module → `_get_fn(mod, fn)()` in each `_collect_*`.
- Any future parallel Python aggregator must follow the same pattern.
- Sequential fallback is NOT a safe alternative: if any one agent is slow (market_data ~3s), 12 sequential calls exceed the 30s route timeout.

## Also: safe coercion helpers
Agent snapshot field shapes are inconsistent (int vs str vs list). Use `_i()`, `_f()`, `_lst()` wrappers throughout — never bare `int()`, `float()`, `list()` on untrusted agent data.
