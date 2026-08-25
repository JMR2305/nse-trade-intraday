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

- Production dashboard and API identities must be derived from a full
  40-character source commit:
  expose the full UI commit and derive the UI build ID as
  `apexquant-<first-12-hex-sha>`. Product version is separate release metadata,
  never a deployment identity. Mission Control only labels UI/API as MATCH for
  exact build-ID equality; missing identity stays actionable.
- **Why:** a retired semantic label was baked into the dashboard static asset,
  obscuring whether the UI was built from the same source as the API.
- **How to apply:** use the root source-commit handoff before `.git` cleanup,
  reject missing/invalid or overriding production UI labels, and curl the
  served hashed asset after publish. Do not trust an immediately opened browser
  tab because static/CDN caches can be stale.
- API runtime reconciliation must additionally expose a non-secret environment,
  build ID, commit, instance label, and runtime time; deployment metadata alone
  cannot prove which source revision serves a route.

## Deployed commit reconciliation

- If production reports a newer SHA, check ancestry and the complete diff before
  advancing the approved reference. A direct report/evidence-only descendant
  is safe to accept without republishing; any runtime or trading diff is not.
