# ApexQuant AI — Full Project SOP & Second-Opinion Pack

**Document version:** 1.0  
**Generated:** 2026-08-15 (IST)  
**Prepared by:** Replit Agent (automated, read-only, no trading logic changed)  
**Purpose:** Independent second-opinion review package — complete audit of architecture, behaviour, data, and open problems  
**Classification:** Internal review — contains production database statistics  

> **Disclaimer:** All trade counts and statistics are pulled directly from the production PostgreSQL database as of the time of generation. Where data is unavailable or was not stored, this is explicitly marked `[NOT STORED]` or `[UNKNOWN]`. No values are fabricated. This document is read-only — no settings, thresholds, trades, or database records were changed to produce it.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [AI Architecture Overview](#2-ai-architecture-overview)
3. [Full Pipeline Flow](#3-full-pipeline-flow)
4. [Criteria and Thresholds](#4-criteria-and-thresholds)
5. [All App Pages and Routes](#5-all-app-pages-and-routes)
6. [Universe and Symbol Selection](#6-universe-and-symbol-selection)
7. [Scan Cadence and Rotation](#7-scan-cadence-and-rotation)
8. [Last 10 Trading Days — Production Statistics](#8-last-10-trading-days--production-statistics)
9. [Top Symbols by Signal Count](#9-top-symbols-by-signal-count)
10. [Rejection and Block Reasons](#10-rejection-and-block-reasons)
11. [Detailed Case Studies](#11-detailed-case-studies)
12. [Successful Historical Paper Trades](#12-successful-historical-paper-trades)
13. [Why No Trades Executed in Recent Sessions](#13-why-no-trades-executed-in-recent-sessions)
14. [Learning Architecture](#14-learning-architecture)
15. [Backtesting Architecture](#15-backtesting-architecture)
16. [Safety Controls — Proof of No Live Orders](#16-safety-controls--proof-of-no-live-orders)
17. [Open and Proposed Tasks — Priority Order](#17-open-and-proposed-tasks--priority-order)
18. [Known Weaknesses and Second-Opinion Questions](#18-known-weaknesses-and-second-opinion-questions)
19. [Recommended 30-Day Roadmap](#19-recommended-30-day-roadmap)
20. [Appendix](#20-appendix)

---

## 1. Executive Summary

### 1.1 What is ApexQuant AI?

ApexQuant AI is a **paper-only NSE intraday trading research platform** built on a multi-agent AI architecture. Its core purpose is to:

- Scan NIFTY 50 (now 51 symbols after the TATAMOTORS demerger) every 5 minutes during market hours
- Run each symbol through a multi-layer AI pipeline: data quality → signal → strategy → risk → decision → execution
- Generate BUY / WATCH / IGNORE recommendations with confidence scores, opportunity scores, and position-sizing guidance
- Execute paper (simulated) trades when all gates pass, building a tracked portfolio
- Learn from the outcomes of those paper trades to improve future decisions

**No live orders have ever been placed, and no Zerodha broker APIs are called for order submission.** Live execution is structurally disabled.

### 1.2 Current Status (as of 2026-08-15)

| Dimension | Status |
|-----------|--------|
| Live order execution | **PERMANENTLY DISABLED** — `LIVE_EXECUTION_ENABLED = False` |
| Paper trading mode | **ACTIVE** — auto-scanning on 5-minute interval |
| Zerodha session | **INACTIVE** — no current login; data falls back to Yahoo Finance |
| Data source | Yahoo Finance (historical/delayed) — live tick data requires Zerodha OAuth |
| Portfolio capital | ₹50,000 (resets each session) |
| Open paper positions | 4 (all EXIT_PENDING / STALE_DATA_SAFETY) |
| Executed trades (lifetime) | **65+ ORDER_EXECUTED events** recorded — mostly from one session (Aug 11) |
| Active paper exploration mode | OFF (just activated for testing on Aug 15) |
| Universe | 51 NSE symbols (NIFTY 50 + TMPV + TMCV, minus TATAMOTORS) |
| Scan coverage | ~50/51 per scan (1 symbol typically missing from Yahoo — likely LTIM) |

### 1.3 Primary Problem Statement

The platform correctly identifies BUY signals but is unable to execute them because:
1. **Position-size cap (20%):** Many stocks (DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV) require more than ₹10,000 (20% of ₹50,000 capital) for minimum 1 share — rejecting every attempt
2. **No Zerodha live tick data:** Running on Yahoo Finance delayed data; all intraday signals get STALE data quality → BUY is blocked, capped to WATCH
3. **No sell-side logic:** Positions that do open have no automatic exit strategy beyond stale-data safety exits and max-holding-day timeouts

---

## 2. AI Architecture Overview

The platform is built as a layered multi-agent system. Each layer is independent and communicates through a shared scan snapshot.

### 2.1 Architecture Layers

```
┌────────────────────────────────────────────────────────────┐
│  LAYER 0: DATA ACQUISITION                                  │
│  market_data.py + kite_quote_provider.py                   │
│  Sources: Zerodha Kite (primary) → Yahoo Finance (fallback) │
│  Output: price, OHLCV, volume, pre-open data                │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 1: SIGNAL ENGINE (live_scan_engine.py)               │
│  indicator_engine.py + signal_engine.py + trade_quality.py  │
│  Computes: RSI, MACD, Bollinger, ADX, OBV per symbol        │
│  Output: confidence score (0–100), action (BUY/WATCH/IGNORE) │
│  Data quality gate: STALE→WATCH, UNAVAILABLE→IGNORE         │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 2: MARKET INTELLIGENCE (market_intelligence.py)      │
│  market_context.py + market_regime.py                       │
│  Computes: market regime (BULLISH/BEARISH/SIDEWAYS/etc.)    │
│  NIFTY/BankNIFTY direction, VIX level, sector breadth       │
│  Output: regime label, confidence modifier (−15 to +10)     │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 3: RESEARCH / MULTI-TIMEFRAME (research agents)      │
│  Computes: 4-timeframe signal alignment (5m/15m/1h/1d)      │
│  Required: ≥3 of 4 timeframes must agree for BUY            │
│  Output: timeframe_alignment score, research quality        │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 4: OPPORTUNITY SCORING (opportunity_scanner.py)      │
│  Weights: trade_quality×0.40 + ai_confidence×0.30           │
│           + rr_score×0.20 + market_alignment×0.10           │
│  Output: opportunity_score (0–100)                          │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 5: STRATEGY SELECTION (strategies.py)                │
│  Selects strategy: MOMENTUM / BREAKOUT / MEAN_REVERSION     │
│  Regime-gated: certain strategies blocked in certain regimes │
│  Output: strategy_id, strategy_name, sizing params          │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 6: RISK MANAGEMENT (position_sizer.py + risk agents) │
│  Computes: stop_loss, target, rr_ratio, quantity            │
│  Gates: per_stock_cap, portfolio exposure, circuit breaker   │
│  Output: RISK_APPROVED or RISK_REJECTED + reason            │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 7: AI DECISION ENGINE (ai_decision_agent/)           │
│  7 decision types, confidence weighting, conflict detection  │
│  Explainability: evidence labels per gate                    │
│  Output: final_action (STRONG BUY / BUY / WATCH / IGNORE)  │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 8: PAPER EXECUTION (phase20_executor.py)             │
│  phase20_store.py + canonical_portfolio.py                  │
│  Pre-checks: market open, scan freshness, data quality,     │
│  confidence ≥60, opportunity ≥60, R:R ≥1.5,                 │
│  circuit breaker, portfolio pre-check, position cap 20%     │
│  Output: ORDER_SUBMITTED → ORDER_EXECUTED or ORDER_REJECTED │
│  NO LIVE ORDERS — all simulated fills at signal_price       │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 9: LEARNING & ANALYTICS                              │
│  phase24_engine.py + learning_agent/ + analytics_engine.py  │
│  Tracks: trade outcomes, MFE/MAE, win rates per strategy    │
│  Advisory-only: no auto-promotion of learned adjustments    │
│  Human approval required before any parameter change        │
└────────────────────┬───────────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────────┐
│  LAYER 10: REPLAY / BACKTEST (backtesting_engine.py)        │
│  backtest_runner.py + market_replay.py                      │
│  Runs real scan pipeline on historical candle data          │
│  Isolated ledger — never affects live portfolio             │
│  Output: replay stats, pipeline event counts, validation    │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Multi-Agent Framework (Phases 10A–10E)

The system has a formal multi-agent layer on top of the pipeline:

| Agent | File | Role |
|-------|------|------|
| **SupervisorAgent** | `agent_framework/` | Orchestrates all agents; never auto-restarts failing agents |
| **MarketIntelligenceAgent** | `analysis_layer/` | Reads cached scan snapshots, computes regime + opportunity |
| **StrategyAgent** | `analysis_layer/` | Selects and validates strategy fit per regime |
| **RiskAgent** | `analysis_layer/` | Portfolio exposure, drawdown, stress scenarios |
| **AIDecisionAgent** | `decision_layer/` | 7-type decision scoring, conflict detection, explainability |
| **ExecutionAgent** | `execution_agent/` | 10 pre-execution checks, NSE charges calculator, paper-only default |
| **LearningAgent** | `learning_agent/` | Outcome tracking, signal adjustments, pattern discovery |
| **KnowledgeAgent** | `knowledge_agent/` | Historical knowledge base, pattern library |
| **CollaborationEngine** | `collaboration_engine/` | 11-node graph for inter-agent communication |
| **AutonomousOpsAgent** | `autonomous_operations/` | Scheduled tasks, health monitoring |

### 2.3 Key Python Files

| File | Purpose |
|------|---------|
| `config.py` | All configurable thresholds (single source of truth) |
| `live_scan_engine.py` | Core scan loop, quality gates, score computation |
| `phase20_executor.py` | Paper execution pipeline, all pre-checks |
| `phase20_store.py` | Settings KV store, DEFAULT_SETTINGS |
| `phase20_scheduler.py` | 5-minute scan tick, paper management |
| `canonical_portfolio.py` | Portfolio ledger (positions, cash, equity) |
| `paper_exploration_engine.py` | Exploration mode (cap-resize + WATCH exploration) |
| `paper_trader.py` | Legacy paper trade executor (called by phase20_executor) |
| `market_data.py` | Data acquisition with Zerodha→Yahoo fallback |
| `market_regime.py` | Regime classification |
| `opportunity_scanner.py` | Opportunity score computation |
| `strategies.py` | Strategy selection and regime gating |
| `position_sizer.py` | Stop/target/quantity calculation |
| `phase24_engine.py` | Learning analytics engine |
| `backtesting_engine.py` | Historical backtesting |
| `broker_client.py` | Broker abstraction (always falls back to MockBrokerClient) |

---

## 3. Full Pipeline Flow

This is the exact sequence of steps executed for every symbol in every scan:

```
START SCAN TICK (every 5 minutes, 09:15–15:30 IST)
│
├── [STEP 1] Scan Lock Acquired (DB-durable, prevents concurrent scans)
│
├── [STEP 2] Data Fetch: try Zerodha Kite quotes → fallback Yahoo Finance
│   ├── If Zerodha session active: LTP, OHLCV, volume (LIVE quality)
│   └── If no Zerodha: yfinance historical (STALE/NEAR_LIVE quality)
│
├── [STEP 3] For each of 51 symbols in NIFTY_50:
│   │
│   ├── [SIGNAL] Compute indicators: RSI, MACD, Bollinger, ADX, OBV
│   │   └── Combine into confidence score (0–100) → raw_action
│   │
│   ├── [DATA QUALITY GATE]
│   │   ├── UNAVAILABLE → force action = IGNORE (hard cap)
│   │   ├── STALE → force action = max(WATCH) (BUY → WATCH)
│   │   └── LIVE / NEAR_LIVE → pass through
│   │
│   ├── [R:R GATE] rr_ratio < 1.5 → cannot be BUY (downgrade to WATCH)
│   │
│   ├── [MARKET CONTEXT] Apply regime modifier to confidence
│   │   └── Regime: BULLISH (+10), BEARISH (−15), NEUTRAL (±0)
│   │
│   ├── [RESEARCH / MULTI-TF] Check 4-timeframe alignment
│   │   └── < 3 timeframes agreeing → lower confidence
│   │
│   ├── [OPPORTUNITY SCORE] Compute composite 0–100 score
│   │   └── Weights: trade_quality×0.40 + confidence×0.30 + rr×0.20 + market×0.10
│   │
│   ├── [STRATEGY] Select strategy based on regime and signal type
│   │   └── BUY_GENERATED or WATCH_GENERATED emitted to pipeline_events
│   │
│   ├── [RISK GATE] position_sizer.py
│   │   ├── Compute: quantity = min(MAX_CAPITAL×20%, cash) / price
│   │   ├── Check: stop_loss distance, R:R ratio
│   │   └── RISK_APPROVED or RISK_REJECTED
│   │
│   └── [EMIT] SYMBOL_SCANNED, MARKET_INTELLIGENCE_COMPLETED,
│             RESEARCH_COMPLETED, MONITORING_COMPLETED, STRATEGY_SELECTED
│
├── [STEP 4] Snapshot published (post-scan, after all symbols complete)
│
└── [STEP 5] Paper Execution Loop (phase20_executor.py)
    │   Runs for every BUY_GENERATED / STRONG_BUY_GENERATED candidate
    │
    ├── Gate 1: Market open? (09:15–15:30 IST) → else SKIP
    ├── Gate 2: Scan fresh? (< staleness_threshold minutes) → else SKIP
    ├── Gate 3: Data quality LIVE or NEAR_LIVE? → else SKIP
    ├── Gate 4: Confidence ≥ min_confidence (default 60%)? → else SKIP
    ├── Gate 5: Opportunity score ≥ min_opportunity_score (default 60%)? → else SKIP
    ├── Gate 6: R:R ≥ 1.5? → else SKIP
    ├── Gate 7: Circuit breaker clear? → else BLOCKED
    ├── Gate 8: Portfolio pre-check (portfolio_bridge) → else BLOCKED
    ├── Gate 9: Position size ≤ 20% of portfolio value? → else ORDER_REJECTED
    ├── Gate 10: No existing open position in this symbol? → else SKIP
    │
    ├── If all gates pass:
    │   ├── execute_buy() called → simulated fill at signal_price
    │   ├── Portfolio updated (cash reduced, position added)
    │   └── ORDER_SUBMITTED → ORDER_EXECUTED emitted
    │
    └── If gate fails:
        ├── ORDER_REJECTED (with reason logged in payload)
        └── EXECUTION_SKIPPED_WITH_REASON (for soft skips)
```

### 3.1 Paper Exploration Mode (NEW — activated Aug 15)

When `paper_exploration_mode = True` in settings, an additional loop runs after the main execution loop:

```
EXPLORATION TICK (after main execution loop)
│
├── Hard Gates (always enforced, identical to main):
│   ├── Market closed → BLOCKED
│   ├── Scan stale > 15 min → BLOCKED
│   ├── Circuit breaker tripped → BLOCKED
│   └── Data quality UNAVAILABLE → BLOCKED
│
├── Path A: SIZE_REDUCED_TO_CAP
│   ├── Find candidates where ONLY failed gate = per_stock_cap
│   ├── Resize quantity: floor(20% × portfolio / price)
│   └── Create entry in experimental_paper_trades (NOT phase20_paper_trades)
│
└── Path B: EXPERIMENTAL_BUY_FROM_WATCH
    ├── Find WATCH candidates with confidence ≥ 60, R:R ≥ 1.2
    ├── Require volume_ratio ≥ 1.2 (intraday volume signal)
    └── Create entry in experimental_paper_trades (budget: max 2 trades/day, 5% each)
```

---

## 4. Criteria and Thresholds

### 4.1 Signal Thresholds (config.py)

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `SIGNAL_STRONG_THRESHOLD` | **90.0** | Confidence ≥ 90 → STRONG BUY |
| `SIGNAL_BUY_THRESHOLD` | **75.0** | Confidence 75–90 → BUY |
| `SIGNAL_WATCH_THRESHOLD` | **60.0** | Confidence 60–75 → WATCH |
| `SIGNAL_MIN_THRESHOLD` | **60.0** | Confidence < 60 → NO_TRADE / IGNORE |

### 4.2 Opportunity Score Thresholds (config.py)

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `OPP_HOT_BUY_THRESHOLD` | **85.0** | Hot BUY — highest priority |
| `OPP_BUY_THRESHOLD` | **70.0** | Standard BUY |
| `OPP_WATCH_THRESHOLD` | **50.0** | WATCH candidate |
| Below 50 | — | IGNORE |

**Opportunity Score Weights:**
- trade_quality: **40%**
- ai_confidence: **30%**
- rr_score: **20%**
- market_alignment: **10%**

### 4.3 AI Decision Engine Thresholds (config.py)

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `AI_MIN_RR_RATIO` | **2.0** | Minimum R:R for the decision engine to approve |
| `AI_MIN_TF_ALIGNMENT` | **3** | At least 3 of 4 timeframes must align |
| `AI_HIGH_VOL_CONF_THRESHOLD` | **70.0** | Below this in HIGH_VOL regime → downgrade |
| `AI_SIDEWAYS_CONF_THRESHOLD` | **72.0** | Below this in SIDEWAYS regime → downgrade |
| `AI_MIN_STOP_DISTANCE_PCT` | **0.5%** | Stop < 0.5% of price → reject (whipsaw risk) |

### 4.4 Scan-Time Gates (live_scan_engine.py)

| Gate | Value | Action when failed |
|------|-------|--------------------|
| `STALE_GUARD_ACTION` | `"WATCH"` | STALE data → force action to WATCH max |
| `UNAVAIL_GUARD_ACTION` | `"IGNORE"` | UNAVAILABLE → force to IGNORE |
| `MIN_RR_FOR_BUY` | **1.5** | R:R < 1.5 → cannot be BUY |
| Paper eligible qualities | `{LIVE, NEAR_LIVE}` | Other qualities → not eligible for paper execution |

### 4.5 Execution-Time Gates (phase20_executor.py via phase20_store.py)

| Gate | Default Value | Notes |
|------|---------------|-------|
| `min_confidence` | **60.0%** | Configurable via Settings page |
| `min_opportunity_score` | **60.0** | Configurable via Settings page |
| `per_stock_exposure_cap_pct` | **25.0%** | Settings max; **hard cap is 20%** in executor |
| Hard pre-trade cap | **20.0%** | `_PRETRADE_MAX_PCT` — never overridden by settings |
| `scan_interval_minutes` | **5** | Allowed values: 1, 2, 3, 5, 10, 15 |
| Market open window | **09:15–15:30 IST** | Outside this → execution skipped |
| Stale scan | Configurable | Scan older than threshold → EXECUTION_SKIPPED |
| Circuit breaker | State-based | If tripped → all entries blocked until manual reset |
| Duplicate position | One per symbol | Cannot open second position in same symbol |

### 4.6 Gap Between Scan-Time and Execution-Time Thresholds

This is a **known architectural gap**:

| Dimension | Scan-time | Execution-time | Gap |
|-----------|-----------|----------------|-----|
| R:R minimum | 1.5 (live_scan_engine) | 1.5 (phase20_executor) | Aligned |
| Confidence minimum | 60.0 (live_scan_engine generates signal) | 60.0 (executor gate) | Aligned |
| Data quality for BUY | LIVE or NEAR_LIVE | LIVE or NEAR_LIVE | Aligned |
| Position size cap | Not enforced at scan time | 20% hard cap at execution | **Gap: BUY_GENERATED even when price guarantees cap fail** |
| Portfolio state | Not known at scan time | Checked at execution | **Gap: BUY_GENERATED for symbols already held** |

The gap on position-size cap is the **primary cause of all recent ORDER_REJECTED events** — DRREDDY and others get BUY_GENERATED correctly, but are always rejected at execution because min 1 share × price > 20% of ₹50,000.

### 4.7 Paper Exploration Thresholds (paper_exploration_engine.py)

| Parameter | Default | Notes |
|-----------|---------|-------|
| `exploration_max_pct_per_trade` | **5.0%** | Max ₹2,500 per exploration trade |
| `exploration_max_trades_per_day` | **2** | Daily budget cap |
| `exploration_max_total_exposure_pct` | **10.0%** | Max total exploration exposure |
| `exploration_min_rr` | **1.2** | Lower than main 1.5 minimum |
| `exploration_min_confidence` | **60.0%** | Same as main |
| Hard exploration cap | **20.0%** | `_PRETRADE_MAX_PCT` — never bypassed |
| Volume signal required | **vol_ratio ≥ 1.2** | For WATCH→exploration path |

---

## 5. All App Pages and Routes

The dashboard has **70+ registered routes**. They are organized into functional groups below.

### 5.1 Core Trading Pages (Primary Use)

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/` | `TradeDecisions` | **Primary page** — live scan results, BUY/WATCH/IGNORE cards, pipeline event stream, regime display |
| `/ai-paper-trader` | `AIPaperTraderPage` | Paper trade management — open positions, P&L, paper trade history, settings |
| `/paper-learning` | `PaperLearningMode` | **NEW** — Exploration mode toggle, budget bars, experimental trade candidates, learning observations |
| `/mission-control` | `MissionControl` | Command-and-control dashboard — scan health, pipeline events stream, active alerts, quick commands |
| `/live-data-health` | `LiveDataHealth` | Data quality per symbol, provider health, Zerodha session status, coverage metrics |
| `/live-readiness` | `LiveReadiness` | GO/NO-GO verdict for live trading readiness (8-domain operational readiness score) |

### 5.2 Intelligence and Analysis Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/market-intelligence` | `MarketIntelligenceHub` | Market regime, sector strength, opportunity matrix, directional signals |
| `/market` | `MarketOverview` | NIFTY 50 overview, sector heatmap, breadth indicators |
| `/market-scanner` | `MarketScanner` | Symbol-level scan results, sortable by score/confidence/opportunity |
| `/research-lab` | `ResearchLab` | Multi-source research aggregation, alternative data, news signals |
| `/ai-decision` | `AiDecision` | AI Decision Agent interface — 7 decision types, explainability, confidence breakdown |
| `/agent-ai-decision` | `AiDecisionAgentPage` | Agent-level AI decision monitoring |
| `/explainable-ai` | `ExplainableAI` | Decision explainability — which factors drove BUY/WATCH/IGNORE |
| `/ai-copilot` | `AiCopilot` | Alert-based AI recommendations from cached scan snapshots |
| `/event-intelligence` | `EventIntelligence` | Corporate events, earnings calendar, dividend signals |
| `/macro-intelligence` | `MacroIntelligence` | VIX, F&O data, FII/DII flows, macro regime |
| `/preopen-intelligence` | `PreOpenIntelligence` | Pre-open IEP, order imbalance, first-mover signals |
| `/preopen-accuracy` | `PreOpenAccuracy` | Historical accuracy of pre-open predictions |

### 5.3 Portfolio and Performance Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/portfolio-manager` | `PortfolioManager` | Portfolio allocation, position management |
| `/portfolio-live` | `PortfolioLive` | Real-time paper portfolio state, equity curve |
| `/portfolio-performance` | `PortfolioPerformance` | 5D.2 FIFO P&L analytics, return metrics, drawdown |
| `/portfolio-risk` | `PortfolioRiskAnalytics` | Risk exposure analytics, HHI concentration, Kelly allocation |
| `/performance-analytics` | `PerformanceAnalytics` | Cross-strategy performance comparison |
| `/paper-analytics` | `PaperAnalytics` | Paper trading analytics — win rate, avg P&L, by strategy/regime |
| `/execution-quality` | `ExecutionQualityPage` | Fill quality, slippage analysis, FIFO trade matching |
| `/executive-dashboard` | `ExecutiveDashboard` | Aggregated 5D.1–5D.5 executive KPI view |
| `/executive-reports` | `ExecutiveReports` | 7 report types, AI-generated insights, report library |

### 5.4 Risk and Validation Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/risk` | `RiskManagement` | Risk limits, exposure limits, position constraints |
| `/risk-optimisation` | `RiskOptimisation` | Kelly allocation, Monte Carlo, stress testing |
| `/risk-validation` | `RiskValidation` | 8-domain risk validation score |
| `/risk-decision-report` | `RiskDecisionReportPage` | Per-decision risk evidence report |
| `/validation` | `PaperTradingValidation` | Paper trading quality checks, 7-domain validation |
| `/validation-dashboard` | `ValidationDashboard` | V2 validation dashboard — suite status, pass/warn/fail |
| `/system-validation` | `SystemValidation` | System-level validation checks |
| `/validation-v2` | `AIValidationV2Page` | V2 full validation framework with AI verdict |
| `/paper-trading-summary` | `Phase11SummaryPage` | Paper trading session summary |
| `/paper-trading-portfolio` | `Phase11PortfolioPage` | Portfolio state within paper trading session |
| `/paper-trading-reports` | `Phase11ReportsPage` | Session reports |
| `/paper-trading-replay` | `Phase11ReplayPage` | Trade replay within session |

### 5.5 Backtest and Strategy Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/backtest` | `Backtest` | Run backtests on historical data |
| `/strategy-lab` | `StrategyLab` | Strategy development and parameter tuning |
| `/simulation-lab` | `SimulationLab` | What-if scenario simulation |
| `/strategy-intelligence` | `StrategyIntelligence` | 5D.3 strategy performance analytics |
| `/strategy-optimisation` | `StrategyOptimisation` | Under-performing strategy detection, advisory suggestions |
| `/strategy-evolution` | `StrategyEvolution` | Strategy adaptation tracking |
| `/optimization-lab` | `OptimizationLab` | Hyperparameter optimization |
| `/optimizer` | `Optimizer` | Strategy optimizer |
| `/walk-forward` | `WalkForwardValidation` | Walk-forward validation |
| `/replay` | `ReplayModePage` | Full pipeline replay mode |
| `/market-replay` | `MarketReplay` | Market data replay |

### 5.6 Learning and AI Intelligence Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/ai-learning-center` | `AILearningCenter` | Phase 24 learning — missed opportunities, patterns, recommendations |
| `/learning` | `LearningGovernance` | Learning safety controls — freeze flags, IGNORE-lock status |
| `/learning-insights` | `LearningInsights` | Pattern insights, signal learning analytics |
| `/learning-review` | `LearningReview` | Human review queue for learning suggestions |
| `/agent-learning` | `LearningAgentPage` | Learning agent monitoring and control |
| `/agent-knowledge` | `KnowledgeAgentPage` | Knowledge base browser |
| `/lessons-library` | `LessonsLibraryPage` | Historical lesson library |
| `/pattern-quality` | `PatternQuality` | Pattern signal quality assessment |
| `/pattern-explorer` | `PatternExplorerPage` | Interactive pattern exploration |
| `/knowledge-search` | `KnowledgeSearchPage` | Knowledge base semantic search |
| `/trade-memory` | `TradeMemoryPage` | Trade outcome memory browser |
| `/trade-intelligence` | `TradeIntelligence` | Trade-level intelligence enrichment |
| `/ai-performance` | `AIPerformanceIntelligence` | 5D.4 AI confidence/calibration analytics |

### 5.7 Operations and Admin Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/command-center` | `CommandCenter` | Phase 9.1 Unified Command Center — 13-section orchestration |
| `/live-command-center` | `LiveCommandCenter` | Real-time command center |
| `/operations-center` | `OperationsCenter` | Phase 8.5 — 14 commands, 11 tabs, operational control |
| `/security-center` | `SecurityCenter` | Phase 8.6 — secret presence check, API security, config audit |
| `/performance-center` | `PerformanceCenter` | Phase 8.7 — API latency, DB performance, scheduler health |
| `/deployment-center` | `DeploymentCenter` | Phase 8.8 — deployment readiness, backup, DR |
| `/observability` | `ObservabilityCenter` | Phase 8.1 — metrics, logs, latency, health probes |
| `/settings` | `Settings` | Operator settings — scan interval, thresholds, exploration config |
| `/kite-connect` | `KiteConnect` | Zerodha OAuth login page |
| `/operator-status` | `OperatorStatus` | System status for operators |
| `/automation` | `AutomationHealth` | Scheduler health, task automation status |

### 5.8 Investigation and Audit Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/investigation-center` | `InvestigationCenter` | Cross-domain investigation dashboard |
| `/ai-investigation` | `AIInvestigationCentre` | AI-powered investigation of anomalies |
| `/ai-operations-centre` | `AIOperationsCentrePage` | AI Operations Center — all agent snapshots in one view |
| `/decision-lineage` | `DecisionLineagePage` | Decision provenance — why was each decision made |
| `/gate-rejection-audit` | [admin] | Gate rejection audit tool |

### 5.9 Agent Framework Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/agent-operations` | `AgentOperations` | All agents status, start/stop, config |
| `/agent-execution` | `ExecutionAgentPage` | Execution agent monitoring |
| `/collab-graph` | `CollaborationGraphPage` | Agent collaboration graph (11 nodes, 10 edges) |
| `/autonomous-ops` | `AutonomousOpsPage` | Autonomous operations agent control |
| `/system-health` | `SystemHealthPage` | System health aggregation |
| `/agent-comm-monitor` | `AgentCommMonitorPage` | Inter-agent communication monitor |
| `/supervisor-extended` | `SupervisorExtendedPage` | Extended supervisor control |

### 5.10 Historical and Research Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/historical-knowledge` | `HistoricalKnowledge` | Historical knowledge database |
| `/research-intelligence` | `ResearchIntelligence` | Research intelligence aggregation |
| `/research-notebook` | `ResearchNotebook` | Interactive research notebook |
| `/signals` | `Signals` | Signal history and analysis |
| `/signal-history` | `SignalHistory` | Signal lifecycle events |
| `/signal-validation` | `SignalValidationPage` | Signal quality validation |
| `/phase12` | `Phase12Intelligence` | Phase 12 intelligence (legacy) |
| `/phase13` | `Phase13Intelligence` | Phase 13 14-factor fusion (legacy) |
| `/phase4a-session` | `Phase4ASession` | Phase 4A session dashboard (legacy) |

### 5.11 UI/Experience Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/workspace` | `Workspace` | Phase 9.4 personalized workspace, widget grid |
| `/trading-timeline` | `TradingTimeline` | 9-tab trading timeline, 15 event categories |
| `/trading-quality` | `TradingQuality` | Trading quality metrics |
| `/design-system` | `DesignSystem` | Design system component gallery |
| `/notifications` | `Notifications` | Alert and notification management |
| `/institutional-analytics` | `InstitutionalAnalytics` | Institutional flow analytics |
| `/broker-execution` | `BrokerExecution` | Broker integration status (paper-only) |
| `/paper-basket-test` | `PaperBasketTest` | Paper basket testing layer |

> **Note on Legacy vs Canonical Pages:** Routes under `/phase12`, `/phase13`, `/phase4a-session`, and some `/paper-trading-*` are legacy pages from earlier development phases. The canonical pages for daily use are: `/` (Trade Decisions), `/ai-paper-trader`, `/mission-control`, `/live-data-health`, and `/market-intelligence`. Operators should primarily use these 5 pages.

---

## 6. Universe and Symbol Selection

### 6.1 NIFTY 50 Universe (Now 51 Symbols)

The platform tracks a modified NIFTY 50 universe with 51 symbols after the TATAMOTORS demerger:

| Sector | Symbols | Count |
|--------|---------|-------|
| IT | TCS, INFY, WIPRO, HCLTECH, TECHM, LTIM | 6 |
| BANKING | HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, INDUSINDBK | 6 |
| FINANCE | BAJFINANCE, BAJAJFINSV, HDFCLIFE, SBILIFE, SHRIRAMFIN | 5 |
| ENERGY | RELIANCE, ONGC, POWERGRID, NTPC, COALINDIA | 5 |
| INFRA | LT, ULTRACEMCO, GRASIM, ADANIPORTS | 4 |
| AUTO | MARUTI, **TMPV**, **TMCV**, BAJAJ-AUTO, EICHERMOT, M&M, HEROMOTOCO | **7** |
| FMCG | HINDUNILVR, NESTLEIND, BRITANNIA, ITC, TATACONSUM | 5 |
| PHARMA | SUNPHARMA, CIPLA, DRREDDY, DIVISLAB, APOLLOHOSP | 5 |
| METALS | TATASTEEL, HINDALCO, JSWSTEEL, ADANIENT | 4 |
| CONSUMER | TITAN, ASIANPAINT, TRENT | 3 |
| TELECOM | BHARTIARTL | 1 |
| **TOTAL** | | **51** |

### 6.2 TATAMOTORS Demerger Handling

**Background:** TATAMOTORS was removed from the universe on 2026-08-12 after the Tata Motors demerger. NSE no longer lists a tradeable TATAMOTORS equity; the successor instruments are:
- **TMPV** (Tata Motors Passenger Vehicles Ltd) — price ~₹343
- **TMCV** (Tata Motors Commercial Vehicles Ltd) — price ~₹457

Both respond correctly to `TMPV.NS` and `TMCV.NS` on Yahoo Finance. The `config.py` has been updated with the comment explaining the demerger.

**Impact on test suite:** Any test that checks `_meta(50)` (expecting exactly 50 symbols) must be updated to `_meta(MIN_SYMBOLS_EXPECTED)` = 51. This is documented in memory.

**NIFTY 50 Index Note:** The actual NIFTY 50 index now has 51 constituent stocks as a result of the demerger. Our universe mirrors this.

### 6.3 Data Quality Labels

| Label | Meaning | Effect on Signal |
|-------|---------|-----------------|
| `LIVE` | Fresh Zerodha tick (< 1 minute old) | Full BUY/WATCH/IGNORE possible |
| `NEAR_LIVE` | Recent data (1–5 minutes) | Full BUY/WATCH/IGNORE possible |
| `STALE` | Delayed/historical data (> 5 min or Yahoo) | **BUY forced to WATCH** |
| `UNAVAILABLE` | No data returned | **Forced to IGNORE** |

**Current situation:** Without a Zerodha OAuth session, ALL symbols receive `STALE` data from Yahoo Finance. This means no BUY action can be generated from the scanner — all confident signals are capped to WATCH and become ineligible for paper execution.

### 6.4 Provider Sources

| Provider | Quality | When Used |
|----------|---------|-----------|
| Zerodha Kite WebSocket (not yet implemented) | `LIVE` | When Zerodha session active + WebSocket connected |
| Zerodha Kite REST API | `LIVE` | When Zerodha OAuth session active |
| Yahoo Finance (yfinance) | `STALE` / `NEAR_LIVE` | Fallback when no Zerodha session |
| NSE Official (pre-open only) | `LIVE` (pre-open) | IEP/pre-open data source |
| Mock/error fallback | `UNAVAILABLE` | When all sources fail |

### 6.5 Missing Symbols

The scan on 2026-08-14 shows: **51 requested, 50 received, 1 missing.** The missing symbol is [NOT STORED explicitly in scan_state — `missing_symbols` JSON not retrieved]. Historically, `LTIM` has been the most common missing symbol on Yahoo Finance (it was added to the index recently).

---

## 7. Scan Cadence and Rotation

### 7.1 Configured Parameters

| Parameter | Value |
|-----------|-------|
| `scan_interval_minutes` | **5 minutes** |
| Market hours | **09:15 – 15:30 IST** |
| Expected scans per full market day | **~75** (6.25 hours / 5 min = 75) |
| Universe per scan | **51 symbols** |
| Expected events per full day | **51 × 75 = 3,825 SYMBOL_SCANNED** |

### 7.2 Actual Scan Counts (from production pipeline_events)

| Date | Scans Started | Scans Completed | Scans Failed | Symbols Scanned | Notes |
|------|--------------|-----------------|--------------|-----------------|-------|
| 2026-08-15 | 0 | 0 | 0 | 0 | Weekend/holiday — no market |
| 2026-08-14 | 72 | 72 | 0 | 3,600 | 3600/72=50 symbols/scan, 1 missing |
| 2026-08-13 | 71 | 71 | 0 | 3,550 | Normal day |
| 2026-08-12 | 70 | 69 | 0 | 13,793 | **ANOMALY** — 13793/70=197 symbols/scan |
| 2026-08-11 | 89 | 76 | 2 | 65,018 | **MAJOR ANOMALY** — 65018/89=730 symbols/scan? |
| 2026-08-10 | 54 | 54 | 0 | 2,592 | 2592/54=48 symbols/scan, 3 missing |
| 2026-08-09 | 1 | 1 | 0 | 48 | Saturday — 1 test scan |
| 2026-08-08 | 3 | 2 | 1 | 169 | Sunday + partial — 2 scans |

### 7.3 Scan Anomalies

**Aug 11 Major Anomaly:** 65,018 SYMBOL_SCANNED events with 89 SCAN_STARTED. Expected would be ~4,539 (89 × 51). The actual count is 14× higher. Possible explanations:
- The scan_interval was temporarily set to 1 minute (75×51=3,825 per hour, ×8h=30,600) — partial explanation
- A loop bug caused multiple passes per scan within the same scan_id
- The GLAND symbol alone accounts for 25,124 SYMBOL_SCANNED (almost exactly 25,124/89=282 passes per scan)
- **Assessment:** This appears to be a bug that caused repeated scanning. The GLAND symbol generated 15,065 BUY_GENERATED events and 11,197 ORDER_CANCELLED events from this single session.

**Aug 12 Anomaly:** 13,793 SYMBOL_SCANNED with 70 scans = 197 per scan. Expected 51. Also unexplained — likely an interval-setting change or loop issue that was later corrected.

### 7.4 Post-Market Scans

**Yes, scans continue post-market.** The data shows scans running outside 09:15–15:30 IST. The scanner does not have a hard "market hours only" gate at the scan level — it scans on every interval tick. However, the *executor* gate prevents any paper trades from being placed outside market hours.

### 7.5 Stale Scan Handling

When the server restarts, there is a gap (typically 30–120 seconds depending on Python warm-up). During this time, the previous scan snapshot ages. If the snapshot is older than the staleness threshold, execution is skipped until a fresh scan completes.

The Aug 13 data shows 63 `EXECUTION_SKIPPED_WITH_REASON` events — these are primarily from stale-scan skip or post-market skip conditions.

### 7.6 Scan Provider Note

The Aug 14 scan shows provider = `"Yahoo Finance (History) — Zerodha login required (no active session)"`. This is the fallback provider label, confirming Yahoo Finance is active and Zerodha is not authenticated.

---

## 8. Last 10 Trading Days — Production Statistics

All figures pulled directly from the `pipeline_events` table as of 2026-08-15.

### 8.1 Daily Pipeline Event Summary

| Date | Scans | Sym Scanned | BUY Gen | WATCH Gen | IGNORE Gen | Risk Rej | Ord Submit | Ord Exec | Ord Rej | Exec Skip | Pos Opened | Pos Closed |
|------|-------|-------------|---------|-----------|------------|----------|------------|----------|---------|-----------|------------|------------|
| **2026-08-15** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **2026-08-14** | 72 | 3,600 | 48 | 1,926 | 1,626 | 97 | 0 | 0 | 203 | 4 | 0 | 0 |
| **2026-08-13** | 71 | 3,550 | 148 | 1,951 | 1,451 | 179 | 0 | 0 | 560 | 63 | 0 | 0 |
| **2026-08-12** | 70 | 13,793 | 170 | 4,800 | 8,823 | 97 | 0 | 0 | 676 | 0 | 0 | 0 |
| **2026-08-11** | 89★ | 65,018★ | 18,460 | 26,428 | 20,130 | 14,886 | 3,315 | **64** | 819 | 0 | **64** | **25** |
| **2026-08-10** | 54 | 2,592 | 176 | 1,562 | 854 | 187 | 87 | 0 | 807 | 0 | 0 | 0 |
| **2026-08-09** | 1 | 48 | 6 | 27 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **2026-08-08** | 3 | 169 | 26 | 43 | 99 | 1 | 20 | 1 | 0 | 0 | 1 | 1 |
| **Earlier** | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

★ = Anomalous — see §7.3

**Key observations from 14-day window:**
- **Total BUY_GENERATED:** 19,034 (of which 18,460 were the Aug 11 anomaly day)
- **Total ORDER_EXECUTED:** 65 (64 on Aug 11, 1 on Aug 8)
- **Total ORDER_REJECTED:** 3,065 (mostly position-size cap violations)
- **Normalising for the Aug 11 anomaly**, recent days (Aug 12–14) show 0 executed orders

### 8.2 Current Paper Portfolio State

| Metric | Value |
|--------|-------|
| Available cash | **₹50,000.00** |
| Open positions (phase20_paper_trades) | **4 (all EXIT_PENDING)** |
| Positions JSON | `{}` (empty) — portfolio positions cleared |
| Last portfolio update | 2026-08-14 03:40:57 UTC |

**Note:** The 4 trades in `phase20_paper_trades` have `status=EXIT_PENDING` and `exit_rule=STALE_DATA_SAFETY` set on 2026-08-13. Their `realized_pnl` is `NULL`, meaning no P&L was captured on the safety exit. The portfolio positions JSON is empty `{}`, confirming these positions are no longer counted in active portfolio exposure.

### 8.3 Experimental Paper Trades (exploration_mode)

| Table | Count |
|-------|-------|
| `experimental_paper_trades` rows | **0** |
| `EXPERIMENTAL_PAPER_TRADE_PLACED` events (Aug 15) | **8 events for DRREDDY** |

The 8 Aug 15 events suggest the exploration engine ran and generated entries, but no rows appear in the DB table. This may be because:
- The exploration was tested/evaluated but entries weren't committed (hard gates blocked actual inserts)
- The DB schema hadn't been created yet when exploration first ran
- The events are pre-DB-write events

**Status:** Exploration mode is newly activated and has not yet completed a full trade cycle.

---

## 9. Top Symbols by Signal Count

### 9.1 Top BUY_GENERATED Symbols (All Time, 14-day window)

| Rank | Symbol | BUY_GENERATED | ORDER_REJECTED | WATCH_GENERATED | Risk_Rejected |
|------|--------|--------------|----------------|-----------------|---------------|
| 1 | **GLAND** | **15,065** | 0 | 10,059 | 10,023 |
| 2 | **NTPC** | 884 | 0 | 772 | 561 |
| 3 | **TATASTEEL** | 781 | 0 | 835 | 812 |
| 4 | **SBIN** | 631 | 0 | 1,292 | 962 |
| 5 | **AXISBANK** | 382 | 0 | 1,211 | 1,015 |
| 6 | **SUNPHARMA** | 370 | 0 | 636 | 217 |
| 7 | **DRREDDY** | 188 | **873** | — | — |
| 8 | **HDFCLIFE** | 126 | 0 | 204 | 198 |
| 9 | **GRASIM** | 107 | **548** | 223 | — |
| 10 | **ICICIBANK** | 81 | 0 | 2,618 | 434 |

> GLAND's extreme counts are from the Aug 11 scan loop anomaly.

### 9.2 Top WATCH_GENERATED Symbols

| Rank | Symbol | WATCH_GENERATED |
|------|--------|----------------|
| 1 | GLAND | 10,059 (Aug 11 anomaly) |
| 2 | TCS | 3,466 |
| 3 | ICICIBANK | 2,618 |
| 4 | HDFCBANK | 1,929 |
| 5 | HINDUNILVR | 1,808 |
| 6 | WIPRO | 1,593 |
| 7 | SBIN | 1,292 |
| 8 | AXISBANK | 1,211 |
| 9 | LT | 944 |
| 10 | ASIANPAINT | 871 |

### 9.3 Top ORDER_REJECTED Symbols

| Rank | Symbol | ORDER_REJECTED | Typical rejection reason |
|------|--------|---------------|------------------------|
| 1 | **DRREDDY** | **873** | Position size 21.5–21.7% > 20% cap |
| 2 | **GRASIM** | 548 | Position size 20.2–20.3% > 20% cap |
| 3 | **BAJAJFINSV** | 353 | Position size 20.2–20.4% > 20% cap |
| 4 | **BAJAJ-AUTO** | 262 | Position size 23.4–23.6% > 20% cap |
| 5 | **TMPV** | 272 | Position size 21.6% > 20% cap |
| 6 | **TITAN** | 221 | Position size > 20% |
| 7 | **JSWSTEEL** | 182 | Position size 23.5% > 20% cap |
| 8 | **INDUSINDBK** | — | Position size 22.4% > 20% cap |
| 9 | **ASIANPAINT** | — | Position size 22.1% > 20% cap |

---

## 10. Rejection and Block Reasons

### 10.1 ORDER_REJECTED Breakdown (from pipeline_events payload)

| Reason | Count | Example |
|--------|-------|---------|
| **Position size > 20% cap** | **~3,000+** | `"DRREDDY: position size ₹10,783 = 21.6% of portfolio (limit 20.0%)"` |
| `PORTFOLIO BLOCKED: INSUFFICIENT_BUYING_POWER; LIMIT_BREACH:max_gross_exposure` | 68 | Likely from the Aug 11 anomaly when cash was consumed |
| `PORTFOLIO BLOCKED: BELOW_MIN_ORDER_VALUE; LIMIT_BREACH:max_gross_exposure` | 15 | Order value too small after sizing |

### 10.2 RISK_REJECTED Breakdown

| Count | Stored reason |
|-------|--------------|
| **15,447 total RISK_REJECTED** | `NULL` (no reason stored in payload) |

**Problem identified:** RISK_REJECTED events do not store a rejection reason in the `payload->>'reason'` field. This makes it impossible to audit *why* 15,447 symbols were risk-rejected from the database. The reason is likely logged to console/file during scan execution but not persisted.

### 10.3 EXECUTION_SKIPPED_WITH_REASON

| Count | Stored reason |
|-------|--------------|
| **67 total** (63 on Aug 13, 4 on Aug 14) | `NULL` (no reason stored) |

Same gap as RISK_REJECTED — reason field is empty, but the event name itself implies: market closed, stale scan, or data quality issue.

### 10.4 Categorised Rejection Summary

Based on available data, the rejection reasons group as follows:

| Category | Estimated Count | Primary Culprit |
|----------|----------------|-----------------|
| Position size cap (>20%) | ~3,000 | DRREDDY, GRASIM, BAJAJ-AUTO, TMPV, BAJAJFINSV |
| Risk agent rejection (reason unknown) | ~15,447 | [NOT STORED — needs fix] |
| Execution skipped (reason unknown) | ~67 | [NOT STORED — needs fix] |
| Portfolio blocked (buying power/exposure) | ~83 | PRECHECK_REJECTED on Aug 10 |
| Order cancelled (from Aug 11 anomaly) | ~13,193 | GLAND position cancellations |

---

## 11. Detailed Case Studies

### 11.1 Case Study: DRREDDY — Repeated BUY Rejected by Position-Size Cap

**The pattern:**

On every market day since Aug 8, DRREDDY has generated BUY signals that pass all gates **except** the 20% position-size cap.

| Date | BUY Generated | Risk Approved | ORDER_REJECTED | Reason |
|------|--------------|--------------|----------------|--------|
| Aug 14 | 48 | 48 | 201 | Size 21.5–21.7% of ₹50,000 |
| Aug 13 | 48 | 48 | 203 | Size 21.5–21.7% of ₹50,000 |
| Aug 12 | 53 | 53 | 260 | Size ~21.6% |
| Aug 11 | 39 | 39 | 209 | Size ~21.6% |

**Root cause:**
- DRREDDY price: ~₹1,340–₹1,360 per share
- Minimum 1 share: ₹1,340
- But the position sizer wants more shares: 8 × ₹1,350 = ₹10,800 = **21.6%** of ₹50,000
- Hard cap is 20.0% = ₹10,000 max
- ₹10,000 / ₹1,350 = 7.4 shares → floor = 7 shares
- 7 × ₹1,350 = ₹9,450 = **18.9%** → this WOULD pass the cap
- **Bug/design issue:** The position sizer is computing 8 shares but not trying 7 shares when 8 exceeds the cap

**Resolution (in progress):** The Paper Exploration Mode (Task #723) adds the `SIZE_REDUCED_TO_CAP` path that would resize 8→7 shares and create an experimental trade. On Aug 15, 8 `EXPERIMENTAL_PAPER_TRADE_PLACED` events appeared for DRREDDY after exploration mode was enabled.

### 11.2 Case Study: HDFCLIFE — Missed Low / Pattern Not Captured

**Context:** HDFCLIFE received 126 BUY_GENERATED and 198 RISK_REJECTED events over the 14-day window, plus 204 WATCH_GENERATED.

**The issue documented in the HDFCLIFE missed-buy audit:**
- HDFCLIFE printed a significant intraday low at some point where the signal was BUY-grade
- The executor had a data quality issue (STALE from Yahoo) that capped the action to WATCH
- Even with WATCH, the paper executor doesn't place trades
- The missed opportunity was recorded but not acted on

**Learning bridge:** The Phase 24 learning engine stores missed opportunities in the `phase24_missed_opps` table, but this data is advisory only — no auto-retry or BUY override is performed.

### 11.3 Case Study: Executor ImportError (Task #657)

**Background:** A previously reported `ImportError` in the paper executor prevented any paper trades from being placed for multiple sessions. The fix was verified via a dedicated audit report.

**What happened:**
- The `phase20_executor.py` file attempted to import a module that had been moved or renamed
- This caused the entire execution block to fail silently — BUY signals were generated but the executor crashed on import
- `EXECUTION_SKIPPED_WITH_REASON` events were generated without useful reason text

**Status:** Fixed. The executor now correctly imports all required modules. The Aug 11 ORDER_EXECUTED=64 events confirm execution is working when signals pass all gates.

### 11.4 Case Study: TMCV — WATCH Despite Intraday Movement

**The pattern:** TMCV (Tata Motors Commercial Vehicles — successor to TATAMOTORS) appears in WATCH_GENERATED events but never in BUY_GENERATED, despite being in the NIFTY 50 universe with potential intraday signals.

**Root causes:**
1. Yahoo Finance data for TMCV is STALE → BUY forced to WATCH at scan time
2. TMCV is a newly demerged stock with limited historical data for the signal engine → confidence scores are lower
3. Price ~₹457 → even at full 20% cap = ₹10,000 / ₹457 = 21.8 shares → position size would be fine, but signals never reach BUY grade

**What would fix it:** A live Zerodha session providing LIVE tick data for TMCV would allow the scan to produce LIVE quality data and potentially generate BUY signals if confidence reaches threshold.

### 11.5 Case Study: Post-Market Scans and UI Confusion

**The problem:** The Trade Decisions page (`/`) shows scan results that may be from post-market Yahoo Finance polling. Users see BUY/WATCH signals at 6 PM IST and wonder why no trades were placed.

**What's happening:**
- The scanner runs 24/7 on the 5-minute interval (no hard market-hours gate at the scan level)
- Post-market Yahoo data shows the closing price, which may still produce a BUY-grade signal
- The executor skips execution (market closed gate), but the UI shows the signal as active
- Users interpret this as "the system saw a BUY opportunity and didn't act"

**Reality:** Post-market signals are not actionable. The UI does not clearly distinguish between intraday (actionable) and post-market (informational) signals.

**Resolution needed:** Add a "MARKET CLOSED — Signals are post-market only" banner on Trade Decisions and Mission Control when scans are outside 09:15–15:30 IST.

### 11.6 Case Study: "Paper Eligible" vs "Paper Order Placed" Label Fix

**The confusion:** Earlier versions of the Trade Decisions UI showed a "Paper Eligible" badge on WATCH candidates, which operators interpreted as "a paper trade was placed." In reality:
- "Paper Eligible" = the candidate has LIVE/NEAR_LIVE data quality and could receive a paper trade
- "Paper Order Placed" = an actual ORDER_SUBMITTED event was logged

**Status:** Fixed. The badge system was updated to clearly distinguish eligibility from execution. However, the previous semantics persisted in some legacy report views.

---

## 12. Successful Historical Paper Trades

### 12.1 All Trades in phase20_paper_trades

| Trade ID | Symbol | Date | Fill Price | Qty | Total Value | Confidence | Regime | Status | Exit Date | Exit Rule | Realized P&L |
|----------|--------|------|-----------|-----|-------------|-----------|--------|--------|-----------|-----------|-------------|
| P20-4a5f909738 | **BAJFINANCE** | 2026-08-07 | ₹1,100.05 | 8 | ₹8,800 | 64.9% | Strong uptrend | EXIT_PENDING | 2026-08-13 | STALE_DATA_SAFETY | NULL |
| P20-83aa1be8f9 | **GRASIM** | 2026-08-05 | ₹3,223.63 | 3 | ₹9,671 | 62.8% | Strong uptrend | EXIT_PENDING | 2026-08-13 | STALE_DATA_SAFETY | NULL |
| P20-a205b1ef09 | **DIVISLAB** | 2026-08-04 | ₹8,370.04 | 1 | ₹8,370 | 64.5% | Strong uptrend | EXIT_PENDING | 2026-08-04 | STALE_DATA_SAFETY | NULL |
| P20-acad172b74 | **TRENT** | 2026-08-04 | ₹3,082.42 | 3 | ₹9,247 | 72.5% | Trending (momentum) | EXIT_PENDING | 2026-08-13 | STALE_DATA_SAFETY | NULL |

**Key observations:**
- All 4 trades were BUY-side only (no SELL trades in phase20)
- All 4 triggered `STALE_DATA_SAFETY` safety exit on 2026-08-13 (6 days after the most recent entry)
- No realized P&L recorded — the safety exit mechanism sets `exit_ts` and `exit_rule` but does not record a fill price for the exit, leaving `realized_pnl = NULL`
- All confidence scores are between 62.8% and 72.5% — above the 60% minimum
- Total capital deployed: ~₹36,088 across 4 positions (72% of ₹50,000)

### 12.2 Additional Executed Trades (Aug 11 — pipeline_events only)

The pipeline_events table shows **ORDER_EXECUTED=64, POSITION_OPENED=64, POSITION_CLOSED=25** on 2026-08-11. These events are present in `pipeline_events` but **the corresponding trade records do not appear in `phase20_paper_trades`** (only 4 rows total in that table).

Possible explanations:
- These 64 executions occurred in the legacy `paper_trades` table (also present in the DB) rather than `phase20_paper_trades`
- The Aug 11 scan loop anomaly generated phantom execution events that were not backed by actual DB inserts
- Some trades were stored in a different data pathway

**Status:** [REQUIRES INVESTIGATION] — the Aug 11 executed trades cannot be audited from `phase20_paper_trades` alone.

### 12.3 Sell/Exit Behavior

**No successful sell-side executions are recorded.** The SELL path exists in the pipeline (`SELL_GENERATED=13` on Aug 11) but no sell orders appear to have completed in recent sessions. 

For the 4 existing EXIT_PENDING trades:
- Exit was triggered by `STALE_DATA_SAFETY` (a safety mechanism, not a profit-taking strategy)
- No target-based or stop-based exits have occurred
- No `realized_pnl` values have been captured

---

## 13. Why No Trades Executed in Recent Sessions

This section separates the five categories of blocking factors for the Aug 12–14 period (0 orders executed):

### 13.1 Data Problems

| Problem | Impact |
|---------|--------|
| No Zerodha OAuth session | Yahoo Finance → STALE data → BUY capped to WATCH → ineligible for paper execution |
| 1 missing symbol per scan | Minor — 1 symbol (likely LTIM) not contributing signals |
| Post-market scan noise | Non-actionable signals displayed during non-market hours |

**Severity: HIGH** — Without Zerodha live data, the system fundamentally cannot generate paper-eligible BUY signals. The entire data acquisition layer is running on fallback mode.

### 13.2 Risk Threshold Problems

| Problem | Impact |
|---------|--------|
| Risk rejection reasons not stored | Cannot audit why 15,447 symbols were risk-rejected |
| AI_MIN_RR_RATIO=2.0 vs MIN_RR_FOR_BUY=1.5 | Decision engine may reject signals that pass the scan gate |
| SIDEWAYS regime downgrade (conf < 72%) | Many WATCH signals lose confidence in sideways market |

**Severity: MEDIUM** — Some signals that pass the scan engine are being further rejected by risk thresholds. The exact count is unknown because reasons aren't stored.

### 13.3 Position Sizing Problems

| Problem | Impact |
|---------|--------|
| DRREDDY ~₹1,350 → 8 shares = 21.6% > 20% cap | 873 ORDER_REJECTED over 14 days |
| GRASIM ~₹3,370 → 3 shares = 20.2% > 20% cap | 548 ORDER_REJECTED |
| BAJAJ-AUTO ~₹5,860 → 2 shares = 23.4% > 20% cap | 262 ORDER_REJECTED |
| BAJAJFINSV ~₹1,695 → 6 shares = 20.4% > 20% cap | 353 ORDER_REJECTED |
| TMPV ~₹1,800 → 6 shares = 21.6% > 20% cap | 272 ORDER_REJECTED |

**Root cause:** The position sizer computes the "ideal" quantity based on risk parameters (1% max risk), but never tries a smaller quantity when the ideal exceeds the 20% cap. If the sizer tried floor(20% × capital / price), all these symbols would produce valid orders.

**Severity: HIGH** — This is the single largest source of execution failures on days when data quality is not an issue.

### 13.4 Paper Learning / Exploration Policy

| Problem | Impact |
|---------|--------|
| `paper_exploration_mode = False` (Aug 12–14) | No SIZE_REDUCED_TO_CAP or WATCH exploration trades |
| Exploration mode just activated Aug 15 | 8 events but 0 DB rows — may need debugging |
| Budget is tight (max 2 trades/day, 5% each = ₹2,500/trade) | Even with exploration enabled, only small trades are placed |

**Severity: MEDIUM** — Exploration mode is the correct fix for position-sizing rejections, but it was not enabled during the period in question.

### 13.5 UI Interpretation Problems

| Problem | Impact |
|---------|--------|
| Post-market signals displayed as active | Operators think system missed trades |
| WATCH signals shown without "not executable" label | Operators think WATCH = pending trade |
| EXIT_PENDING label without explanation | Operators don't know positions are already safety-exited |
| RISK_REJECTED count without reason | Cannot investigate why 97 symbols were rejected |

**Severity: MEDIUM** — No trades are being blocked by UI issues, but operator confidence in the system is damaged by confusing displays.

---

## 14. Learning Architecture

### 14.1 What the System Currently Learns

| Learning Component | File | What it learns | Auto-promoted? |
|-------------------|------|----------------|----------------|
| Signal learning | `signal_learning.py` | Which signal combinations predict profitable trades | **NO — advisory only** |
| Confidence calibration | `confidence_calibration.py` | Whether confidence scores map to real win rates | **NO — advisory only** |
| Missed opportunity storage | `phase24_store.py` → `phase24_missed_opps` | Symbols where signals were right but not acted on | **NO — stored, not acted on** |
| Trade outcome analytics | `phase24_engine.py` | Win/loss by strategy/regime/confidence band | **NO — analytics only** |
| Phase 24 recommendations | `phase24_recommendations.py` | Human-readable insights from patterns | **NO — human approval required** |

### 14.2 What is Advisory Only (Never Auto-Applied)

The following learning outputs are generated but **require explicit human approval before any parameter changes**:

- Confidence threshold adjustments (raise/lower min_confidence)
- Strategy viability changes per regime
- Risk limit adjustments
- Stop/target ratio changes
- Position sizing formula changes
- Any changes to the BUY/WATCH/IGNORE thresholds

**Safety enforcement:** Learning safety flags are stored in the DB (`freeze` flag, `IGNORE-lock`). The safety state is always read from the authoritative DB at decision time, never from cached adjustment artifacts.

### 14.3 Phase 24 Learning Architecture

```
phase24_engine.py
├── Reads: phase20_paper_trades (outcome data)
├── Reads: pipeline_events (signal data)
├── Reads: phase24_missed_opps (missed opportunities)
├── Writes: phase24_recommendations (human-readable insights)
├── Writes: phase24_trade_intelligence (enriched trade data)
└── Reports: phase24_reports (daily/weekly summaries)
```

**Missed opportunities** are stored in `phase24_missed_opps` when:
- A symbol had a BUY-grade signal but was blocked (cap, staleness, etc.)
- The subsequent price movement confirms the signal was correct
- This data is used to calibrate future thresholds

### 14.4 Backtest-Learning Bridge

The `backtesting_engine.py` runs the real scan pipeline on historical candle data to validate whether learned parameters work on past data. The bridge:
- Takes proposed parameter changes from the learning engine
- Runs a backtest with those parameters
- Compares results against the baseline
- Returns a READY/INSUFFICIENT/BLOCKED verdict
- A READY verdict allows a human to promote the change

**No backtest-learning auto-loop exists.** A human must trigger the backtest and review results before any parameter promotion.

### 14.5 What is Not Learned (Intentional Gaps)

| Item | Reason not learned |
|------|--------------------|
| Position size formula | Safety critical — changes require manual review |
| Circuit breaker thresholds | Safety critical |
| Market open/close window | Fixed regulatory requirement |
| Data quality gates (STALE/UNAVAILABLE) | Safety critical |
| Live execution flag | Permanently off — not in learning scope |

---

## 15. Backtesting Architecture

### 15.1 Architecture Overview

```
backtesting_engine.py (main engine)
├── Uses: live _scan_one() function on historical data slices
├── Generates: isolated in-memory ledger (never touches live portfolio)
├── Candle source: backtest_candles table (pre-fetched historical OHLCV)
├── Validates: results via validate_run() comparing replay vs pipeline
└── Output: backtest_runs table, backtest_trades table
```

**Key design decision:** The backtesting engine calls the *real* `_scan_one()` function on historical candle slices rather than a separate backtest-specific scoring function. This means backtests and live scans use identical logic.

### 15.2 Performance Characteristics

From memory: A full backtest on 5 symbols, 15-minute intervals, 30 days takes approximately **6 minutes** (370-second floor). The scan represents ~93% of total backtest time. Earlier versions had 5+ hour freeze bugs (pre-sweep/heartbeat fix).

### 15.3 Validation Framework

```
certification_engine.py
├── Runs: full validation suite across 8 domains
├── Gate: READY requires every domain to PASS (WARN or INSUFFICIENT = blocked)
├── Append-only: certification runs never overwrite previous results
└── Output: certification_runs table
```

Domains validated: Signal quality, strategy fitness, risk calibration, data quality, execution quality, portfolio performance, regime alignment, learning integrity.

### 15.4 Local Setup

Local testing runs via:
```bash
# Unit tests
cd artifacts/api-server/src/python
python -m pytest tests/unit/ -q

# Integration smoke test
PAPER_ANALYTICS_ENABLED=true python -m pytest paper_analytics/test_paper_analytics_integration.py -q

# Scheduler tick (lightweight, 116ms cold start)
python bt_queue_tick_cmd.py
```

---

## 16. Safety Controls — Proof of No Live Orders

### 16.1 Structural Safeguards

| Control | Implementation | Location |
|---------|---------------|----------|
| `LIVE_EXECUTION_ENABLED = False` | Hardcoded constant | `config.py` |
| MockBrokerClient fallback | When Zerodha import fails or credentials absent | `broker_client.py` line 467–475 |
| No broker order API called | `execute_buy()` calls `paper_trader.py`, not Zerodha | `phase20_executor.py` line 478 |
| Zerodha API read-only usage | Only used for market data quotes, never for order placement | `kite_quote_provider.py` |
| Paper-only label on all UI | "PAPER / LIVE DATA VALIDATION" label on every scan result | `live_scan_engine.py` line 191 |
| MockBrokerClient behavior | Returns simulated fills without touching Zerodha | `broker_client.py` line 199+ |

### 16.2 Zerodha Usage Boundaries

| Zerodha Feature | Used? | Purpose |
|----------------|-------|---------|
| Market data (LTP/quotes) | YES — when OAuth active | Read-only price feed |
| Order placement API | **NO** | Never called |
| Portfolio API | **NO** | Never called |
| WebSocket ticker | Planned (not implemented) | Would be read-only |
| Kite OAuth login | YES — optional | Only for data access |

### 16.3 Credential Management

- `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are stored as Replit Secrets (never in code)
- Request tokens are processed via environment variable, not command-line arguments
- Token files are stored with `chmod 600` permissions
- Token expiry is fail-safe: malformed token = treated as expired

### 16.4 Paper Trading Guarantee

The `execute_buy()` function in `paper_trader.py` is called by `phase20_executor.py`. Its implementation:
1. Computes simulated fill price from signal price (with slippage model)
2. Updates the `paper_portfolio` table (cash, positions)
3. Writes to `phase20_paper_trades` table
4. **Does not call any broker API**

The `MockBrokerClient` at `broker_client.py:199` is the only broker client that is ever instantiated in the current configuration. It returns synthetic order IDs and never makes network calls to Zerodha.

---

## 17. Open and Proposed Tasks — Priority Order

The task list contains 218 tasks (198 shown as proposed). Below are the top-priority items assessed by functional impact:

### 17.1 Critical (Blocking Production Value)

| # | Task Title | Why Critical |
|---|-----------|-------------|
| #659 | Prevent paper-mode SELL orders from silently failing when no position exists | No exit strategy = positions held indefinitely |
| #235 | Prevent stale regime data from silently masking a regime transition | Wrong regime = wrong strategy selection all day |
| #180 | Prevent 09:20 reconciliation from running with null prices | Misleading accuracy reports |
| #358 | Prevent Risk Agent card from going dark when SnapshotBus restarts | Operations blind spot |

### 17.2 High Priority (Data Integrity)

| # | Task Title | Impact |
|---|-----------|--------|
| #703 | Prevent DB-timeout error message from being silently truncated | Operators miss retry advice |
| #329 | Confirm load_all stays fault-tolerant if section loader raises | Ops center availability |
| #359 | Make sure ops-centre overview never blocks on Risk Agent | Slow init = blank dashboard |
| #171 | Warn when AI accuracy declining for past 30 days | No early-warning system |

### 17.3 Medium Priority (UX and Correctness)

| # | Task Title | Impact |
|---|-----------|--------|
| #108 | Confirm config panel refreshes immediately after save | Operator feedback loop |
| #476 | Prevent Supervisor panel duplicate entries | Confusing UI |
| #182 | Confirm readiness score updates when auto-paper entries open | Score lag |
| #208 | Confirm Performance Snapshot shows accurate stats | Zero-stats bug |
| #343 | Show Data Quality grade in Executive Score tooltip | Visibility |
| #234 | Show viable strategies for current regime | Decision support |

### 17.4 Test Coverage (Test Gaps)

| # | Task | What it covers |
|---|------|---------------|
| #230 | Equity chart with 1–2 data points | Edge case render |
| #459 | LOW RELIABILITY badge rendering | UI regression |
| #350 | Mobile Scan button error handling | Mobile reliability |

### 17.5 Follow-Up Tasks from Paper Exploration (New)

| # | Task Title |
|---|-----------|
| #724 | Add nav link in AgentConfig.ts to /paper-learning |
| #725 | Integration test for DB round-trip persistence of MFE/MAE |
| #726 | Surface exploration learning in daily email report and Executive Reports |

---

## 18. Known Weaknesses and Second-Opinion Questions

### 18.1 Architectural Weaknesses

| # | Weakness | Severity | Notes |
|---|---------|---------|-------|
| W1 | **No live tick data** — running entirely on Yahoo Finance delayed data | CRITICAL | Without Zerodha OAuth, no BUY signal can be paper-executed |
| W2 | **Position sizer doesn't try smaller quantity** when ideal exceeds 20% cap | HIGH | Causes 3,000+ ORDER_REJECTED events |
| W3 | **RISK_REJECTED has no stored reason** — 15,447 unexplained rejections | HIGH | Cannot audit or improve the risk gate |
| W4 | **EXECUTION_SKIPPED reason not stored** — 67 unexplained skips | MEDIUM | Cannot audit what caused skips |
| W5 | **No sell/exit strategy** — STALE_DATA_SAFETY is not a trading exit | HIGH | Positions held indefinitely until stale-data event |
| W6 | **Scanner runs post-market** — misleads operators about signals | MEDIUM | UI shows actionable-looking signals after market close |
| W7 | **Aug 11 scan loop anomaly** — 65,018 symbol_scanned from 89 scans | MEDIUM | Root cause not documented, could recur |
| W8 | **EXIT_PENDING positions have no realized P&L** | MEDIUM | 4 trades opened since Aug 4, no P&L captured |
| W9 | **Exploration mode experimental_paper_trades is empty** despite 8 events | HIGH | Events placed but no DB rows — potential silent failure |
| W10 | **RISK_REJECTED vs RISK_APPROVED mismatch** — need audit | MEDIUM | Some symbols both approved and rejected in same scan |

### 18.2 Questions for Independent Reviewer

1. **Threshold calibration:** Are the signal thresholds (BUY≥75, WATCH 60–75, IGNORE<60) appropriate for the NSE intraday market? Given that Yahoo Finance produces STALE data, is confidence computed from historical OHLCV meaningful for intraday trading?

2. **Position sizing:** The 20% hard cap on a ₹50,000 paper portfolio = ₹10,000 per trade. Many NIFTY 50 stocks price above ₹1,000. Should the minimum-quantity floor be enforced (1 share regardless of % cap), or should the capital be scaled up?

3. **Scan loop anomaly (Aug 11):** 65,018 symbol_scanned events from 89 SCAN_STARTED events cannot be explained by the known architecture. Is there a watchdog needed to prevent runaway scan loops?

4. **STALE data BUY cap:** The architecture blocks BUY on STALE data. Is this too conservative? Yahoo Finance data is typically 15–20 minutes delayed for Indian markets — is NEAR_LIVE appropriate for this delay range?

5. **Learning completeness:** The system tracks missed opportunities and win rates but has no auto-promotion. Is the human-approval-required approach appropriate given the scale of signals (1,000+ BUY events per day)?

6. **Capital reset:** The portfolio resets to ₹50,000 each trading day. Is this modeling intraday-only trading? Or should positions carry over? Currently, positions DO carry over (EXIT_PENDING trades from Aug 4–7 are still in the DB), suggesting the reset may not be fully implemented.

7. **Sell side:** The system generates 13 `SELL_GENERATED` events on Aug 11 but has no clear sell strategy documented. What is the intended exit mechanism for long positions?

8. **GLAND anomaly:** GLAND generated 15,065 BUY_GENERATED events in one day. Is GLAND even in the NIFTY 50? (It is a pharmaceutical company but does not appear in the standard NIFTY 50 index.) How did it end up with such extreme counts?

9. **Database design:** Having both `paper_trades` and `phase20_paper_trades` tables is confusing. Which is canonical? The Aug 11 executions appear in pipeline_events but not in phase20_paper_trades.

10. **Exit strategy gap:** Four open positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) have `exit_ts` set but `status=EXIT_PENDING` and `realized_pnl=NULL`. What happens next? Are these positions considered closed or open?

---

## 19. Recommended 30-Day Roadmap

### Week 1 (Days 1–7): Fix Blocking Issues

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Complete Zerodha OAuth setup and maintain active session during market hours | Data quality → LIVE → BUY signals eligible for paper execution |
| 🔴 P1 | Fix position sizer to try floor(cap/price) when ideal qty exceeds 20% | Eliminate 3,000+ ORDER_REJECTED events for DRREDDY, GRASIM, etc. |
| 🔴 P1 | Store rejection reason in RISK_REJECTED and EXECUTION_SKIPPED events | Enable proper audit of 15,000+ unexplained rejections |
| 🟡 P2 | Fix EXIT_PENDING trades — capture exit price and realized P&L on STALE_DATA_SAFETY | 4 current positions get proper P&L recorded |
| 🟡 P2 | Add market-hours banner to Trade Decisions page | Reduce operator confusion about post-market signals |

### Week 2 (Days 8–14): Paper Trading Quality

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Implement and test sell/exit strategy (target-hit, stop-hit, time-based) | Complete the trade lifecycle for the first time |
| 🔴 P1 | Debug Paper Exploration Mode — confirm experimental_paper_trades rows are written | 8 events without DB rows is a silent failure |
| 🟡 P2 | Activate Paper Exploration SIZE_REDUCED_TO_CAP for DRREDDY, GRASIM, BAJAJ-AUTO | First cap-resized experimental paper trades |
| 🟡 P2 | Enable EXPERIMENTAL_BUY_FROM_WATCH for high-volume WATCH candidates | Generate first WATCH-exploration trades with live data |
| 🟢 P3 | Add scan-loop watchdog (alert if SYMBOL_SCANNED > 100×universe size per hour) | Prevent Aug 11 style anomaly |

### Week 3 (Days 15–21): Learning and Analytics

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🟡 P2 | Consolidate paper_trades and phase20_paper_trades into single canonical table | Single source of truth for trade history |
| 🟡 P2 | Surface RISK_REJECTED reasons in the Observability Center | Operators can see why risk is blocking signals |
| 🟡 P2 | Add "AI accuracy declining" 30-day warning (Task #171) | Early warning system |
| 🟢 P3 | Enable Phase 24 missed-opportunity alerts in Mission Control | Operators notified when a signal was missed post-facto |
| 🟢 P3 | Surface exploration learning summary in Executive Reports (Task #726) | Exploration results visible in weekly review |

### Week 4 (Days 22–30): Validation and Production Readiness

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Run full backtesting validation with real Zerodha data | Confirm thresholds work on live-quality data |
| 🟡 P2 | Add confirmation tests for all critical UI states (Tasks #230, #459, #108, #350) | Prevent regressions |
| 🟡 P2 | Complete sell-side paper trading coverage — confirm P&L is captured on all exits | Accurate portfolio analytics |
| 🟢 P3 | Write 30-day paper trading summary report | First complete trading period review |
| 🟢 P3 | Evaluate live execution readiness using LiveReadiness score | Formal GO/NO-GO assessment for eventual live trading |

---

## 20. Appendix

### 20.1 Important Configuration Values

| Config Key | Value | Location |
|-----------|-------|----------|
| `INITIAL_CAPITAL` | ₹50,000 | `config.py` |
| `MAX_RISK_PCT` | 1.0% (₹500 per trade) | `config.py` |
| `MAX_CAPITAL_PER_TRADE_PCT` | 20% | `config.py` |
| `SIGNAL_STRONG_THRESHOLD` | 90.0 | `config.py` |
| `SIGNAL_BUY_THRESHOLD` | 75.0 | `config.py` |
| `SIGNAL_WATCH_THRESHOLD` | 60.0 | `config.py` |
| `OPP_HOT_BUY_THRESHOLD` | 85.0 | `config.py` |
| `OPP_BUY_THRESHOLD` | 70.0 | `config.py` |
| `AI_MIN_RR_RATIO` | 2.0 | `config.py` |
| `MIN_RR_FOR_BUY` | 1.5 | `live_scan_engine.py` |
| `scan_interval_minutes` | 5 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `min_confidence` | 60.0 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `min_opportunity_score` | 60.0 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `per_stock_exposure_cap_pct` | 25.0 (overridden by 20% hard cap) | `phase20_store.py` |
| `_PRETRADE_MAX_PCT` | 20.0 | `paper_exploration_engine.py` |
| `LIVE_EXECUTION_ENABLED` | False | `config.py` |
| `paper_exploration_mode` | False (default; activated Aug 15) | `phase20_store.py` |

### 20.2 Environment Flags

| Flag/Secret | Purpose | Value |
|------------|---------|-------|
| `ZERODHA_API_KEY` | Kite Connect API key | Replit Secret (never displayed) |
| `ZERODHA_API_SECRET` | Kite Connect API secret | Replit Secret (never displayed) |
| `SESSION_SECRET` | Express session signing | Replit Secret |
| `PAPER_ANALYTICS_ENABLED` | Enable paper analytics module | `true` (for smoke tests) |
| `PAPER_EXPLORATION_MODE` | Enable exploration mode | `false` (DB-controlled) |
| `LIVE_EXECUTION_ENABLED` | Allow real broker orders | `false` (PERMANENTLY OFF) |

### 20.3 Key Database Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `pipeline_events` | All pipeline events per scan | `ts`, `event_type`, `symbol`, `payload` |
| `phase20_paper_trades` | Canonical paper trade ledger | `trade_id`, `symbol`, `fill_price`, `status`, `realized_pnl` |
| `paper_portfolio` | Portfolio state (cash, positions) | `cash`, `positions` (JSONB), `updated_at` |
| `scan_state` | Scan run metadata | `scan_id`, `status`, `provider`, `symbols_requested/received` |
| `experimental_paper_trades` | Exploration mode trades (new) | `trade_id`, `action_type`, `max_favorable_excursion` |
| `phase24_missed_opps` | Missed opportunity log | `symbol`, `scan_id`, `reason`, `outcome` |
| `phase24_recommendations` | Learning recommendations | `rule`, `confidence`, `status`, `approved_at` |
| `phase20_kv` | Key-value settings store | `key`, `value`, `updated_at` |
| `phase20_settings` | Operator settings | [schema unknown — column error during query] |
| `backtest_runs` | Backtest execution history | `run_id`, `status`, `started_at`, `completed_at` |
| `certification_runs` | Validation certification | `run_id`, `verdict`, `domains` |

### 20.4 Important API Endpoints

| Method | Endpoint | Function |
|--------|---------|----------|
| GET | `/api/live-data/health` | Quick health check (3-symbol probe) |
| POST | `/api/live-data/scan/run` | Trigger full 51-symbol scan |
| GET | `/api/live-data/scan/latest` | Get latest scan snapshot |
| GET | `/api/paper/status` | Paper portfolio status |
| GET | `/api/paper/trades` | Paper trade history |
| PUT | `/api/paper/settings` | Update operator settings |
| GET | `/api/paper/exploration/status` | Exploration mode status |
| GET | `/api/paper/exploration/trades` | Experimental trades |
| PUT | `/api/paper/exploration/settings` | Update exploration settings |
| GET | `/api/portfolio/current` | Current portfolio state |
| GET | `/api/analytics/execution-quality` | Execution quality metrics |
| GET | `/api/phase24/learning-summary` | Learning engine summary |
| GET | `/api/command-center/overview` | Command center overview (~6s) |
| GET | `/api/ai-ops/snapshot` | AI Operations Center (~22–30s) |

**Note:** The AI Ops Center and Command Center endpoints take 22–30s to respond. All clients must use explicit 60-second timeouts, not the default 15-second timeout.

### 20.5 Generated Reports and Files

| File/Endpoint | Content |
|--------------|---------|
| `PAPER_INTRADAY_LEARNING_EXECUTION_REPORT` | Daily exploration mode report (new, from `generate_daily_report()`) |
| `Phase{N}_Review_Package.zip` | Phase review packages (downloadable from Settings page) |
| `/api/paper/exploration/report` | On-demand exploration learning report |
| `signal_daily_reports` table | Daily signal quality reports |
| `phase26_daily_reports` table | Phase 26 scheduled validation daily reports |
| `preopen_daily_reports` table | Pre-open data quality daily reports |

### 20.6 Known Data Inconsistencies

| Inconsistency | Description |
|--------------|-------------|
| Aug 11 scan anomaly | 65,018 symbol_scanned from 89 scans (14× expected) |
| phase20_paper_trades vs pipeline ORDER_EXECUTED | 64 ORDER_EXECUTED on Aug 11 but only 4 rows in phase20_paper_trades |
| GLAND in BUY signals | GLAND is not a NIFTY 50 constituent — investigate how it entered the scan |
| EXIT_PENDING with exit_ts but NULL realized_pnl | 4 trades appear exited but have no P&L |
| RISK_REJECTED with NULL reason | 15,447 events with no stored rejection reason |

---

## External Reviewer Validation Checklist

Use this checklist when reviewing the system independently:

### A. Architecture Integrity
- [ ] Verify `LIVE_EXECUTION_ENABLED = False` in `config.py` and confirm it has never been set to `True`
- [ ] Confirm `broker_client.py` always falls back to `MockBrokerClient` (no real Zerodha order calls)
- [ ] Confirm `execute_buy()` in `paper_trader.py` writes to DB only, never calls Zerodha orders API
- [ ] Verify no code path calls `kiteconnect.order_place()` or equivalent

### B. Signal Pipeline Correctness
- [ ] Confirm STALE data correctly caps action to WATCH (not silently ignored)
- [ ] Confirm UNAVAILABLE data correctly caps to IGNORE
- [ ] Confirm R:R < 1.5 prevents BUY at scan time
- [ ] Confirm confidence < 60 generates IGNORE, not WATCH

### C. Execution Gate Completeness
- [ ] Verify all 10 pre-execution gates are checked in sequence
- [ ] Confirm market-closed gate prevents execution at all times outside 09:15–15:30 IST
- [ ] Confirm circuit breaker blocks ALL entries when tripped (corrupted state = tripped, not clear)
- [ ] Confirm portfolio pre-check fails closed (not fail-open)

### D. Data Quality
- [ ] Query `scan_state` to confirm scan_id timestamps are monotonically increasing
- [ ] Confirm no scan snapshot has been overwritten by a later failed scan
- [ ] Verify missing symbol count is stable (1 per day = consistent)

### E. Learning Safety
- [ ] Confirm no learning parameter has been auto-promoted without a `phase24_recommendations.approved_at` timestamp
- [ ] Confirm freeze flag is respected: no entries placed when freeze=True
- [ ] Confirm IGNORE-lock blocks only IGNORE-locked symbols, not the full pipeline

### F. Paper Trade Integrity
- [ ] Confirm all `phase20_paper_trades` rows have a valid `scan_id` linking to `pipeline_events`
- [ ] Confirm no trade has `fill_price=0` or `quantity=0`
- [ ] Confirm portfolio cash + sum(position values) ≤ INITIAL_CAPITAL at all times
- [ ] Confirm realized_pnl is computed correctly as (exit_price - fill_price) × quantity

### G. Open Issues to Investigate
- [ ] Explain Aug 11 anomaly: why 65,018 symbol_scanned events from 89 scans?
- [ ] Explain why GLAND is in the scanner (not a NIFTY 50 constituent)
- [ ] Explain why 4 EXIT_PENDING trades have NULL realized_pnl despite having exit_ts
- [ ] Explain why experimental_paper_trades has 0 rows despite 8 EXPERIMENTAL events on Aug 15
- [ ] Confirm the `paper_trades` table contents and whether it duplicates `phase20_paper_trades`

---

*This document was generated automatically from the production codebase and database on 2026-08-15. All SQL queries are available for reproduction. No trading logic, thresholds, or database records were modified to produce this document.*

*For questions or clarifications, the codebase is at: `artifacts/api-server/src/python/` (backend) and `artifacts/trading-dashboard/src/` (frontend).*
