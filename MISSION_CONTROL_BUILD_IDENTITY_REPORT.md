# Mission Control Build Identity Report

**Date:** 25 August 2026 (IST)  
**Scope:** Dashboard build identity and Mission Control display only. No trading,
scan, portfolio, universe, broker, order, safety-setting, or backend runtime
behavior was changed.

## Root cause

The dashboard had two independent build-time overrides that forced the retired
semantic deployment label `apexquant-v1.0.0`:

- `artifacts/trading-dashboard/package.json` set that value directly in the
  dashboard build command.
- `artifacts/trading-dashboard/.replit-artifact/artifact.toml` set the same
  value in the production build environment.

Vite then baked that value into the static hashed JavaScript asset. It was not
derived from source, so it could appear to match an unrelated API deployment.
Mission Control also displayed only a compact `UI … · API …` string, which
mixed product/version vocabulary with deployment identity.

## Corrected UI identity source

The dashboard now follows the existing source-commit handoff used before
deployment cleanup removes `.git`:

1. `scripts/deploy-build.sh` validates the exact source commit, writes the
   non-secret `.apexquant-source-commit` handoff, and exports
   `APEXQUANT_GIT_COMMIT` to child builds.
2. `artifacts/trading-dashboard/buildIdentity.mjs` resolves the commit from
   the approved environment handoff, the Git checkout, or the persisted
   handoff file.
3. Production builds require a full 40-character hexadecimal source commit and derive:
   - `ui_git_commit`: the full source commit
   - `ui_build_id`: `apexquant-<first 12 commit characters>`
4. Production builds reject missing/invalid commits and reject retired,
   generic, or overriding `APEXQUANT_BUILD_ID` values. Deployment IDs and
   semantic product versions are not eligible UI build identities.
5. Vite injects `VITE_UI_GIT_COMMIT` and `VITE_UI_BUILD_ID` into the static
   browser bundle. Product metadata is injected separately as
   `VITE_PRODUCT_VERSION` (`v1.0.0`).

The production dashboard build command and artifact build environment no
longer force `apexquant-v1.0.0`.

## Mission Control display contract

Mission Control now presents three separate fields:

- **Product Version:** `v1.0.0`
- **UI Build:** the commit-derived browser build ID
- **API Build:** the API-provided deployment build ID

Only exact UI/API build-ID equality displays **MATCH**. The UI also provides
explicit **CHECKING**, **MISMATCH**, **UI IDENTITY UNAVAILABLE**, and
**API IDENTITY UNAVAILABLE** states with actionable explanations. A missing
identity is never treated as a match.

## Read-only production evidence

Production requests on 25 August 2026:

| Endpoint / asset | Observation |
| --- | --- |
| `/api/health/details` | HTTP 200; `environment: production`; API commit `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832`; API build `apexquant-2e54e5e2f23f` |
| `/trading-dashboard/` | HTTP 200; returned hashed entry `/trading-dashboard/assets/index-ZjAoSbX2.js` |
| Served entry asset | Still contains `apexquant-v1.0.0`; it does not yet contain a commit-derived UI identity |

### Cache assessment

- The production API, HTML, and JavaScript responses returned
  `Cache-Control: private`.
- The HTML and asset responses have the same last-modified timestamp
  (`Mon, 24 Aug 2026 11:29:58 GMT`), consistent with the currently published
  static dashboard output.
- No source or public asset reference to a service worker was found.

The served UI label is therefore confirmed as an older frontend artifact, not
a service-worker or response-cache artifact falsely serving a current bundle.

## Latest public verification

**Checked:** 25 August 2026, 03:43–03:49 UTC (09:13–09:19 IST)
**Method:** Read-only `curl` requests and a Chromium screenshot of the public
Mission Control route. The active deployment metadata reported a successful,
public autoscale deployment at `https://nse-trade-intraday.replit.app`.

| Check | Latest observation |
| --- | --- |
| Production API `/api/health/details` | HTTP 200. `runtime_identity.environment` is `production`; `runtime_identity.git_commit` is `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832`; `runtime_identity.build_id` is `apexquant-2e54e5e2f23f`. |
| Dashboard HTML `/trading-dashboard/` | HTTP 200 and still references `/trading-dashboard/assets/index-ZjAoSbX2.js`. |
| Served entry asset | The 4,216,106-byte JavaScript asset contains `apexquant-v1.0.0` twice. It contains neither `ui_git_commit` nor `ui_build_id`, and no `apexquant-<12-hex-character>` source-derived UI build label. |
| Rendered Mission Control | The public route renders the older compact identity text `UI apexquant-v1.0.0 · API loading`. It does **not** render the corrected Product Version, UI Build, API Build, and MATCH/MISMATCH fields. |
| Cache and service worker | The public HTML and entry asset both return `Cache-Control: private` and `Last-Modified: Mon, 24 Aug 2026 11:29:58 GMT`. They name the same old asset. No `navigator.serviceWorker`, `serviceWorker`, or Workbox registration occurs in the served HTML or entry asset; direct probes for conventional service-worker URLs found no registered public worker. |

This rerun confirms that the public static dashboard has **not advanced** to
the corrected commit-derived build. The API identity is valid, but it cannot
truthfully be compared to the currently served UI artifact. A new
user-initiated dashboard publish is required before the source-derived UI
identity and MATCH/MISMATCH display can be confirmed in production.

## Automated post-publish smoke check

The dashboard now provides a read-only production smoke check:

```bash
APEXQUANT_PUBLIC_URL=https://your-app.replit.app \
  pnpm --filter @workspace/trading-dashboard run test:build-identity:public
```

It fetches the public dashboard HTML, resolves its referenced hashed Vite entry
asset, and requires a linked full UI commit plus
`apexquant-<12-character-commit>` identity. It rejects every retired identity,
including `apexquant-v1.0.0`, and reads `/api/health/details` only to compare
the source-derived API identity.

The check then opens the public `/trading-dashboard/mission-control` route in
headless Chromium and requires the rendered identity area to expose **Product
Version**, **UI Build**, **API Build**, and the truthful **MATCH** or
**MISMATCH** state. A failed identity check exits non-zero and prints cache
headers for the HTML/asset plus HTML/asset service-worker markers, conventional
worker-route probes, and browser service-worker registrations. It never sends
an order, command, mutation, or scan trigger.

## Final UI/API status

The currently live API identity is valid and commit-derived. The currently
served dashboard asset uses the retired semantic label, so it has no
source-derived UI identity and remains visibly actionable under the corrected
Mission Control UI.

No legitimate divergent UI source commit was evidenced; the existing served UI
cannot truthfully be compared to the API source commit. A dashboard publish is
needed to replace the retired asset. This report does not claim a coordinated
deployment is required to reconcile two legitimate divergent commits.

## Validation

Passed:

- Dashboard focused tests:
  `PORT=9999 BASE_PATH=/trading-dashboard/ pnpm --filter @workspace/trading-dashboard exec vitest run src/pages/MissionControl.freshness.test.tsx build.identity.test.ts`
  — 16 tests passed, including short-SHA rejection and a 12-character
  build-suffix assertion.
- Dashboard production asset check:
  `pnpm --filter @workspace/trading-dashboard run test:build-identity`
  — built a production bundle from a controlled exact commit and verified the
  full commit plus `apexquant-aaaaaaaaaaaa` were injected, with the retired
  label absent.
- Dashboard and API TypeScript checks — passed.
- API build/runtime identity tests:
  `pnpm --filter @workspace/api-server exec vitest run build.identity.test.ts src/lib/runtimeIdentity.test.ts`
  — 8 tests passed after full-SHA hardening, including short-SHA and
  retired/generic-label rejection.
- Root deployment handoff:
  `SOURCE_COMMIT=abcdef0 bash scripts/deploy-build.sh`
  — rejected before dependency installation with the full-40-character
  source-commit error.
- A local production dashboard build from the workspace source commit completed
  successfully; its hashed bundle contained
  `apexquant-dc419a6e61c9` and the full source commit, with the retired label
  absent.

Observed but outside this task:

- The broad dashboard test command ran 981 existing tests and reported 71
  failures in unrelated freshness-coverage and AI Validation V2 marker tests.
  The focused identity tests above pass; no unrelated pages were changed.

## Changed files

- `artifacts/trading-dashboard/buildIdentity.mjs`
- `artifacts/trading-dashboard/vite.config.ts`
- `artifacts/trading-dashboard/package.json`
- `artifacts/trading-dashboard/scripts/check-build-identity.mjs`
- `artifacts/trading-dashboard/.replit-artifact/artifact.toml`
- `artifacts/trading-dashboard/src/pages/MissionControl.tsx`
- `artifacts/trading-dashboard/src/pages/MissionControl.freshness.test.tsx`
- `artifacts/trading-dashboard/build.identity.test.ts`
- `artifacts/api-server/build.mjs`
- `artifacts/api-server/build.identity.test.ts`
- `scripts/deploy-build.sh`
- `MISSION_CONTROL_BUILD_IDENTITY_REPORT.md`

The existing API runtime-identity contract was intentionally not changed.