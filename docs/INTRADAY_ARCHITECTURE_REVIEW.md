# NSE Trader — Intraday Architecture Review

> **Analysis date:** July 18, 2026  
> **Scope:** Read-only architectural audit. No code was modified, deleted, or created.  
> **Basis:** Direct inspection of all source modules via read-only subagent exploration.

---

## Table of Contents

1. [Current System Architecture](#1-current-system-architecture)
2. [Module-by-Module Classification](#2-module-by-module-classification)
3. [Data Flow](#3-data-flow)
4. [AI Workflow](#4-ai-workflow)
5. [Training Workflow](#5-training-workflow)
6. [Signal Generation Workflow](#6-signal-generation-workflow)
7. [Database Design](#7-database-design)
8. [Existing Strengths](#8-existing-strengths)
9. [Existing Weaknesses](#9-existing-weaknesses)
10. [Intraday Migration Plan](#10-intraday-migration-plan)
11. [Missing Components for Intraday](#11-missing-components-for-intraday)
12. [Technical Debt](#12-technical-debt)
13. [Final Deliverables](#13-final-deliverables)

---

## 1. Current System Architecture

### High-Level Stack

```
┌─────────────────────────────────────────────────────────┐
│                     USER INTERFACES                      │
│  React/Vite Dashboard (43 pages)  │  Expo Mobile App    │
│  Port: dynamic via artifact proxy │  React Native       │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (REST + SSE)
                     ▼
┌─────────────────────────────────────────────────────────┐
│              NODE.JS / EXPRESS API LAYER                 │
│  app.ts  →  routes/index.ts  →  routes/trading.ts       │
│  routes/kite.ts  │  routes/phaseXX.ts  │  routes/stream │
│  scanScheduler.ts (minute ticker)                       │
│  alertQueue.ts  │  pushNotifier.ts  │  events.ts (SSE)  │
└────────────────────┬────────────────────────────────────┘
                     │ child_process.spawn (JSON stdout)
                     ▼
┌─────────────────────────────────────────────────────────┐
│               PYTHON TRADING ENGINE                      │
│  main.py (CLI dispatcher)                               │
│  ├── market_data_engine.py  ←─ yfinance / Kite          │
│  ├── indicator_engine.py    (EMA, RSI, MACD, ATR, …)    │
│  ├── signal_engine.py       (rule-based, multi-TF)      │
│  ├── ai_decision.py / decision_service.py               │
│  ├── confidence_calibration.py                          │
│  ├── live_scan_engine.py  +  scan_pipeline.py           │
│  ├── phase20_scheduler.py  (automation engine)          │
│  ├── phase20_executor.py / gates / exits / circuit      │
│  ├── paper_trader.py  /  portfolio_manager.py           │
│  ├── adaptive_learning.py  /  learning_engine.py        │
│  ├── walk_forward_validator.py  /  backtesting_engine   │
│  └── phase13/14/21/22 governance & evidence layers      │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴────────────┐
         ▼                        ▼
┌─────────────────┐    ┌──────────────────────────────────┐
│   PostgreSQL DB  │    │  Market Data Sources              │
│  (Drizzle ORM)  │    │  yfinance (daily OHLCV, fallback) │
│  paper_trades   │    │  Zerodha Kite Connect (live LTP)  │
│  signals_cache  │    │  kite_quote_provider.py (30s TTL) │
│  alert_delivery │    └──────────────────────────────────┘
│  push_subscript │
└─────────────────┘
```

### Technology Choices

| Layer | Technology | Notes |
|---|---|---|
| Frontend web | React 18, Vite, Wouter, Recharts, Tailwind, Radix UI | 43 pages |
| Frontend mobile | Expo / React Native | 6 tab screens |
| API server | Node.js 24, Express 5, TypeScript 5.9 | Pino logging |
| Trading engine | Python 3 (child_process) | Spawned per API call |
| Indicators | pandas, numpy | No TA-Lib |
| Market data | yfinance + Zerodha KiteConnect SDK | Daily primary |
| Database | PostgreSQL via Drizzle ORM | + JSON file fallback |
| Notifications | Expo Push API + Resend/SMTP | alertQueue.ts |
| Build system | pnpm workspaces | Monorepo |

---

## 2. Module-by-Module Classification

### Legend
- ✅ **Reuse as-is** — Works identically for intraday
- 🔄 **Reuse with modifications** — Framework is sound, parameters/logic need adjustments
- ❌ **Swing-only** — Logic is fundamentally incompatible; do not reuse
- 🆕 **New implementation needed** — No equivalent exists

---

### Frontend

| Module / Page | Classification | Reason |
|---|---|---|
| App.tsx (router shell) | ✅ Reuse as-is | Pure routing infrastructure |
| AppLayout, ThemeProvider | ✅ Reuse as-is | UI chrome |
| api.ts (apiJson fetch wrapper) | ✅ Reuse as-is | Generic HTTP client |
| Dashboard.tsx | 🔄 Reuse with modifications | Replace swing portfolio metrics with intraday session P&L, square-off countdown |
| Signals.tsx | 🔄 Reuse with modifications | Add timeframe column (1m/5m/15m), session context |
| MarketScanner.tsx | 🔄 Reuse with modifications | Reorient for intraday heat, VWAP deviation, ORB status |
| BrokerExecution.tsx | ✅ Reuse as-is | Broker modal is broker-agnostic |
| KiteConnect.tsx | ✅ Reuse as-is | Session management works for intraday |
| AutomationHealth.tsx | ✅ Reuse as-is | Scheduler monitoring is generic |
| Settings.tsx | ✅ Reuse as-is | Config panel is generic |
| Backtest.tsx | 🔄 Reuse with modifications | Must support minute-bar backtests |
| WalkForwardValidation.tsx | 🔄 Reuse with modifications | Session-aware windows needed |
| PerformanceAnalytics.tsx | 🔄 Reuse with modifications | Add intraday-specific stats (VWAP slippage, fill rate) |
| TradeDecisions.tsx | 🔄 Reuse with modifications | Confidence display fine; decision labels are swing |
| PortfolioManager.tsx | 🔄 Reuse with modifications | Needs session exposure caps, square-off timer |
| Trades.tsx, TradeIntelligence.tsx | 🔄 Reuse with modifications | General enough; add trade duration column |
| StrategyLab.tsx, Optimizer.tsx | ❌ Swing-only | Optimises daily-bar strategies |
| LearningGovernance.tsx | 🔄 Reuse with modifications | Governance framework reusable; drift thresholds are swing |
| ResearchNotebook.tsx | ✅ Reuse as-is | Journal is session-agnostic |
| Notifications.tsx | ✅ Reuse as-is | Pure UI for alerts |
| Phase12Intelligence.tsx | 🔄 Reuse with modifications | Institutional scoring can be reused; factor weights need intraday tuning |
| Phase13Intelligence.tsx | 🔄 Reuse with modifications | Same as above |
| 🆕 New: IntradayDashboard | 🆕 New | Session P&L heatmap, VWAP live tracker, ORB status, square-off countdown |
| 🆕 New: OrderBook | 🆕 New | Real-time order/fill tracker for live assisted mode |
| 🆕 New: SessionReplay | 🆕 New | Bar-by-bar minute-chart replay of intraday trades |

---

### Backend (Node.js / Express)

| Module | Classification | Reason |
|---|---|---|
| app.ts (Express setup) | ✅ Reuse as-is | Generic |
| routes/index.ts | ✅ Reuse as-is | Router composition |
| routes/health.ts | ✅ Reuse as-is | Generic probes |
| routes/kite.ts | ✅ Reuse as-is | Works for intraday; already provides live quotes |
| routes/trading.ts | 🔄 Reuse with modifications | Add intraday-specific routes; remove swing-only endpoints |
| routes/stream.ts (SSE) | ✅ Reuse as-is | SSE fan-out is format-agnostic |
| scanScheduler.ts | 🔄 Reuse with modifications | Currently triggers 15-min cycles; intraday needs 1-min ticks and session-open/close hooks |
| alertQueue.ts | ✅ Reuse as-is | Delivery infrastructure is format-agnostic |
| pushNotifier.ts | ✅ Reuse as-is | Push delivery is generic |
| python-env.ts | ✅ Reuse as-is | Path resolution utility |
| events.ts (EventEmitter) | ✅ Reuse as-is | Generic pub-sub bus |
| 🆕 New: websocketBus.ts | 🆕 New | Minute-bar and tick streaming needs WebSocket, not just SSE |

---

### Authentication

| Module | Classification | Reason |
|---|---|---|
| No user authentication present | ✅ Reuse as-is (N/A) | Single-user tool; no auth layer exists |
| Zerodha Kite OAuth flow (kite.ts) | ✅ Reuse as-is | Already production-grade |

---

### Database

| Module | Classification | Reason |
|---|---|---|
| paper_portfolio table | 🔄 Reuse with modifications | Add `session_id`, `square_off_deadline` columns |
| paper_trades table | 🔄 Reuse with modifications | Add `timeframe`, `vwap_at_entry`, `ORB_level` columns |
| signals_cache table | 🔄 Reuse with modifications | Add `interval` (1m/5m/15m) and `session_ts` columns |
| signal_snapshots table | ✅ Reuse as-is | Snapshot audit is format-agnostic |
| push_subscriptions table | ✅ Reuse as-is | Generic |
| alert_deliveries table | ✅ Reuse as-is | Generic |
| 🆕 New: intraday_sessions table | 🆕 New | Store session P&L, VWAP history, ORB levels per date |
| 🆕 New: minute_ohlcv_cache table | 🆕 New | Persist intraday bars to reduce API calls |

---

### API Integrations

| Module | Classification | Reason |
|---|---|---|
| yfinance (daily data) | ✅ Reuse as-is | Swing history; still needed for regime detection |
| yfinance (intraday) | 🔄 Reuse with modifications | `interval='1m'` works but 7-day history limit applies |
| Zerodha Kite (quotes) | ✅ Reuse as-is | kite_quote_provider.py already handles live LTP |
| kite_session_manager.py | ✅ Reuse as-is | Session lifecycle is broker-generic |
| broker_client.py | 🔄 Reuse with modifications | Add intraday-specific order types (MIS, CO, BO) |
| Expo Push API | ✅ Reuse as-is | Generic notification delivery |
| 🆕 New: Kite WebSocket (kite.ticker) | 🆕 New | Sub-second tick streaming required for intraday; REST polling is inadequate |

---

### Market Data Pipeline

| Module | Classification | Reason |
|---|---|---|
| market_data.py | ❌ Swing-only | Fetches daily OHLCV only; no intraday intervals |
| market_data_engine.py | 🔄 Reuse with modifications | Supports multiple intervals but no minute-bar session splitting or VWAP reset |
| live_data_provider.py | 🔄 Reuse with modifications | Quality taxonomy and circuit breakers are reusable; needs intraday freshness rules (data older than 2 minutes is stale, not 15 minutes) |
| live_quote_service.py | 🔄 Reuse with modifications | TTL must shrink from 30s to 1–2s for intraday; add WebSocket path |
| kite_quote_provider.py | 🔄 Reuse with modifications | Good foundation; 30s cache is too stale for scalping |
| 🆕 New: intraday_data_pipeline.py | 🆕 New | Minute-bar fetcher with session-aware VWAP/RVOL calculation, ORB detection, gap analysis |

---

### Technical Indicators

| Module | Classification | Reason |
|---|---|---|
| indicator_engine.py | 🔄 Reuse with modifications | EMA/RSI/MACD/ATR are interval-agnostic; add VWAP, RVOL, EMA slope, anchored VWAP |
| EMA, RSI, MACD | ✅ Reuse as-is | Math is interval-agnostic |
| Supertrend | ✅ Reuse as-is | Works on any OHLCV bar |
| ATR | ✅ Reuse as-is | Used for stop-loss sizing |
| ❌ Missing: VWAP (session-reset) | 🆕 New | Must reset at 09:15 IST each session |
| ❌ Missing: RVOL (Relative Volume) | 🆕 New | Volume vs. 20-day same-time average |
| ❌ Missing: ORB levels | 🆕 New | Opening Range Breakout (first 15/30 min high/low) |
| ❌ Missing: Time-of-day features | 🆕 New | First 30 min, power hour, last 30 min regime |
| ❌ Missing: Gap analysis | 🆕 New | Gap %, type (gap-up/down/fill/breakaway) |
| ❌ Missing: VWAP bands | 🆕 New | Standard deviation bands around VWAP |

---

### Feature Engineering

| Module | Classification | Reason |
|---|---|---|
| adaptive_learning.py (feature dims) | 🔄 Reuse with modifications | Sector/Regime dimensions reusable; Technical dimension needs intraday features |
| trade_quality.py (6 sub-scores) | 🔄 Reuse with modifications | Volume sub-score needs RVOL; Trend sub-score needs VWAP alignment |
| ❌ Missing: session_features.py | 🆕 New | Time-of-day encoding, session quarter, distance-from-open, volatility burst detection |

---

### AI / Machine Learning

| Module | Classification | Reason |
|---|---|---|
| ai_decision.py | 🔄 Reuse with modifications | Framework sound; confidence adjustments reference ATR-based swing thresholds |
| decision_service.py | 🔄 Reuse with modifications | Orchestration logic reusable; `TIME_EXIT_FACTOR` and holding-period logic are swing |
| confidence_calibration.py | ✅ Reuse as-is | Isotonic/Platt scaling is interval-agnostic |
| market_regime.py | ✅ Reuse as-is | Macro regime (NIFTY/VIX) applies to intraday too |
| market_context.py | ✅ Reuse as-is | Directional bias is universal |
| phase13_intelligence.py (14-factor model) | 🔄 Reuse with modifications | Institutional scoring framework reusable; factor weights trained on daily bars |
| phase14_governance.py (champion-challenger) | ✅ Reuse as-is | Drift detection and human-approval model is protocol-agnostic |
| meta_learning.py | ✅ Reuse as-is | Failure attribution works for any trade log |
| strategy_evolution.py | ❌ Swing-only | A/B tests are tuned for swing entry conditions |

---

### Model Training

| Module | Classification | Reason |
|---|---|---|
| learning_engine.py | 🔄 Reuse with modifications | Per-strategy reliability computation is generic; needs intraday trade history |
| adaptive_learning.py | 🔄 Reuse with modifications | Pattern-matching framework reusable; dimension weights are swing-biased |
| historical_knowledge_builder.py | 🔄 Reuse with modifications | Must ingest minute-bar data, not just daily |

---

### Walk-Forward Validation

| Module | Classification | Reason |
|---|---|---|
| walk_forward_validator.py | 🔄 Reuse with modifications | No-lookahead window logic is sound; train/test split must be session-day based, not monthly |
| backtesting_engine.py | 🔄 Reuse with modifications | Bar-by-bar simulation works on any OHLCV; needs intraday cost model (brokerage, STT, exchange charges) and MIS square-off rule |
| phase16_validation.py | 🔄 Reuse with modifications | Validation reporting framework reusable |
| phase17_qa.py | ✅ Reuse as-is | QA suite is generic |
| phase22_evidence.py | ✅ Reuse as-is | Evidence accumulation protocol is format-agnostic |
| phase22_readiness.py | 🔄 Reuse with modifications | Some readiness checks are swing-specific (e.g., "250 trades at 2–5 per week" → "250 trades at 5–15 per day") |

---

### Confidence Scoring

| Module | Classification | Reason |
|---|---|---|
| confidence_calibration.py | ✅ Reuse as-is | Calibration math is universal |
| phase21_calibration.py | 🔄 Reuse with modifications | Bayesian shrinkage reusable; priors trained on swing data |
| phase21_thresholds.py | 🔄 Reuse with modifications | Threshold optimisation framework reusable; cutoffs must be re-derived on intraday data |

---

### Stock Scanner

| Module | Classification | Reason |
|---|---|---|
| market_scanner.py | ❌ Swing-only | Ranks stocks by multi-day opportunity score using daily data |
| live_scan_engine.py | 🔄 Reuse with modifications | Snapshot/audit architecture reusable; must operate on 1m/5m bars, not daily |
| scan_pipeline.py | ✅ Reuse as-is | Atomic bundle-publish protocol is format-agnostic |
| scan_state_store.py | ✅ Reuse as-is | Distributed lease management is generic |
| 🆕 New: intraday_scanner.py | 🆕 New | ORB-based, VWAP-deviation, RVOL-filtered universe filter; re-scans every minute |

---

### Ranking Engine

| Module | Classification | Reason |
|---|---|---|
| phase21_ranking.py | 🔄 Reuse with modifications | Composite ranking framework reusable; weight vector trained on daily bars |
| phase21_scorecard.py | 🔄 Reuse with modifications | Scorecard UI is generic; metrics must include intraday stats |
| opportunity_scanner.py | ❌ Swing-only | Computes multi-day "opportunity score" from daily data |

---

### Trade Signal Generation

| Module | Classification | Reason |
|---|---|---|
| signal_engine.py | ❌ Swing-only | Multi-timeframe alignment references daily + weekly + monthly bars |
| strategies.py (TrendRider, BreakoutHunter) | ❌ Swing-only | Entry/exit rules, hold periods, and ATR multipliers calibrated for 4–10 day holds |
| 🆕 New: intraday_signal_engine.py | 🆕 New | ORB breakout signals, VWAP deviation signals, momentum burst signals; timeframes: 1m/5m/15m |
| 🆕 New: intraday_strategies.py | 🆕 New | ORB, VWAP reversion, momentum, gap-fill — each with MIS square-off rules |

---

### Risk Management

| Module | Classification | Reason |
|---|---|---|
| phase11_risk.py | 🔄 Reuse with modifications | 8 pre-trade checks framework is reusable; sector concentration limits and "heat" logic must be redefined for intraday position limits |
| phase20_gates.py | 🔄 Reuse with modifications | Gate framework excellent; add intraday-specific gates (time-before-close, ORB window, RVOL minimum) |
| phase20_circuit_breaker.py | ✅ Reuse as-is | Consecutive-loss pauses work identically for intraday |
| 🆕 New: intraday_risk_engine.py | 🆕 New | Max open positions per session, max loss per session (capital%), mandatory square-off at 15:15 IST |

---

### Position Sizing

| Module | Classification | Reason |
|---|---|---|
| position_sizer.py | 🔄 Reuse with modifications | 1%-risk formula is universal; must account for MIS leverage (typically 5×), STT on square-off |
| portfolio_manager.py | ❌ Swing-only | Half-Kelly swing-portfolio allocation; intraday sizing is per-trade, per-session |
| 🆕 New: intraday_sizer.py | 🆕 New | Leveraged MIS sizing with per-session max-loss cap and slippage model |

---

### Paper Trading

| Module | Classification | Reason |
|---|---|---|
| paper_trader.py | 🔄 Reuse with modifications | Core simulator is reusable; needs MIS position lifecycle (auto square-off at 15:15, no carryforward) |
| phase20_executor.py | 🔄 Reuse with modifications | Durable execution ledger is reusable; add MIS fill model and broker cost engine |
| phase20_exits.py | 🔄 Reuse with modifications | Stop/target logic works; add mandatory time-exit rule |
| phase20_scheduler.py | 🔄 Reuse with modifications | Minute-tick framework is reusable; replace daily-scan triggers with per-minute intraday ticks |
| portfolio_store.py | 🔄 Reuse with modifications | State persistence is generic; add session isolation |

---

### Backtesting

| Module | Classification | Reason |
|---|---|---|
| backtesting_engine.py | 🔄 Reuse with modifications | Bar-by-bar engine works; needs intraday cost model, MIS square-off rule, and minute-bar data source |
| market_replay.py | 🔄 Reuse with modifications | Replay UI framework is reusable; requires minute-bar data |

---

### Trade Journal

| Module | Classification | Reason |
|---|---|---|
| trade_intelligence.py | ✅ Reuse as-is | Deduplication, normalization, and frozen-at-entry metrics are generic |
| trade_evaluator.py | ✅ Reuse as-is | MFE/MAE analysis works on any trade |
| trade_quality.py | 🔄 Reuse with modifications | Volume sub-score must use RVOL not absolute volume |
| phase18_notebook.py | ✅ Reuse as-is | Daily research journal is session-agnostic |

---

### Reporting & Analytics

| Module | Classification | Reason |
|---|---|---|
| analytics_engine.py | ✅ Reuse as-is | Performance metrics (win rate, profit factor, drawdown) are universal |
| performance_alerts.py | 🔄 Reuse with modifications | Degradation rules are universal; thresholds tuned for swing frequency |
| phase10_analytics.py | 🔄 Reuse with modifications | Analytics pipeline reusable; add intraday-specific breakdowns (time-of-day, session vs. pre-open) |
| report_engine.py | ✅ Reuse as-is | Report generation is format-agnostic |
| phase21_exports.py | ✅ Reuse as-is | Export infrastructure is generic |

---

### Scheduler / Background Jobs

| Module | Classification | Reason |
|---|---|---|
| scanScheduler.ts (Node.js) | 🔄 Reuse with modifications | Minute-ticker exists; must add pre-market preparation (08:45), session-open hook (09:15), square-off hook (15:15), session-close EOD (15:30) |
| phase20_scheduler.py (Python) | 🔄 Reuse with modifications | Excellent framework; replace 15-min scan cycle with 1-min intraday scan cycle |
| market_hours.py | ✅ Reuse as-is | NSE session state machine is exact; includes PRE_OPEN, OPEN, POST_CLOSE |

---

### Notifications

| Module | Classification | Reason |
|---|---|---|
| alertQueue.ts | ✅ Reuse as-is | Durable PostgreSQL delivery is generic |
| pushNotifier.ts | ✅ Reuse as-is | Expo push delivery is generic |
| alert_queue.py | ✅ Reuse as-is | Python-side alert dispatch is generic |
| email_alerts.py | ✅ Reuse as-is | Email transport layer is generic |

---

### Deployment

| Module | Classification | Reason |
|---|---|---|
| Replit-managed workflows | ✅ Reuse as-is | Platform infra is format-agnostic |
| artifact.toml (api-server, dashboard) | 🔄 Reuse with modifications | New intraday artifact will need its own TOML |
| pnpm monorepo structure | ✅ Reuse as-is | Workspace structure supports adding new packages |

---

### Environment Variables / Secrets Management

| Module | Classification | Reason |
|---|---|---|
| `ZERODHA_API_KEY`, `ZERODHA_API_SECRET` | ✅ Reuse as-is | Same credentials for intraday |
| `SESSION_SECRET` | ✅ Reuse as-is | Reusable if sharing session layer |
| `DATABASE_URL` | ✅ Reuse as-is | Can point intraday to same or separate DB |
| 🆕 New: `INTRADAY_CAPITAL` | 🆕 New | Separate capital allocation for intraday |
| 🆕 New: `INTRADAY_MAX_SESSION_LOSS_PCT` | 🆕 New | Circuit breaker threshold |

---

## 3. Data Flow

### Current Swing Trading Data Flow

```
User triggers scan (POST /api/run-scan)
        │
        ▼
scanScheduler.ts / Express route
        │ child_process.spawn
        ▼
main.py → live_scan_engine.py
        │
        ├─→ market_data_engine.py
        │       └─→ yfinance (daily OHLCV, 3-month history)
        │       └─→ kite_quote_provider.py (live LTP for OPEN positions)
        │
        ├─→ indicator_engine.py (EMA/RSI/MACD/ATR on daily bars)
        │
        ├─→ signal_engine.py (multi-TF rule-based scoring)
        │
        ├─→ market_regime.py (NIFTY/VIX macro context)
        │
        ├─→ ai_decision.py → decision_service.py
        │       └─→ adaptive_learning.py (pattern matching)
        │       └─→ confidence_calibration.py (probability mapping)
        │       └─→ phase13_intelligence.py (14-factor institutional score)
        │
        ├─→ phase20_gates.py (safety checks)
        │
        ├─→ phase20_executor.py (paper fill at last price)
        │
        └─→ scan_pipeline.py (atomic bundle publish to DB)
                │
                ▼
        PostgreSQL + JSON state files
                │
                ▼
        React Dashboard (TanStack Query polling) / Expo Mobile
```

### Proposed Intraday Data Flow (Additional Layer)

```
Market opens 09:15 IST
        │
        ▼
scanScheduler.ts (1-min tick)
        │
        ├─→ intraday_data_pipeline.py
        │       └─→ Kite WebSocket (tick stream) OR yfinance 1m
        │       └─→ VWAP accumulator (session-reset at 09:15)
        │       └─→ RVOL calculator (vs. 20-day same-time avg)
        │       └─→ ORB detector (captures first-15min range)
        │       └─→ Gap analyser (open vs. prev close)
        │
        ├─→ intraday_scanner.py (RVOL > threshold, ORB break, VWAP cross)
        │
        ├─→ indicator_engine.py (EMA/RSI on 1m/5m/15m bars)
        │
        ├─→ intraday_signal_engine.py
        │
        ├─→ intraday_risk_engine.py (session loss cap, position count)
        │
        ├─→ intraday_sizer.py (MIS leverage, cost engine)
        │
        └─→ phase20_executor.py (MIS paper fill + square-off)

15:15 IST → mandatory square-off hook (phase20_scheduler.py)
15:30 IST → session EOD → analytics_engine.py, phase18_notebook.py
```

---

## 4. AI Workflow

### Current (Swing)

1. **Scan** produces raw signals (BUY/SELL/HOLD per symbol)
2. **market_regime.py** classifies macro environment (Bull/Bear/Sideways/Volatile) using NIFTY 200-DMA and India VIX
3. **ai_decision.py** applies regime modifier (±20 points), risk-reward filter (min 1:2 ATR-based), multi-timeframe alignment check
4. **decision_service.py** aggregates: base signal + expectancy + adaptive learning patterns → final recommendation (STRONG_BUY to AVOID)
5. **phase13_intelligence.py** applies 14-factor institutional scoring (historical similarity, portfolio context, strategy eligibility)
6. **confidence_calibration.py** maps raw 0–100 score → win probability using Isotonic regression
7. **phase14_governance.py** monitors drift; freezes learning on performance degradation
8. Final recommendation passed to phase20_gates.py → executor

### Required Changes for Intraday

- Regime detection must use intraday NIFTY 1m bars (not daily 200-DMA)
- Risk-reward filter must use tick ATR, not daily ATR (much smaller)
- Multi-TF alignment must reference 1m/5m/15m (not daily/weekly/monthly)
- Confidence calibration must be re-derived on intraday trade history
- Learning patterns must use intraday entry conditions (ORB, VWAP, TOD)
- Time-of-day must be an explicit AI feature (first-30-min is high-risk)

---

## 5. Training Workflow

### Current

1. `walk_forward_validator.py` splits history into rolling windows (12-month train / 3-month test)
2. `backtesting_engine.py` simulates bar-by-bar on daily OHLCV
3. `learning_engine.py` computes per-strategy win rate / profit factor from paper trade history
4. `adaptive_learning.py` builds a pattern library: Sector × Regime × Technical dimensions
5. `confidence_calibration.py` refits Isotonic scaling model on latest results
6. `phase14_governance.py` promotes new champion only if performance improves and human approves
7. Model registry versioned in `phase14_model_registry.json`

### Required Changes for Intraday

- Walk-forward windows must be measured in **trading sessions** (days), not months
- Backtesting engine must operate on 1-minute OHLCV (requires minute-bar data store)
- Training data must include intraday features: VWAP deviation, RVOL, ORB result, gap type, time-of-day bucket
- "Reliable sample" thresholds must be re-derived (intraday generates 5–15 trades/day vs 2–5/week for swing)
- Minimum evidence for calibration should lower from ~250 total trades to ~250 sessions (≈ 1,250–3,750 trades)

---

## 6. Signal Generation Workflow

### Current (Swing)

```
symbol
  │
  ├─→ Daily OHLCV (90 days) via yfinance
  │
  ├─→ indicator_engine.py:
  │     EMA20, EMA50, EMA200, RSI(14), MACD(12,26,9), ATR(14), Supertrend
  │
  ├─→ signal_engine.py:
  │     Multi-TF check: daily + weekly + monthly alignment
  │     Regime gate: only BULLISH regime allows BUY signals
  │     Opportunity score: 0–100 composite
  │
  └─→ ai_decision.py → STRONG_BUY / BUY / HOLD / SELL / AVOID
```

### Proposed Intraday Signal Workflow

```
symbol (RVOL-filtered universe, ≥1.5× avg volume)
  │
  ├─→ 1m OHLCV (session bars) + 5m + 15m via Kite
  │
  ├─→ intraday_data_pipeline.py:
  │     VWAP (session-reset), RVOL, ORB (15min high/low), gap%
  │
  ├─→ indicator_engine.py (applied to 1m/5m/15m):
  │     EMA9, EMA21, RSI(14), MACD, ATR(14), Volume EMA
  │
  ├─→ intraday_signal_engine.py:
  │     ORB strategy: break above/below ORB range with volume
  │     VWAP strategy: deviation > 1 SD, reversion signal
  │     Momentum burst: RSI + MACD + volume alignment on 5m
  │
  └─→ intraday_risk_engine.py (session loss cap, position count, time gate)
        └─→ intraday_sizer.py → MIS quantity + stop distance
              └─→ phase20_executor.py → paper fill
```

---

## 7. Database Design

### Current Schema (PostgreSQL via Drizzle ORM)

```
paper_portfolio
  ├── id, cash, total_value, pnl, last_updated
  └── (no session isolation)

paper_trades
  ├── id, symbol, action (BUY/SELL), quantity, price
  ├── entry_date, exit_date, pnl
  └── (no timeframe, no session_id, no MIS flag)

signals_cache
  ├── symbol, signal, confidence, reason
  ├── scan_id, snapshot_ts, updated_at
  └── (no interval column — assumes daily)

signal_snapshots
  └── audit trail of signal states (generic)

push_subscriptions
  └── expo_token, min_confidence, symbol_filter

alert_deliveries
  └── idempotency_key, status, attempts, next_retry_at
```

### Required Additions for Intraday

```
intraday_sessions
  ├── session_date, session_open, session_close
  ├── orb_high, orb_low, orb_period_minutes
  ├── vwap_at_open, nifty_gap_pct
  ├── session_pnl, trade_count, win_count
  └── circuit_breaker_triggered (boolean)

paper_trades (new columns)
  ├── timeframe (1m/5m/15m/1d)
  ├── session_id → intraday_sessions.id
  ├── product_type (MIS/CNC)
  ├── vwap_at_entry, rvol_at_entry
  ├── orb_reference_level
  └── square_off_reason (SL/TARGET/TIME/MANUAL)

minute_ohlcv_cache
  ├── symbol, ts (1-min granularity)
  ├── open, high, low, close, volume
  └── vwap_cumulative, rvol
```

---

## 8. Existing Strengths

**Confidence: High** (directly observed in code)

1. **Production-grade safety architecture**: phase20_gates.py + circuit_breaker + phase22_readiness checklist provide an institutional-quality safeguard before any automated action.
2. **Durable state management**: scan_state_store.py uses DB-backed distributed leases, preventing duplicate scans and race conditions on Autoscale.
3. **Audit trail discipline**: Every scan snapshot is uniquely identified; every trade records frozen-at-entry indicator values via trade_intelligence.py.
4. **Layered validation**: walk_forward_validator.py enforces strict no-lookahead windows; phase14_governance.py requires human approval for model promotion.
5. **Quality taxonomy on data**: live_data_provider.py classifies data as LIVE/RECENT/STALE/DEGRADED/UNAVAILABLE, preventing trades on bad data.
6. **Comprehensive alerting**: PostgreSQL-backed alert queue with exponential backoff, idempotency keys, and dead-letter handling.
7. **Modular Python engine**: CLI dispatcher (main.py) makes each subsystem independently testable.
8. **Rich analytics**: analytics_engine.py produces standardised metrics (win rate, profit factor, Sharpe, drawdown) reusable across backtesting and live.
9. **Active learning governance**: phase14_governance.py + drift detection prevents the model from silently degrading.
10. **Market hours awareness**: market_hours.py correctly models NSE PRE_OPEN / OPEN / POST_CLOSE sessions with IST timezone.

---

## 9. Existing Weaknesses

**Confidence: High** (observed in code)

1. **Daily-bar assumption is pervasive**: signal_engine.py, strategies.py, market_scanner.py, portfolio_manager.py all hardcode daily OHLCV with no abstraction over interval. This is the single biggest migration obstacle.
2. **No WebSocket/streaming data**: kite_quote_provider.py polls every 30 seconds. Intraday strategies require sub-second to 1-second tick data via Kite's WebSocket.
3. **Spawning Python per request is a bottleneck**: Every API call creates a new Python process. For intraday where 50–100 calls/minute may occur, this is a performance ceiling.
4. **No VWAP, RVOL, ORB, or gap analysis**: indicator_engine.py has no session-aware calculations. These are the most important intraday indicators.
5. **No intraday cost engine**: backtesting_engine.py uses a simplified flat brokerage. MIS intraday has STT, exchange charges, SEBI turnover fee, and stamp duty that compound quickly.
6. **No MIS product-type awareness**: paper_trader.py and executor have no concept of intraday-only (MIS) positions that must be squared off by 15:15 IST.
7. **Confidence calibration trained on swing data**: The Isotonic scaling model is calibrated on multi-day holds. Applying it to intraday will produce miscalibrated probabilities.
8. **Duplicate logic between phases**: Phase 13 institutional scoring, adaptive_learning, and phase 21 advisory layers all adjust confidence with overlapping logic. Hard to audit total confidence shift.
9. **Magic numbers**: Numerous hardcoded thresholds (e.g., `TIME_EXIT_FACTOR = 2.0`, `MIN_RELIABLE_SAMPLE = 15`) are not documented or configurable.
10. **Monolithic main.py CLI**: Every subsystem is dispatched through a single CLI, making it hard to parallelize multiple intraday scans.

---

## 10. Intraday Migration Plan

### Shared Modules (unchanged)

- Express app.ts, routes/health.ts, routes/stream.ts
- alertQueue.ts, pushNotifier.ts, events.ts, python-env.ts
- market_hours.py, scan_state_store.py, scan_pipeline.py
- alert_queue.py, email_alerts.py
- confidence_calibration.py (framework; retrain data)
- trade_intelligence.py, trade_evaluator.py, analytics_engine.py
- phase20_circuit_breaker.py, phase14_governance.py
- phase17_qa.py, phase18_notebook.py
- PostgreSQL DB schema (extended, not replaced)

### Modules to Separate (different instances)

| Module | Swing Instance | Intraday Instance |
|---|---|---|
| signal_engine | ✅ Daily bars, keep | 🆕 1m/5m/15m bars |
| strategies.py | ✅ TrendRider, BreakoutHunter | 🆕 ORB, VWAP, Momentum |
| market_scanner.py | ✅ Daily universe scan | 🆕 Intraday universe scan |
| paper_trader.py | ✅ CNC positions (multi-day) | 🔄 MIS positions (same-day) |
| position_sizer.py | ✅ 1% risk, no leverage | 🔄 MIS leverage, session cap |
| walk_forward_validator.py | ✅ Monthly windows | 🔄 Session-day windows |
| backtesting_engine.py | ✅ Daily bar simulation | 🔄 1-minute bar simulation |
| portfolio_manager.py | ✅ Half-Kelly swing allocation | 🆕 Per-session intraday rules |

### Modules to Rewrite

| Module | Reason |
|---|---|
| signal_engine.py | Fundamentally swing-oriented; no clean parameterization path |
| strategies.py | Entry/exit logic hardcoded for multi-day holds |
| market_scanner.py | Daily Opportunity Score incompatible with intraday |
| live_data_provider.py | TTL and freshness rules must be completely redesigned for 1-second granularity |

### Modules to Remain Identical

All infrastructure, notification, audit, validation, and governance modules. See "Shared Modules" above.

---

## 11. Missing Components for Intraday

### 🆕 Intraday Data Pipeline

- **Kite WebSocket integration**: Sub-second tick streaming via `kite.ticker` (KiteTicker Python library). Required for real-time VWAP update, momentum detection, and fill simulation.
- **1-minute bar builder**: Aggregate tick stream into OHLCV bars; store in `minute_ohlcv_cache`.
- **Session isolation**: Each trading day resets VWAP, ORB, and cumulative volume at 09:15 IST.

### 🆕 Session-Aware Indicators

- **VWAP (Volume-Weighted Average Price)**: Mandatory. Session-reset at 09:15. Tracks price fair value intraday.
- **VWAP Standard Deviation Bands**: Upper/lower at 1σ, 2σ for reversal signals.
- **Anchored VWAP**: Reference price anchored to significant session events.
- **RVOL (Relative Volume)**: Today's volume vs. 20-day rolling average for the same 5-minute slot.

### 🆕 VWAP Reset Logic

- VWAP must recalculate from zero at 09:15:00 IST each session.
- Pre-market trades (09:00–09:15) must be excluded.
- Post-close trades (15:30+) must not contaminate next-day VWAP.

### 🆕 Time-of-Day Features

- **Session quarter encoding**: Q1 (09:15–10:30), Q2 (10:30–12:00), Q3 (12:00–14:00), Q4 (14:00–15:30)
- **Opening volatility flag**: First 15 minutes are high-risk (avoid entries in first 5 minutes)
- **Power hour flag**: 14:00–15:15 often sees directional moves

### 🆕 Opening Range Breakout (ORB)

- Capture high and low of first 15 or 30 minutes (configurable)
- ORB breakout signal: price closes above/below range with RVOL > 1.5
- Invalid above/below logic if gap is large (pre-defined threshold)

### 🆕 Gap Analysis

- **Gap % calculation**: `(open - prev_close) / prev_close × 100`
- **Gap classification**: Gap-up, Gap-down, Inside-day, Gap-and-go, Gap-fill
- **Gap quality filter**: Gaps > 2% are high-risk for intraday reversal; use as signal modifier

### 🆕 Relative Volume (RVOL)

- **Formula**: `current_volume_by_time / 20day_avg_volume_by_same_time`
- **Liquidity filter**: Only scan symbols with RVOL > 1.2 in first 30 minutes
- **High conviction threshold**: RVOL > 2.0 combined with ORB breakout = high confidence

### 🆕 Liquidity Filters

- Minimum tick volume per minute (avoid illiquid instruments)
- Bid-ask spread check (Kite Level 2 data required)
- Exclude symbols with circuit filters active

### 🆕 Intraday Risk Engine

- **Session loss cap**: e.g., stop all entries if daily P&L < −1.5% of capital
- **Max concurrent open positions**: Configurable (e.g., max 3 MIS positions simultaneously)
- **Time gate**: No new entries after 14:45 IST
- **Mandatory square-off**: All MIS positions closed at 15:15 IST regardless of P&L
- **Pre-close protection**: Avoid entries if < 30 minutes to market close

### 🆕 Position Sizing (Intraday)

- **MIS leverage model**: Account for 5× MIS margin (Zerodha standard)
- **True cost per trade**: Brokerage (₹20/order flat for Zerodha) + STT (0.025% on sell side for MIS) + Exchange charges + GST + Stamp duty
- **Per-trade risk cap**: max 0.5% of capital per trade (smaller than swing due to higher frequency)
- **Slippage model**: 0.05–0.1% for liquid NSE mid/large caps; higher for small caps

### 🆕 Cost Engine

| Cost Component | Rate (MIS intraday equity) |
|---|---|
| Brokerage | ₹20 per order (Zerodha flat) |
| STT | 0.025% of sell turnover |
| Exchange charges | 0.00345% of turnover |
| SEBI fee | 0.0001% of turnover |
| GST | 18% on (brokerage + exchange) |
| Stamp duty | 0.003% of buy turnover |

### 🆕 Slippage Model

- Market order assumption: 1-tick slippage for NSE Nifty 50 stocks
- Partial fill risk: model 90% fill rate on limit orders
- Impact cost: increases with position size / ADV ratio

### 🆕 Square-Off Rules

- Phase20Scheduler must trigger a mandatory EXIT at 15:15 IST for all MIS positions
- No new entries within 30 minutes of close
- Emergency square-off if daily loss limit breached mid-session

### 🆕 Paper Trading Engine (Intraday)

- Extends current paper_trader.py with `product_type='MIS'`
- Maintains session-level P&L separately from cumulative portfolio
- Simulates realistic fill (last price ± slippage model)
- EOD reconciliation: marks all unclosed positions to theoretical market price at 15:30

### 🆕 Model Monitoring

- Per-session win rate tracking (not per-week like swing)
- Intraday-specific drift alerts: < 40% win rate over 20 consecutive sessions
- VWAP model performance: track accuracy of VWAP-deviation reversal predictions separately

### 🆕 Performance Analytics (Intraday-Specific)

- Time-of-day P&L heatmap (which session quarter is most profitable)
- Strategy-by-session-type breakdown (gap-up day vs. range day vs. trending day)
- VWAP accuracy metrics (how often does price return to VWAP within N minutes)
- ORB success rate by gap type and RVOL level

---

## 12. Technical Debt

### Duplicate Logic

**Confidence: High**

- Confidence adjustment logic exists in at least 4 places: `adaptive_learning.py`, `ai_decision.py`, `phase13_intelligence.py`, and `phase21_calibration.py`. The total confidence delta applied to any signal requires reading all four files to audit, with no single aggregation point.
- Market regime classification is computed in both `market_regime.py` and `market_context.py` with overlapping logic.
- Opportunity score is computed in `market_scanner.py` and `opportunity_scanner.py` with partially duplicated logic.

### Performance Bottlenecks

**Confidence: High**

- **Python spawned per request**: Every Express route spawns a new Python process (`child_process.spawn`). Cold start is 400–800ms. For intraday where 50–100 API calls/minute are expected, this becomes the primary throughput bottleneck.
- **30-second quote cache**: `kite_quote_provider.py` caches LTP for 30 seconds. For intraday, a 30-second stale quote can result in trades at 0.3–0.5% adverse prices.
- **yfinance blocking downloads**: `yfinance.download()` in `market_data_engine.py` blocks the Python process for 5–15 seconds per symbol. Sequential, not parallel.
- **No WebSocket streaming**: All live data arrives via polling. Intraday trading requires event-driven tick processing.
- **No in-memory data bus**: Each Python process re-reads JSON state files. Minute-bar accumulation requires a shared in-memory store (Redis or PostgreSQL).

### Poor Architecture

**Confidence: High**

- **Monolithic CLI dispatcher (main.py)**: All commands routed through a single file. Adding an intraday command requires touching a central file shared with swing logic.
- **JSON file state**: Most state (portfolio, signals, scan snapshots) lives in JSON files next to the Python scripts. This is fragile for concurrent access, not crash-recoverable, and incompatible with multi-process or multi-instance deployment.
- **No service abstraction for data sources**: `market_data.py` and `market_data_engine.py` directly call `yfinance` with no interface layer. Swapping to Kite minute-bars requires editing core files.
- **Tight coupling between scan and execution**: `live_scan_engine.py` writes directly to JSON files consumed by `phase20_executor.py`. No message bus or event queue between scan and execution.

### Code Smells

**Confidence: High**

- **Magic numbers scattered across files**: `TIME_EXIT_FACTOR = 2.0`, `MIN_RELIABLE_SAMPLE = 15`, `STALE_THRESHOLD_MINUTES = 15` are hardcoded in individual files with no central config source.
- **Mock data fallback in production path**: `market_data_engine.py` generates geometric Brownian motion mock data if yfinance fails. This means production can silently trade on synthetic data.
- **Phase-numbered files**: 30+ files named `phase{N}_*.py` creates an implicit sequential dependency that is invisible at import time. Phase 20 files import Phase 14 files which import Phase 13 files — creating a deep dependency chain.
- **Heavy reliance on global JSON files**: `state.json`, `calibration_state.json`, `phase20_settings.json` are read and written by multiple modules. No locking on most reads; `flock` added only in Phase 18 for specific files.

### Technical Debt

**Confidence: High**

- **No instrument master / symbol validation for intraday**: `symbol_validation.py` validates NSE equity symbols against yfinance. Intraday instruments (futures, options, currency) have different token formats in Kite.
- **Calibration model trained on daily closes**: The Isotonic regression model in `confidence_calibration.py` uses day-close outcomes. Intraday outcomes at 1-minute resolution are fundamentally different distributions.
- **Walk-forward windows are monthly**: For intraday data (375 bars/day), monthly windows contain ~7,500 bars. Training/test split should be measured in sessions (days), not calendar months.
- **No separation of intraday vs. swing trade records**: `trade_intelligence.py` stores all trades in the same repository. Mixing daily and intraday trades contaminates learning models for both.

### Security Concerns

**Confidence: Medium**

- **API key stored in environment variables only**: The Zerodha API secret is in `ZERODHA_API_SECRET`. This is correct practice, but there is no key rotation mechanism.
- **No request authentication**: The Express API server has no auth middleware. Any process on the same network can call `/api/run-scan` or `/api/portfolio`. Acceptable for single-user dev; unacceptable for cloud deployment.
- **Access token persisted in local file**: `kite_token_store.py` writes Zerodha access tokens to a local file (chmod 600) as fallback. On Replit, this file may not survive container restarts reliably.
- **No rate limiting on scan trigger**: `POST /api/run-scan` can be called repeatedly; each call spawns a Python subprocess and fetches from yfinance. No debounce or concurrency gate at the Express layer.

---

## 13. Final Deliverables

### 13.1 Current Architecture Diagram (Text)

```
┌──────────────────────────────────────────────────────────────┐
│                    SWING TRADING PLATFORM                     │
├──────────────────────────────────────────────────────────────┤
│  WEB DASHBOARD (React/Vite, 43 pages)                        │
│  MOBILE APP (Expo/React Native, 6 screens)                   │
│    └── TanStack Query polling /api/*                         │
├──────────────────────────────────────────────────────────────┤
│  EXPRESS API (Node.js 24, TypeScript)                        │
│  ├── routes/trading.ts      → paper trading ops             │
│  ├── routes/kite.ts         → Zerodha OAuth + quotes        │
│  ├── routes/phaseXX.ts      → per-phase endpoints           │
│  ├── scanScheduler.ts       → 15-min cron trigger           │
│  ├── alertQueue.ts          → PostgreSQL-backed delivery     │
│  └── pushNotifier.ts        → Expo Push API                 │
├──────────────────────────────────────────────────────────────┤
│  PYTHON ENGINE (spawned per request via child_process)       │
│  main.py CLI dispatcher                                      │
│  ├── DATA: yfinance (daily) + Kite REST quotes (30s TTL)    │
│  ├── INDICATORS: EMA/RSI/MACD/ATR/Supertrend (daily bars)   │
│  ├── SIGNALS: rule-based, daily multi-TF alignment          │
│  ├── AI: 14-factor scoring, confidence calibration           │
│  ├── LEARNING: adaptive patterns, walk-forward validation    │
│  ├── EXECUTION: MIS-unaware paper fill, JSON state          │
│  └── GOVERNANCE: drift detect, human-approval gate          │
├──────────────────────────────────────────────────────────────┤
│  PERSISTENCE                                                  │
│  ├── PostgreSQL (paper_trades, signals_cache, alerts)       │
│  └── JSON files (portfolio state, scan snapshots)           │
└──────────────────────────────────────────────────────────────┘
```

---

### 13.2 Recommended Intraday Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   INTRADAY TRADING PLATFORM                   │
├──────────────────────────────────────────────────────────────┤
│  WEB DASHBOARD (new intraday artifact or extended pages)     │
│  ├── IntradayDashboard: session P&L, VWAP tracker, ORB      │
│  ├── SessionReplay: 1-minute bar-by-bar replay              │
│  ├── OrderBook: real-time fill tracker                       │
│  └── Existing pages (adapted)                               │
├──────────────────────────────────────────────────────────────┤
│  EXPRESS API (extended, not replaced)                        │
│  ├── scanScheduler.ts → 1-min ticks + session hooks         │
│  ├── New: websocketBus.ts → tick streaming                  │
│  └── Existing: alertQueue, pushNotifier, kite.ts            │
├──────────────────────────────────────────────────────────────┤
│  PYTHON ENGINE (refactored to long-running process)          │
│  ├── DATA: Kite WebSocket (tick) → 1m bar builder           │
│  │         yfinance (daily) for regime detection only        │
│  ├── INTRADAY PIPELINE:                                      │
│  │   VWAP (session-reset) + RVOL + ORB + Gap analysis       │
│  ├── INDICATORS: existing + VWAP bands + TOD features       │
│  ├── SIGNALS: intraday_signal_engine (ORB/VWAP/Momentum)    │
│  ├── RISK: intraday_risk_engine (session cap, square-off)   │
│  ├── SIZING: intraday_sizer (MIS leverage + cost engine)    │
│  ├── EXECUTION: paper_trader (MIS mode) + cost model        │
│  ├── AI: retrained calibration on intraday trade history     │
│  └── GOVERNANCE: reused (phase14, phase22)                  │
├──────────────────────────────────────────────────────────────┤
│  PERSISTENCE (extended schema)                               │
│  ├── PostgreSQL (+ intraday_sessions, minute_ohlcv_cache)   │
│  └── Redis (optional: shared in-memory tick buffer)         │
└──────────────────────────────────────────────────────────────┘
```

---

### 13.3 Reusable Modules (No Changes)

**Confidence: High**

1. Express infrastructure (app.ts, routes/health.ts, routes/stream.ts, routes/kite.ts)
2. alertQueue.ts, pushNotifier.ts, events.ts, python-env.ts
3. alert_queue.py, email_alerts.py
4. market_hours.py
5. scan_state_store.py, scan_pipeline.py
6. confidence_calibration.py (framework; data must be replaced)
7. trade_intelligence.py, trade_evaluator.py
8. analytics_engine.py, report_engine.py
9. phase20_circuit_breaker.py
10. phase14_governance.py (drift detection + human approval)
11. phase17_qa.py, phase18_notebook.py
12. PostgreSQL Drizzle schema (extended)
13. pnpm monorepo structure, artifact routing

---

### 13.4 Modules Requiring Redesign

**Confidence: High**

1. **live_data_provider.py** — Freshness taxonomy must change from 15-min stale to 2-min stale
2. **live_quote_service.py** — TTL must drop from 30s to 1–2s; add WebSocket path
3. **kite_quote_provider.py** — 30s cache incompatible with intraday; replace with tick-driven update
4. **backtesting_engine.py** — Must operate on 1-min bars with MIS cost model and square-off rule
5. **walk_forward_validator.py** — Windows must be measured in sessions, not months
6. **phase20_scheduler.py** — Replace 15-min scan cycle with 1-min intraday ticks + session event hooks
7. **scanScheduler.ts** — Add pre-market (08:45), session-open (09:15), square-off (15:15) hooks
8. **paper_trader.py** — Add MIS product type, mandatory square-off, session isolation
9. **position_sizer.py** — Add MIS leverage model and intraday cost engine
10. **portfolio_manager.py** — Completely different logic for intraday; keep swing version untouched
11. **adaptive_learning.py** — Feature dimensions must include VWAP, ORB, TOD, gap type
12. **trade_quality.py** — Volume sub-score must use RVOL, not absolute volume
13. **phase22_readiness.py** — Evidence thresholds must reflect intraday frequency

---

### 13.5 Completely New Modules

**Confidence: High**

1. **intraday_data_pipeline.py** — Kite WebSocket tick ingestion, 1m bar builder, session management
2. **intraday_scanner.py** — RVOL-filtered universe scan, ORB detection, VWAP deviation scoring
3. **intraday_signal_engine.py** — ORB breakout, VWAP reversion, momentum burst strategies
4. **intraday_strategies.py** — Strategy definitions with MIS square-off rules and intraday entry conditions
5. **intraday_risk_engine.py** — Session loss cap, position count limit, time gates, mandatory square-off
6. **intraday_sizer.py** — MIS leverage sizing, brokerage + STT + exchange cost model, slippage model
7. **session_features.py** — Time-of-day encoding, session quarter, distance-from-open, volatility burst
8. **vwap_engine.py** — Session-reset VWAP, standard deviation bands, anchored VWAP
9. **gap_analyser.py** — Gap % calculation, gap classification, gap-fill prediction
10. **rvol_calculator.py** — 20-day rolling average per 5-minute slot, real-time RVOL
11. **orb_detector.py** — First-N-minute high/low capture, breakout signal generation
12. **cost_engine.py** — NSE intraday cost model (brokerage, STT, exchange, SEBI, GST, stamp duty)
13. **websocketBus.ts** — Node.js WebSocket server for tick streaming to frontend
14. **IntradayDashboard.tsx** — Session P&L heatmap, live VWAP, ORB status, square-off countdown
15. **SessionReplay.tsx** — Bar-by-bar 1-minute chart replay with signal overlay

---

### 13.6 Risks

| Risk | Severity | Confidence | Mitigation |
|---|---|---|---|
| Kite WebSocket rate limits | High | High | Use a single persistent connection per session; avoid reconnecting on every scan |
| 1-minute bar data availability via yfinance | High | High | yfinance limits intraday history to 7 days; plan to persist all bars in PostgreSQL immediately |
| Calibration model applied to wrong distribution | High | High | Must retrain confidence_calibration.py on ≥500 intraday trades before enabling automation |
| Python spawned per request cannot handle 1-min ticks | High | High | Migrate hot-path Python to a long-running process with a message queue (or FastAPI) |
| Mixing swing and intraday trades in learning models | High | High | Tag all trades with `product_type` and `timeframe`; filter strictly in learning queries |
| MIS square-off delay risk | High | Medium | Phase20Scheduler must guarantee 15:15 trigger even if circuit breaker is active |
| No auth on API endpoints | Medium | High | Add token-based API auth before cloud deployment |
| JSON state file corruption under concurrent access | Medium | High | Migrate all state to PostgreSQL; eliminate JSON file writes from hot path |
| False confidence from swing-calibrated model | Medium | High | Create a separate calibration model instance for intraday; do not share |
| Slippage underestimation in backtesting | Medium | Medium | Use bid-ask spread data from Kite Level 2 for realistic slippage modelling |

---

### 13.7 Technical Recommendations

**Priority: Critical**

1. **Migrate Python hot path to long-running process**: Replace `child_process.spawn` with a persistent Python FastAPI or gRPC service. This is the single highest-impact change for intraday viability. **(Confidence: High)**
2. **Implement Kite WebSocket (KiteTicker)**: REST polling cannot support intraday at 1-second granularity. Switch to `KiteTicker` for tick streaming. **(Confidence: High)**
3. **Separate intraday from swing trade records**: Add `product_type` and `timeframe` columns immediately; enforce strict filtering in all learning queries. **(Confidence: High)**
4. **Build the cost engine before any backtesting**: Intraday P&L is dominated by transaction costs at high frequency. An accurate cost model must exist before the first backtest is trusted. **(Confidence: High)**
5. **Build VWAP and ORB modules first**: These are prerequisites for all intraday signal strategies. **(Confidence: High)**

**Priority: High**

6. **Persist all 1-minute bars to PostgreSQL immediately**: yfinance 7-day limit means you lose training data if you don't persist. **(Confidence: High)**
7. **Create a separate calibration model for intraday**: Do not reuse the swing-trained Isotonic model. **(Confidence: High)**
8. **Implement MIS square-off guarantee**: The 15:15 IST square-off must be the highest-priority scheduler hook, overriding all other gates. **(Confidence: High)**
9. **Add Redis or PostgreSQL-backed shared state**: Eliminate JSON file state from the hot execution path. **(Confidence: High)**
10. **Refactor confidence score aggregation into a single module**: Currently split across 4+ files. Create a `ConfidenceAggregator` that is the single caller of all adjustment layers. **(Confidence: Medium)**

**Priority: Medium**

11. **Implement per-API-endpoint debounce for scan trigger**: Prevent duplicate scans from rapid button presses or polling clients. **(Confidence: High)**
12. **Add API authentication middleware**: Even a shared bearer token significantly reduces attack surface for cloud deployment. **(Confidence: High)**
13. **Replace mock data fallback with explicit failure**: Remove GBM mock-data generation from production path; return a clear error instead. **(Confidence: High)**

---

### 13.8 Phased Migration Roadmap

#### Phase A — Infrastructure Preparation (2–3 weeks)
*Do not touch swing platform*

1. Add `product_type`, `timeframe`, `session_id` columns to existing DB tables
2. Create `intraday_sessions`, `minute_ohlcv_cache` tables
3. Implement Kite WebSocket tick ingestion (`kite_ticker.py`) — write only, no signal logic
4. Build 1-minute bar builder with session isolation
5. Migrate Python hot path to a long-running FastAPI process (or keep spawn but add `interval` parameter)
6. Add WebSocket server to Express (websocketBus.ts) for real-time frontend updates

#### Phase B — Core Intraday Indicators (2–3 weeks)

7. Implement `vwap_engine.py` (session-reset VWAP, SD bands)
8. Implement `rvol_calculator.py` (20-day same-slot rolling average)
9. Implement `gap_analyser.py`
10. Implement `orb_detector.py` (configurable 15/30 min)
11. Implement `session_features.py` (TOD encoding, session quarter)
12. Extend `indicator_engine.py` to accept interval parameter

#### Phase C — Intraday Signal Engine (2–3 weeks)

13. Implement `intraday_strategies.py` (ORB, VWAP reversion, momentum)
14. Implement `intraday_signal_engine.py`
15. Implement `intraday_scanner.py` (RVOL-filtered universe)
16. Backtest all three strategies on 3 months of 1-min historical data
17. Verify walk-forward result is positive expectancy before enabling any automation

#### Phase D — Risk & Execution (2 weeks)

18. Implement `cost_engine.py` (full NSE MIS cost model)
19. Implement `intraday_sizer.py` (MIS leverage + slippage)
20. Implement `intraday_risk_engine.py` (session cap, square-off enforcement)
21. Extend `paper_trader.py` with MIS mode and 15:15 square-off hook
22. Add mandatory square-off hook to `phase20_scheduler.py`

#### Phase E — AI & Learning (3–4 weeks)

23. Collect ≥200 intraday paper trades with full feature capture
24. Re-train `confidence_calibration.py` on intraday trade outcomes
25. Extend `adaptive_learning.py` with intraday feature dimensions (VWAP, ORB, TOD, gap)
26. Re-run `walk_forward_validator.py` with session-day windows
27. Validate: win rate > 45%, profit factor > 1.3 over 3 months of paper sessions

#### Phase F — Frontend & Monitoring (2 weeks)

28. Build `IntradayDashboard.tsx` (session P&L, VWAP ticker, ORB status, square-off countdown)
29. Build `SessionReplay.tsx` (1-minute chart replay)
30. Add intraday performance analytics pages (TOD heatmap, strategy breakdown)
31. Extend `AutomationHealth.tsx` with intraday-specific scheduler health

#### Phase G — Production Readiness (2 weeks)

32. Run `phase22_readiness.py` checklist (adapted for intraday)
33. Add API authentication middleware
34. Migrate remaining JSON file state to PostgreSQL
35. Security review: verify no real orders can be placed accidentally
36. Documentation: intraday runbook, session start/end procedures

---

**Total estimated timeline**: 15–19 weeks for a production-ready intraday paper trading platform.

---

## Confidence Summary

| Section | Confidence | Basis |
|---|---|---|
| Module classifications | **High** | Direct code inspection via subagents |
| Data flow diagrams | **High** | Traced from main.py through all callers |
| Existing strengths | **High** | Observed architectural patterns in code |
| Existing weaknesses | **High** | Confirmed by reading implementation details |
| Missing components list | **High** | Verified absence in codebase + NSE intraday requirements |
| Technical debt findings | **High** | Directly observed in code |
| Phased roadmap timeline | **Medium** | Best-practice estimates; actual effort depends on team size and familiarity |
| Slippage/cost model values | **Medium** | Standard Zerodha published rates; verify against current brokerage schedule |
| Redis recommendation | **Medium** | Industry best practice for tick data; PostgreSQL LISTEN/NOTIFY is a viable alternative |
| AI model retraining estimates | **Medium** | Depends on live paper trade volume; 200 trades minimum is a conservative estimate |

---

*This document is a read-only analysis. No code was modified, created outside this document, or deleted.*
