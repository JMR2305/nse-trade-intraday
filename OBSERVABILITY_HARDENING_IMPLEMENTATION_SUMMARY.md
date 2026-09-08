# Recent Changes and Implementation Summary

**Last updated:** August 25, 2026
**Scope:** Observability provenance hardening plus dashboard-wide freshness coverage

## Current status

- Task #934, **Harden observability provenance**, is merged.
- Task #936, **Restore dashboard-wide freshness checks so releases can pass safely**, is merged at commit `ee6eb38e5003226f6b5c58e606067099f641f98b`.
- Task #937 was cancelled because its warning-handling scope was no longer needed after the validation fixes.
- The Task #936 post-merge dashboard gate passed with **51 test files and 998
  tests passing**.
- The deployment was published with matching UI/API identity
  `apexquant-5b22ea84b68e`; the later `Published your App` commit has no source
  delta from that deployed source commit.
- Post-deployment verification is **blocked**: the Mission Control cards render
  `UNAVAILABLE / NOT PROVEN` even though the production health response contains
  recorded closed-market quote provenance. Task #939 tracks the correction.

## Task #934 — Observability provenance

The implementation improves operator-facing evidence without changing trading,
readiness, execution, portfolio, universe, or broker behavior.

### Current-price provenance

- Mission Control now distinguishes:
  - current quote provider;
  - last quote timestamp and age;
  - quote freshness;
  - historical OHLCV provider;
  - fallback, synthetic, and unavailable counts; and
  - scan origin/provenance.
- Closed-market recorded prices are labeled `MARKET_CLOSED_LAST_KNOWN`.
- Missing evidence is rendered explicitly as `UNAVAILABLE / NOT PROVEN`.
- A closed-market last-known label requires a real recorded quote timestamp;
  `scan.snapshot_ts` is never substituted as quote-time evidence.
- Historical OHLCV provenance is derived only from recorded scan safety,
  indicator, or OHLCV fields, never from the live quote provider status.
- The provenance block remains visible when the custom universe is inactive, while custom-universe controls remain conditional.
- Existing readiness and execution predicates were not relaxed or reinterpreted.

### Manual-scan provenance

- Future API/manual scans record sanitized actor, endpoint, method, request/correlation ID, trigger source, approval status, and timestamp data in the existing `details.provenance` object.
- Request and correlation IDs are restricted to server-issued numeric IDs or `scan-UUID` values.
- Direct CLI/manual paths generate deterministic `scan-UUID` audit identifiers.
- JWT-shaped and other arbitrary opaque identifiers are rejected at the durable persistence boundary.
- `RECOVERY` and `BACKFILL` activity is classified as `INTERNAL_DIAGNOSTIC`, not `MANUAL_SCAN`.
- Legacy manual records are not rewritten or backfilled. They render explicit unavailable/unknown provenance.

### Safety boundaries

- No scans, retries, replays, logins, bootstrap actions, automatic entries,
  controlled execution, broker orders, or production mutations were performed.
- Historical manual scan `e1ded4dfba2e` remains unchanged.
- Paper-only mode, disabled automatic entries/bootstrap, disabled controlled
  execution, and disabled live broker orders remain in effect.
- No readiness gate was weakened and no portfolio, ledger, universe, or
  configuration data was changed.

## Task #936 — Dashboard-wide freshness coverage

### Implementation

- Added `RouteFreshnessIndicator`, a shared route registry covering the
  dashboard’s registered pages with `scan`, `historical`, or `none` semantics.
- Mounted the route-level indicator through `AppLayout`, filling gaps without
  duplicating page-local freshness bars that already exist.
- Kept freshness timestamps sourced from backend metadata and displayed in IST.
- Expanded the route coverage test to validate:
  - every registered route has a local indicator or registry entry;
  - registry entries refer only to registered routes;
  - route variants are valid;
  - the shared layout renders the indicator;
  - no browser-clock timestamps or secrets are introduced; and
  - stale/failed-data protection remains visible.
- Updated the AI Validation marker test to assert the current user-visible
  heading, `Strategy Validation — Research Models`.

### Files changed by the merge

- `artifacts/trading-dashboard/src/components/RouteFreshnessIndicator.tsx`
- `artifacts/trading-dashboard/src/components/layout/AppLayout.tsx`
- `artifacts/trading-dashboard/src/lib/freshness-coverage.test.ts`
- `artifacts/trading-dashboard/src/pages/__tests__/AIValidationV2Page.markers.test.tsx`

## Validation record

### Completed for Task #934

- Focused backend provenance, scheduler, and Kite regressions: **68 passed**
- Custom-universe regression: **14 passed**
- API scan-cache invalidation regression: **13 passed**
- Focused Mission Control tests: **20 passed**
- Python compilation and diff checks: **passed**
- Configured dashboard/API/workspace TypeScript checks: **passed**
- Dashboard production build: **passed**, with existing non-blocking warnings
- API workflow restart and startup: **passed**
- Browser smoke check: **passed**; missing quote evidence visibly rendered as
  `UNAVAILABLE / NOT PROVEN` with no browser console errors
- Final independent architecture/security review: **passed**

### Dashboard suite status

- The full post-merge dashboard suite passed: **51 files passed, 998 tests
  passed, 0 failures**.
- The formerly failing `freshness-coverage.test.ts` and
  `AIValidationV2Page.markers.test.tsx` files both pass.
- Dashboard, API, and workspace TypeScript checks passed.
- The dashboard production build passed using the required
  `PORT=9999 BASE_PATH=/trading-dashboard/` contract. Existing sourcemap,
  dynamic-import, and bundle-size notices remained warnings only.
- The remaining release action is a user-initiated controlled publish followed
  by the specified read-only production verification. The publish is complete,
  but that verification currently fails because the Mission Control display does
  not present the production provenance evidence truthfully.

## Follow-up

Task #936 is the existing follow-up for restoring a clean dashboard-wide release
gate. Its pre-deployment validation is complete; do not create a duplicate task.
Task #930 evidence remains outside this summary’s scope and must not be manually
replayed, changed, or backfilled.