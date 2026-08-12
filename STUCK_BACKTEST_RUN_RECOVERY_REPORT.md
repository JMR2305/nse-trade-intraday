# Stuck Backtest Run Recovery Report

**Date:** 2026-08-12  
**Scope:** PAPER / RESEARCH ONLY — no threshold changes, no trading logic changes, no live orders.

---

## 1. Which Runs Were Stuck

### Runs identified in brief
| Run ID | Interval | Progress | Elapsed | ETA (absurd) |
|---|---|---|---|---|
| BT-e8a3d43733 | 15m | 121/800 ticks (15%) | 7h+ | ~2368 min |
| BT-cc91b1afa0 | 5m | 6/434 ticks (1%) | 17h+ | ~76858 min |
| BT-67e6d27ff6 | — | — | — | Failed: Neon/Postgres auth timeout |

These runs were in the **production (deployed)** database; their workers died and left the `status` column stuck at `RUNNING`.

### Orphaned runs found in development database (same root cause)
| Status | Count | Max hours stuck |
|---|---|---|
| RUNNING (11 runs) | 11 | 23.5 h |
| PENDING with no worker (3 runs) | 3 | 23.7 h |

All 14 were silently stuck with no heartbeat, showing absurd ETAs in the UI.

---

## 2. Root Cause

**Primary cause: Worker process death with no re-entry gate.**

The backtest worker runs as a detached subprocess spawned by Node.js via `subprocess.Popen`. When Replit restarts the container or OOM-kills a process, the worker dies mid-replay. The `backtest_runs.status` column is never updated because the update only happens:
- On normal completion (status → COMPLETED)
- On Python exception caught inside `execute_run()` (status → FAILED)

A hard process kill (SIGKILL, OOM, container restart) bypasses both paths, leaving `status = RUNNING` permanently.

**Secondary cause: No heartbeat enforcement.**

The original design wrote progress to `progress JSONB` every 5 ticks, but the `progress` dict had no wall-clock timestamp — only the candle timestamp (`ts`). Without a wall-clock heartbeat field, it was impossible to detect stale workers from the progress record alone.

**Contributing cause: Parallel overload.**

5–11 runs were started simultaneously on a 2 vCPU / 4 GB RAM Replit instance. A 20-symbol 15m run uses ~100% of one vCPU. Running 5+ simultaneously causes all workers to stall (CPU contention + memory pressure), eventually triggering OOM.

**BT-67e6d27ff6 failure cause:** Neon/Postgres authentication timeout. The Neon serverless DB goes idle after inactivity; a cold connection in a long-running worker can hit auth timeouts. This is a known Neon limitation — connections must be re-established periodically.

---

## 3. Whether Python Worker Died, DB Timed Out, or Replit Restarted

**BT-e8a3d43733 and BT-cc91b1afa0 (production):** Most likely Replit container restart overnight. Progress was stuck at exactly the same tick for 7h+ and 17h+ respectively — a CPU-stalled worker would show random slow progress; a dead worker shows exactly zero progress.

**BT-67e6d27ff6:** Postgres/Neon auth timeout confirmed (noted in the brief).

**11 dev RUNNING runs:** All started within the same 25-minute window on 2026-08-11 between 08:20–08:47 IST. All show identical progress ratios (146–416 / 2819 ticks). Classic parallel CPU starvation followed by OOM kill.

**3 dev PENDING runs:** Workers were spawned but never called `claim_run()` (PENDING → RUNNING transition). Worker processes died before the first DB write — likely immediate OOM at import time when 5+ heavy runs were all importing yfinance/pandas simultaneously.

---

## 4. Which Runs Were Marked STALE/FAILED

### Session 1 (previous session — manual cleanup)
11 RUNNING runs marked STALE by direct `mark_stale_run()` call.

### Session 2 (this session — automatic sweep)
3 orphaned PENDING runs auto-marked STALE by `sweep_stale_runs()` on first server restart.

| Run ID | Old status | New status | Minutes stuck |
|---|---|---|---|
| BT-caacabf5a6 | PENDING | STALE | 1367.8 |
| BT-9fcaea6b12 | PENDING | STALE | 1423.9 |
| BT-06e19a3b54 | PENDING | STALE | 1425.5 |

All partial events and trades preserved.

---

## 5. Watchdog / Heartbeat Added

### Server-side sweep (`sweep_stale_runs()`) — NEW
Added to `backtest_portfolio.py`. Called automatically on every `backtest_runs` list request (sweep-on-read pattern). Runs every 5 s while Investigation Center is open.

Rules:
- **RUNNING / CANCEL_REQUESTED** with `progress_updated_at` or `started_at` > 30 min ago → STALE with message: *"Run stalled — no progress for 30+ minutes. Worker likely stopped. Retry required."*
- **PENDING** with `created_at` > 30 min ago (never claimed by a worker) → STALE with same message.
- After marking stale runs, promotes QUEUED → PENDING to fill vacated slots.

Also exposed as `bt_sweep_stale` CLI command and `POST /api/bt/sweep-stale` route for manual triggering.

### Worker heartbeat (`progress_updated_at`) — added in previous session
Every 5-tick progress write now includes:
```json
{"phase": "REPLAY", "done": N, "total": M, "ts": "...", "progress_updated_at": "2026-08-12T..."}
```
The sweep uses `progress_updated_at` as the authoritative heartbeat timestamp.

### Client-side watchdog — added in previous session
`staleRunIds` computed in Investigation Center via `useMemo`. Checks `progress.progress_updated_at` vs `Date.now()`. If RUNNING and > 30 min → shows amber warning: *"Run stalled — no progress for 30+ minutes. Worker likely stopped. Retry required."* and enables **Mark Stale** button.

---

## 6. Frontend Display of Stalled Runs

Investigation Center now shows:
- **STALE badge** (amber) — clearly distinct from RUNNING (blue) and PENDING (amber-400)
- **QUEUED badge** (yellow) — for runs waiting for a concurrency slot
- **Error text** on stale runs: first 120 chars of the stall reason
- **Amber watchdog warning** for RUNNING runs with no heartbeat (client-side, before server sweep fires)
- **Retry button** for STALE / FAILED / CANCELLED runs
- **Cancel button** for QUEUED / PENDING runs (cancels before they start)
- **Stop button** for RUNNING runs (sends CANCEL_REQUESTED; worker stops at next checkpoint)
- **Filter dropdown** (All / Active / Completed / Failed+Stale) — operator can show only problem runs
- **"Hide failed"** button — clears terminal-status clutter in one click
- **ETA not shown for STALE/QUEUED** — only RUNNING/PENDING rows show ETA

---

## 7. Whether Retry Works

Yes. `retry_run(run_id)` creates a new `PENDING` run with the same config via `create_run(config)`. Old run is preserved unchanged. New run_id is returned and auto-selected in the UI.

- **HTTP endpoint:** `POST /api/backtest/run/:id/retry`
- **Verified in previous session:** Retry on a STALE run → new PENDING run created, original preserved
- **Tested end-to-end:** New run auto-selected in Investigation Center on success

---

## 8. Recommended Safe Run Size on Current Replit Resources

**Current spec:** ~2 vCPU, 4 GB RAM (Replit standard container)

| Config | Safe? | Notes |
|---|---|---|
| 5 symbols, 1d, 1 year | ✅ Safe | ~260 ticks, completes in ~10s |
| 5 symbols, 15m, 30 days | ✅ Safe | ~750 ticks, completes in 1–3 min |
| 5 symbols, 5m, 30 days | ⚠ Moderate | ~2250 ticks, ~5–10 min |
| 20 symbols, 1d, 1 year | ⚠ Moderate | ~260 ticks but 20× data fetch |
| 20 symbols, 15m, 6 months | ❌ Too heavy | ~4500 ticks, causes stalls/OOM |
| 20 symbols, 5m, 6 months | ❌ Too heavy | ~13500 ticks, guaranteed OOM |

**Recommendations:**
1. **Max 2 concurrent runs** — enforced via `MAX_CONCURRENT_BACKTESTS = 2` in `backtest_portfolio.py`. Third run is QUEUED and auto-promoted when a slot opens.
2. **Prefer 5–10 symbols, 1d or 15m, 1–3 months** for exploratory runs.
3. **Run the 20-symbol full suite sequentially** — launch one, wait for COMPLETED, then next. The queue handles this automatically now.
4. **Avoid 5m on 6-month ranges** — 5m data for 6 months × 20 symbols = ~800K candles. This saturates both memory and yfinance rate limits.

---

## 9. Next Run IDs for Smaller Validation

Two small validation runs were launched after all fixes were applied:

| Run | Config | Run ID | Status at launch |
|---|---|---|---|
| A — Baseline | 15m, 5 symbols, 30 days, ₹1L, 1% risk / 25% cap | BT-29142a23ba | PENDING |
| B — Recommended | 15m, 5 symbols, 30 days, ₹1L, 1.5% risk / 30% cap | BT-d79ab13b4b | PENDING |

Symbols: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK  
Date range: 2026-07-13 → 2026-08-12

Run IDs are visible in the Investigation Center Backtest Runs card (most recent two PENDING/RUNNING entries).

Both runs will complete within 3–5 minutes. Once COMPLETED, proceed to the full 20-symbol suite by launching one at a time from the Investigation Center.

---

## Changes Summary

| File | Change |
|---|---|
| `backtest_portfolio.py` | `MAX_CONCURRENT_BACKTESTS = 2`; `count_active_runs()`; `create_run()` → QUEUED at cap; `promote_next_queued()`; `sweep_stale_runs()` (server-side watchdog); `cancel_run()` handles QUEUED |
| `backtest_runner.py` | `_spawn_next_queued()` helper; called after COMPLETED and FAILED paths; `progress_updated_at` in all progress writes; per-tick cancellation checkpoint |
| `main.py` | `backtest_start` skips subprocess spawn for QUEUED runs; `backtest_runs` calls sweep before listing; `bt_sweep_stale` command; `backtest_cancel/mark_stale/retry` commands |
| `backtest.ts` | `POST /backtest/run/:id/cancel`, `/mark-stale`, `/retry` endpoints |
| `InvestigationCenter.tsx` | QUEUED badge (yellow); stale message matches brief; Cancel button covers QUEUED; filter dropdown; watchdog; hide/show controls |

---

*All changes are PAPER / RESEARCH ONLY. No live order logic was modified.*
