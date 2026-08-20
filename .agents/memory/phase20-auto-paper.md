---
name: Phase 20 auto paper trading
description: Safety and concurrency invariants for the automatic scan scheduler + paper-trade executor.
---

- **Auto paper entries default OFF.** Enabling requires the exact confirmation sentence stored in settings (`confirmation_text`); disabling clears `auto_paper_entries_confirmed_at`. `run_auto_entries` re-checks both flags (defence in depth).
  **Why:** research-only system; accidental automation is the top risk.
  **How to apply:** any new entry path must go through settings validation in phase20_store, never bypass it.
- **Exits never fabricate fills.** Stale/unavailable quotes → `EXIT_PENDING` (recorded, retried), never a simulated sell at a guessed price.
- **Trailing stop uses a persisted high-water mark** (kv `trail_peak:<trade_id>`): arm when peak ≥ fill+2R, exit when quote ≤ fill+1R. A single-quote condition is unreachable — regression tests cover arm/no-arm boundaries.
- **Concurrency:** partial unique index `phase20_open_symbol_uidx (symbol) WHERE status='OPEN'`; entries claim the ledger row BEFORE the buy and delete it if the buy fails. File fallback replicates the duplicate check.
- **Entry-time gates must re-check under the admission lock immediately before INSERT.**
  **Why:** a pre-lock market-window check can pass, then wait on a contended advisory lock until the entry cutoff has elapsed.
  **How to apply:** retain a preflight check only as a fast rejection; treat the post-lock, pre-commit check as authoritative for every automatic entry path.
- **Scheduler health enum is canonical end-to-end:** HEALTHY / DEGRADED (missed>0) / DOWN (silent >3 intervals) / UNKNOWN / DISABLED. Validation treats HEALTHY and DEGRADED as passing the scheduler check.
- Node ticks every 1 min; Python decides due-ness from durable settings (intervals 1/3/5/10/15m, NSE market hours only).
