---
name: Detached background-run status handshake
description: Status-file handshake rules between Node route layer and detached Python runners
---
The rule: when Node writes a placeholder "running" status before/around spawning a detached Python runner, the Python side's "is this runnable?" guard MUST accept the placeholder "running" state, and both sides should record the runner PID in the status file so stale "running" states can be detected via liveness checks.

**Why:** A run got stuck as "running" forever: Node wrote status="running", then spawned Python, whose guard only allowed "queued"/"failed" — Python exited silently, nothing ever updated the file, and the concurrency guard blocked all future runs.

**How to apply:** For any new background job type (experiments, walk-forward, exports): (1) spawn first, then write the placeholder including `pid`; (2) Python guard allows the placeholder state; (3) Python overwrites status with its own `os.getpid()`; (4) concurrency checks verify PID liveness (`process.kill(pid, 0)`) instead of trusting the status string.
