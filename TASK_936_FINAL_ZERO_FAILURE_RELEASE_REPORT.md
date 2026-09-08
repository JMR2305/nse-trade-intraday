# Task #936 — Final Post-Merge Zero-Failure Dashboard Gate

**Validation date:** August 25, 2026

## Final post-deployment verdict

**G. SAFETY / OBSERVABILITY REGRESSION**

The zero-failure pre-deployment gate passed and the release was published. The
post-deployment safety check found that Mission Control fails to display
production quote-provenance evidence that the API does provide. This blocks an
“deployed and verified” verdict until the display mismatch is corrected.

## Approved release candidate

- **Published UI/API build ID:** `apexquant-5b22ea84b68e`
- **Deployed source commit:** `5b22ea84b68e05b818f88e0d98ecdfd39090f1ab`
- **Publish marker commit:** `9d36bafc3a78da5fbc8d78a41c979beccfc5dab2`
- **Task #936 merge:** `ee6eb38e5003226f6b5c58e606067099f641f98b`
- The publish marker has no source-file delta from the deployed source commit.

## Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| Source identity | PASS | Task #936 merge is an ancestor of the approved commit. |
| Tracked source worktree | PASS | No tracked-file modifications or staged changes. |
| External upload state | NOT RELEASE CONTENT | The supplied validation checklist remains an untracked file under `attached_assets/`; it is not part of the approved commit. |
| Full dashboard suite | PASS | `51` files passed; `998` tests passed; `0` failed files; `0` failed tests. |
| Freshness coverage regression | PASS | `src/lib/freshness-coverage.test.ts` passed. |
| AI Validation marker regression | PASS | `src/pages/__tests__/AIValidationV2Page.markers.test.tsx` passed. |
| Mission Control focused coverage | PASS | Included in the completed full dashboard suite. |
| Dashboard TypeScript | PASS | `pnpm --filter trading-dashboard exec tsc --noEmit` passed. |
| API and workspace TypeScript | PASS | `pnpm exec tsc -b lib/api-client-react lib/api-zod lib/db artifacts/api-server` passed. |
| Dashboard production build | PASS | Passed with `PORT=9999 BASE_PATH=/trading-dashboard/`. Existing sourcemap, dynamic-import, and bundle-size notices are warnings, not build failures. |
| Source scope | PASS | Since the publish checkpoint, changes are confined to observability provenance, manual-scan auditability, freshness coverage, tests, UI, generated API types, and supporting reports. |
| Schema safety | PASS | No migration files, destructive DDL, `DROP`, `TRUNCATE`, or historical evidence rewrite found. |
| Trading/execution safety | PASS | No change enabling auto entries, bootstrap, controlled execution, live broker orders, or trading policy was found. |

## Post-deployment read-only verification

| Check | Result | Production evidence |
| --- | --- | --- |
| Deployment health | PASS | Public autoscale deployment has a successful build. |
| UI/API build identity | PASS | Mission Control displays `UI Build apexquant-5b22ea84b68e`, `API Build apexquant-5b22ea84b68e`, and `MATCH`. |
| Dashboard freshness coverage | PASS | Browser audit visited 41 registered routes: no missing indicators, no route errors, and one consistent scan ID (`e4707672`). |
| Active universe and mappings | PASS | `CUSTOM_LOW_PRICE_SECTOR` is active with 23 active symbols and 23/23 instrument mappings. |
| Execution barriers | PASS | Market is closed; automatic paper entries and bootstrap are false; broker mode is `PAPER_TRADING`; live-assisted readiness is `NOT_READY`; daily orders are zero. |
| Portfolio and ledger state | PASS — snapshot | Portfolio API uses the Phase 20 ledger; production snapshots are paper-mode with 0 open and 0 pending positions; all 6 Phase 20 trade records are closed. |
| Legacy manual scan | PASS | Scan `e1ded4dfba2e` remains one legacy manual canonical record with 23 requested/received symbols and an explicit unknown-legacy provenance object. |
| Future manual-scan provenance schema | PASS | Production history responses expose the sanitized provenance fields, including actor, request, correlation, approval, timestamp, trigger source, and legacy marker. |
| Truthful Mission Control price provenance | **FAIL** | `/api/live-data/health-v2` reports `ZERODHA_KITE`, `2026-08-25T09:53:23Z`, `MARKET_CLOSED_LAST_KNOWN`, `YFINANCE`, and `SCHEDULED`; the rendered Mission Control provenance cards all show `UNAVAILABLE / NOT PROVEN`. |

### Observed closed-market evidence

The API correctly preserves the distinction between current quote and historical
data:

- current quote provider: `ZERODHA_KITE`;
- recorded current quote timestamp: `2026-08-25T09:53:23Z`;
- freshness: `MARKET_CLOSED_LAST_KNOWN`;
- historical OHLCV provider: `YFINANCE`; and
- scan provenance: `SCHEDULED`.

Because the recorded quote timestamp exists, a closed-market last-known label is
valid. The rendered UI instead reports that all of this evidence is unavailable,
which is misleading.

## Scope review

The audited code changes cover:

- truthful current-price and historical-OHLCV provenance;
- safe manual-scan provenance and identifier handling;
- Mission Control provenance presentation;
- route-level dashboard freshness coverage;
- test coverage and generated API-client types; and
- release, validation, and audit documentation.

The provenance work touches scheduler/store code only to record and sanitize
audit metadata. It does not alter trade execution, readiness decisions,
portfolio/ledger data, universe settings, or broker-order behavior.

## Safety boundaries preserved

- No scans, retries, replays, Phase 5A/5B/5C actions, or broker calls were
  triggered during this validation.
- Automatic entries and bootstrap remain disabled.
- Controlled execution remains disabled.
- Live broker orders remain disabled.
- The portfolio, ledger, universe, and settings were not modified.
- Historical scan `e1ded4dfba2e` and Task #930 evidence were not changed or
  backfilled.

## Required remediation and recheck

Task #939, **Prevent Mission Control from hiding recorded closed-market quote
provenance**, must reconcile the health response with the rendered Mission
Control cards. After that focused fix is published, repeat only the read-only
production checks in the table above. Do not trigger scans, change settings, or
alter Task #930 evidence as part of the recheck.