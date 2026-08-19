# ApexQuant AI — Public Build ID Label Fix Report

## Scope and safety

This change only corrects build-identity metadata shown by Mission Control.
It does not modify trading logic, scan logic, paper-trading controls, or broker
execution. Live orders remain disabled and the application remains paper-only.

## Root cause

Mission Control displayed:

```text
UI development · API 1 · Build mismatch
```

The label was not evidence of a development bundle in production. The
dashboard is deployed as static Vite assets, and its production build received
no build-ID environment variable. Vite therefore embedded its intended
development fallback into the browser bundle. The API is a runtime service and
did receive Replit's deployment identifier, so it reported `1`.

## Corrected build identity contract

Both production artifacts now receive the same explicit release identifier:

```text
APEXQUANT_BUILD_ID=apexquant-v1.0.0
```

- The dashboard receives it in the production **build** environment and embeds
  it in the static browser bundle.
- The API receives it in its production build and runtime environments and
  reports it in `api_build_id`.
- Both surfaces prefer `APEXQUANT_BUILD_ID` over platform deployment IDs.
- Development keeps the explicit `development` label.
- If production metadata is unexpectedly absent, either surface reports
  `production-unidentified` rather than incorrectly calling itself
  `development`.
- Mission Control still uses an exact ID comparison. A genuine difference
  remains a visible, actionable **Build mismatch** warning.

## Verification before publish

| Check | Result |
| --- | --- |
| Production-mode Vite build | Passed |
| Compiled browser bundle contains `apexquant-v1.0.0` | Passed |
| Compiled browser bundle contains `production-unidentified` | Not present |
| Mission Control freshness test | 6 passed |
| Dashboard typecheck | Passed |
| Focused API scan-cache test and API typecheck | 6 passed |
| Restarted development API build label | `development` |

One attempted broad dashboard test command ran unrelated legacy suites and
reported pre-existing freshness-coverage failures outside this metadata change.
The focused Mission Control test for the changed behavior passed.

## Required public verification after publish

After publishing, verify the production API returns:

```text
api_build_id: apexquant-v1.0.0
```

Then verify the public Mission Control page shows:

```text
UI apexquant-v1.0.0 · API apexquant-v1.0.0 · Builds match
```

If a deployment supplies different identifiers in the future, Mission Control
will retain the red mismatch state with an investigation hint rather than
hiding the difference.