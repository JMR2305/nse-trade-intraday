---
name: Phase 7.1 Market Intelligence Hub
description: Architecture decisions and data-source strategy for the Market Intelligence Hub module.
---

# Phase 7.1 Market Intelligence Hub

## Module location
`artifacts/api-server/src/python/market_intelligence_hub/`

## Feature flag
`MARKET_INTELLIGENCE_HUB_ENABLED=true` (set in shared env)

## 5 endpoints (all advisory-only)
- `GET /api/market-intelligence/summary`
- `GET /api/market-intelligence/sectors`
- `GET /api/market-intelligence/watchlist`
- `GET /api/market-intelligence/breadth`
- `GET /api/market-intelligence/overview`

## Data source strategy
`_get_scan_items()` cascades: Postgres scan_state_store → intelligence_cache.json → empty list (never triggers a full scan).
`_get_regime()` always calls `market_regime.get_regime()` — which fetches NIFTY/BankNifty/VIX from yfinance (fast, ~1s).
`_get_timeframes()` calls `multi_timeframe_analyser.analyse_timeframes()` which runs 7 yfinance downloads in sequential threads (each with 12s timeout). Takes ~3s total.

**Why:** Running a full expensive scan per-request would be unacceptable; using cached data keeps endpoints sub-5s.

## Regime taxonomy (extended from market_regime.get_regime())
Priority order:
1. HIGH_VOLATILITY if VIX ≥ 25 (overrides everything)
2. BULL if NIFTY+BankNifty both UP (outranks LOW_VOL)
3. BEAR if NIFTY+BankNifty both DOWN
4. LOW_VOLATILITY if VIX ≤ 15 AND market is non-directional
5. BREAKOUT, TRANSITION, TRENDING, SIDEWAYS based on price change

**Why:** Directional signals (BULL/BEAR) must outrank LOW_VOLATILITY; only extreme VIX overrides them.

## Breadth analysis
Uses `final_action` field from scan items as advancing/declining proxy (STRONG_BUY+BUY=advancing, IGNORE=declining, WATCH=neutral). No live price change_pct needed.

## Test count
54/54 passing. All modules mocked at `_get_scan_items` / `_get_regime` level — no DB/yfinance calls in tests.

## Dashboard page note
`MarketIntelligenceHub.tsx` uses React + `@tanstack/react-query` (NOT Solid.js). `useQuery` with `refetchInterval: 30_000`. All 5 queries fire in parallel on mount. In React dev mode (Strict Mode), first request batch may be aborted by Strict Mode remount (~3.6s); second batch succeeds. This is expected — not a bug.

## Nav location
Analytics → Market Intelligence (Globe2 icon)
