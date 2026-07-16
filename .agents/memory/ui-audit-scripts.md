---
name: UI audit script robustness
description: Lessons for puppeteer-based page audits in this workspace
---
- Background (`nohup`/`setsid`) node processes get reaped between agent shell sessions. Long audits must be **resumable** (write a per-page row file, skip pages whose row exists) and run in repeated foreground passes under `timeout 115`.
- **Why:** two detached runs died silently mid-audit; resumable passes converged in 3 runs.
- Dashboard pages poll forever — never use `networkidle`. Wait for the target element itself (`waitForSelector` on the component testid, ~60s) since data-heavy pages sit on a loading spinner well past any fixed delay.
- Tabs can crash mid-run ("Attempted to use detached Frame"); recover by recreating `browser.newPage()` on error and checking for detached main frame before each navigation.
- Auto scans can run mid-audit, so cross-page scan_id consistency checks may show two IDs; delete stale-id rows and recapture rather than treating it as a bug.
