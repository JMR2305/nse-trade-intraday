# Task 949 — Runtime Identity and Safety

## Approved release identity

- `APPROVED_RELEASE_COMMIT = 68f18b078fe9de37da175480d40d4d42ae727830`
- `EXPECTED_BUILD_ID = apexquant-68f18b078fe9`
- Release branch: `release/task949-clean`
- Verified production parent: `c8b2a08bf14f227a38c8cdb6f9a75c223f7893bc`

Only the approved release commit may be published. The mixed audited head `194972de208fc7ef4aa2073637219f7523ff580b` must not be published.

## Task 947 preservation

Task 938 does not change any Task 947 pre-open source or test file. Exact source comparison confirms no semantic conflict with:

- automatic collection from 09:00 IST until, but not including, 09:12 IST;
- the 09:08–09:12 IST naturally scheduled final-proof window;
- 09:15 IST exact-batch freeze authority;
- `SCHEDULED` versus `MANUAL` origin semantics;
- strict freshness where age `< 300` seconds is fresh and age `>= 300` seconds is stale;
- provider scope `ALL`;
- active-universe authority.

## Task 938 behavior

After a successful versioned universe activation, the server invalidates scanner coverage cache state and advances its generation. A delayed pre-activation response may still complete for its original caller, but it cannot become the next cached result for the newly active universe.

Failed activation responses do not invalidate coverage. Retired universe mutation routes remain unable to change coverage state.

## Exact runtime delta from production

- `artifacts/api-server/src/routes/universe-management.ts`

The accompanying test file is not runtime code.

## Safety invariants

Release preparation did not:

- trigger Phase 5A, Phase 5B, or Phase 5C;
- trigger a market scan;
- collect or freeze pre-open evidence manually;
- activate or edit a universe;
- enable automatic entries;
- enable bootstrap mode;
- enable controlled execution;
- enable live broker orders;
- change settings;
- mutate portfolio or ledger state;
- publish or deploy.

## Post-publish read-only verification

Performed against `https://nse-trade-intraday.replit.app` on 28 August 2026.

### Passed

- `environment = production`
- `git_commit = 68f18b078fe9de37da175480d40d4d42ae727830`
- `build_id = apexquant-68f18b078fe9`
- `deployment_id = 0d018179-abe0-42c2-a554-dbb19d11341f`
- Task 947 source is present because the deployed commit is the exact approved tree.
- Task 938 source is present because the deployed commit is the exact approved tree.
- `auto_paper_entries = false`
- `auto_paper_entries_confirmed_at = null`
- `bootstrap_paper_enabled = false`
- controlled paper entry returns `DISABLED`, `dry_run_only = true`, and `execution_allowed = false`
- broker execution mode is `PAPER_TRADING`
- broker readiness is `NOT_READY` for real execution
- Kite reports `live_order_placement_enabled = false`
- portfolio reports `paper_mode = true`, `status = DISABLED`, and source `phase20_ledger`
- two read-only portfolio observations were financially identical: no open positions, cash/equity ₹99,721.26, realised P&L -₹278.74

The public health field `automatic_paper_entry_allowed = true` describes the market-hours window, not the durable auto-entry setting. The authoritative Phase 20 setting and portfolio health both report automatic paper entries disabled.

### Failed

- The durable setting names `CUSTOM_LOW_PRICE_SECTOR`, but the versioned universe API reports zero revisions and `active_revision = null`.
- Scanner coverage returns `success = false`, `coverage = null`, and `revision_not_found`.
- `/api/health/ready` reports `scanner_coverage_ok = false`.
- Pre-open status is `ERROR`; pre-open health is `UNIVERSE_UNAVAILABLE`.
- Therefore active count and mapping coverage cannot be certified as 23/23 from the authoritative current universe store.

The public health details still show the prior 23-symbol scan snapshot and 100% token coverage, but that historical snapshot is not current universe authority and cannot satisfy this gate.

## Final verdict

`F. SAFETY REGRESSION`

Identity and execution controls pass, but the production universe authority is unavailable. No natural-session certification may start until a separate, explicitly approved remediation restores and verifies the immutable versioned universe without triggering scans or trading.