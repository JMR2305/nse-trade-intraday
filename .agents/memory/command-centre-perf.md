---
name: Command Centre performance & cold-start fix
description: Why the Unified Command Centre showed an error on mobile after deploy, and how it was fixed.
---

## The problem
`get_summary()` in `command_center/shared_services.py` loaded 13 sub-snapshots **sequentially**.
Each loader does I/O (DB reads, JSON file reads). Total wall time: ~19s in dev, ~12–14s in prod.

On cold-start (first request after server restart), the Python process occasionally failed before
completing all 13 loads, returning `{"error": "...", "trace": "..."}` from main.py's top-level
exception handler. `apiJson` in the frontend throws on any response with an `error` key (line 117
of `lib/api.ts`), making React Query enter error state — showing the "Failed to load" banner.

## The fix (two parts)

### Backend — `command_center/shared_services.py`
1. Added `_SUMMARY_MODULES` list and `_preload_summary_modules()` which imports all 13 modules
   in the **main thread** before any threads are started (avoids import-lock contention).
2. Rewrote `get_summary()` to run all 13 `_load_*()` calls concurrently via `ThreadPoolExecutor`
   with `max_workers=13` and a 15s per-loader timeout.
3. Result: cold-start ~10s (was 19s); subsequent calls stay ~10s (I/O-bound, not CPU).

### Frontend — `CommandCenter.tsx`
1. Changed `retry: 1` → `retry: 3` with exponential backoff (`retryDelay`) so transient cold-start
   failures auto-recover without user action.
2. Error state now shows a helpful message ("API may still be warming up, usually resolves in 10–20s")
   plus a **Retry** button (calls `window.location.reload()`).

**Why:**
The pattern follows `ops_centre.py` — pre-load modules in main thread, then parallelise I/O workers.
See `[AI Ops Centre import pattern](ops-centre-import-pattern.md)` for the general rule.
