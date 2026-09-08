# ApexQuant — Public Build-ID Label Fix Report

Date: 20 August 2026 (IST)
Scope: Mission Control build-identity label only. No trading, scan, broker, paper-entry, or live-order behavior was changed.

## Problem

After the scan-status freshness remediation, public Mission Control showed a persistent warning:

```
UI development · API 1 · Build mismatch
```

Root cause: the static dashboard bundle is compiled by Vite with no build-time
release identifier (falling back to the literal `development`), while the
production API reported Replit's runtime `REPLIT_DEPLOYMENT=1`. Both surfaces
were healthy — only the label vocabulary differed.

## Fix

A single shared release identifier, `apexquant-v1.0.0`, is now supplied to both
production artifacts:

1. **`artifacts/trading-dashboard/.replit-artifact/artifact.toml`** — production
   build env sets `APEXQUANT_BUILD_ID=apexquant-v1.0.0` (and `NODE_ENV=production`);
   the build block was converted to the `[services.production.build]` args form
   so it can carry environment variables. Applied via the validated artifact
   workflow (not a direct TOML edit).
2. **`artifacts/api-server/.replit-artifact/artifact.toml`** — the same
   `APEXQUANT_BUILD_ID` is set in both the production build env and the
   production runtime env.
3. **`artifacts/trading-dashboard/vite.config.ts`** — the compiled
   `VITE_BUILD_ID` now prefers `APEXQUANT_BUILD_ID`, then Replit deployment
   variables, then `BUILD_ID`. If all are absent, a production build labels
   itself `production-unidentified` (visibly actionable) instead of falsely
   claiming `development`. Development previews still say `development`.
4. **`artifacts/api-server/src/routes/trading.ts`** — `apiBuildId()` uses the
   identical preference order and the identical `production-unidentified`
   production fallback.
5. **`artifacts/trading-dashboard/package.json`** — the production `build`
   script sets `APEXQUANT_BUILD_ID=apexquant-v1.0.0` unconditionally as a
   defensive second layer, so the release ID is baked in even if the artifact
   build env were ever dropped.

Mismatch detection is unchanged: `buildIdsMatch()` still requires exact
equality, so a genuinely divergent publish (e.g. only one artifact republished
with a bumped ID) still renders a red `Build mismatch`.

## Verification

Development (after workflow restarts):
- `GET /api/live-data/scan/status` on the dev domain → `api_build_id: "development"`.
- Dev Mission Control header → `UI development · API development · Builds match`.
- `MissionControl.freshness.test.tsx` → 6/6 pass.
- `scan-cache-invalidation.test.ts` → 6/6 pass; api-server `tsc --noEmit` clean;
  dashboard `typecheck` clean.
- Local production-mode build contains `"apexquant-v1.0.0"` and no
  `production-unidentified` marker.

Production (read-only; no scan, order, command, or settings mutation):
- `GET https://nse-trade-intraday.replit.app/api/live-data/scan/status` →
  HTTP 200, `api_build_id: "apexquant-v1.0.0"`, strict no-store headers
  (`cache-control: no-store, no-cache, must-revalidate, proxy-revalidate`,
  `pragma: no-cache`, `expires: 0`, `surrogate-control: no-store`).
- The served static bundle (`/trading-dashboard/assets/index-*.js`) contains the
  compiled constant `"apexquant-v1.0.0"` as the frontend build ID.
- Fresh public Mission Control page render shows:
  `UI apexquant-v1.0.0 · API apexquant-v1.0.0 · Builds match · Last refreshed 04:00:17 IST`
  with no mismatch warning and the PAPER TRADING / RESEARCH ONLY and read-only
  indicators intact (screenshot: `screenshots/public-build-id-verification.png`).

## Operational note

The release identifier is intentionally a stable version string, not a per-build
hash. When shipping a new public version, bump `apexquant-v1.0.0` in all three
places together (both `artifact.toml` production env blocks and the dashboard
`build` script). Bumping only one surface will — by design — show a genuine
`Build mismatch` until both artifacts are republished.
