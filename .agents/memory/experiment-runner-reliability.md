---
name: Experiment runner reliability
description: Lessons from detached Python runner dying silently (OOM) and how liveness is now tracked
---

- Detached runner processes spawned with `stdio: "ignore"` die without any trace; always redirect stdout/stderr to a per-run log file and add a Node `proc.on("exit")` handler that records exit code/signal if the status file still says "running".
- **Why:** two long Bull Market runs were killed mid-window by a signal (OOM) with zero evidence; PID-liveness checks were also fooled by PID reuse (a language server inherited the old PID).
- **How to apply:** liveness = heartbeat file refreshed every 5s by a daemon thread inside the runner; reconciliation treats >30s stale heartbeat as dead (PID check only as fallback when no heartbeat file exists). Long pandas walk-forward loops should `gc.collect()` per window to limit peak memory.
- Stage-level exec_log.json (queued/starting/loading/walk-forward/scoring/completed/failed) makes silent deaths localizable to a stage; `faulthandler.enable()` captures native crashes into the runner log.
