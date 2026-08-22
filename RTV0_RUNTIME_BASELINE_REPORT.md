# RTV-0 Runtime Truth Verification Baseline

Scope: read-only runtime and database verification only. Baseline: Sunday 2026-08-23 around 03:35 to 03:40 IST. NSE state: WEEKEND / CLOSED. Branch: phase4a-controlled-paper-entry-framework-disabled. Commit: 56c7f99489d08c5d9b255794c92a73eb44325871.

No fixes, configuration changes, broker calls, trades, scans, pre-open jobs, reconciliation, resets, database writes, schema changes, restarts, deployment, or publication were performed. Production database was not queried.

## Executive truth

1. Active runtime universe is NIFTY_50 with 50 symbols, not the populated CUSTOM_LOW_PRICE_SECTOR candidate universe with 23 symbols.
2. Latest canonical scan is 8ea114ecb962 at 2026-08-21T09:55:44Z, 50 requested and received, provider Yahoo Finance history because Zerodha login is unavailable. It is stale for current-session decisions.
3. Kite session is not valid: runtime status says credentials_present false, token_status MISSING, connected false and LOGIN_REQUIRED. Secret names being provisioned does not prove runtime loading.
4. Instrument cache is stale from 2026-08-09 and covers RELIANCE only. Forty-nine active symbols lack a cached Kite token.
5. Canonical main portfolio reconciles at 100000 INR, zero open positions and zero PnL. A separate disabled portfolio snapshot reports 50000 INR and 50 percent drawdown.
6. Scheduler safe weekend behavior is confirmed: scheduled_scan_tick creates non-market heartbeats and does not run a market scan.
7. Readiness 90.18 A+ does not mean current data is fresh: data quality is 56.25 and session freshness is false off-hours.

## Deliverables

- RTV0_MARKET_DATA_PROVENANCE.csv: one row for every active symbol with actual source, price field, freshness, fallback and Kite-token coverage.
- RTV0_RUNTIME_DATABASE_INVENTORY.csv: every observed public table with row count, latest timestamp and authority class.
- RTV0_PORTFOLIO_RECONCILIATION.csv: canonical, independent, legacy, broker and divergent snapshot comparison.
- RTV0_RUNTIME_AUTHORITY_MAP.md: runtime authority, concurrency and topology map.

## Tasks 1 to 4: topology, scans, provider provenance and synthetic-data decision

- Task 1: API workflow runs as Node; Python is on-demand through subprocess calls. Dashboard, mobile Expo, document hub, project video and sandbox workflows were running.
- Task 2: Scheduler statically dispatches scheduled_scan_tick every minute. Runtime phase20_scan_runs shows SCHEDULER / SYSTEM_HEARTBEAT / NON_MARKET / SUCCESS rows with market_not_open. Configured market scan interval is four minutes.
- Task 3: The latest market scan is Friday 2026-08-21. Scan state records Yahoo Finance History with no active Zerodha session. daily_ohlcv_cache is warm for 50 symbols and post-market refresh succeeded 50 of 50 on Friday.
- Task 4 synthetic-data verdict: D. Unable to verify. Stored data_quality LIVE does not prove all prices/bars are live-originated; current path is yfinance/cache fallback and stale. No positive mock-data evidence was found, but none was invented.

## Tasks 5 to 7: freshness, scheduler, health

- Task 5: market context computed 2026-08-21T09:56:32Z; scan snapshot 2026-08-21T09:55:44Z; latest OHLCV post-market refresh finished 2026-08-21T10:00:56Z. Embedded timestamps, not later cache-file mtime, determine freshness.
- Task 6 5A: latest Friday preopen session RECONCILED_0930 with 0 symbols. 5B: Friday COMPLETE, 10 total and 10 valid. 5C: Friday ACTIVE with 0 generated, approved, paper trades and rejections. Provider-health has a Sunday row claiming NSE Official 50 symbols/data age zero, inconsistent with persisted 5A session content.
- Task 7: health ready and coverage ok are off-hours state semantics; /api/live-data/coverage explicitly has scan_fresh_for_session false.

## Tasks 8 to 11: capital, reconciliation, authority, concurrency

- Task 8 observed settings: capital 100000 INR, auto entries false, bootstrap false, auto exits true, active universe NIFTY_50. Phase8 config contains a separate 1500 INR assisted-execution maximum; disabled Phase20 bootstrap code contains a 15000 INR ceiling. Effective live sizing is not exercised.
- Task 9: Phase20 has four CLOSED BUY rows, gross historical fill notional 36088.59 INR, zero realized PnL and no OPEN row. Main API, independent ledger result, legacy store and broker summary reconcile at 100000 INR.
- Task 10: authority map identifies phase20_ledger as main API portfolio authority and portfolio service snapshot as divergent secondary path.
- Task 11: classification B, admission protected by static advisory-lock and one-open-symbol evidence. It was not load tested or invoked. REQUIRES LIVE SESSION VERIFICATION.

## Tasks 12 to 14: pages and visible runtime state

- Task 12 static query mapping plus endpoints: Dashboard and data freshness use scan status; Portfolio Live calls portfolio snapshot and health; PreOpen Intelligence uses preopen snapshot/watchlist/accuracy; Broker uses paper summary/mode; Live Data Health uses scan/health endpoints.
- Task 13 current labels: PAPER_TRADING, no live order placement, main portfolio 100000 INR/no positions, snapshot path DISABLED/50000 INR/50 percent drawdown, scheduler IDLE weekend, active universe NIFTY_50.
- Task 14 material UI data-authority issue is the 50000 INR portfolio delta. Readiness/coverage positive labels coexisting with stale freshness fields are a documented off-hours semantic distinction.

## Tasks 15 to 18: configuration, database and errors

- Task 15 effective runtime configuration is the Phase20 settings row stated above. Kite is not connected; mock indication is true.
- Task 16 development PostgreSQL has 74 observed public tables. Exact inventory is in RTV0_RUNTIME_DATABASE_INVENTORY.csv. trading.db is zero bytes and not runtime state.
- Task 17 deployment logs contain 83 Backtest queue tick timed out after 30 s warnings; latest was 2026-08-22T22:01:39Z. No matching inspected entries for yfinance, Kite, instrument-token, scan, pre-open, signal-validation, negative cash or zero-quantity failures. API workflow startup was clean with warm OHLCV cache.
- Task 18 deployment metadata says public successful Autoscale at https://nse-trade-intraday.replit.app. Production was intentionally not queried.

## Tasks 19 to 20: findings and Monday gate

P0: portfolio snapshot path differs from canonical portfolio by 50000 INR.
P0: active universe remains NIFTY_50 rather than custom 23-symbol target.
P0: no valid Kite session and 49 missing active-universe instrument tokens.
P1: current canonical scan is Friday stale and yfinance fallback.
P1: pre-open provider-health versus persisted zero-record session mismatch.
P1: 83 backtest queue timeouts.
P2: off-hours readiness/coverage can look healthy while session freshness is false.

REQUIRES LIVE SESSION VERIFICATION: authenticate/probe Kite and refresh full tokens; obtain a new canonical scan after open; prove four-minute scheduler cadence without duplicate manual path; validate fallback gates; capture 5A then 5B/5C lifecycle; reconcile Portfolio Live display; and, only after separately approved enablement, test one controlled paper-only entry for sizing/risk/concurrency/ledger/UI reconciliation.

## Kite token coverage

Present: RELIANCE only.
Missing active symbols: ADANIENT, ADANIPORTS, APOLLOHOSP, ASIANPAINT, AXISBANK, BAJAJ-AUTO, BAJAJFINSV, BAJFINANCE, BHARTIARTL, BRITANNIA, CIPLA, COALINDIA, DIVISLAB, DRREDDY, EICHERMOT, GRASIM, HCLTECH, HDFCBANK, HDFCLIFE, HEROMOTOCO, HINDALCO, HINDUNILVR, ICICIBANK, INDUSINDBK, INFY, ITC, JSWSTEEL, KOTAKBANK, LT, M&M, MARUTI, NESTLEIND, NTPC, ONGC, POWERGRID, SBILIFE, SBIN, SHRIRAMFIN, SUNPHARMA, TATACONSUM, TATASTEEL, TCS, TECHM, TITAN, TMCV, TMPV, TRENT, ULTRACEMCO, WIPRO.

Final classification: paper-only; automatic entries disabled; bootstrap disabled; auto exits enabled; live order placement disabled; current data is stale yfinance fallback; synthetic-data verdict D Unable to verify; no production code or runtime state changed.
