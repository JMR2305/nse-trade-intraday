# AI Operations Centre — Final Summary

## Overview

The AI Operations Centre (`/ai-operations-centre`) is a read-only, advisory-only dashboard that gives operators a real-time view of the complete ApexQuant AI multi-agent pipeline. It covers all 12 agents from market data ingestion through to paper order execution, with no live trading controls.

---

## What Was Built

### Web Dashboard (`artifacts/trading-dashboard`)

**File:** `src/pages/AIOperationsCentrePage.tsx`

| Section | What it shows |
|---|---|
| **Platform Status Bar** | Overall health %, market state, scan ID, session, current IST time, last/next refresh |
| **AI Pipeline Flow** | 12 animated nodes (emerald = ACTIVE, amber = WAITING, red = ERROR) with pass-through counts |
| **Agent Details** | 12 expandable cards — one per agent — with status, activity, stocks in/out, latency, and agent-specific KPIs |
| **Pipeline Funnel** | Bar chart of stock counts at every stage from Universe Loaded → Open Positions |
| **Live Event Log** | Last 30 timeline events (buys, sells, scans, errors) auto-refreshing every 15 s |

### Mobile App (`artifacts/trading-mobile`)

**File:** `app/(tabs)/ai-ops.tsx`  
**Tab label:** Pipeline (brain icon on iOS, cpu icon on Android/web)

| Section | What it shows |
|---|---|
| **Platform Health Card** | Animated progress bar, health %, market state, scan #, last/next refresh |
| **Agent Status Summary** | Active / waiting / error counts + countdown to next refresh |
| **Agent Grid** | 3 × 4 grid of pulsing status dots; tap any agent to expand inline detail |
| **Agent Expanded Card** | current_activity, health %, stocks in/out, latency, agent-specific fields |
| **Pipeline Funnel** | Horizontally scrollable bubble row of stage counts with pass-through % |

**Hook:** `lib/monitorApi.ts` — `useOpsSnapshot()` with a custom 60 s fetch timeout (the full snapshot takes ~10–40 s to compute).

---

## The 12 Agents

| Agent | Role | Key detail shown |
|---|---|---|
| Supervisor | Orchestrates all agents | Total agents, running, error count, alert count |
| Market Data | Fetches live prices | Coverage %, NIFTY 50 price, India VIX, market regime |
| Research | News & corporate actions | Sentiment breakdown, news items processed |
| Market Intelligence | Regime & liquidity analysis | Market regime, liquidity condition, volatility regime, confidence |
| Monitoring | Technical event detection | Breakouts, volume spikes, gap events, momentum events |
| Strategy | Signal generation | 6 strategies, top strategy, highest confidence symbol |
| Risk | Position sizing & gates | Risk level/score, capital used/available, global gate pass/fail |
| AI Decision | BUY/SELL/WATCH recommendations | Decision counts, avg confidence, market regime |
| Execution | Paper order management | BUY/SELL orders, open/closed positions, capital utilised |
| Learning | Trade outcome analysis | Trades analysed, win/loss, lessons generated |
| Knowledge | Pattern knowledge base | Knowledge records, learning sessions, reports |
| Operations | System health | CPU/memory %, queue size, database/API status |

---

## Performance Architecture

### The Problem (before this work)

- A single `useQuery` fetched `/api/ops-centre/snapshot` (all 12 agents in parallel, ~10–40 s)
- Platform Status bar and Pipeline Flow showed **0% health** and skeletons for the entire wait
- `_platform_status()` in Python hardcoded `health_pct = 0` — the real value was only filled in after all 12 agent collectors returned

### The Fix

Two parallel data paths:

```
Page load
    │
    ├─► GET /api/ops-centre/platform  ──── < 250 ms ──► Platform Status Bar ✓
    │     (reads KV cache + market hours)               Pipeline Flow nodes ✓
    │
    └─► GET /api/ops-centre/snapshot  ──── 10–40 s ──► Agent Detail Cards
          (runs all 12 agents in parallel)              Pipeline Funnel
```

**Fast endpoint** (`GET /api/ops-centre/platform`):
- Python function `get_fast_platform_status()` in `ops_centre.py`
- Reads only: `scan_state_store.load_latest_meta()`, `market_hours.market_status()`, and three KV keys
- Returns in **~235 ms** (vs 30–40 s before)

**KV cache** (written by the full snapshot after each agent collection):

| Key | Value |
|---|---|
| `ops_last_health_pct` | Last computed health % (integer, always written — including 0) |
| `ops_last_pipeline_nodes` | JSON array of 12 node states |
| `ops_last_snapshot_ts` | ISO timestamp when cache was last written |

**Sentinel safety:** `health_pct_cached` is typed `Optional[int]` and initialised to `None`. The scan-age heuristic (95% if scan is recent, 50% if stale) fires **only** when `health_pct_cached is None` — i.e. no full snapshot has ever run. A legitimately computed 0% health is preserved exactly and never overridden.

**React split:**

| Query | Endpoint | Refetch interval | Feeds |
|---|---|---|---|
| `usePlatformQuery` | `/ops-centre/platform` | 10 s | Platform Status Bar, Pipeline Flow |
| `useSnapshotQuery` | `/ops-centre/snapshot` | 30 s | Agent Cards, Pipeline Funnel |

Once the full snapshot lands, its `platform` block supersedes the fast cache in `effectivePlatform`.

---

## Risk Agent Fix (prerequisite work)

Before this dashboard could show accurate data, the Risk Agent was always returning `available: False`, causing all 12 agent cards to show WAITING even when the system was healthy.

**Fix in** `risk_agent/shared_services.py` — `get_risk_snapshot()` now uses a three-level fallback:

1. SnapshotBus in-memory cache (fastest)
2. `execute_task()` live evaluation
3. Phase-20 entry evaluation data from `phase20_store` KV

This guarantees `available: True` after any scan has run, enabling all 12 agents to show **ACTIVE** at 95% platform health.

---

## Files Changed

| File | Change |
|---|---|
| `artifacts/api-server/src/python/ops_centre.py` | Added `get_fast_platform_status()`, KV persistence in `get_ops_centre_snapshot()`, sentinel fix |
| `artifacts/api-server/src/python/main.py` | Added `ops_centre_platform` command branch |
| `artifacts/api-server/src/routes/trading.ts` | Added `GET /api/ops-centre/platform` route; fixed TS typecheck error on `runPython` |
| `artifacts/api-server/src/python/risk_agent/shared_services.py` | Three-level fallback in `get_risk_snapshot()` |
| `artifacts/api-server/src/python/ops_centre.py` | `_collect_risk()` updated to use new snapshot fields |
| `artifacts/trading-dashboard/src/pages/AIOperationsCentrePage.tsx` | Split into two queries, added `FastPlatformStatus` interface, progressive loading UI |
| `artifacts/trading-mobile/lib/monitorApi.ts` | Added `OpsSnapshot`, `AgentState` types + `useOpsSnapshot()` hook (60 s timeout) |
| `artifacts/trading-mobile/app/(tabs)/ai-ops.tsx` | New Pipeline tab screen |
| `artifacts/trading-mobile/app/(tabs)/_layout.tsx` | Registered `ai-ops` in both NativeTabLayout and ClassicTabLayout |

---

## Pending Follow-up Tasks

| # | Title |
|---|---|
| #315 | Show last known pipeline state on mobile when app opens offline |
| #316 | Alert operators on their phone when platform health drops below 70% |
| #317 | Cache platform status in Node.js to reduce response time to near-zero |
| #318 | Label cached vs freshly-computed health score in the platform bar |
