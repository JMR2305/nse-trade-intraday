---
name: Scheduler health shape & IST day counting
description: phase20 get_scheduler_health() returns a FLAT dict; IST day windows must use ist_day_bounds_utc
---

- `phase20_store.get_scheduler_health()` returns scheduler fields at the TOP level (no `"state"` wrapper). Reading `.get("state")` silently yields `{}` and downstream fallbacks mask the bug.
- **Why:** a cadence fix was rejected in review because it read a non-existent `state` key, so the "since restart" boundary always fell back and equalled the full-day count.
- **How to apply:** consume `next_due_at`, `status`, `process_start_at` etc. directly from the health dict. The scheduler records `process_start_at` at boot via the `phase20_scheduler_started` command (called from scanScheduler.ts).
- Any "today" count over pipeline_events must use IST day bounds, not UTC calendar date — use `scan_state_store.ist_day_bounds_utc()` (shared with `count_scans_today_ist`). After 18:30 UTC the IST day has already rolled over.
- UI must never present an UNKNOWN/loading market state as "Market closed" — only explicit CLOSED/POST_CLOSE/HOLIDAY.
