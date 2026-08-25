---
name: Market-hours scanner coverage probe
description: Rules for the Monday-recovery coverage check (scanner_coverage.py, /live-data/coverage, health/ready).
---
Rule: a session-hours coverage/health probe must (1) require the scan snapshot to be from TODAY'S session (>= 09:00 IST pre-open start) before reporting healthy; (2) judge coverage against the authoritative active universe (durable custom membership or configured NIFTY 50), never the scan's requested count; (3) treat PRE_OPEN as in-session and be holiday-aware.
**Why:** stale prior-session metadata must not mask a Monday failure, and a healthy 23-symbol custom universe must not be measured against the legacy NIFTY 50 baseline. An unreadable or empty custom master must fail closed, never become an expected count of zero.
**How to apply:** all market-state/session and active-universe logic lives server-side (scanner_coverage.py → main.py `scanner_coverage` → GET /api/live-data/coverage); the dashboard banner and health readiness consume the canonical `ok` verdict. Tests cover NIFTY and custom-universe full/partial coverage.
