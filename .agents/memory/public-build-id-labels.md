---
name: Public build-ID labels
description: How Mission Control UI/API build identity works and how to verify a published static bundle.
---

# Public build-ID labels (Mission Control)

## API production identity

- The published API build ID must be derived from the exact source commit as
  `apexquant-<first-12-hex-sha>`. Production treats every other shape as
  unidentified, never as a valid release.
- **Why:** a retained shared release label survived the correct source-commit
  handoff and was embedded in a new API bundle, producing a false
  artifact/commit mismatch.
- **How to apply:** the root publish build preserves the source SHA before
  cleanup removes `.git`; the API bundle must embed that SHA and its derived
  build ID. Inspect the compiled API bundle before publishing and reject any
  retired value rather than merely displaying it.

## Static dashboard labeling

- Dashboard release labels are build-time constants. To verify a published
  static bundle, curl the served hashed asset and grep for the compiled constant
  — do not trust a browser/tester run immediately after a publish because CDN
  and browser caches can be stale.
- A dashboard/API label mismatch is meaningful only after both artifacts are
  rebuilt. API runtime reconciliation must additionally expose a non-secret
  environment, build ID, commit, instance label, and runtime time; deployment
  metadata alone cannot prove which source revision serves a route.
