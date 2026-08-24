---
name: Dashboard scan GET side effect
description: Prevent accidental Phase 7 scans during read-only market-session observation.
---

**Rule:** Do not call `/api/live-data/recommendations` during a read-only
market-session validation unless starting a scan is explicitly authorized.

**Why:** Its market-open cold-cache path delegates to `getP7Scan()`, which
spawns `phase7_scan`; the HTTP method and route description make this easy to
mistake for a stored-snapshot read.

**How to apply:** For observation, use the durable scan metadata/history
endpoints only after a scheduler-emitted scan has completed. Treat any scan
returned by the recommendations route after a cold-cache request as
non-certifying for natural-scheduler evidence.