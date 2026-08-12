#!/usr/bin/env python3
"""
bt_queue_tick_cmd.py — Lightweight backtest queue tick entry point.

Called every 2 minutes by the TypeScript backtestScheduler.

WHY THIS FILE EXISTS
--------------------
The original entry point (main.py bt_queue_tick) needed 13–25 s to start
because main.py imports pandas (~9 s), yfinance (~2.6 s), and SQLAlchemy
(~1.5 s) unconditionally at module load time — even for commands that need
none of those libraries.  The TypeScript scheduler's 30-second timeout fired
before bt_queue_tick ran a single DB query, generating "bt_queue_tick timed
out after 30 s" failures in the scheduler health counters.

This script imports ONLY:
  • sys, json, os, subprocess  (stdlib, ~0 ms)
  • backtest_portfolio          (psycopg2-only, ~23 ms cold)

Cold-start: < 100 ms  vs  13–25 s for main.py.

WHAT IT DOES (identical to main.py's bt_queue_tick handler)
------------------------------------------------------------
  1. sweep_stale_runs()       — marks RUNNING/PENDING runs with no heartbeat
                                for 30+ min → STALE; promotes QUEUED → PENDING.
  2. find_unclaimed_pending() — finds PENDING runs older than 2 min whose
                                original spawn failed (recovery path).
  3. Spawns a detached worker for each promoted / recovered run_id by calling
     main.py backtest_exec — the FULL entry point, so worker subprocesses
     still have access to pandas / yfinance / all trading modules.
  4. If Popen fails, reverts the run from PENDING back to QUEUED so the next
     tick can retry without waiting for the 30-min stale watchdog.

Outputs JSON to stdout and exits 0 on success (matching the format that
backtestScheduler.ts parses for its health counters).
"""
import sys
import json
import os
import subprocess

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

import backtest_portfolio as bp  # psycopg2-based; no pandas/yfinance/sqlalchemy

sweep_result = bp.sweep_stale_runs()
spawned: list = []

# Workers are spawned via the full main.py entry point so they have access
# to all trading-engine modules (pandas, yfinance, live_scan_engine, etc.).
_main_py = os.path.join(_dir, "main.py")

# Runs promoted in this tick (QUEUED → PENDING) + unclaimed PENDING recovery
to_spawn: list = list(sweep_result.get("promoted_runs") or [])
recovery: list = bp.find_unclaimed_pending(older_than_min=2.0)
for rid in recovery:
    if rid not in to_spawn:
        to_spawn.append(rid)

for rid in to_spawn:
    try:
        with open(f"/tmp/backtest_{rid}.log", "ab") as lf:
            subprocess.Popen(
                [sys.executable, _main_py,
                 "backtest_exec", json.dumps({"run_id": rid})],
                stdout=lf, stderr=lf,
                cwd=_dir,
                start_new_session=True,   # detach from scheduler process group
            )
        spawned.append(rid)
    except Exception:
        # Popen failed — revert PENDING → QUEUED immediately so the next tick
        # can retry without waiting for the 30-min stale watchdog.
        try:
            bp.revert_pending_to_queued(rid)
        except Exception:
            pass

print(json.dumps({
    **sweep_result,
    "spawned": spawned,
    "spawned_count": len(spawned),
    "recovery_candidates": recovery,
}))
