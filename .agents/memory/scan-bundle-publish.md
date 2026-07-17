---
name: Post-scan bundle publish semantics
description: Rules for regenerating derived caches after a scan and atomically publishing the bundle pointer
---

- Every derived dataset (signals, phase13/14, copilot alerts/briefing, entry evaluation) must be regenerated from the ONE canonical scan snapshot right after each successful scan — otherwise consistency checks flag dozens of STALE_SOURCE out-of-sync values (mtime vs snapshot_ts, 300s window).
- **Why:** derived caches previously regenerated on their own schedules, so pages showed values from different scans.
- **How to apply:** any new scan-derived cache must be added to the post-scan pipeline's module list and be regenerated with force=True from the warmed canonical snapshot.
- Publish rules: bundle pointer advances only when ALL required modules pass AND consistency reports 0 hard mismatches AND the bundle is not older (snapshot_ts) than the currently published one (monotonic; same scan_id republish is idempotent). Failed attempts are recorded separately and never advance the pointer.
- Guard: reject snapshots missing scan_id/snapshot_ts before running the pipeline — otherwise a bundle with scan_id None can be published.
- Scheduler health API returns {success, scheduler:{...}} — UI must read fields under `.scheduler`, not top-level (caused "-" dashes bug).
- Detached long-running python from the agent shell needs `setsid nohup ... & disown`, otherwise the process dies when the shell session ends.
- Autoscale scale-to-zero kills the Node setInterval scheduler; truly unattended production scans need a Reserved VM deployment.
