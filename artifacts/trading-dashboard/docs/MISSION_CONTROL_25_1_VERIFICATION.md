# Mission Control — Phase 25.1 Verification Report (Live Operations Enhancement)

Date: 2026-08-08 · Scope: Phase 25.1 Parts 1–13 (13 new capabilities on `/mission-control`)

Hard constraints honored: **no new business logic, no duplicate calculations** — every widget reads
canonical stores (Pipeline Event Store, Unified Replay Snapshot, phase20 Ledger / Portfolio Store,
Learning Engine, Observability). Presentation-level aggregation only (counting today's rows,
mapping status → colour). No new backend routes were added.

## 1. Widget → canonical source map

| Part | Widget (file) | Endpoint(s) / shared query | Cadence · timeout | Notes |
|---|---|---|---|---|
| 1 | MarketSessionWidget (`SessionWidgets.tsx`) | pure IST clock (Intl Asia/Kolkata) + SSE `market` prop | 1s tick | Phases 09:00 pre-open → 16:00 close; weekend/closed states; authoritative `market.state` wins when present |
| 2 | ThroughputWidget (`SessionWidgets.tsx`) | shared `["mc","replay-latest"]` snapshot (props) + `useLedgerToday()` `/phase20/ledger?limit=500` | 30s · 30s | Funnel = replay stage `stocks_out`; BUY/SELL/WATCH from replay decisions; order/trade counts = today-IST ledger rows |
| 3 | LivePerformanceWidget (`SessionWidgets.tsx`) | shared `["mc","portfolio"]` snapshot (props) + shared `useLedgerToday()` | 15s/30s | PnL/exposure/utilisation read from snapshot fields; win-rate & best strategy/sector = aggregation of today's CLOSED ledger rows; "—" when none |
| 4 | MarketBreadthWidget (`SessionWidgets.tsx`) | market-intelligence overview/regime endpoints (existing phase 7.1 hub) | 60s · 60–90s | Fields with no canonical source render "—" (never recomputed from raw quotes) |
| 5 | Investigate shortcuts | Event feed rows + Mission Timeline → `/investigation-center?symbol=&ts=&run=&trade=` | — | `InvestigationCenter.tsx` now parses deep-link params: run selection, symbol focus, cursor jump to `ts` / trade entry tick |
| 6 | AgentMetricsWidget (`DeepWidgets.tsx`) | `/agent-framework/agents` + `/autonomous-ops/snapshot` | 60s · 45/90s | queue_depth, processing_time_ms, last_error per agent; peak latency/recovery = "—" (no canonical source) |
| 7 | StockWatchWidget (`DeepWidgets.tsx`) | `/live-data/recommendations` + shared portfolio & scan props | 60s · 60s | ≤12 cards; PnL only for open positions from portfolio snapshot |
| 8 | ExplainabilityWidget (`DeepWidgets.tsx`) | `/live-data/recommendations` list + `/explainable-ai/decision?symbol=` on selection | 60s · 60s | Indicators, confidence breakdown, research/risk summaries, expected reward:risk from target/stop fields |
| 9 | SystemHealth2Widget (`DeepWidgets.tsx`) | `/observability/summary`, `/live-data/health-v2`, `/kite/status`, `/pipeline/summary`, cheap engine probes (`/backtest/runs`, learning status, optimisation summary) + portfolio/replay props | 30–60s | 12-cell green/amber/red grid; Redis row intentionally omitted (no Redis in this stack) |
| 10 | Alert Center ack/dismiss (`IntelWidgets.tsx`) | existing alert endpoints; ack/dismiss state in localStorage `mc-alert-state-v1` | 30s | Display-level only — no backend alert mutation exists; dismissed alerts restorable |
| 11 | Layout customization (`LayoutManager.tsx`) | localStorage `mc-layout-v1` | — | Section pin/hide/reorder + reset; sections: market-session, mission-map, pipeline-row, throughput-row, stockwatch-row, intel-row, ops-row, timeline, event-feed |
| 12 | Performance | — | — | All 8 new widgets are `React.lazy` chunks behind Suspense; shared queries fetched once page-level; event feed stays virtualized (fixed 22px rows) |

## 2. No-duplicate-fetch guarantees

- `/replay/sessions/latest`, `/portfolio/snapshot`, `/live-data/scan/status` are fetched **once**
  page-level and passed down as props (Throughput, LivePerformance, StockWatch, SystemHealth2).
- `/phase20/ledger` fetched once via `useLedgerToday()` and shared by Throughput + LivePerformance.
- SystemHealth2 engine probes use only cheap status/list endpoints — never slow aggregate summaries
  (per the observability-probe rule).

## 3. Validation performed

- `pnpm --filter trading-dashboard exec tsc --noEmit` — clean.
- Browser verification (weekend): session widget shows weekend state with IST clock; throughput
  funnel populated from real replay snapshot (50→48→…→5); live performance shows snapshot PnL with
  "—" for empty today-trade stats; alert center Ack/✕ working; slow widgets hydrate after cold load.
- Vitest suite for new widgets under `src/components/mission/__tests__/` (see test run output).
- DataFreshnessBar contract preserved on `/mission-control`.
