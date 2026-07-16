---
name: Phase 17 audit conventions
description: Durable lessons from the Phase 17 evidence/validation gap audit
---
- Equity-curve points in the analytics module use key `equity`, not `value` — any new drawdown/window math must read `p["equity"]`. **Why:** a silent 0-drawdown bug shipped when a helper assumed `value`.
- Daily session-report bundle (CSV/XLSX/PDF validation exports) auto-generates once per IST day from the scheduler tick when market state is CLOSED and a successful scan ran that day; guarded by kv `session_report_date`, stamped claim-first with rollback on failure. **How to apply:** don't add a second auto-report trigger; reuse/extend this guard.
- Cross-page "stale source" consistency warnings after market close are environmental (old scan snapshot), not bugs — check `hard_mismatch_count` instead.
