# Mission Control Provenance Fix and Release

**Task:** #940 — Show verified quote provenance in Mission Control  
**Report date:** August 26, 2026  
**Scope:** Mission Control health-response presentation and directly related tests only

## Final verdict

A. PASS — PROVENANCE DISPLAY FIXED AND VERIFIED

The approved completion commit was published and every required production
check passed through read-only requests and a no-click browser audit.

## Exact binding trace

| Stage | Source / transformed field | Evidence |
| --- | --- | --- |
| Authoritative API | `GET /api/live-data/health-v2` → `market_data_readiness.current_quote_provider`, `current_quote_timestamp`, `current_quote_freshness`, `historical_ohlcv_provider`, `scan_provenance_state` | The endpoint returns the canonical nested health object. Production evidence contains `ZERODHA_KITE`, `2026-08-25T09:53:23Z`, `MARKET_CLOSED_LAST_KNOWN`, `YFINANCE`, and `SCHEDULED`. |
| API client | `apiJson()` preserves the JSON envelope without renaming or flattening fields | No snake/camel conversion, object spread, generated-type drift, or old-response normalization is present. |
| Page query | `customUniverseMarketDataHealthQ` stores `LiveDataHealthResponse` from `/live-data/health-v2` | The query reads the endpoint once per configured poll and never triggers a scan. |
| Card prop | `marketDataHealthQ.data.market_data_readiness` is passed to the provenance summary | After the response settles, the populated nested values reach the card unchanged. |
| Original failing condition | Before that GET completes, `marketDataHealthQ.data` is undefined; the prior `if (!readiness)` branch emitted `UNAVAILABLE / NOT PROVEN` for every card | The live endpoint takes several seconds in the development/production environment. This was the first point where displayed values were lost: a loading state was falsely presented as unavailable evidence. |
| Corrected rule | The card now presents an explicit loading state until the health response arrives; after it arrives, only explicit valid provider, timestamp, and freshness fields are rendered as current-quote provenance | Connection state, mapping coverage, scan time, and fallback counts cannot fabricate a current quote. |

## Presentation rules now enforced

- A valid `ZERODHA_KITE` provider, recorded timestamp, and
  `MARKET_CLOSED_LAST_KNOWN` freshness display as:
  - Current Quote Provider: `ZERODHA_KITE`
  - Last Quote: exact recorded timestamp
  - Quote Freshness: `MARKET CLOSED / LAST KNOWN`
- `YFINANCE` is rendered exactly when it is the explicit current provider.
- Historical OHLCV and scan provenance use their own explicit API fields and
  remain independent from current-quote provenance.
- Missing provider, missing timestamp, malformed timestamp, missing freshness,
  or explicit unavailable evidence display `UNAVAILABLE / NOT PROVEN` for the
  current-quote fields.
- A connected Kite session or complete Kite coverage alone cannot imply a Kite
  quote source or a `LIVE` freshness label.
- The market-open path displays only the authoritative provider, timestamp, and
  freshness returned by the API.

## Runtime changes

- `artifacts/trading-dashboard/src/pages/MissionControl.tsx`
  - Adds explicit evidence/timestamp validation and a loading presentation.
  - Removes provider and freshness inference from Kite connection and coverage
    counters.
  - Leaves API semantics, provider selection, readiness, trading, portfolio,
    universe, settings, and lifecycle behavior unchanged.
- `artifacts/trading-dashboard/src/pages/MissionControl.custom-universe.test.tsx`
  - Adds direct coverage for closed-market Kite and Yahoo records, a market-open
    record, provider/timestamp/malformed/unavailable cases, loading behavior,
    separate historical and scan provenance, and non-inference from Kite
    connection.

No API routes, Python health logic, generated API types, schema, trading logic,
or provider policy changed.

## Validation results

| Gate | Result | Evidence |
| --- | --- | --- |
| Focused Mission Control tests | PASS | 2 files, 22 tests passed. |
| Full dashboard Vitest | PASS | 51 files, 1000 tests passed, 0 failures. |
| Dashboard TypeScript | PASS | `pnpm --filter @workspace/trading-dashboard exec tsc --noEmit` completed successfully. |
| Shared/API/workspace TypeScript | PASS | `pnpm exec tsc -b lib/api-client-react lib/api-zod lib/db artifacts/api-server` completed successfully. |
| Dashboard production build | PASS | Build completed with existing sourcemap, dynamic-import, and bundle-size warnings only. |
| Browser verification | PASS | The live development page received the nested health response and rendered matching card values with no page or browser-console errors. |
| Source scope | PASS | Runtime changes are limited to Mission Control provenance rendering and its direct test file. |

### Browser contract confirmation

The local browser received:

```text
market_data_readiness.current_quote_provider = YFINANCE
market_data_readiness.current_quote_timestamp = null
market_data_readiness.current_quote_freshness = UNAVAILABLE_NOT_PROVEN
market_data_readiness.historical_ohlcv_provider = YFINANCE
market_data_readiness.scan_provenance_state = SCHEDULED
```

It rendered:

```text
Current quote provider = UNAVAILABLE / NOT PROVEN
Last quote = UNAVAILABLE / NOT PROVEN
Quote freshness = UNAVAILABLE / NOT PROVEN
Historical OHLCV = YFINANCE
Scan provenance = SCHEDULED
```

This proves unavailable current-quote evidence does not erase separate
historical or scan provenance.

## Safety boundaries

- No scans, retries, replays, Phase 5A/5B/5C actions, broker calls, portfolio
  actions, universe changes, settings changes, or Task #930 evidence changes
  were triggered.
- Automatic paper entries, bootstrap, controlled execution, and live broker
  orders were not enabled or modified.
- Legacy manual scan `e1ded4dfba2e` was not changed or backfilled.

## Controlled publish and post-deployment verification

**Published commit:** `fa612a219c2ca2aa682e5af58b051e2da4425c16`
**Published build ID:** `apexquant-fa612a219c2c`
**Production URL:** `https://nse-trade-intraday.replit.app`

| Required check | Result | Read-only production evidence |
| --- | --- | --- |
| Exact approved build published | PASS | `/api/health/details` reports the full approved commit and `apexquant-fa612a219c2c`. |
| UI/API build identity | PASS | Mission Control renders `UI Build apexquant-fa612a219c2c`, `API Build apexquant-fa612a219c2c`, and `MATCH`. |
| Authoritative health provenance | PASS | `/api/live-data/health-v2` returned `ZERODHA_KITE`, `2026-08-25T09:53:23Z`, `MARKET_CLOSED_LAST_KNOWN`, `YFINANCE`, and `SCHEDULED` under `market_data_readiness`. |
| Rendered Mission Control provenance | PASS | After both health GETs settled, the five provenance cards rendered `ZERODHA_KITE`, the exact recorded timestamp, `MARKET CLOSED / LAST KNOWN`, `YFINANCE`, and `SCHEDULED`. No browser console or page errors occurred. |
| Active universe and mappings | PASS | `CUSTOM_LOW_PRICE_SECTOR` remains active with 23 active symbols and 23/23 complete active mappings. |
| Paper and execution safety | PASS | Phase 20 has automatic paper entries and bootstrap disabled; broker mode is `PAPER_TRADING`; live-assisted readiness is `NOT_READY`; daily broker orders are zero; controlled paper entry is disabled at the route boundary with `execution_allowed: false`. |
| Portfolio and ledger | PASS | The Phase 20 ledger remains paper-mode with zero open positions and six closed trades, matching the prior release snapshot. |
| Legacy manual scan | PASS | Production database read-only query confirms `e1ded4dfba2e` remains `MANUAL`, `SUCCESS`, with 23 requested and 23 received symbols. |
| Task #930 / pre-open evidence | PASS | A read-only production database query found zero `preopen_sessions` updates after the deployed process started; no pre-open lifecycle was triggered. |
| No validation mutation | PASS | The audit used GET requests, a production browser with no clicks, and read-only SQL only. Scan status stayed at scheduled scan `e4707672dda6`; no scan, retry, replay, broker, portfolio, universe, or settings mutation was sent. |