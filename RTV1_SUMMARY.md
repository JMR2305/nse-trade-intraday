# RTV-1 Summary

**Status:** **CODE PASS — LIVE SESSION VERIFICATION PENDING**  
**Branch:** `rtv1-market-data-portfolio-truth`  
**Final commit:** `c0cee091`  
**Follow-up:** Task #903 — Confirm live market data is genuinely ready before paper trading resumes

## Objective

RTV-1 corrected confirmed market-data, portfolio-truth, pre-open lifecycle, and safe paper-admission issues without changing the trading universe, strategy, thresholds, or activation controls.

## Safety controls preserved

- Initial paper capital: **₹100,000**
- Automatic paper entries: **disabled**
- Bootstrap paper trading: **disabled**
- Automatic paper exits: **enabled**
- Live broker order placement: **disabled**
- Active universe: **NIFTY 50 / 50 symbols**, unchanged
- No manual trades, portfolio resets, broker orders, deployment, or external Kite calls were made

## Main fixes

### Market data

- Preserved per-symbol quote provenance through the Kite LTP overlay.
- Prevented fallback and synthetic prices from being labeled execution-grade Kite/live data.
- Added fail-closed trading readiness checks for:
  - authenticated Kite session
  - complete instrument-token coverage
  - fresh canonical scan timestamp
  - valid, fresh per-symbol Kite quote timestamps
- Added health visibility for active symbols, valid/missing tokens, source counts, fallback symbols, and freshness.
- Cleared store-hydrated session values safely on disconnect without exposing or changing static secrets.

### Portfolio truth

- Made the Phase-20 ledger the canonical source for portfolio snapshots and drawdown basis.
- Unified `/api/portfolio` and `/api/portfolio/snapshot` financial aliases.
- Routed active portfolio bridge, performance, and paper-analytics calculations through the dynamic Phase-20 capital accessor.
- Blocked same-symbol BUY admission when an `OPEN` or `EXIT_PENDING` position already exists inside the locked transaction.

### Pre-open lifecycle

- Preserved omitted fields during partial Phase 5A/5B updates.
- Added collection-versus-persistence mismatch reporting.
- Prevented frozen, reconciled, complete, and no-candidate lifecycle states from regressing.
- Added explicit `NO_CANDIDATES` and `EOD_RETRY_REQUIRED` semantics instead of false completion.

## Verification

- RTV-1 focused regression suite: **92 passed**
- Paper analytics unit and real-DB smoke suites: **161 passed**
- API/dashboard TypeScript checks: **passed**
- API rebuild and restart: **passed**
- PortfolioLive browser verification: **passed**
- Independent code review: **passed**
- Completion validation: **passed**
- One pre-existing `datetime.utcnow()` deprecation warning remains.

## Current runtime truth

The runtime is intentionally not trading-ready yet:

- `credentials_present=false`
- Kite token status: `MISSING`
- Authenticated connection: `false`
- Valid cached instrument tokens: **1 of 50**
- Missing cached instrument tokens: **49**
- Token coverage: **2%**
- `service_ready=true`
- `data_ready=true`
- `session_fresh=false`
- `trading_data_ready=false`

This is the expected fail-closed result while Kite authentication, full instrument hydration, and a fresh live-session scan are unavailable.

## Required next step

Complete `RTV1_MONDAY_LIVE_SESSION_CHECKLIST.md` during the next NSE session. Live-session verification must confirm authenticated Kite status, 100% token coverage, fresh quote provenance for all active symbols, Phase 5A persistence parity, and canonical portfolio parity without enabling automatic entries or live orders.