# RTV-1D — Controlled Deployment Report

## Verdict

**DEPLOYMENT VERIFICATION FAILED — production commit mismatch / unapproved runtime**

The approved RTV-1D source candidate was committed as `3ca36c4847c6309149aaf78a94da87b529034881`.
The post-publish production response reported `git_commit: "unknown"` and
`build_id: "apexquant-v1.0.0"`, so the deployed source cannot be proven to be
the approved candidate. Per the control procedure, verification stopped at the
runtime-identity gate.

This report does **not** claim RTV-1D production pass. No order endpoint,
trade trigger, universe refresh, portfolio reset, or configuration mutation was
performed during the failed verification.

## Deployment context

| Field | Result |
|---|---|
| API base URL | `https://nse-trade-intraday.replit.app` |
| Deployment type | Public Autoscale |
| Development branch before publish | `rtv1-market-data-portfolio-truth` |
| Approved source commit | `3ca36c4847c6309149aaf78a94da87b529034881` |
| Pre-publish source status | Source tree clean; the controlling RTV-1D attachment remained an untracked workspace file |
| Post-publish workspace checkpoint | `c1fffc86` (`Published your App`) |
| Production reported git commit | `unknown` |
| Production reported build ID | `apexquant-v1.0.0` |
| Production deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Production instance ID | `nse-trade-intraday.replit.app` |
| Production runtime timestamp | `2026-08-23T20:50:47.518Z` |
| Deployment verification | **FAILED — exact deployed commit does not match the approved source** |

The post-publish workspace checkpoint is not accepted as proof of the
production runtime commit. The API itself is the authority for this check, and
its reported commit was `unknown`.

## Scoped source changes in the approved candidate

Only the following eight source files were committed in the RTV-1D candidate:

- `artifacts/api-server/build.mjs`
- `artifacts/api-server/src/lib/runtimeIdentity.ts`
- `artifacts/api-server/src/lib/runtimeIdentity.test.ts`
- `artifacts/api-server/src/routes/health.ts`
- `artifacts/api-server/src/python/custom_universe_store.py`
- `artifacts/api-server/src/python/main.py`
- `artifacts/api-server/src/python/tests/unit/test_custom_universe_store.py`
- `artifacts/api-server/src/python/test_paper_capital_migration.py`

The changes add non-secret build/runtime identity, hydrate only instrument
reference metadata for the existing active custom universe, invoke hydration
after the existing instrument-cache refresh, and make the database-admission
test independent of the wall-clock market session. They do not change strategy,
thresholds, universe membership, capital, broker mode, or order behavior.

## Pre-deployment verification

| Gate | Result |
|---|---|
| Targeted Python gates | 184 passed |
| Targeted TypeScript tests | 28 passed |
| API-server typecheck | Passed |
| Full configured TypeScript checks | Passed |
| Paper analytics smoke | 5 passed; one existing datetime deprecation warning |
| Broader portfolio/reconciliation/pre-open/admission suite | 246 passed, 5 skipped, 1 warning, 11 subtests passed |
| Phase-20 status tests | 33 passed, 1 warning |
| RTV-1 portfolio-truth tests | 5 passed, 1 warning |
| API build | Passed |
| Static diff check | Passed |
| Pre-existing unrelated suite issue | `test_phase20.py` has 38 import-contract failures because legacy tests patch symbols no longer exposed by `phase20_exits.py`; those modules were not part of RTV-1D |

The admission fixture correction was not a production safety relaxation. It
explicitly mocked the market-entry state to `OPEN` so the test reaches and
asserts the database-unavailable fail-closed branch.

## Production observations

### Runtime identity

| Field | Pre-deploy candidate | Production observation |
|---|---|---|
| Environment | development build | `production` |
| Git commit | `3ca36c48…` | `unknown` |
| Build ID | `apexquant-phase0c-20260821` locally | `apexquant-v1.0.0` |
| Deployment ID | local/unknown | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Instance ID | `repl` locally | `nse-trade-intraday.replit.app` |
| Runtime timestamp | local request identity present | `2026-08-23T20:50:47.518Z` |

Because the commit identity failed, no further post-deployment verification
was treated as evidence that the approved candidate was running.

### Kite session

| Check | Pre-deploy known state | Production observation |
|---|---|---|
| `credentials_present` | true | true |
| `token_status` | VALID | VALID |
| `token_stored` | true | true |
| `connected` | true | true |
| Read-only session health | healthy | `health-v2` reported connected and session-fresh |
| Orders | disabled / not called | no order endpoint called |

### Universe and token coverage

| Check | Pre-deploy known state | Production observation |
|---|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | `CUSTOM_LOW_PRICE_SECTOR` |
| Active count | 23 | 23 |
| Sector counts | BANK 9, INFRA 13, IT 1 | BANK 9, INFRA 13, IT 1 |
| Global instrument cache | 10,222 rows in the approved refresh | production status showed 1 row dated 2026-08-09 and stale |
| Active custom mappings | 0/23 before candidate | 0/23 in production response |
| Duplicate active mappings | 0 in prior evidence | not re-certified after the identity failure |

The symbols endpoint returned 26 total rows: 23 active rows and three inactive
historical rows. The 23 active rows retained the expected membership and
sectors, but their `instrument_token` values were null in the production
response.

### Portfolio and snapshot parity

The two production endpoints did reconcile at the time of the read-only
check:

| Shared field | `/api/portfolio` | `/api/portfolio/snapshot` |
|---|---:|---:|
| `initial_capital` | 100000 | 100000 |
| `cash` | 99721.26 | 99721.26 |
| `equity` / `total_equity` | 99721.26 | 99721.26 |
| `realized_pnl` | -278.74 | -278.74 |
| `unrealized_pnl` | 0 | 0 |
| `total_pnl` | -278.74 | -278.74 |
| `open_position_count` | 0 | 0 |

The six-row raw-ledger evidence captured before deployment sums to
`-278.74`, with cash/equity `99721.26`. A new raw-row comparison was not
performed after the commit mismatch because the procedure required stopping.
No ledger mutation was performed by this verification.

### Readiness contract

Production exposed a readiness object, but it reflected the legacy 50-symbol
scan context rather than a verified 23-symbol post-deploy hydration:

- `service_ready=true`
- `data_ready=true`
- `session_fresh=false` in the market-data readiness object
- `trading_data_ready=false`
- `active_universe_count=50`
- `valid_token_count=1`
- `missing_token_count=49`
- `token_coverage_pct=2`
- `symbols_synthetic=0`
- `symbols_fallback=0`
- latest quote timestamp was null
- market timestamp was stale

This is correctly fail-closed for trading readiness and is not a live-session
failure by itself. It does, however, prevent certifying the required
23-symbol post-deploy market-data state.

## Safety state

Production settings remained unchanged in the read-only response:

- paper mode enabled
- automatic paper entries disabled
- bootstrap disabled
- automatic exits enabled
- no live-broker enablement action or order call occurred
- active universe `CUSTOM_LOW_PRICE_SECTOR`
- initial capital basis `100000`
- historical realized P&L `-278.74`
- no open positions

## Remaining blockers

1. Re-publish the approved candidate and obtain a production runtime identity
   whose `git_commit` exactly matches
   `3ca36c4847c6309149aaf78a94da87b529034881`.
2. Do not enable automatic entries, bootstrap, or live broker orders.
3. After an exact identity match, re-run the stopped checks: 23/23 mappings,
   read-only quote provenance, raw six-row ledger comparison, and safety/readiness
   reconciliation.
4. Keep next-open-session checks pending; the current closed/stale market state
   does not prove fresh scan or quote timestamps.

## Final classification

**RTV-1D CODE: candidate verified locally.**
**RTV-1D PRODUCTION: verification failed because the production commit is
unidentified and does not match the approved source.**
**Trading activation: not performed and remains disabled.**