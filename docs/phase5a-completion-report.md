# Phase 5A — Pre-Open Intelligence Module
## Completion Report

**Date:** 27 July 2026  
**Branch:** `phase-5-preopen-intelligence` → merged to `main`  
**Task ref:** #142 (MERGED)  
**Status:** ✅ Complete and live

---

## Overview

Phase 5A delivers a fully self-contained Pre-Open Intelligence system for the ApexQuant AI platform. It monitors the NSE pre-open session (08:45–09:20 IST), scores every symbol in the watchlist across eight analytical factors, generates ranked watchlists, and presents the results in a dedicated operator UI — all with a hard advisory-only guarantee: no buy, sell, or order function exists anywhere in the module.

---

## Deliverables

### Python backend (9 modules)

| File | Purpose |
|------|---------|
| `preopen_data_model.py` | Dataclasses: `PreOpenSnapshot`, `PreOpenSession`, `WatchlistItem`, `ReconciliationRecord`; enums `ProviderState`, `Classification` |
| `preopen_provider.py` | Abstract `PreOpenDataProvider`; `YFinancePreOpenProvider` (live); `MockPreOpenProvider` with fixture data for testing |
| `preopen_analytics.py` | 8-factor opportunity score (0–100, transparent); `classify_snapshot`; `enrich_universe`; `rank_snapshots` |
| `preopen_db.py` | 6 Postgres tables; `DISTINCT ON (symbol)` dedup query; Python belt-and-suspenders safety dedup |
| `preopen_engine.py` | Top-level orchestrator: `get_status`, `get_health`, `collect_snapshot`, `get_snapshot`, `get_symbol_snapshot`, `get_rankings`, `get_watchlists`, `get_sectors`, `get_report`, `refresh` |
| `preopen_watchlist.py` | `generate_watchlists()` — 8 ranked lists at 09:15 IST; stale snapshots excluded; risk flags + confirmation checklist per item |
| `preopen_reconciliation.py` | `confirm_candidate()` — 13-criteria post-open gate (verdict: CONFIRMED / DOWNGRADE_WATCH / NO_TRADE); `reconcile_session()` — 6 accuracy metrics |
| `preopen_scheduler.py` | Full IST cadence 08:45 → 09:20; module-level singleton; `run_preopen_cycle_now()` |
| `test_preopen.py` | 58 unit tests — all passing; fixture-based, no live NSE calls |

### Database (6 tables, all protected)

| Table | Content |
|-------|---------|
| `preopen_sessions` | One row per collection session; status, counts, provider health |
| `preopen_snapshots` | One enriched row per symbol per collection; `DISTINCT ON (symbol)` read semantics |
| `preopen_rankings` | Frozen ranked list snapshots per session |
| `preopen_watchlists` | 8 typed watchlists generated at 09:15 |
| `preopen_provider_health` | Provider latency and availability log |
| `preopen_reconciliation` | Post-open indicative vs actual price error records |

All six tables are registered in `lib/db/protected-tables.json` — drizzle-kit will never drop them.

### API routes (9 endpoints, `artifacts/api-server/src/routes/preopen.ts`)

| Method | Path | TTL | Purpose |
|--------|------|-----|---------|
| GET | `/api/preopen/status` | 30 s | Engine status + feature flag state |
| GET | `/api/preopen/health` | 60 s | Provider health check |
| GET | `/api/preopen/snapshot` | 60 s | Full snapshot for today |
| GET | `/api/preopen/snapshot/:symbol` | 60 s | Single-symbol snapshot |
| GET | `/api/preopen/rankings` | 60 s | Ranked opportunity list |
| GET | `/api/preopen/watchlist` | 60 s | 8 watchlists (frozen at 09:15) |
| GET | `/api/preopen/sectors` | 120 s | Sector aggregates |
| GET | `/api/preopen/report` | 60 s | Full session report |
| POST | `/api/preopen/refresh` | — | Manual refresh (30 s rate-limit) |

In-memory response cache with per-route TTLs. 30-second rate-limit on POST `/refresh`.

### Frontend (`artifacts/trading-dashboard/src/pages/PreOpenIntelligence.tsx`)

- **Status bar** — session state, data age, provider health, advisory label
- **6 highlight cards** — Universe, Valid, Stale, Strong Gap Up/Down, Top Opportunity
- **15-column sortable/filterable table** — all enriched symbols with classification badges and factor scores
- **Detail drawer** — per-symbol factor score breakdown (8 bars), gap/imbalance/liquidity detail, confirmation checklist
- **Disabled state** — friendly banner when feature flag is off, with exact env var name

### Navigation & routing

- `AppLayout.tsx` — **Pre-Open Intelligence** added to the Operations group (between Market Scanner and Live Data Health) with the `Sunrise` icon
- `App.tsx` — route `/preopen-intelligence` wired
- `main.py` — 9 `preopen_*` dispatch commands added to the Python bridge

---

## Safety invariants (enforced)

| Invariant | Mechanism |
|-----------|-----------|
| No order functions in preopen modules | `test_no_order_function_exists` scans all 7 preopen source files via `ast.walk` |
| Advisory label on every engine response | `test_paper_mode_advisory_labels_present` checks all enabled responses |
| Stale data cannot be actionable | `test_stale_data_cannot_be_actionable` — stale snapshots score 0 and are excluded from watchlists |
| Confirmation requires risk engine approval | `test_confirmation_requires_risk_engine` — `risk_engine_approved=False` → NO_TRADE, no exception |
| Feature flag off → silent DISABLED response | All 9 engine functions return `{status:"DISABLED"}` when flag is off |

---

## Confirmation gate thresholds (13 criteria)

| Verdict | Criteria passed |
|---------|----------------|
| `CONFIRMED` | ≥ 12 / 13 |
| `DOWNGRADE_WATCH` | 7 – 11 / 13 |
| `NO_TRADE` | < 7, or stale data gate failed, or risk engine not approved |

Stale-data gate and risk-engine approval are **veto conditions** — either one alone forces NO_TRADE regardless of other scores.

---

## Key bug fixed during review

**Snapshot deduplication after repeated refreshes** — the initial `get_latest_snapshots()` query selected all rows for the trading date, causing the symbol count to grow (e.g. 30 rows after 3 refresh cycles of 10 symbols). Fixed with:

1. `DISTINCT ON (symbol) … ORDER BY symbol, created_at DESC` in the SQL query — PostgreSQL picks the most recent row per symbol at the database level.
2. Python-level `seen: dict` dedup as a belt-and-suspenders safety net.
3. 6 new `TestSnapshotDeduplication` regression tests verifying stable symbol counts across 1, 2, and 3 refresh cycles.

---

## Test summary

```
Ran 58 tests in 1.076s — OK

TestClassification              4 tests
TestDuplicateSnapshots          1 test
TestFeatureFlagDisabled         2 tests
TestFirstSessionHandling        2 tests
TestGapCalculation              5 tests
TestImbalanceCalculation        3 tests
TestImbalancePercent            2 tests
TestMalformedProviderResponse   2 tests
TestMarketHolidayHandling       1 test
TestMissingFields               2 tests
TestNoTradeExecutionFromPreOpen 4 tests   ← safety invariants
TestPartialMarketResponse       2 tests
TestPostOpenConfirmationGate    3 tests
TestPostOpenReconciliation      2 tests
TestProviderTimeout             3 tests
TestRankings                    2 tests
TestSectorAggregation           1 test
TestSnapshotDeduplication       6 tests   ← dedup regression
TestStaleData                   3 tests
TestTieBreaking                 1 test
TestTimezoneCorrectness         1 test
TestWatchlistGeneration         3 tests
TestZeroQuantityDivision        3 tests
```

---

## Deployment state

| Environment | Status |
|-------------|--------|
| Development | ✅ Live — `PREOPEN_INTELLIGENCE_ENABLED=true` set, API server restarted |
| Production (`nse-trade-intraday.replit.app`) | ⏳ Pending republish |

---

## Follow-up tasks proposed

| Ref | Title |
|-----|-------|
| #143 | Enable Pre-Open Intelligence for live operator sessions (flag already flipped in dev; production needs republish) |
| #144 | Connect pre-open opportunity scores to the Trade Decisions signal feed |
| #145 | Validate pre-open accuracy by comparing indicative vs actual open prices post-session |
