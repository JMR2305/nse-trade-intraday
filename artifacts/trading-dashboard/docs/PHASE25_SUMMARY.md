# Phase 25 Summary — Mission Control

**The unified operational landing screen for ApexQuant AI**
**Date:** 2026-08-08 · **Status:** ✅ Complete (25A + 25B + 25C all merged and verified)

Mission Control (`/mission-control`) gives operators one screen for the entire trading day — pipeline, scanner, paper trading, portfolio, intelligence, alerts and controls — so they never need to jump between pages during market hours. It is a **pure dashboard**: every widget reads existing canonical endpoints; no business logic was added.

---

## Phase 25A — Shell & Core Live Panels
- **Widget framework** (`components/mission/Widget.tsx`): every widget fetches independently with its own query key, refresh cadence, timeout, inline error state and last-updated/stale pill — one slow endpoint can never blank the page.
- **Top status bar:** market status, IST clock/session, Nifty / Bank Nifty / VIX, portfolio value, today's P&L, open positions, system health.
- **Five core live panels:**
  1. **Live AI Pipeline** — the 10-stage Supervisor→Portfolio flow with per-stage in/out/rejected/pending/cancelled counts from the unified replay snapshot (the only sanctioned pipeline-count source), animated during scans.
  2. **Live Scanner** — universe, progress, current symbol, duration, freshness.
  3. **Live Paper Trading** — orders and positions from the canonical phase20 ledger.
  4. **Live Event Stream** — SSE-first event feed with polling fallback, virtualized rendering.
  5. **Live Portfolio** — value, cash, exposure, P&L, sector allocation from the canonical portfolio snapshot.

## Phase 25B — Intelligence & Ops Widgets
Nine additional widgets, all on the same framework, in lazy-loaded chunks:
- **Mission Map** (pipeline overview sharing the page-level replay query — stage counts are fetched once, never twice), **AI Health**, **AI Learning**, **Alert Center** (dedupes observability + operations + notification alerts by severity|title).
- **Replay**, **Backtest launcher** (IST-dated runs, 10s polling), **Mission Timeline** (IST 09:00–15:30 dot track from today's pipeline events), **Broker status**, **System Health**.
- Slow endpoints get explicit long timeouts (learning ~200s, phase24 ~150s, replay snapshot ~45s) so first paint shows skeletons instead of hung panels.

## Phase 25C — Command Bar, Search, Responsive & Verification
- **Command bar** — 9 operator actions (Start Scan, Pause/Resume AI, Emergency Stop, Replay Today, Run Backtest, Generate Report, Open Investigation, Open Learning Center) wired only to existing control endpoints. Emergency Stop = scan abort + kill-switch trigger with partial-failure reporting; destructive actions require explicit confirmation.
- **Global search** — QuickSwitcher now also covers trades, orders, recommendations, replay sessions and pipeline events with deep links, fault-isolated per source.
- **Responsive** — full grid on desktop, 2-column tablet stacking, compact mobile quick dashboard (status + portfolio + alerts) with a "Full dashboard" toggle.
- **Performance** — below-the-fold widget rows lazy-loaded, event feed windowed (fixed-height rows), shared page-level queries, tuned cadences (5s while scanning → 120s for slow aggregates); shell paints in under ~2s.
- **Configurable home** — Home pins to Mission Control during NSE market hours (Mon–Fri 09:00–15:30 IST) and Command Centre otherwise, with an AUTO/MC/CC preference toggle.

## Verification
- **22 new automated tests, all passing:** CommandBar (8 — confirmations, endpoint wiring, error surfacing), Widget framework (5 — error isolation, skeletons, stale pills), homeRoute (9 — market-hours boundaries, preference persistence).
- Full dashboard typecheck clean; browser smoke pass on desktop (1280×720) and mobile (402×874) with zero console errors.
- Freshness-coverage baseline unchanged (63 legacy failures pre-date Phase 25 and are tracked separately).

## Known limitations
- Generate Report blocks up to ~2 minutes (synchronous phase17 endpoint) — inline feedback shown while it runs.
- Weekend scans without a Zerodha session may complete STALE (environmental).

Full panel-by-panel detail: `MISSION_CONTROL_VERIFICATION.md` (same directory).
