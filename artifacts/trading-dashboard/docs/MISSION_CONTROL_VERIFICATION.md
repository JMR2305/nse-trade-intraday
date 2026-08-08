# Mission Control — Final Verification Report (Phase 25C)

Date: 2026-08-08 · Scope: Phases 25A (framework) + 25B (widgets) + 25C (command bar, search, responsive, performance, tests)

## 1. Panel-by-panel data sources

All panels read canonical stores only — no page-local calculations.

| Panel / Widget | Endpoint(s) | Cadence | Notes |
|---|---|---|---|
| Status bar | `/portfolio/snapshot` (shared `["mc","portfolio"]`) + SSE market ticks | 30s + SSE | Single fetch shared with Portfolio sidebar |
| Command bar | `/live-data/scan/run`, `/live-data/scan/abort`, `/risk/kill-switch/trigger`, `/risk/kill-switch/resume`, `/phase17/reports` | on-demand | Existing control endpoints only; Emergency Stop & Pause AI gated by confirmation dialog |
| Mission Map | `["mc","replay-latest"]` → `/replay/sessions/latest` (45s timeout) | 60s | Only pipeline-count source (unified replay snapshot) |
| Live AI Pipeline | same shared replay query | 60s | Never refetched separately |
| Live Scanner | `/live-data/scan/status` | 5s while scanning, 30s idle | |
| Paper Trading | `/phase20/ledger` | 30s | phase20 canonical ledger |
| Live Portfolio | shared `["mc","portfolio"]` | 30s | canonical_portfolio-backed |
| Event Stream | `/pipeline/events?limit=80&newest_first=true` + SSE tail | 15s + SSE | **Virtualized** (fixed 22px rows, windowed slice + overscan, 200-event cap) |
| AI Health / AI Learning | phase24 learning + agent snapshots | 60s | Lazy-loaded chunk |
| Alert Center | `/command-center/alerts` | 30s | Dedupe by severity\|title |
| Replay / Backtest / Broker / System Health | replay shared query · `/backtest/*` · `/broker/*` · obs summary | 60–120s | Lazy-loaded chunks |
| Mission Timeline | existing timeline endpoints | 60s | Lazy-loaded chunk |

## 2. Phase 25C deliverables

- **Command bar** (`components/mission/CommandBar.tsx`): 9 actions. Emergency Stop = scan abort + kill-switch trigger (partial-failure reporting); Pause AI = kill-switch trigger; both require explicit confirmation. Resume AI posts `{acknowledge:true}`. Generate Report posts `/phase17/reports` (130s timeout). Replay/Investigation/Learning deep-link; Run Backtest scrolls to the launcher widget. Inline success/failure feedback; buttons disabled while an action is in flight.
- **Global search** (`components/layout/QuickSwitcher.tsx`): warm cache now also queries `/phase20/ledger` (trades/orders), `/replay/sessions`, `/pipeline/events`, `/phase11/recommendations`. New result sections — Trades & Orders → `/trades`, Recommendations → `/paper-trading-recommendations`, Replay Sessions → `/replay`, Pipeline Events → `/mission-control` — alongside existing pages/agents/stocks/strategies/positions/alerts. All fetches fault-isolated via `Promise.allSettled`.
- **Responsive layout**: desktop 3–4-column grid; tablet (md) 2-column stacking; mobile (<768px, `useIsMobile`) renders a compact quick dashboard (status bar + portfolio + alert center) with a "Full dashboard" toggle.
- **Performance**: intel/ops widget rows and timeline are `React.lazy` chunks behind `Suspense` skeletons (shell paints without them); event feed windowed; refresh cadences tuned per widget (5s scan-in-progress → 120s slow aggregates); shared queries fetched once page-level. Shell (header, command bar, status bar, panels' skeletons) renders on first paint — verified visually; full data hydration depends on API latency.
- **Default landing** (`lib/homeRoute.ts` + `AppLayout.tsx`): pinned Home is Mission Control during NSE market hours (Mon–Fri 09:00–15:30 IST) and Command Centre otherwise, configurable via the AUTO/MC/CC toggle next to the Home button (persisted in localStorage).

## 3. Test results

`pnpm --filter trading-dashboard exec vitest run` (new suites):

| Suite | Tests | Result |
|---|---|---|
| `components/mission/CommandBar.test.tsx` — renders all 9 actions; Emergency Stop confirm → abort + kill-switch; Pause AI cancel calls nothing; confirm triggers kill-switch; Start Scan no-confirm + error surfaced inline; Resume AI acknowledges; nav actions deep-link with zero endpoint calls | 8 | ✅ pass |
| `components/mission/Widget.test.tsx` — error isolation (failing widget shows inline error, sibling keeps data); loading skeleton; stale pill at 2× cadence; `fmtINR`/`timeAgo` guards | 5 | ✅ pass |
| `lib/homeRoute.test.ts` — market-hours boundaries (09:00/15:29/15:30, weekend), preference overrides, localStorage round-trip + garbage rejection | 9 | ✅ pass |

Full dashboard typecheck (`tsc --noEmit`): ✅ clean.
`freshness-coverage.test.ts`: 63 failures — verified identical with changes stashed (pre-existing legacy baseline, untouched by 25C).

## 4. Browser smoke pass

- Desktop 1280×720 `/mission-control`: command bar, status bar (HEALTHY, ₹49,770, 4 open), Mission Map stage counts from replay snapshot, pipeline/scanner/portfolio panels, stale-scan warning banner — all rendered; no console errors.
- Mobile 402×874: compact quick dashboard rendered (status strip, Live Portfolio with sector allocation, Alert Center) with "Full dashboard" toggle; no console errors.
- Sidebar pinned Home correctly showed "Command Centre · AUTO" outside market hours.

## 5. Known limitations

- Generate Report blocks up to ~2 min (synchronous phase17 endpoint) — feedback shown while running.
- "Start Scan" during an active Zerodha-session-less weekend returns started=true but the scan may end STALE (environmental, documented in phase22 memory).
- Legacy freshness-coverage failures (63) predate 25C and are tracked separately.
