---
name: Scheduled scan cache invalidation
description: Why scheduler lifecycle events must clear API scan caches in addition to browser cache controls
---

Scheduled scans run outside the manual scan route, so their start, completion,
busy/no-op, and failure outcomes must publish lifecycle events that invalidate
both the API's scan-status and scan-history caches. Each cache needs a
generation guard so an in-flight pre-event Python read cannot repopulate a
stale payload after invalidation.

**Why:** `Cache-Control: no-store` and a browser cache-busting query parameter
do not clear a server-side TTL cache. Without scheduler-path invalidation,
Mission Control can display an old status immediately after a scheduled scan.

**How to apply:** Keep browser freshness controls and server invalidation
together. Count durable completion events independently from presentation
history pairing, because pairing is enrichment rather than the authoritative
daily total.