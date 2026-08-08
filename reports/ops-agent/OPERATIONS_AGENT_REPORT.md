# Operations Agent — Comprehensive Page Report

Generated: 2026-08-08 09:28 IST · Scan: `2bf7afb3d547` · All 23 pages of the **Operations Agent** group captured live from the running dashboard.

## Executive summary

- **Live readiness: 90.18 (A+)** — verdict: *READY FOR EXTENDED PAPER TRADING*; 0 blocking issues, 8 warnings (weakest category: DataQuality 56.25).
- **Observability: 86.3 (grade A)** — system/DB/API HEALTHY, scheduler DEGRADED (stale weekend scan), 0 session errors.
- **Paper trading**: 4 open positions, exposure ₹36,088.59, unrealized ₹-286.49 (marks from last scan — broker NOT CONNECTED), portfolio value ₹49,713.51.
- **Latest scan**: 50 symbols → 43 passed; decisions: 2 BUY / 31 WATCH / 17 AVOID of 50. Scan is stale (29.0h old — weekend), so BUY recommendations are gated off.
- **Validation pipeline**: 9/11 stages PASS; WARNINGs on Market Data (Yahoo DEGRADED, 96% coverage) and Execution (gates blocked both eligible BUYs).
- **Data integrity**: replay/execution/portfolio/database checks all PASS; 0 duplicates; 2 symbols missing candles; 2 provider errors.
- **5 of 23 pages** are gated behind feature flags that are currently off (Operations, Data Quality, Security, Performance, Deployment centres) — their UIs render an enable banner.

## Session context (at capture time)

Market CLOSED (weekend), regime LOW_VOLATILITY, Nifty 24622.6 (+0.98%), VIX 18, bias BULLISH; top sector IT (75.0), worst AUTO (50.0). Today's trades: 0 (risk blocks: 2). AI: 10 decisions, avg confidence 35.6%, top strategy mean_reversion, worst breakout_hunter.

## Page-by-page report

| # | Page | Route | Status |
|---|------|-------|--------|
| 1 | My Workspace | `/workspace` | 🟢 live |
| 2 | Trading Day Timeline | `/trading-timeline` | 🟢 live |
| 3 | Executive Reports | `/executive-reports` | 🟢 live |
| 4 | Design System | `/design-system` | 🟢 live |
| 5 | AI Operations Centre | `/ai-operations-centre` | 🟢 live |
| 6 | AI Investigation Centre | `/ai-investigation` | 🟢 live |
| 7 | Replay Mode | `/replay` | 🟢 live |
| 8 | Agent Operations | `/agent-operations` | 🟢 live |
| 9 | Operations Centre | `/operations-center` | 🟡 flag off |
| 10 | Observability | `/observability` | 🟢 live |
| 11 | Data Quality | `/data-quality` | 🟡 flag off |
| 12 | Security & Compliance | `/security-center` | 🟡 flag off |
| 13 | Performance Centre | `/performance-center` | 🟡 flag off |
| 14 | Deployment & DR | `/deployment-center` | 🟡 flag off |
| 15 | Live Readiness | `/live-readiness` | 🟢 live |
| 16 | Notifications | `/notifications` | 🟢 live |
| 17 | Kite Connect | `/kite-connect` | 🟢 live |
| 18 | Settings | `/settings` | 🟢 live |
| 19 | System Validation | `/system-validation` | 🟢 live |
| 20 | Paper Trading Validation | `/validation` | 🟢 live |
| 21 | Phase 4A Operations | `/phase4a-session` | 🟢 live |
| 22 | Operator Status | `/operator-status` | 🟢 live |
| 23 | Automation Health | `/automation` | 🟡 flag off |

### My Workspace — `/workspace`

**Purpose.** Personalised widget dashboard (drag-and-drop grid, 21 widgets, KPI bar, focus modes, profiles).

**Status.** Operational — layout and widget CRUD are client-side (localStorage).

![My Workspace](screenshots/workspace.jpg)

### Trading Day Timeline — `/trading-timeline`

**Purpose.** Chronological trading-day timeline: 15 event categories, 10 IST session milestones, annotations, checklist.

**Status.** Operational — built from 4 existing API feeds.

![Trading Day Timeline](screenshots/trading-timeline.jpg)

### Executive Reports — `/executive-reports`

**Purpose.** 7 executive report types with AI insights, 9 KPI scores, and a saved-report library.

**Status.** Operational — derived from cached queries; Security/Performance/Deployment KPI scores await those centres being enabled.

![Executive Reports](screenshots/executive-reports.jpg)

### Design System — `/design-system`

**Purpose.** Design token + component gallery (15 DS components) used across the app.

**Status.** Operational — static gallery.

![Design System](screenshots/design-system.jpg)

### AI Operations Centre — `/ai-operations-centre`

**Purpose.** Aggregated AI pipeline monitor across all agents.

**Status.** Operational — summary endpoint is slow (~20-30s), page uses extended timeout.

![AI Operations Centre](screenshots/ai-operations-centre.jpg)

### AI Investigation Centre — `/ai-investigation`

**Purpose.** Digital-twin investigation: why a symbol was bought/rejected, replay of pipeline decisions.

**Status.** Operational — reads cached scan + replay stores.

![AI Investigation Centre](screenshots/ai-investigation.jpg)

### Replay Mode — `/replay`

**Purpose.** Time-travel replay of the last scan pipeline, stage by stage, with conservation checks.

**Status.** Operational — replay integrity PASS on scan 2bf7afb3d547.

![Replay Mode](screenshots/replay.jpg)

### Agent Operations — `/agent-operations`

**Purpose.** Multi-agent framework console: supervisor, snapshot bus, agent lifecycle.

**Status.** Operational — agents lazy-init on first call; supervisor never auto-restarts.

![Agent Operations](screenshots/agent-operations.jpg)

### Operations Centre — `/operations-center`

**Purpose.** 11-tab operational control centre (ops_* commands).

**Status.** Backend collector DISABLED (feature flag) — page shows enable instructions; UI itself renders. Flag: OPERATIONS_CENTER_ENABLED.

![Operations Centre](screenshots/operations-center.jpg)

### Observability — `/observability`

**Purpose.** System observability: API/DB/scheduler health, error counts, score.

**Status.** ENABLED — score 86.3 (grade A); system HEALTHY, DB HEALTHY, API HEALTHY, scheduler DEGRADED, session errors 0.

![Observability](screenshots/observability.jpg)

### Data Quality — `/data-quality`

**Purpose.** Data-quality centre: provider coverage, staleness, gate outcomes.

**Status.** Backend collector DISABLED (feature flag) — page shows enable instructions; UI itself renders. Flag: DATA_QUALITY_ENABLED (aggregate quality still visible on Validation page).

![Data Quality](screenshots/data-quality.jpg)

### Security & Compliance — `/security-center`

**Purpose.** Security & compliance centre: secrets presence, session, config, deps (sec_* commands).

**Status.** Backend collector DISABLED (feature flag) — page shows enable instructions; UI itself renders. Flag: SECURITY_CENTER_ENABLED.

![Security & Compliance](screenshots/security-center.jpg)

### Performance Centre — `/performance-center`

**Purpose.** Performance optimisation centre: API/DB/cache/scheduler/resource scores.

**Status.** Backend collector DISABLED (feature flag) — page shows enable instructions; UI itself renders. Flag: PERFORMANCE_CENTER_ENABLED.

![Performance Centre](screenshots/performance-center.jpg)

### Deployment & DR — `/deployment-center`

**Purpose.** Deployment & DR centre: readiness, backups, continuity (deploy_* commands).

**Status.** Backend collector DISABLED (feature flag) — page shows enable instructions; UI itself renders. Flag: DEPLOYMENT_CENTER_ENABLED.

![Deployment & DR](screenshots/deployment-center.jpg)

### Live Readiness — `/live-readiness`

**Purpose.** Operational Readiness Score with GO/NO-GO verdict for live trading.

**Status.** ENABLED — score 90.18 (grade A+), verdict: READY FOR EXTENDED PAPER TRADING; 8 warnings, 0 blocking issues. Category scores: SystemHealth 100, DataQuality 56.25, Recovery 100, Security 92.86, Config 100, APIHealth 100.

![Live Readiness](screenshots/live-readiness.jpg)

### Notifications — `/notifications`

**Purpose.** Notification centre: in-app, email and push delivery history and settings.

**Status.** Operational — email transport env-resolved; push registration user-initiated.

![Notifications](screenshots/notifications.jpg)

### Kite Connect — `/kite-connect`

**Purpose.** Zerodha Kite session management (OAuth login, token status).

**Status.** Operational — broker currently NOT CONNECTED; marks fall back to last-scan prices.

![Kite Connect](screenshots/kite-connect.jpg)

### Settings — `/settings`

**Purpose.** Platform settings incl. scan interval, paper-trading limits, review-package export.

**Status.** Operational.

![Settings](screenshots/settings.jpg)

### System Validation — `/system-validation`

**Purpose.** System validation dashboard (phase16 checks).

**Status.** Operational — reads validation caches.

![System Validation](screenshots/system-validation.jpg)

### Paper Trading Validation — `/validation`

**Purpose.** Paper Trading Validation: session context, trading stats, historical performance, data quality, 11-stage pipeline checklist, AI validation.

**Status.** Operational — aggregate dashboard always renders; legacy collector flag PAPER_VALIDATION_ENABLED is off (banner shown).

![Paper Trading Validation](screenshots/validation.jpg)

### Phase 4A Operations — `/phase4a-session`

**Purpose.** Phase 4A controlled paper-trading operations: readiness checks, live session monitor, 6 operational tiles, decision distribution, pipeline summary, trade journal.

**Status.** Operational — full live dashboard (details below).

![Phase 4A Operations](screenshots/phase4a-session.jpg)

### Operator Status — `/operator-status`

**Purpose.** Operator-facing status board of automation and session state.

**Status.** Operational.

![Operator Status](screenshots/operator-status.jpg)

### Automation Health — `/automation`

**Purpose.** Automation health: auto paper trading entries/exits, circuit breaker, health enum.

**Status.** Operational — auto entries default OFF; health enum HEALTHY/DEGRADED/DOWN/UNKNOWN/DISABLED.

![Automation Health](screenshots/automation.jpg)

## Method & sources

- Screenshots: headless Chromium against the running dev server (1440×1400, per-page capture), stored in `reports/ops-agent/screenshots/`.
- Live metrics: `/api/readiness/summary`, `/api/observability/summary`, `/api/phase4a/dashboard`, `/api/validation/dashboard` — all backed by canonical stores (phase20 ledger, scan snapshot, replay engine, portfolio store, AI decision cache).
- Disabled centres return `status: DISABLED` from their summary endpoints (`/api/operations|security|performance|deployment/summary`, `/api/data-quality/summary`).