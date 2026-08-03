# ApexQuant AI — Autonomous Paper Trading Platform
### Project Summary

---

## Overview

ApexQuant AI is a fully autonomous paper trading platform built for the NSE (National Stock Exchange of India). It combines a real-time market intelligence engine, a multi-agent AI decision framework, and an end-to-end paper trading lifecycle — all wrapped in a professional-grade web dashboard and companion mobile app. The platform is **research and advisory only**: no real money moves, no real broker orders execute without explicit operator confirmation.

---

## Architecture

| Layer | Technology |
|---|---|
| API Server | Node.js + Express (TypeScript), esbuild bundle |
| Intelligence Engine | Python 3.12, yfinance, pandas, NumPy |
| Database | PostgreSQL (Drizzle ORM) |
| Web Dashboard | React + Vite + Wouter + TanStack Query |
| Mobile App | Expo React Native |
| Auth | Replit Auth (OpenID Connect + PKCE) |
| Notifications | Expo Push + Email (Resend/SMTP) |
| Broker Integration | Zerodha Kite Connect (OAuth, advisory only) |

---

## What Was Built — Phase by Phase

### Phase 1–6 · Core Intelligence & Paper Trading Engine
- **NIFTY 50 watchlist scanner** with multi-timeframe analysis (EMA, RSI, MACD, VWAP, Supertrend, ATR)
- **Signal generation pipeline** producing STRONG_BUY / BUY / WATCH / SELL / STRONG_SELL verdicts with confidence scores
- **Paper portfolio engine** — virtual ₹5,000 starting capital, FIFO trade matching, open/closed positions, P&L tracking
- **Market regime detection** — BULLISH / BEARISH / SIDEWAYS / HIGH_VOL / LOW_VOL, used to gate strategy selection
- **Execution quality analytics** — slippage, fill quality, timing analysis
- **Strategy intelligence** — underperformance detection, lifecycle states, optimisation signals
- **Risk optimisation** — Kelly allocation, HHI concentration, drawdown severity, Monte Carlo stress tests
- **Live readiness score** — GO / NO-GO verdict across 8 domains before any paper entry

### Phase 7 · Live Market Intelligence Hub
- Canonical Phase 7 scan: single `scan_id` + `snapshot_ts` per session
- Provider health chain: NSE Official → Kite → Yahoo Finance fallback
- Pre-open market data (IEP, order book, imbalance)
- Safety quality gate: STALE→WATCH, UNAVAILABLE→IGNORE enforced in engine, not per-route
- Postgres-durable scan state store (`scan_state_store`) — local files are warm caches only

### Phase 8 · Broker Safety & Operations Centres
- **Zerodha Kite OAuth** — request token via env, durable tokens in Postgres, authenticated session probe
- **Credential masking** — secrets presence-only, never exposed in any API response
- **No-auto-execution guarantee** — two-step confirm tokens, MockBrokerClient fallback
- **Observability Centre** — 6 endpoints, system health probes (never calls Phase 7 from probes)
- **Risk Validation Centre** — 8-domain weighted score
- **Operations Centre** — 14 commands, scheduler control, session management
- **Security & Compliance Centre** — 13 commands, API key audit, dependency scan
- **Performance Optimisation Centre** — 13 commands, cache/DB/API profiling
- **Deployment & DR Centre** — 12 commands, backup via scan_state_store proxy, continuity scoring

### Phase 9 · Workspace UX & Executive Reporting
- **Multi-Agent Workspace** — 10 agents, 71 pages, colour-coded navigation
- **Quick Switcher** (Ctrl+K) — 6 search categories, dynamic data cache, workflow shortcuts
- **Personalised Dashboard** — drag-and-drop widget grid (@dnd-kit), 21 widgets, 5 profiles
- **Trading Timeline** — 9 tabs, 15 event categories, 10 IST market milestones
- **Executive Reports** — 7 report types, AI insight questions, 9 KPI scores, Report Library
- **Design System** — `designTokens.ts` + 15 shared DS components, `BrandMark` / `BrandLogo` / `BrandHeader`

### Phase 10 · Multi-Agent AI Framework
- **10A — Supervisor** — lazy-init agents, SnapshotBus process singleton, no auto-restart
- **10B — Analysis Layer** — Market Intelligence, Signal, Strategy, and Risk advisory agents
- **10C — Decision Layer** — AIDecisionAgent (7 decision types, explainability, conflict detection) + ExecutionAgent (10 pre-exec checks, NSE charges, paper-only default)
- **10D — Learning Layer** — LearningAgent + KnowledgeAgent; pattern discovery, outcome tracking
- **10E — Collaboration & Autonomous Ops** — 11-node agent graph, CollaborationEngine, AutonomousOpsAgent

### Phase 11 · Autonomous Paper Trading Centre
- **Capital modes A & B** — conservative vs aggressive allocation
- **Recommendation queue** — AI-scored entries sorted by confidence, regime-gated
- **Auto paper entry** — default OFF with exact confirmation flow; EXIT_PENDING on stale data
- **Session replay** — step-through any trading day with portfolio chart
- **Calendar heatmap** — daily P&L drill-down
- **Daily / weekly / monthly reports** with AI performance breakdown
- **Phase 11 snapshot** — aggregated across all sub-modules, surfaced on Command Centre

### Phase 19–22 · Live Data, Session Management & Push
- **Bulk yfinance download** — fixed 900s timeout for NIFTY 50 full scans
- **Scan lock with heartbeat** — DB-durable via Postgres, skip-not-poll pattern
- **Fail-safe token expiry** — malformed = expired; never silently treats bad tokens as valid
- **Circuit breaker** — corrupted safety state blocks entries (tripped+unreadable), manual-review resume only
- **Expo push notifications** — advisory-only, deduped by `signals_cache.updated_at` per token
- **Email alerts** — critical events emailed from `add_notification` hook (Resend→SMTP→logged skip)

---

## Scan Abort (Task #294)
A frozen Yahoo Finance connection inside `yf.download()` could leave the scan button stuck for up to 2 minutes. The fix:

- `POST /api/run-scan` (target of `useRunScan`) now uses **`spawnRunScan()`** — a tracked spawn that records `rsScanProc` + `rsScanReject`
- Phase 7's `spawnP7Scan()` records `p7Proc` + `p7InFlightReject`
- `POST /api/live-data/scan/abort` kills **both** process types; reject callbacks settle the in-flight promises immediately (before the OS delivers the close event)
- Race-safety: process handle cleared only when identity matches (`if (proc === ref) ref = null`); `.finally()` — not the abort handler — clears the in-flight promise reference
- **Web dashboard**: elapsed timer in scan button label + **Cancel scan** button (with XCircle icon) appears after 30 seconds
- **Mobile**: same Cancel button appears at 30 seconds; `handleAbort` calls the abort endpoint via `apiJson`

---

## Key Safety Invariants

| Invariant | Where enforced |
|---|---|
| No real orders without explicit operator confirmation | ExecutionAgent + two-step confirm token |
| Corrupted safety state always blocks entries | `circuit_breaker.py` — tripped+unreadable = BLOCKED |
| Secrets never exposed in API responses | Security Centre — presence-only check |
| Scan snapshots are append-only / write-once | `scan_state_store` — COALESCE per column + outcome_complete guard |
| Failed scans never overwrite a good snapshot | Postgres scan lock + monotonic `snapshot_ts` publish gate |
| Learning safety flags always read at decision time | Never from cached adjustment artifacts |

---

## Artifact Inventory

| Artifact | Kind | Purpose |
|---|---|---|
| `artifacts/api-server` | API | Express + Python intelligence engine |
| `artifacts/trading-dashboard` | Web | NSE Trading Dashboard (React) |
| `artifacts/trading-mobile` | Mobile | NSE Trading Mobile (Expo React Native) |
| `artifacts/trading-document-hub` | Web | Intraday Trade Hub (Next.js) |
| `artifacts/project-video` | Video | Platform overview animation |
| `artifacts/mockup-sandbox` | Design | Component preview server |

---

*Generated 2026-08-03 · ApexQuant AI — Paper / Research Only*
