---
name: Market-hours scanner coverage probe
description: Rules for the Monday-recovery coverage check (scanner_coverage.py, /live-data/coverage, health/ready).
---
Rule: a session-hours coverage/health probe must (1) require the scan snapshot to be from TODAY'S session (>= 09:00 IST pre-open start) before reporting healthy — a Friday 50/50 scan must not mask a Monday failure; (2) judge coverage against config.MIN_SYMBOLS_EXPECTED, never the scan's own requested count; (3) treat PRE_OPEN as in-session and be holiday-aware.
**Why:** completion review rejected a first version that reported healthy from stale prior-session metadata and let the browser apply its own (divergent) market-hours logic.
**How to apply:** all market-state/session logic lives server-side (scanner_coverage.py → main.py `scanner_coverage` → GET /api/live-data/coverage); the dashboard banner renders ok/warning verbatim. Tests: test_scanner_coverage.py.
