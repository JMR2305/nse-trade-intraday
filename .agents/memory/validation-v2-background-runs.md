---
name: Validation V2 background runs
description: Failure-handling contract for the async validation-v2 backtest executor.
---
Rule: any detached background executor must (a) capture stdio to a per-run log, (b) mark its run FAILED on non-zero exit/spawn error, (c) heartbeat `last_progress_at` at every unit of work (per symbol AND per strategy), and (d) guard terminal transitions: COMPLETED only from RUNNING, FAILED never downgraded.

**Why:** the V2 executor originally spawned with `stdio: "ignore"` — a crash left runs RUNNING forever with no error anywhere. A lazy stuck-run watchdog (30 min, fired from list/get) without granular heartbeats falsely fails long single-symbol replays, and an unguarded completion UPDATE resurrects watchdog-FAILED runs.

**How to apply:** see `validation_v2_engine.py` (mark_run_failed, _fail_stuck_runs, execute wrapper) and `validation-v2.ts` spawnBackground. Canonical page mapping: /investigation-center = Phase 23 production-pipeline backtest; /validation-v2 = research models; /backtest = legacy single-strategy simulator (labelled non-canonical).
