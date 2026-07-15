---
name: Phase review package generator
description: Conventions for the Settings "Generate Review Package" feature when advancing phases
---
- The package name is phase-versioned (Phase{N}_Review_Package). When advancing a phase, bump `PHASE` in review_package.py AND the hardcoded zip filename in the /api/review-package/download route in lockstep, or downloads serve the old phase's zip.
- **Why:** the Phase 10 → 15 upgrade initially left the download route serving Phase10_Review_Package.zip.
- **How to apply:** any future phase review package task.
- Honesty rules are a hard requirement: no placeholder screenshots (write NOT_AVAILABLE.txt instead), mark missing data "Not Available"/"Insufficient Data", never claim test/integration results that were not actually executed during generation.
- Generation takes ~4-5 min (37 full-page captures + 3 live test suites); trigger via background curl and poll files, per headless-screenshot-capture.md.
- Generation must be start-then-poll: POST /generate returns 202 immediately and the UI polls GET /status every few seconds; a synchronous response gets killed by the ~2-min browser/proxy request timeout (statusCode null abort at ~120s), so the user never receives the ZIP.

**Rule:** Standing user requirement — every executed change must also be reflected in the review package generator (implementation summary, feature matrix, test suites, data exports). Recorded in replit.md User preferences.
**How to apply:** When finishing any feature/phase, update review_package.py in the same task; download route auto-picks newest Phase<N>_Review_Package.zip by mtime, so only the generator needs updating.
