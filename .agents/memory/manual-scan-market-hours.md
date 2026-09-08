---
name: Manual scan market-hours gate
description: Full canonical scans must be blocked outside the OPEN session at every entry point, including operator-triggered routes.
---

All full canonical scan entry points must require the market to be `OPEN`, not only the scheduler path.

**Why:** Execution-time `market_open` and `scan_fresh` gates prevent paper orders, but they do not prevent a manually triggered after-hours scan from replacing canonical scan state or producing new advisory signals.

**How to apply:** When adding or changing an operator/API scan trigger, check authoritative market status before invalidating caches, publishing scan-start events, or starting background scan work. Closed, pre-open, and unknown states must fail closed.