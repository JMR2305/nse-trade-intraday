---
name: Public build-ID labels
description: How Mission Control UI/API build identity works and how to verify a published static bundle.
---

# Public build-ID labels (Mission Control)

The shared release ID `apexquant-v1.0.0` is supplied via `APEXQUANT_BUILD_ID` in
three places that must be bumped together: the dashboard artifact's production
build env, the api-server artifact's production build+run env, and the dashboard
`build` npm script. UI reads it at Vite compile time (`VITE_BUILD_ID` define);
API reads it at runtime. A missing production value renders
`production-unidentified`, never `development`.

**Why:** the public "UI development · API 1 · Build mismatch" warning came from
a static bundle with no build-time ID vs. Replit's runtime `REPLIT_DEPLOYMENT=1`.

**How to apply:**
- Shorthand `build = [...]` in artifact.toml cannot carry env vars; use the
  `[services.production.build]` args form with a `[...build.env]` table.
- To verify a published static bundle, curl the served hashed asset and grep for
  the compiled constant — do not trust a browser/tester run right after a
  publish (CDN/browser caches and propagation delay produce stale labels), and
  identical Rollup content hashes do not prove the platform rebuilt.
- Bumping the release ID on only one artifact intentionally shows a real
  `Build mismatch` until both are republished.
