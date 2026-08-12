# Backtest Run Controls — Implementation Verification Report

**Date:** 2026-08-12  
**Scope:** PAPER / RESEARCH ONLY — no threshold changes, no strategy changes, no live orders.  
**Brief:** Stop / Cancel / Retry / Clear Stale controls for backtest runs in Investigation Center.

---

## Summary

All 10 tasks implemented and verified. 11 previously stuck RUNNING runs cleaned up. Three new HTTP endpoints live. Client-side watchdog and filter UI deployed.

---

## Task Verification

### Task 1 — New status constants and `get_run_status()`

**File:** `artifacts/api-server/src/python/backtest_portfolio.py`

Added `TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "STALE", "FAILED"}` constant and lightweight `get_run_status(run_id)` that issues a single-column `SELECT status` query — no JSON deserialisation — for use inside the tight per-tick replay loop.

**New statuses in use** (all stored in the TEXT `status` column; no schema migration needed):
| Status | Meaning |
|---|---|
| `PENDING` | Created, not yet claimed by a worker |
| `RUNNING` | Worker active |
| `CANCEL_REQUESTED` | Operator issued cancel; worker will stop at next checkpoint |
| `CANCELLED` | Stopped cleanly (PENDING→immediately, RUNNING→on checkpoint) |
| `COMPLETED` | Finished normally |
| `FAILED` | Worker crashed |
| `STALE` | Worker dead (no progress for 30+ min), operator-marked |

**Verified:** Direct Python call chain tested — correct errors for not-found, terminal, and wrong-state inputs.

---

### Task 2 — `cancel_run()` in `backtest_portfolio.py`

State machine:
- `PENDING → CANCELLED` immediately (no worker to signal)
- `RUNNING → CANCEL_REQUESTED` + stores `cancel_requested_at` in progress JSONB
- Terminal statuses → `{"ok": false, "error": "..."}` with exact status name

**Verified:**
```
POST /api/backtest/run/BT-ea7d3223e9/cancel
→ {"ok":true,"run_id":"BT-ea7d3223e9","status":"CANCELLED","message":"Run was PENDING; cancelled immediately..."}
```

---

### Task 3 — Cancellation checkpoint in `backtest_runner.py`

**File:** `artifacts/api-server/src/python/backtest_runner.py`

Added cancellation check **inside the existing `% 5` progress block** (every 5 ticks) so no extra DB round-trips occur on other ticks. When `CANCEL_REQUESTED` is detected:
1. Worker updates run to `CANCELLED` with `error="Cancelled by operator"` and `completed_at=now`
2. Worker returns `{"ok": False, "cancelled": True, "ticks_completed": N}` immediately
3. All partial events and trades in the DB are preserved for audit

Also added `progress_updated_at: datetime.now(timezone.utc).isoformat()` to both the DATA phase and REPLAY phase progress JSONB payloads — this timestamp is the heartbeat the client-side watchdog reads.

---

### Task 4 — `mark_stale_run()` and `retry_run()` in `backtest_portfolio.py`

**`mark_stale_run(run_id)`:**
- Only applies to `RUNNING` or `CANCEL_REQUESTED`
- Computes `minutes_stale` from `progress.progress_updated_at` → `started_at` → `created_at` (fallback chain)
- Sets `status=STALE` with a human-readable error message
- All other states → graceful `{"ok": false, "error": "..."}`

**`retry_run(run_id)`:**
- Creates a **new** PENDING run from the same config via `create_run(config)`
- Strips `cash_by_tick` and `learning_fingerprint` internal fields from config
- Original run **unchanged** — preserved for full audit
- Returns `{"ok": true, "original_run_id": ..., "new_run_id": ..., "status": "PENDING"}`

**Verified:**
```python
cancel nonexistent: {'ok': False, 'error': 'Run DOES-NOT-EXIST not found'}
mark_stale completed run: {'ok': False, 'error': '...COMPLETED; mark-stale only applies to RUNNING or CANCEL_REQUESTED runs'}
retry stale run: {'ok': True, 'new_run_id': 'BT-cf247628e9', 'status': 'PENDING'}
```

---

### Task 5 — Three new CLI commands in `main.py`

**File:** `artifacts/api-server/src/python/main.py`

Added after `backtest_validate`:
- `backtest_cancel` → `bp.cancel_run(run_id)`
- `backtest_mark_stale` → `bp.mark_stale_run(run_id)`
- `backtest_retry` → `bp.retry_run(run_id)`

All accept `JSON.stringify({ run_id })` as `sys.argv[2]`, consistent with all other backtest commands.

---

### Task 6 — Three new HTTP endpoints in `backtest.ts`

**File:** `artifacts/api-server/src/routes/backtest.ts`

```
POST /api/backtest/run/:id/cancel      → backtest_cancel
POST /api/backtest/run/:id/mark-stale  → backtest_mark_stale
POST /api/backtest/run/:id/retry       → backtest_retry
```

All timeout at 15 s. All errors go through the existing `fail(res, err)` handler.

**Verified (live dev server):**
```
POST /api/backtest/run/BT-ea7d3223e9/cancel
→ {"ok":true,"run_id":"BT-ea7d3223e9","status":"CANCELLED",...}

POST /api/backtest/run/BT-ea7d3223e9/mark-stale
→ {"ok":false,"error":"Run BT-ea7d3223e9 is CANCELLED; mark-stale only applies to RUNNING/CANCEL_REQUESTED"}
```
(Correct rejection — the run was already CANCELLED before mark-stale was attempted.)

---

### Task 7 — Run control buttons in `InvestigationCenter.tsx`

**File:** `artifacts/trading-dashboard/src/pages/InvestigationCenter.tsx`

Three `useMutation` hooks added:
- `cancelMut` → `POST /backtest/run/:id/cancel`
- `markStaleMut` → `POST /backtest/run/:id/mark-stale`
- `retryMut` → `POST /backtest/run/:id/retry` (auto-selects the new run_id on success)

Each run row now renders a control buttons strip (click-propagation stopped with `e.stopPropagation()` so buttons don't also trigger row selection):

| Button | Visible when | data-testid |
|---|---|---|
| **Stop** | status=RUNNING | `btn-cancel-{id}` |
| **Cancel** | status=PENDING | `btn-cancel-{id}` |
| **Stopping…** (disabled) | status=CANCEL_REQUESTED | `btn-cancel-{id}` |
| **Mark Stale** | status=RUNNING AND watchdog fired | `btn-mark-stale-{id}` |
| **Retry** | status=FAILED/STALE/CANCELLED | `btn-retry-{id}` |
| **Hide** | always | `btn-hide-{id}` |

The outer run row element was changed from `<button>` to `<div>` (with `cursor-pointer` on the clickable body) so HTML-spec button-in-button nesting is avoided.

---

### Task 8 — Filter dropdown + Show-all + Hide-failed in card header

Status filter dropdown added to the Backtest Runs card header:
- **All** — show all visible (non-hidden) runs
- **Active** — PENDING, RUNNING, CANCEL_REQUESTED
- **Completed** — COMPLETED only
- **Failed/Stale** — FAILED, STALE, CANCELLED, CANCEL_REQUESTED

Additional header controls:
- **Show all (N hidden)** — clears localStorage `bt-hidden-runs`, restores all previously hidden runs
- **Hide failed** — one-click hides all FAILED/STALE/CANCELLED runs from the list

Hidden state is persisted in `localStorage["bt-hidden-runs"]` (serialised as a JSON array of run_ids). Refresh-safe. Never deletes from DB.

---

### Task 8b — Client-side watchdog

`staleRunIds` computed via `useMemo` over the live runs list. A run is watchdog-stale when:
1. `status === "RUNNING"`, **and**
2. `now - new Date(progress.progress_updated_at ?? created_at).getTime() > 30 * 60 * 1000`

When fired, the run row shows an amber warning:  
`⚠ No progress for 30+ min — worker may be stuck` (`data-testid="text-stale-{id}"`)  
…and the **Mark Stale** button becomes visible.

The watchdog updates every 5 s (matching `runsQ.refetchInterval`). No server push required.

---

### Task 9 — Clean up existing stuck RUNNING runs

11 RUNNING runs from 2026-08-11 (all stuck 18–24 hours) marked STALE directly via `mark_stale_run()` before the API server restarted:

| Run ID | Minutes stale |
|---|---|
| BT-e8a676975d | 1,409.8 min |
| BT-19c7568aa7 | 1,154.4 min |
| BT-94bd1a3c5d | 1,150.1 min |
| BT-27b0ca58b7 | 1,150.0 min |
| BT-cb2a4e5081 | 1,149.9 min |
| BT-bc6b55820d | 1,149.9 min |
| BT-5d2ba71f70 | 1,127.8 min |
| BT-c5e69f6674 | 1,127.8 min |
| BT-536cc0f4bd | 1,127.7 min |
| BT-da5e7f9a58 | 1,127.7 min |
| BT-dcbfd63627 | 1,127.6 min |

Post-cleanup run status distribution: **COMPLETED: 12, STALE: 11, FAILED: 3, PENDING: 3**.

---

## New Status Badge Colours (UI)

| Status | Badge colour |
|---|---|
| COMPLETED | green |
| RUNNING | blue |
| PENDING | amber |
| CANCEL_REQUESTED | orange |
| CANCELLED | red/60 (dimmed) |
| STALE | amber-500 |
| FAILED | red |

---

## Safety Properties

- **No live orders.** All new code paths touch only the backtest DB tables (`backtest_runs`, `backtest_trades`) and the `pipeline_events` table. No Paper/Live execution touched.
- **Partial data preserved.** `cancel_run`, `mark_stale_run`, and the worker cancellation checkpoint all explicitly preserve events and trades already written.
- **Fail-closed controls.** Wrong-state transitions return `{"ok": false}` with a clear error message; they never corrupt run state.
- **Audit trail.** `retry_run` creates a new run ID; the original run (STALE/FAILED/CANCELLED) is never modified, deleted, or renamed.
- **No schema migrations.** The `status` column is TEXT; no `ALTER TABLE` needed for the three new statuses.

---

## TypeScript Typecheck

```
pnpm --filter trading-dashboard exec tsc --noEmit
→ 0 errors
```

---

*All tasks complete. PAPER / RESEARCH ONLY constraints maintained throughout.*
