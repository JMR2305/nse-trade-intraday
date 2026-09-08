# RTV-1C — Production Authority Reconciliation

## Target environment

| Field | Value |
|---|---|
| API base URL | `https://nse-trade-intraday.replit.app` |
| Deployment type | public Autoscale |
| Development branch | `rtv1-market-data-portfolio-truth` |
| Development commit | `d14b81e36af38f79d9e309b8df8fc76db3786dbd` |
| Production build/commit identifier | **not exposed by the production API or deployment metadata** |
| Production process start estimate | 2026-08-21T20:16:13Z (derived from `/api/health/details` uptime; not a build timestamp) |
| Runtime identity contract | absent: no production endpoint reports environment, deployment/build ID, or git commit |

All runtime and database checks in this report targeted production. No localhost or development API result was used as production truth.

## Executive verdict

### Production is behind RTV-1 development — code and configuration differ

The production response surface demonstrates that it does not contain the complete RTV-1 runtime behavior:

- `/api/live-data/health-v2` has no `market_data_readiness` object, while the current source includes it in the RTV-1 change set `c91e476090e4761c9841fde27794963dd53b6448`.
- `/api/portfolio` correctly reports `source=phase20_ledger`, but `/api/portfolio/snapshot` reports `position_source=portfolio_service` and returns an empty local snapshot. Current source maps the canonical Phase-20 ledger into the snapshot path.
- The production build does not emit a commit/build identity, so its exact commit cannot be proven. The observable behavior is nevertheless sufficient to classify it as behind the RTV-1 implementation.

No deployment was performed.

## Safety state preserved

| Control | Production result |
|---|---|
| Kite authentication | valid, stored, connected; read-only quotes successful |
| Live broker order placement | disabled |
| Automatic paper entries | disabled |
| Bootstrap paper trading | disabled |
| Automatic paper exits | enabled |
| Paper mode | enabled |
| Portfolio reset | not performed |
| Universe change | not performed |
| Historical rows | not modified |

## 1. Production active-universe authority

### Classification: C — different modules use different universes across time

The current production authority is the persisted Phase-20 setting:

| Evidence | Value |
|---|---|
| `phase20_settings` row | id `1` |
| Current active setting | `CUSTOM_LOW_PRICE_SECTOR` |
| Setting updated | 2026-08-21T17:40:14.649598Z |
| Last updater | not recorded in the table |
| Current master | `custom_universe_master` |
| Current active count | 23 |
| Sectors | BANK 9, INFRA 13, IT 1 |
| IT member | WIPRO |

Current development source resolves the scanner universe from the persisted Phase-20 setting, then reads active custom-universe rows when the mode is `CUSTOM_LOW_PRICE_SECTOR`. The scheduler follows that same setting before asking the live scan engine to scan.

The last **data-bearing** production scan, `76e307f291e7`, completed at 2026-08-21T10:17:25Z and requested/received 50 symbols. It occurred before the custom setting was updated at 17:40:14Z. Weekend scheduler rows correctly contain no symbol payload because the market is closed. Therefore:

- `NIFTY_50` is not merely a development-only setting; it is the historical universe of the latest actual production scan.
- `CUSTOM_LOW_PRICE_SECTOR` is the current persisted production authority.
- The next open-session scan is required to prove that the scheduler has picked up the now-current 23-symbol setting.

The active list is:

```text
BANKBARODA, BANKINDIA, CANBK, FEDERALBNK, IDFCFIRSTB, KTKBANK,
MAHABANK, PNB, UNIONBANK, COALINDIA, GAIL, HUDCO, IRCON, IRFC,
MRPL, NBCC, NMDC, NTPC, PFC, RECLTD, RVNL, SAIL, WIPRO
```

## 2. Kite instrument hydration and quote provenance

### Approved reference-data refresh

The approved `POST /api/kite/instruments/refresh` route was invoked once. It has no order capability and only refreshed the daily instrument reference cache.

| Check | Result |
|---|---|
| Refresh result | success |
| Cache session date | 2026-08-23 |
| Cache refresh timestamp | 2026-08-23T14:36:31Z |
| Instrument rows fetched | 10,222 |
| Cache freshness | fresh |
| Active custom symbols | 23 |
| Active custom mappings with token | 0 |
| Missing mappings | 23 |
| Duplicate active mappings | 0 |
| Active-universe token coverage | **0 / 23 (0%)** |

The refresh repaired the global cache, but did not propagate mappings into `custom_universe_master.instrument_token`. The canonical custom scan and the Kite LTP overlay currently operate by symbol, so the missing metadata did not prevent quote retrieval. Calling `/api/universe/custom/refresh` was deliberately avoided because it recomputes and writes the active universe, which this task forbids before a root cause is established.

### Quote plumbing

Every active symbol returned a read-only `kite_live` quote at 2026-08-23T14:36:34Z. The complete symbol-level evidence, including sector, mapping presence, LTP, provenance, fallback state, and reliability is in:

- `RTV1C_PRODUCTION_MARKET_DATA_COVERAGE.csv`

This was a weekend check. It proves quote-provider plumbing, **not** session-fresh market data for the next trading session.

## 3. Portfolio root-cause reconciliation — P0

### Authoritative verdict: A — `/api/portfolio` is correct; `/api/portfolio/snapshot` is stale/wrong

The raw production Phase-20 ledger contains six `CLOSED` rows, zero `OPEN` or `EXIT_PENDING` rows, and sums to realized P&L of **₹-278.74**:

```text
0.00 - 12.60 + 7.66 - 273.80 + 0.00 + 0.00 = -278.74
```

There are no open positions and therefore no current invested amount or unrealized P&L. The ledger reconstruction is:

```text
initial capital      ₹100,000.00
realized P&L             -278.74
open cost                    0.00
unrealized P&L               0.00
cash / equity            ₹99,721.26
```

The single largest component is the 20-share DRREDDY close:

```text
entry  ₹1,193.79 × 20
exit   ₹1,180.10 × 20
price P&L = ₹-273.80
```

The recorded `est_charges` and `slippage` fields are evidence metadata. The current production ledger’s `realized_pnl` and the main portfolio cash calculation both use the stored price P&L total; they do not apply estimated charges a second time.

| Path | Runtime service/store | Result |
|---|---|---|
| `/api/portfolio` | Node trading route → Python `portfolio` → `canonical_portfolio` → `phase20_paper_trades` | cash ₹99,721.26; realized ₹-278.74; correct |
| `/api/portfolio/snapshot` | Node portfolio route → Python `portfolio_snapshot` → `portfolio_service` / `portfolio_snapshots` | cash/equity ₹100,000; realized ₹0; wrong for this ledger |

The snapshot’s latest durable payload was created after the ledger closes, but still says `state_version=1`, `cash.source=local`, `current_equity=100000`, and no realized history. This excludes the possibility that the endpoints are merely showing different valid scopes. It is a stale, empty portfolio-service snapshot.

The detailed comparison and every contributing trade are in:

- `RTV1C_PRODUCTION_PORTFOLIO_RECONCILIATION.csv`

## 4. RTV-1 deployment and readiness-contract drift

The current source change `c91e476090e4761c9841fde27794963dd53b6448` implements the RTV-1 market-data and canonical-portfolio corrections. Production lacks its consolidated readiness response and retains the old snapshot behavior.

| RTV-1 claim | Production evidence | Status |
|---|---|---|
| Phase-20 ledger canonical | main portfolio endpoint reads it | partially deployed |
| Snapshot unified with ledger | snapshot returns legacy/local empty data | not deployed / divergent |
| Dynamic capital authority | main endpoint uses ₹100,000 and ledger math | present on main endpoint |
| `market_data_readiness` health contract | field absent from production `health-v2` and health details | not deployed / divergent |

The exact deployed commit cannot be named until a non-secret production identity field is added. The behavior establishes **production behind RTV-1 development**, not merely configuration drift.

## 5. Persistence hardening recommendation

The current source still allows `kite_token_store._db_save()` to suppress a durable-store failure. The smallest safe future patch is:

1. Make durable KV write/delete outcome observable and fail the operation on error.
2. Require a successful authoritative KV write before redirecting the login callback to success.
3. Treat the chmod-0600 local file as a warm cache only, not Autoscale-safe persistence.
4. Confirm durable deletion before reporting a completed disconnect.
5. Keep access-token and secret values out of results and logs.

Required focused tests: failed durable save, failed durable clear, callback failure on non-durable save, fresh-process DB reload, expired record behavior, and no secret disclosure.

This patch was **not** implemented because it is already tracked by queued task #905, and the current production session is healthy.

## 6. Runtime identity contract to add before future RTV checks

Production diagnostics need a non-secret identity object:

```json
{
  "environment": "production",
  "build_id": "<build-time identifier>",
  "git_commit": "<build-time commit>",
  "deployment_id": "<deployment identifier when available>",
  "instance_id": "<ephemeral instance label>",
  "runtime_timestamp": "<UTC ISO-8601>"
}
```

It must be injected from build/runtime metadata, never derived from or used to reveal secrets. Until this exists, every RTV report should lead with target URL and state that production commit identification is unavailable.

## 7. Fixes made and intentionally not made

### Made

- Performed one approved, read-only Kite instrument-master refresh.
- Captured live read-only Kite quote provenance for all 23 active production symbols.
- Created the four RTV-1C evidence artifacts.

### Not made

- No portfolio code change, reset, ledger edit, capital change, or deletion.
- No universe switch, custom-universe recompute, threshold change, strategy change, or scheduler change.
- No automatic-entry, bootstrap, or live-trading enablement.
- No broker order placement/modification/cancellation.
- No deployment.
- No persistence hardening patch; task #905 is already queued.
- No portfolio endpoint patch; task #906 is already in progress.

## 8. Tests and remaining gates

Focused regression suite:

```text
165 passed, 2 non-blocking datetime deprecation warnings
```

Covered current-source token/session behavior, token-store integration, market-data readiness, Kite LTP overlay, portfolio snapshot source selection, and portfolio contracts.

Before any paper-entry discussion:

1. Deploy the verified RTV-1 portfolio/readiness corrections through the approved publish flow.
2. Re-run production portfolio parity: `/api/portfolio == /api/portfolio/snapshot` for shared financial fields, preserving the ₹-278.74 history.
3. Implement and deploy custom-universe token-map propagation, then require 23/23 valid mappings.
4. Observe a next-open-session production scan using `CUSTOM_LOW_PRICE_SECTOR` and prove fresh provenance for every active symbol.
5. Add runtime environment/build identity so deployed commit comparisons are evidence-based.

No user decision is needed to preserve current historical P&L. A user decision is required before switching the active universe back to `NIFTY_50`.