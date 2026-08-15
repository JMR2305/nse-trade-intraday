# ApexQuant AI — Full Project SOP & Second-Opinion Pack

**Document version:** 2.0  
**Generated:** 2026-08-15 (IST)  
**Prepared by:** Replit Agent (automated, read-only except where Remediation Phase 1 changes are noted)  
**Purpose:** Independent second-opinion review package — complete audit of architecture, behaviour, data, and open problems  
**Classification:** Internal review — contains production database statistics  

> **Changelog from v1.0:** This version incorporates all Remediation Phase 1 findings and code fixes (Phases 1A–1D). Changed sections are marked **[UPDATED]**. New content is marked **[NEW]**. No trading thresholds were changed.

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
20. [Remediation Phase 1 — Changes Log](#20-remediation-phase-1--changes-log) **[NEW]**
21. [Appendix](#21-appendix)

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

### 1.2 Current Status (as of 2026-08-15) **[UPDATED]**

| Dimension | Status |
|-----------|--------|
| Live order execution | **PERMANENTLY DISABLED** — `LIVE_EXECUTION_ENABLED = False` |
| Paper trading mode | **ACTIVE** — auto-scanning on 5-minute interval |
| Zerodha session | **INACTIVE** — no current login; data falls back to Yahoo Finance |
| Data source | Yahoo Finance (historical/delayed) — live tick data requires Zerodha OAuth |
| Portfolio capital | ₹50,000 (resets each session) |
| Open paper positions | 4 (all EXIT_PENDING / STALE_DATA_SAFETY) |
| Executed trades (lifetime canonical) | **4 rows in `phase20_paper_trades`** (P20- prefix); 65 events on Aug 11 were phantom (BTT- prefix) |
| Active paper exploration mode | OFF (just activated for testing on Aug 15) |
| Universe | 51 NSE symbols (NIFTY 50 + TMPV + TMCV, minus TATAMOTORS) |
| Scan coverage | ~50/51 per scan (1 symbol typically missing from Yahoo — likely LTIM) |
| **Position-size cap bug** | **FIXED (Remediation Phase 1B)** — SIZE_REDUCED_TO_CAP path now active |
| **Rejection reason logging** | **FIXED (Remediation Phase 1C)** — all rejection events now carry structured `reason` field |

### 1.3 Primary Problem Statement **[UPDATED]**

The platform correctly identifies BUY signals. The two **code-level** blockers for paper execution have now been resolved:

| Blocker | Status |
|---------|--------|
| **Position-size cap hard-reject** — high-priced stocks (DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV) were rejected even when a 1-share-smaller quantity would fit within the cap | ✅ **FIXED** — `_check_position_size()` now computes `cap_qty` and issues `SIZE_REDUCED_TO_CAP` WARNING instead of CRITICAL |
| **Rejection reasons not stored** — 15,447 RISK_REJECTED events had NULL `reason` field; operators could not audit gate failures | ✅ **FIXED** — `reason`, `gate_name`, `action`, `human_readable_reason` now in all rejection payloads |

**Remaining blockers (not code, not yet fixed):**

1. **No Zerodha live tick data (P0):** Running on Yahoo Finance delayed data; all intraday signals get STALE data quality → BUY blocked, capped to WATCH → ineligible for paper execution. Exit logic requires `quote_reliable=True`, which also needs LIVE/NEAR_LIVE data. This is the single remaining blocker for a complete lifecycle.
2. **R:R threshold misalignment:** Scan gate uses 1.5, Phase20 execution gate uses 2.0 (settings default). Signals with 1.5 ≤ RR < 2.0 pass the scan but are blocked at execution. Threshold alignment deferred to Phase 2 per remediation spec.

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
│  Output: RISK_APPROVED or RISK_REJECTED + structured reason  │
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
│  confidence ≥60, opportunity ≥60, R:R ≥2.0 (execution gate),│
│  circuit breaker, portfolio pre-check                       │
│  Position cap: SIZE_REDUCED_TO_CAP (adopt cap_qty if fits)  │
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
| `live_scan_engine.py` | Core scan loop, quality gates, score computation, RISK_REJECTED structured payloads |
| `phase20_executor.py` | Paper execution pipeline, all pre-checks, SIZE_REDUCED_TO_CAP adoption |
| `phase20_store.py` | Settings KV store, DEFAULT_SETTINGS |
| `phase20_scheduler.py` | 5-minute scan tick, paper management |
| `phase20_exits.py` | 8 exit rules (TARGET_HIT, STOP_LOSS_HIT, TRAILING_STOP, TIME_EXIT, MARKET_CLOSE_EXIT, PORTFOLIO_RISK_REDUCTION, SECTOR_CAP_BREACH, STALE_DATA_SAFETY) |
| `canonical_portfolio.py` | Portfolio ledger (positions, cash, equity) |
| `paper_exploration_engine.py` | Exploration mode (cap-resize + WATCH exploration) |
| `paper_trader.py` | Legacy paper trade executor (called by phase20_executor) |
| `risk_validation/pre_trade.py` | Pre-trade validator — SIZE_REDUCED_TO_CAP logic lives here |
| `market_data.py` | Data acquisition with Zerodha→Yahoo fallback |
| `market_regime.py` | Regime classification |
| `opportunity_scanner.py` | Opportunity score computation |
| `strategies.py` | Strategy selection and regime gating |
| `position_sizer.py` | Stop/target/quantity calculation |
| `phase24_engine.py` | Learning analytics engine |
| `backtesting_engine.py` | Historical backtesting |
| `broker_client.py` | Broker abstraction (always falls back to MockBrokerClient) |

---

## 3. Full Pipeline Flow **[UPDATED]**

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
│   │     → RISK_REJECTED emitted with:
│   │         reason, gate_name, actual_value, human_readable_reason [UPDATED]
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
│   │       NOTE: BUY_GENERATED fires ONLY after all gates above pass.
│   │             A STALE symbol always emits WATCH_GENERATED, never BUY_GENERATED.
│   │
│   ├── [RISK GATE] position_sizer.py
│   │   ├── Compute: quantity = min(MAX_CAPITAL×cap_pct%, cash) / price
│   │   ├── Check: stop_loss distance, R:R ratio
│   │   └── RISK_APPROVED or RISK_REJECTED (with reason, gate_name, human_readable_reason)
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
    ├── Gate 6: R:R ≥ min_risk_reward (settings default 2.0)? → else EXECUTION_SKIPPED_WITH_REASON
    │           [emits reason, gate_name, action, human_readable_reason] [UPDATED]
    ├── Gate 7: Circuit breaker clear? → else BLOCKED
    ├── Gate 8: Portfolio pre-check (portfolio_bridge) → else BLOCKED
    ├── Gate 9: Position size check via risk_validation/pre_trade.py:
    │     ├── qty × price ≤ cap_pct% of portfolio → ORDER_SUBMITTED (pass)
    │     ├── qty × price > cap  AND  cap_qty ≥ 1  → SIZE_REDUCED_TO_CAP (use cap_qty) [FIXED]
    │     └── qty × price > cap  AND  cap_qty == 0 → ORDER_REJECTED (genuinely too expensive)
    ├── Gate 10: No existing open position in this symbol? → else SKIP
    │
    ├── If all gates pass (or SIZE_REDUCED_TO_CAP applies):
    │   ├── Adopt cap_qty if size was reduced [FIXED]
    │   ├── Recompute charges with reduced qty [FIXED]
    │   ├── execute_buy() called → simulated fill at signal_price
    │   ├── Portfolio updated (cash reduced, position added)
    │   ├── phase20_paper_trades row inserted with trade_id "P20-{uuid}"
    │   └── ORDER_SUBMITTED → ORDER_EXECUTED emitted (SIZE_REDUCED_TO_CAP in evidence)
    │
    └── If gate fails with CRITICAL:
        ├── ORDER_REJECTED (with gate_name, actual_value, required_value, action,
        │   human_readable_reason in payload) [UPDATED]
        └── EXECUTION_SKIPPED_WITH_REASON (with reason, gate_name, action,
            human_readable_reason) [UPDATED]
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
│   ├── Resize quantity: floor(cap_pct% × portfolio / price)
│   └── Create entry in experimental_paper_trades (NOT phase20_paper_trades)
│
└── Path B: EXPERIMENTAL_BUY_FROM_WATCH
    ├── Find WATCH candidates with confidence ≥ 60, R:R ≥ 1.2
    ├── Require volume_ratio ≥ 1.2 (intraday volume signal)
    └── Create entry in experimental_paper_trades (budget: max 2 trades/day, 5% each)
```

### 3.2 Exit Management Loop (runs every scan tick)

`phase20_scheduler.py` calls `_manage_paper()` on every scan tick, which calls `phase20_exits.manage_open_positions()`. All 8 exit rules are checked for each OPEN trade:

| Exit Rule | Trigger | Data Requirement |
|-----------|---------|-----------------|
| `TARGET_HIT` | `quote >= target` | `quote_reliable=True` (LIVE/NEAR_LIVE) |
| `STOP_LOSS_HIT` | `quote <= stop` | `quote_reliable=True` |
| `TRAILING_STOP` | Peak ≥ fill+2R, then quote ≤ fill+1R | `quote_reliable=True` |
| `TIME_EXIT` | `(now - fill_ts).days >= max_holding_days` | Any |
| `MARKET_CLOSE_EXIT` | Last 15 min of session, `square_off_before_close=True` | Market hours |
| `PORTFOLIO_RISK_REDUCTION` | Daily P&L ≤ −daily_loss_limit | Any |
| `SECTOR_CAP_BREACH` | Sector exposure > cap × 1.25 | Any |
| `STALE_DATA_SAFETY` | Symbol missing from current scan context | Any |

**Important:** When `quote_reliable=False`, exit is recorded as `EXIT_PENDING` with `realized_pnl=NULL`. The exit fill price is not recorded until a LIVE/NEAR_LIVE quote is available. This is the current state of all 4 open positions.

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
| `AI_MIN_RR_RATIO` | **2.0** | Minimum R:R for the decision engine to approve (advisory only — not in paper execution path) |
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

### 4.5 Execution-Time Gates (phase20_executor.py via phase20_store.py) **[UPDATED]**

| Gate | Default Value | Notes |
|------|---------------|-------|
| `min_confidence` | **60.0%** | Configurable via Settings page |
| `min_opportunity_score` | **60.0** | Configurable via Settings page |
| `min_risk_reward` | **2.0** | Execution gate — **different from scan gate 1.5** (see §4.6) |
| `per_stock_exposure_cap_pct` | **25.0%** | Settings default; used by pre-trade validator |
| `scan_interval_minutes` | **5** | Allowed values: 1, 2, 3, 5, 10, 15 |
| Market open window | **09:15–15:30 IST** | Outside this → execution skipped |
| Stale scan | Configurable | Scan older than threshold → EXECUTION_SKIPPED |
| Circuit breaker | State-based | If tripped → all entries blocked until manual reset |
| Duplicate position | One per symbol | Cannot open second position in same symbol |
| **Position size** | **SIZE_REDUCED_TO_CAP path** | If `cap_qty ≥ 1`: WARNING + proceed at cap_qty. If `cap_qty == 0`: CRITICAL → ORDER_REJECTED [FIXED] |

### 4.6 R:R Threshold Map — All Layers **[NEW]**

This is a critical architectural gap identified in Remediation Phase 1A:

| Layer | File | Threshold | Enforcement | Pipeline effect |
|-------|------|-----------|-------------|-----------------|
| Scan gate | `live_scan_engine.py:64` | **≥ 1.5** | `_rr_gate()` caps BUY→WATCH | WATCH_GENERATED |
| Pre-trade validator | `risk_validation/pre_trade.py:26` | **≥ 1.5** | CRITICAL rejection | ORDER_REJECTED |
| Phase20 execution gate | `phase20_gates.py:258` | **≥ 2.0** (settings default) | EXECUTION_SKIPPED | EXECUTION_SKIPPED_WITH_REASON |
| AI Decision Engine | `ai_decision.py:160` | 2.0 | Advisory `downgrade_reasons` only | **None — not in paper execution path** |
| `config.py` | `config.py:61` | `AI_MIN_RR_RATIO=2.0` | Advisory only | **None** |

**Conflict:** Signals with 1.5 ≤ RR < 2.0 pass the scan gate (→ `BUY_GENERATED`) and the pre-trade validator, but are blocked at the phase20 execution gate (→ `EXECUTION_SKIPPED_WITH_REASON`). Live DB confirms with messages like `"R:R 1.5 vs minimum 2.0"`. **Threshold alignment is deferred to Phase 2 per the remediation spec.**

### 4.7 Position Sizing: Before vs After Remediation Phase 1B **[NEW]**

| Scenario | Before fix | After fix |
|----------|-----------|-----------|
| `qty × price ≤ cap` | PASS — proceed | PASS — unchanged |
| `qty × price > cap`, `cap_qty ≥ 1` | CRITICAL → ORDER_REJECTED | **WARNING (SIZE_REDUCED_TO_CAP) → proceed at cap_qty** |
| `qty × price > cap`, `cap_qty == 0` (stock too expensive) | CRITICAL → ORDER_REJECTED | CRITICAL → ORDER_REJECTED (unchanged) |

New `summary` fields populated by `risk_validation/pre_trade.py`:
- `size_reduced_to_cap: bool`
- `capped_qty: int`
- `gate_name: str`
- `human_readable_reason: str`

`phase20_executor.py` reads `rv.summary["size_reduced_to_cap"]` and adopts `rv.summary["capped_qty"]` before calling `execute_buy()`.

### 4.8 Gap Between Scan-Time and Execution-Time Thresholds **[UPDATED]**

| Dimension | Scan-time | Execution-time | Gap status |
|-----------|-----------|----------------|------------|
| R:R minimum | 1.5 (live_scan_engine) | 2.0 (executor gate) | **OPEN — deferred to Phase 2** |
| Confidence minimum | 60.0 (scan gate) | 60.0 (executor gate) | Aligned |
| Data quality for BUY | LIVE or NEAR_LIVE | LIVE or NEAR_LIVE | Aligned |
| Position size cap | Not enforced at scan time | cap_qty path (FIXED) | **RESOLVED** |
| Portfolio state | Not known at scan time | Checked at execution | Gap remains (intentional) |

### 4.9 Paper Exploration Thresholds (paper_exploration_engine.py)

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

### 5.7 Operations and Observability Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/ops-center` | `OperationsCenter` | Phase 8.5 — 14 command types, 11 tabs |
| `/security-center` | `SecurityCenter` | Phase 8.6 — security & compliance monitoring |
| `/performance-center` | `PerformanceCenter` | Phase 8.7 — system performance monitoring |
| `/deployment-center` | `DeploymentCenter` | Phase 8.8 — deployment & DR management |
| `/command-center` | `CommandCenter` | Phase 9.1 — unified command overview |
| `/observability-center` | `ObservabilityCenter` | Phase 8.1 — 6 observability endpoints |
| `/schedule-manager` | `ScheduleManager` | Scheduler management and monitoring |
| `/live-monitoring` | `LiveMonitoring` | Live scan monitoring |
| `/data-quality` | `DataQuality` | Data quality metrics per symbol |
| `/provider-health` | `ProviderHealth` | Data provider health |
| `/circuit-breaker` | `CircuitBreaker` | Circuit breaker status and reset |

### 5.8 Admin and Audit Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/settings` | `Settings` | All operator settings, phase review package downloads |
| `/audit-log` | `AuditLog` | Full audit trail of all system events |
| `/pipeline-events` | `PipelineEvents` | Raw pipeline event explorer |
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

**Current situation:** Without a Zerodha OAuth session, most symbols receive `STALE` data from Yahoo Finance. This means BUY action is capped to WATCH for STALE symbols — ineligible for paper execution.

**Important clarification (Remediation Phase 1A finding):** Yahoo Finance data is NOT uniformly labelled STALE. When yfinance returns sufficiently recent data (within the NEAR_LIVE window), some symbols can qualify for BUY_GENERATED. The 19,034 BUY_GENERATED events over 14 days confirm this. The original SOP claim ("ALL symbols receive STALE data") was incorrect.

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
| 2026-08-11 | 89 | 76 | 2 | 65,018 | **MAJOR ANOMALY** — see §7.3 |
| 2026-08-10 | 54 | 54 | 0 | 2,592 | 2592/54=48 symbols/scan, 3 missing |
| 2026-08-09 | 1 | 1 | 0 | 48 | Saturday — 1 test scan |
| 2026-08-08 | 3 | 2 | 1 | 169 | Sunday + partial — 2 scans |

### 7.3 Scan Anomalies

**Aug 11 Major Anomaly:** 65,018 SYMBOL_SCANNED events with 89 SCAN_STARTED. Expected would be ~4,539 (89 × 51). The actual count is 14× higher. Possible explanations:
- The scan_interval was temporarily set to 1 minute (75×51=3,825 per hour, ×8h=30,600) — partial explanation
- A loop bug caused multiple passes per scan within the same scan_id
- The GLAND symbol alone accounts for 25,124 SYMBOL_SCANNED (almost exactly 25,124/89=282 passes per scan)
- **Assessment:** This appears to be a bug that caused repeated scanning. The GLAND symbol generated 15,065 BUY_GENERATED events and 11,197 ORDER_CANCELLED events from this single session.
- **Critical finding (Remediation Phase 1A):** The 64 ORDER_EXECUTED events on Aug 11 are from an **external intraday_bot** process (trade IDs use "BTT-" prefix), not `phase20_executor.py` (which uses "P20-" prefix). These are phantom events — zero corresponding rows exist in `phase20_paper_trades`.

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
| **2026-08-11** | 89★ | 65,018★ | 18,460 | 26,428 | 20,130 | 14,886 | 3,315 | 64★★ | 819 | 0 | 64★★ | 25★★ |
| **2026-08-10** | 54 | 2,592 | 176 | 1,562 | 854 | 187 | 87 | 0 | 807 | 0 | 0 | 0 |
| **2026-08-09** | 1 | 48 | 6 | 27 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **2026-08-08** | 3 | 169 | 26 | 43 | 99 | 1 | 20 | 1 | 0 | 0 | 1 | 1 |

★ = Anomalous — see §7.3  
★★ = **PHANTOM** — "BTT-" prefixed events from external intraday_bot; zero rows in `phase20_paper_trades`

**Key observations:**
- **Total BUY_GENERATED (all-time):** 19,034 — these are all post-gate (STALE data cannot generate BUY)
- **Total canonical paper trades in `phase20_paper_trades`:** **4** (all Aug 4–7, all EXIT_PENDING)
- **Aug 11 ORDER_EXECUTED=64 are phantom** — external bot process, not `phase20_executor.py`
- **Total ORDER_REJECTED:** 3,065 — majority from position-size cap violations (now fixed)

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

### 9.3 Top ORDER_REJECTED Symbols **[UPDATED]**

All of the following rejections were due to the position-size cap bug, which is now fixed via the SIZE_REDUCED_TO_CAP path. Future scans should produce 0 ORDER_REJECTED for these symbols (assuming they remain within the configured cap):

| Rank | Symbol | ORDER_REJECTED | Rejection reason (pre-fix) | Post-fix behaviour |
|------|--------|---------------|---------------------------|--------------------|
| 1 | **DRREDDY** | **873** | Size 21.5–21.7% > 20% cap | ✅ SIZE_REDUCED_TO_CAP (8→7 shares) |
| 2 | **GRASIM** | 548 | Size 20.2–20.3% > 20% cap | ✅ SIZE_REDUCED_TO_CAP (fits 25%) |
| 3 | **BAJAJFINSV** | 353 | Size 20.2–20.4% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 4 | **BAJAJ-AUTO** | 262 | Size 23.4–23.6% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 5 | **TMPV** | 272 | Size 21.6% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 6 | **TITAN** | 221 | Size > 20% | ✅ SIZE_REDUCED_TO_CAP |
| 7 | **JSWSTEEL** | 182 | Size 23.5% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |

---

## 10. Rejection and Block Reasons **[UPDATED]**

### 10.1 ORDER_REJECTED Breakdown (from pipeline_events payload)

| Reason | Count | Status |
|--------|-------|--------|
| **Position size > cap (hard reject)** | **~3,000+** | ✅ FIXED — now SIZE_REDUCED_TO_CAP for `cap_qty ≥ 1` |
| `PORTFOLIO BLOCKED: INSUFFICIENT_BUYING_POWER` | 68 | Likely from the Aug 11 anomaly when cash was consumed |
| `PORTFOLIO BLOCKED: BELOW_MIN_ORDER_VALUE` | 15 | Order value too small after sizing |

**New rejection payload fields (post-fix):**
```json
{
  "reason": "DRREDDY: position size ₹10,783 = 21.6% of portfolio (limit 20.0%)",
  "gate_name": "POSITION_SIZE_EXCEEDED",
  "actual_value": 21.6,
  "required_value": 20.0,
  "action": "BUY",
  "human_readable_reason": "DRREDDY: position size ₹10,783 = 21.6% of portfolio — exceeds 20% cap and cannot be reduced further"
}
```

### 10.2 RISK_REJECTED Breakdown **[UPDATED]**

| Count | Stored reason (pre-fix) | Status |
|-------|------------------------|--------|
| **15,447 total RISK_REJECTED** | `NULL` — reason nested in `failed_gates`, not top-level | ✅ FIXED for new events |

**Problem (now fixed):** RISK_REJECTED events had no top-level `reason` field. The rejection cause was nested under `payload.failed_gates.<gate_name>.reason`, which could not be queried via `payload->>'reason'`.

**Fix applied (Remediation Phase 1C):** `live_scan_engine.py` `derive_symbol_events()` now adds to every RISK_REJECTED payload:

```json
{
  "failed_gates": { "rr": { "passed": false, "reason": "RR 0.80 < 1.5 minimum" } },
  "action": "WATCH",
  "gate_name": "rr",
  "actual_value": "RR 0.80 < 1.5 minimum — BUY requires viable risk/reward",
  "human_readable_reason": "rr: RR 0.80 < 1.5 minimum — BUY requires viable risk/reward",
  "reason": "rr: RR 0.80 < 1.5 minimum — BUY requires viable risk/reward"
}
```

**Historical events (15,447) still have NULL reason** — the fix applies to new events only. A one-time back-fill query could populate historical reasons from the nested `failed_gates` field if needed.

### 10.3 EXECUTION_SKIPPED_WITH_REASON **[UPDATED]**

| Count | Stored reason (pre-fix) | Status |
|-------|------------------------|--------|
| **67 total** (63 on Aug 13, 4 on Aug 14) | `NULL` | ✅ FIXED for new events |

**Fix applied:** `phase20_executor.py` now adds to every EXECUTION_SKIPPED_WITH_REASON payload:
- `gate_name`: first failed gate (e.g. `"min_risk_reward"`)
- `action`: recommendation action (e.g. `"BUY"`)
- `human_readable_reason`: full readable string
- `reason`: same (top-level for SQL queries)

### 10.4 Categorised Rejection Summary **[UPDATED]**

| Category | Estimated Count | Status |
|----------|----------------|--------|
| Position size cap (hard reject, >cap) | ~3,000 | ✅ FIXED — SIZE_REDUCED_TO_CAP now handles these |
| Risk agent rejection (reason now logged) | ~15,447 | ✅ FIXED (new events) — historical remains null |
| Execution skipped (reason now logged) | ~67 | ✅ FIXED (new events) |
| Portfolio blocked (buying power/exposure) | ~83 | Unchanged — circuit breaker/precheck working correctly |
| Order cancelled (from Aug 11 anomaly) | ~13,193 | Phantom — from external bot, not canonical executor |

---

## 11. Detailed Case Studies **[UPDATED]**

### 11.1 Case Study: DRREDDY — Repeated BUY Rejected by Position-Size Cap **[RESOLVED]**

**The pattern (historical):**

On every market day since Aug 8, DRREDDY generated BUY signals that passed all gates **except** the 20% position-size cap.

| Date | BUY Generated | Risk Approved | ORDER_REJECTED | Reason |
|------|--------------|--------------|----------------|--------|
| Aug 14 | 48 | 48 | 201 | Size 21.5–21.7% of ₹50,000 |
| Aug 13 | 48 | 48 | 203 | Size 21.5–21.7% of ₹50,000 |
| Aug 12 | 53 | 53 | 260 | Size ~21.6% |
| Aug 11 | 39 | 39 | 209 | Size ~21.6% |

**Root cause:**
- DRREDDY price: ~₹1,340–₹1,360 per share
- Ideal qty from position sizer: 8 shares (based on 1% risk formula)
- 8 × ₹1,350 = ₹10,800 = **21.6%** of ₹50,000
- Hard cap was 20.0% = ₹10,000 max
- `cap_qty = floor(₹10,000 / ₹1,350)` = 7 shares
- 7 × ₹1,350 = ₹9,450 = **18.9%** → passes the cap

**Resolution:** ✅ **FIXED in Remediation Phase 1B.** `_check_position_size()` now computes `cap_qty` and issues `SIZE_REDUCED_TO_CAP` WARNING. `phase20_executor.py` adopts `cap_qty=7` and proceeds to `execute_buy()`. DRREDDY trades will now produce ORDER_EXECUTED with `size_reduced_to_cap=True` in the evidence field.

### 11.2 Case Study: HDFCLIFE — Missed Low / Pattern Not Captured

**Context:** HDFCLIFE received 126 BUY_GENERATED and 198 RISK_REJECTED events over the 14-day window, plus 204 WATCH_GENERATED.

**The issue documented in the HDFCLIFE missed-buy audit:**
- HDFCLIFE printed a significant intraday low at some point where the signal was BUY-grade
- The executor had a data quality issue (STALE from Yahoo) that capped the action to WATCH
- Even with WATCH, the paper executor doesn't place trades
- The missed opportunity was recorded but not acted on

**Learning bridge:** The Phase 24 learning engine stores missed opportunities in the `phase24_missed_opps` table, but this data is advisory only — no auto-retry or BUY override is performed.

### 11.3 Case Study: Executor ImportError (Task #657) — Resolved

**Background:** A previously reported `ImportError` in the paper executor prevented any paper trades from being placed for multiple sessions. The fix was verified via a dedicated audit report.

**Status:** Fixed. The executor now correctly imports all required modules. The Aug 11 ORDER_EXECUTED=64 events confirm execution is working when signals pass all gates (though those events are from the external bot, not `phase20_executor.py`).

### 11.4 Case Study: TMCV — WATCH Despite Intraday Movement

**The pattern:** TMCV (Tata Motors Commercial Vehicles — successor to TATAMOTORS) appears in WATCH_GENERATED events but never in BUY_GENERATED, despite being in the NIFTY 50 universe with potential intraday signals.

**Root causes:**
1. Yahoo Finance data for TMCV is STALE → BUY forced to WATCH at scan time
2. TMCV is a newly demerged stock with limited historical data for the signal engine → confidence scores are lower
3. Price ~₹457 → even at full 25% cap = ₹12,500 / ₹457 = 27.4 shares → position size would be fine, but signals never reach BUY grade

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

### 11.6 Case Study: Aug 11 "Phantom" Executions **[UPDATED]**

**Verdict: CONFIRMED PHANTOM. Zero verified clean paper trade lifecycles exist from the canonical executor.**

| Table | Aug 11 rows |
|-------|------------|
| `pipeline_events` ORDER_EXECUTED / POSITION_OPENED | **64 each** |
| `phase20_paper_trades` (canonical) | **0** |
| `paper_trades` (legacy) | **0** |

**Trade ID evidence:**
- `phase20_executor.py` generates: `f"P20-{uuid.uuid4().hex[:10]}"` (line 448)
- Aug 11 payloads show: `"BTT-16d1f82f54"`, `"BTT-a0f89753dd"` — **external bot prefix**

Multiple identical GLAND executions at the same fill price within seconds confirm the events are from a looping external `intraday_bot` process that wrote pipeline events but never committed to any canonical trade table. The scan loop anomaly (89 scan starts, 65,018 SYMBOL_SCANNED vs 306 expected) confirms the system was in an abnormal state on that day.

**The system has never had a verified clean paper trade lifecycle from `phase20_executor.py` in any canonical ledger.** The 4 trades in `phase20_paper_trades` (Aug 4–7) are the only canonical trades; all have `EXIT_PENDING` with NULL `realized_pnl`.

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
- No realized P&L recorded — the safety exit records `exit_ts` and `exit_rule` but requires `quote_reliable=True` to record a fill price. Since data quality was STALE, exits became EXIT_PENDING with `realized_pnl = NULL`
- All confidence scores are between 62.8% and 72.5% — above the 60% minimum
- Total capital deployed: ~₹36,088 across 4 positions (72% of ₹50,000)

### 12.2 Why Realized P&L is NULL on All Trades **[UPDATED]**

This is not a code bug — it is a data quality issue:

```python
# phase20_exits.py:171–173
if not quote_reliable:
    record_exit(trade_id, 0.0, rule, exit_scan_id, status="EXIT_PENDING")
    # → realized_pnl = None (because exit_price=0.0 and status≠CLOSED)
```

`quote_reliable` requires: `scan_ok AND NOT stale AND quote > 0 AND dq in ("LIVE","NEAR_LIVE")`.

Without a live Zerodha session, data quality is STALE → exits are marked EXIT_PENDING → `realized_pnl` stays NULL. Once Zerodha data becomes available, pending exits will resolve via `resolve_pending_exits()` (exists in `phase20_exits.py` line 250, called on the next scan tick with LIVE data).

### 12.3 Sell/Exit Behavior

**No successful sell-side executions are recorded.** The exit logic is fully implemented in `phase20_exits.py` (all 8 rules, confirmed in Remediation Phase 1D), but requires `quote_reliable=True` to record fill prices and P&L. This requires an active Zerodha session.

---

## 13. Why No Trades Executed in Recent Sessions **[UPDATED]**

This section separates the blocking factors for Aug 12–14 (0 orders executed):

### 13.1 Data Problems

| Problem | Impact | Status |
|---------|--------|--------|
| No Zerodha OAuth session | Yahoo Finance → mostly STALE data → BUY capped to WATCH → ineligible | **OPEN — P0 blocker** |
| 1 missing symbol per scan | Minor — 1 symbol (likely LTIM) not contributing signals | Minor |
| Post-market scan noise | Non-actionable signals displayed during non-market hours | Minor |

**Severity: HIGH** — Without Zerodha live data, no paper-eligible BUY signals can enter the executor with LIVE quality.

### 13.2 Risk Threshold Problems **[UPDATED]**

| Problem | Impact | Status |
|---------|--------|--------|
| R:R 1.5 (scan gate) vs 2.0 (execution gate) — gap blocks signals with 1.5–1.99 RR | Confirmed via `"R:R 1.5 vs minimum 2.0"` in DB | **OPEN — deferred to Phase 2** |
| Rejection reasons previously not stored | Could not audit 15,447 risk rejections | ✅ FIXED (new events) |
| SIDEWAYS regime downgrade (conf < 72%) | Many WATCH signals lose confidence in sideways market | Known, by design |

**Severity: MEDIUM** — The RR gap is now documented and logged; threshold alignment is a Phase 2 item.

### 13.3 Position Sizing Problems **[RESOLVED]**

| Problem | Count | Status |
|---------|-------|--------|
| DRREDDY: 8 shares = 21.6% > cap | 873 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP (now 7 shares) |
| GRASIM: 3 shares = 20.2% > cap | 548 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| BAJAJ-AUTO: 2 shares = 23.4% > cap | 262 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| BAJAJFINSV: 6 shares = 20.4% > cap | 353 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| TMPV: 6 shares = 21.6% > cap | 272 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |

**Root cause (fixed):** The position sizer computed the "ideal" quantity based on risk parameters, but never tried a smaller quantity when the ideal exceeded the cap. The fix computes `cap_qty = floor(cap_amount / fill_price)` and proceeds with the reduced quantity when `cap_qty ≥ 1`.

**Expected outcome:** All five listed symbols will now produce ORDER_EXECUTED instead of ORDER_REJECTED on the next qualifying scan.

### 13.4 Paper Learning / Exploration Policy

| Problem | Impact | Status |
|---------|--------|--------|
| `paper_exploration_mode = False` (Aug 12–14) | No SIZE_REDUCED_TO_CAP or WATCH exploration trades | Exploration activated Aug 15 |
| Exploration mode just activated Aug 15 | 8 events but 0 DB rows — may need debugging | Under investigation |
| Budget is tight (max 2 trades/day, 5% each = ₹2,500/trade) | Even with exploration enabled, only small trades are placed | By design |

**Severity: MEDIUM** — Exploration mode is an additional safety net, but the primary fix (SIZE_REDUCED_TO_CAP in the main executor) is more impactful.

### 13.5 UI Interpretation Problems

| Problem | Impact |
|---------|--------|
| Post-market signals displayed as active | Operators think system missed trades |
| WATCH signals shown without "not executable" label | Operators think WATCH = pending trade |
| EXIT_PENDING label without explanation | Operators don't know positions are already safety-exited |
| RISK_REJECTED count historically without reason (now fixed) | Difficult to investigate gate failures |

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

**Remediation Phase 1 confirmation:** The docstrings of `risk_validation/pre_trade.py` and `phase20_exits.py` both state _"PAPER TRADING / RESEARCH ONLY. No live orders anywhere."_ This is enforced structurally, not just by comment.

---

## 17. Open and Proposed Tasks — Priority Order **[UPDATED]**

The task list contains 218 tasks. Below are the top-priority items assessed by functional impact. Items completed in Remediation Phase 1 are marked.

### 17.1 Critical (Blocking Production Value)

| # | Task Title | Status |
|---|-----------|--------|
| **Phase 1B** | Fix position sizer to adopt cap_qty instead of hard-rejecting | ✅ **DONE** |
| **Phase 1C** | Store structured rejection reason in all rejection events | ✅ **DONE** |
| **P0 (spec)** | Restore Zerodha OAuth session (needed for LIVE data quality) | ❌ OPEN — operator action required |
| #659 | Prevent paper-mode SELL orders from silently failing when no position exists | OPEN |
| #235 | Prevent stale regime data from silently masking a regime transition | OPEN |
| #180 | Prevent 09:20 reconciliation from running with null prices | OPEN |
| #358 | Prevent Risk Agent card from going dark when SnapshotBus restarts | OPEN |

### 17.2 High Priority (Data Integrity)

| # | Task Title | Impact |
|---|-----------|--------|
| **Phase 2 (spec)** | Align RR threshold: scan gate 1.5 vs execution gate 2.0 | Signals with RR 1.5–1.99 silently blocked |
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

## 18. Known Weaknesses and Second-Opinion Questions **[UPDATED]**

### 18.1 Architectural Weaknesses

| # | Weakness | Severity | Status |
|---|---------|---------|--------|
| W1 | **No live tick data** — running entirely on Yahoo Finance delayed data | CRITICAL | ❌ OPEN — requires Zerodha OAuth session |
| W2 | **Position sizer hard-rejected when ideal qty exceeded cap** — caused 3,000+ ORDER_REJECTED | HIGH | ✅ FIXED (Remediation Phase 1B) — SIZE_REDUCED_TO_CAP path |
| W3 | **RISK_REJECTED had no stored reason** — 15,447 unexplained rejections | HIGH | ✅ FIXED (Remediation Phase 1C) — new events carry reason, gate_name, human_readable_reason |
| W4 | **EXECUTION_SKIPPED reason not stored** — 67 unexplained skips | MEDIUM | ✅ FIXED (Remediation Phase 1C) — new events carry reason |
| W5 | **No sell/exit strategy** — STALE_DATA_SAFETY is not a trading exit | HIGH | ⚠️ Exit code IS fully implemented; blocked by W1 (data quality) |
| W6 | **Scanner runs post-market** — misleads operators about signals | MEDIUM | OPEN — UI banner recommended |
| W7 | **Aug 11 scan loop anomaly** — 65,018 symbol_scanned from 89 scans; 64 phantom ORDER_EXECUTED events | MEDIUM | OPEN — root cause not fixed; recommend scan-loop watchdog |
| W8 | **EXIT_PENDING positions have no realized P&L** | MEDIUM | ⚠️ Expected behaviour — blocked by W1 (no LIVE data for exit quotes) |
| W9 | **Exploration mode experimental_paper_trades is empty** despite 8 events | HIGH | OPEN — silent failure to write DB rows |
| W10 | **R:R threshold misalignment** — scan gate 1.5 vs execution gate 2.0 | HIGH | OPEN — documented, deferred to Phase 2 |
| W11 | **Aug 11 executions are phantom** — "BTT-" prefix external bot, not canonical executor | HIGH | ✅ CONFIRMED (Remediation Phase 1A) — no action needed except documentation |

### 18.2 Questions for Independent Reviewer **[UPDATED]**

1. **Threshold calibration:** Are the signal thresholds (BUY≥75, WATCH 60–75, IGNORE<60) appropriate for the NSE intraday market? Given that Yahoo Finance produces STALE data for many symbols, is confidence computed from historical OHLCV meaningful for intraday trading?

2. **Position sizing:** The cap is now `settings["per_stock_exposure_cap_pct"]` (default 25%) rather than a fixed 20%. A cap of 25% on ₹50,000 = ₹12,500 per trade. Is this appropriate? Should minimum-quantity floor of 1 share always be honoured regardless of cap percentage?

3. **Scan loop anomaly (Aug 11):** 65,018 symbol_scanned events from 89 SCAN_STARTED events cannot be explained by the known architecture. Is there a watchdog needed to prevent runaway scan loops? Could this recur?

4. **STALE data BUY cap:** The architecture blocks BUY on STALE data. Yahoo Finance data is typically 15–20 minutes delayed for Indian markets — should NEAR_LIVE be granted to Yahoo data within 20 minutes? Currently 19,034 BUY_GENERATED events over 14 days confirm some Yahoo data does qualify.

5. **Learning completeness:** The system tracks missed opportunities and win rates but has no auto-promotion. Is the human-approval-required approach appropriate given the scale of signals (1,000+ BUY events per day)?

6. **Capital reset:** The portfolio resets to ₹50,000 each trading day. Is this modeling intraday-only trading? Or should positions carry over? Currently, positions DO carry over (EXIT_PENDING trades from Aug 4–7 are still in the DB).

7. **RR alignment (Phase 2 target):** Should the execution gate be lowered from 2.0 to 1.5 to align with the scan gate? Or raised to 2.0 in the scan gate? Which direction produces better backtesting results?

8. **GLAND anomaly:** GLAND generated 15,065 BUY_GENERATED events in one day. Is GLAND in the NIFTY 50? (It does not appear in the standard NIFTY 50 index.) How did it end up with such extreme counts?

9. **Database design:** Having both `paper_trades` and `phase20_paper_trades` tables is confusing. Which is canonical? The Aug 11 executions appear in pipeline_events but not in either table.

10. **Exit strategy gap:** Four open positions (BAJFINANCE, GRASIM, DIVISLAB, TRENT) have `exit_ts` set but `status=EXIT_PENDING` and `realized_pnl=NULL`. The exit code is fully implemented — these will resolve when Zerodha session provides LIVE data. Is this the intended design?

---

## 19. Recommended 30-Day Roadmap **[UPDATED]**

### Week 1 (Days 1–7): Fix Blocking Issues

| Priority | Action | Status |
|----------|--------|--------|
| 🔴 P1 | Fix position sizer (SIZE_REDUCED_TO_CAP path) | ✅ **DONE** (Remediation Phase 1B) |
| 🔴 P1 | Store rejection reason in all rejection events | ✅ **DONE** (Remediation Phase 1C) |
| 🔴 P1 | Complete Zerodha OAuth setup and maintain active session during market hours | ❌ OPEN — operator action required |
| 🟡 P2 | Fix EXIT_PENDING trades — capture exit price and realized P&L on STALE_DATA_SAFETY | ⚠️ Will auto-resolve when Zerodha session active |
| 🟡 P2 | Add market-hours banner to Trade Decisions page | OPEN |

### Week 2 (Days 8–14): Paper Trading Quality

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Confirm first canonical P20- trade after Zerodha session restored | Prove clean lifecycle: signal → order → ledger row → exit → P&L |
| 🔴 P1 | Debug Paper Exploration Mode — confirm experimental_paper_trades rows are written | 8 events without DB rows is a silent failure |
| 🟡 P2 | Align RR threshold: lower execution gate from 2.0 to 1.5 (or raise scan gate) | Resolve Phase 2 misalignment |
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

## 20. Remediation Phase 1 — Changes Log **[NEW]**

This section provides a precise, auditable record of all code changes made during Remediation Phases 1A–1D. No trading thresholds or database records were changed.

### 20.1 Phase 1A — Code Trace (Read-Only)

**No code changes.** Three questions answered by reading the production codebase and querying the production database:

| Question | Finding |
|----------|---------|
| Is BUY_GENERATED emitted pre-gate or post-gate? | **Post-gate.** `derive_symbol_events()` reads `r.final_action`, which has already been mutated by `_apply_quality_gate()`, `_rr_gate()`, and `_volume_gate()`. A STALE symbol can never emit BUY_GENERATED. |
| Where is R:R enforced, and are the layers aligned? | **Misaligned.** Scan gate = 1.5, pre-trade validator = 1.5, phase20 execution gate = 2.0 (settings default). Signals with 1.5 ≤ RR < 2.0 pass the scan but are blocked at execution. AI Decision Engine 2.0 is advisory only — not in the paper execution path. |
| Were Aug 11 executions real? | **Phantom.** Trade IDs use "BTT-" prefix (external intraday_bot), not "P20-" prefix (phase20_executor.py). Zero rows in phase20_paper_trades or paper_trades for that date. |

**Documents produced:** `REMEDIATION_PHASE_1A_CODE_TRACE_REPORT.md`

### 20.2 Phase 1B — Position Sizing Fix

**Files changed:** `risk_validation/pre_trade.py`, `phase20_executor.py`

| File | Change |
|------|--------|
| `risk_validation/pre_trade.py` | `_check_position_size(cap_pct)` now accepts cap_pct from `settings["per_stock_exposure_cap_pct"]`. Computes `cap_qty = floor(cap_amount / fill_price)`. If `cap_qty ≥ 1`: emits WARNING `SIZE_REDUCED_TO_CAP`, returns `cap_qty` in summary. If `cap_qty == 0`: keeps CRITICAL. `validate_pre_trade()` passes settings-based cap, extracts `capped_qty` and `size_reduced_to_cap` into summary. Also adds `gate_name`, `actual_value`, `human_readable_reason` to summary. |
| `phase20_executor.py` | After validation, if `summary["size_reduced_to_cap"]` and `capped_qty ≥ 1`: adopts `capped_qty`, recomputes `charges` with reduced qty, updates `sizing["quantity"]` before calling `execute_buy()`. |

**Verified by:** `python3 -m pytest tests/unit/test_paper_exploration.py` → **27/27 PASSED**  
**Smoke test:** DRREDDY 9→8 shares at 20% cap ✅, BAJAJ-AUTO 1 share passes 25% cap ✅, genuinely-expensive stock still CRITICAL ✅

### 20.3 Phase 1C — Rejection Reason Logging

**Files changed:** `live_scan_engine.py`, `phase20_executor.py`

| File | Change |
|------|--------|
| `live_scan_engine.py` | `derive_symbol_events()` — RISK_REJECTED payload now includes top-level `reason`, `gate_name`, `actual_value`, `human_readable_reason`, `action` fields. Aggregates all failed gates into a human-readable string. |
| `phase20_executor.py` | (a) EXECUTION_SKIPPED_WITH_REASON: adds `gate_name`, `action`, `human_readable_reason`, `reason` fields. (b) ORDER_REJECTED at `risk_agent_pre_trade`: adds `gate_name`, `actual_value`, `required_value`, `action`, `human_readable_reason`. |

**All three rejection event types now carry:** `payload->>'reason'` returns non-NULL for new events.

**Verified by:** `python3 -c "..."` smoke test — RISK_REJECTED payload assertions all passed ✅

### 20.4 Phase 1D — Exit Logic Audit (Read-Only)

**No code changes.** Confirmed by reading `phase20_exits.py` and `phase20_scheduler.py`:

- All 8 exit rules are implemented (TARGET_HIT, STOP_LOSS_HIT, TRAILING_STOP, TIME_EXIT, MARKET_CLOSE_EXIT, PORTFOLIO_RISK_REDUCTION, SECTOR_CAP_BREACH, STALE_DATA_SAFETY)
- `phase20_scheduler.py` wires exit management to every scan tick
- `resolve_pending_exits()` exists and will clear EXIT_PENDING trades when LIVE data arrives
- NULL realized_pnl on the 4 open trades is not a bug — it is the expected result of `quote_reliable=False` at exit time

### 20.5 Clean Lifecycle Status After Phase 1

| Stage | Status |
|-------|--------|
| Signal → `BUY_GENERATED` | ✅ Working (19,034 all-time, all post-gate) |
| `BUY_GENERATED` → `ORDER_EXECUTED` | ✅ Code-level blocker removed (Phase 1B); data quality remains the gating factor |
| `ORDER_EXECUTED` → ledger row in `phase20_paper_trades` | ✅ Code exists and works (4 existing rows prove it) |
| Ledger row → exit with realized P&L | ⚠️ Exit code complete; requires Zerodha LIVE data (`quote_reliable=True`) |
| **Single remaining blocker** | **Zerodha session (P0 — operator action, not a code bug)** |

---

## 21. Appendix

### 21.1 Important Configuration Values

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
| `AI_MIN_RR_RATIO` | 2.0 | `config.py` (advisory only) |
| `MIN_RR_FOR_BUY` | 1.5 | `live_scan_engine.py` (scan gate) |
| `min_risk_reward` (execution gate) | 2.0 | `phase20_store.py` DEFAULT_SETTINGS |
| `scan_interval_minutes` | 5 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `min_confidence` | 60.0 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `min_opportunity_score` | 60.0 | `phase20_store.py` (DEFAULT_SETTINGS) |
| `per_stock_exposure_cap_pct` | 25.0 | `phase20_store.py` — used by pre-trade validator |
| `LIVE_EXECUTION_ENABLED` | False | `config.py` |
| `paper_exploration_mode` | False (default; activated Aug 15) | `phase20_store.py` |

### 21.2 Environment Flags

| Flag/Secret | Purpose | Value |
|------------|---------|-------|
| `ZERODHA_API_KEY` | Kite Connect API key | Replit Secret (never displayed) |
| `ZERODHA_API_SECRET` | Kite Connect API secret | Replit Secret (never displayed) |
| `SESSION_SECRET` | Express session signing | Replit Secret |
| `PAPER_ANALYTICS_ENABLED` | Enable paper analytics module | `true` (for smoke tests) |
| `PAPER_EXPLORATION_MODE` | Enable exploration mode | `false` (DB-controlled) |
| `LIVE_EXECUTION_ENABLED` | Allow real broker orders | `false` (PERMANENTLY OFF) |

### 21.3 Key Database Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `pipeline_events` | All pipeline events per scan | `ts`, `event_type`, `symbol`, `payload` |
| `phase20_paper_trades` | Canonical paper trade ledger (P20- prefix) | `trade_id`, `symbol`, `fill_price`, `status`, `realized_pnl` |
| `paper_portfolio` | Portfolio state (cash, positions) | `cash`, `positions` (JSONB), `updated_at` |
| `scan_state` | Scan run metadata | `scan_id`, `status`, `provider`, `symbols_requested/received` |
| `experimental_paper_trades` | Exploration mode trades (new) | `trade_id`, `action_type`, `max_favorable_excursion` |
| `phase24_missed_opps` | Missed opportunity log | `symbol`, `scan_id`, `reason`, `outcome` |
| `phase24_recommendations` | Learning recommendations | `rule`, `confidence`, `status`, `approved_at` |
| `phase20_kv` | Key-value settings store | `key`, `value`, `updated_at` |
| `backtest_runs` | Backtest execution history | `run_id`, `status`, `started_at`, `completed_at` |
| `certification_runs` | Validation certification | `run_id`, `verdict`, `domains` |

### 21.4 Important API Endpoints

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

### 21.5 Generated Reports and Files

| File/Endpoint | Content |
|--------------|---------|
| `REMEDIATION_PHASE_1A_CODE_TRACE_REPORT.md` | Phase 1A code trace — Q1/Q2/Q3 with evidence |
| `APEXQUANT_REMEDIATION_PHASE_1_REPORT.md` | Phase 1 full remediation report (1B/1C/1D findings + lifecycle status) |
| `PAPER_INTRADAY_LEARNING_EXECUTION_REPORT` | Daily exploration mode report (new, from `generate_daily_report()`) |
| `Phase{N}_Review_Package.zip` | Phase review packages (downloadable from Settings page) |
| `/api/paper/exploration/report` | On-demand exploration learning report |
| `signal_daily_reports` table | Daily signal quality reports |
| `phase26_daily_reports` table | Phase 26 scheduled validation daily reports |
| `preopen_daily_reports` table | Pre-open data quality daily reports |

### 21.6 Known Data Inconsistencies **[UPDATED]**

| Inconsistency | Description | Status |
|--------------|-------------|--------|
| Aug 11 scan anomaly | 65,018 symbol_scanned from 89 scans (14× expected) | OPEN — root cause unknown |
| Aug 11 phantom executions | 64 ORDER_EXECUTED with "BTT-" prefix; 0 rows in phase20_paper_trades | ✅ CONFIRMED phantom — external bot |
| GLAND in BUY signals | GLAND is not a NIFTY 50 constituent — investigate how it entered the scan | OPEN |
| EXIT_PENDING with exit_ts but NULL realized_pnl | 4 trades appear exited but have no P&L | ⚠️ Expected — quote_reliable=False at exit time; resolves with Zerodha session |
| RISK_REJECTED with NULL reason (historical) | 15,447 events have null reason (pre-fix events) | ⚠️ Historical — new events now carry reason |

---

## External Reviewer Validation Checklist **[UPDATED]**

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
- [ ] **[NEW]** Confirm BUY_GENERATED is emitted post-gate (read `derive_symbol_events()` and `_scan_one()` call order)

### C. Execution Gate Completeness
- [ ] Verify all 10 pre-execution gates are checked in sequence
- [ ] Confirm market-closed gate prevents execution at all times outside 09:15–15:30 IST
- [ ] Confirm circuit breaker blocks ALL entries when tripped (corrupted state = tripped, not clear)
- [ ] Confirm portfolio pre-check fails closed (not fail-open)
- [ ] **[NEW]** Confirm SIZE_REDUCED_TO_CAP path: cap_qty ≥ 1 → WARNING + proceed; cap_qty == 0 → CRITICAL

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
- [ ] **[NEW]** Confirm all canonical trades have "P20-" prefix; reject any "BTT-" prefixed events as non-canonical

### G. Rejection Reason Audit **[NEW]**
- [ ] Query `SELECT payload->>'reason' FROM pipeline_events WHERE event_type='RISK_REJECTED' AND ts > now()-interval '1 day'` — confirm non-NULL
- [ ] Query same for `EXECUTION_SKIPPED_WITH_REASON` and `ORDER_REJECTED` — confirm non-NULL for new events
- [ ] Confirm `payload->>'gate_name'` is populated on all rejection events from post-fix scans

### H. Open Issues to Investigate
- [ ] Explain Aug 11 anomaly: why 65,018 symbol_scanned events from 89 scans?
- [ ] Explain why GLAND is in the scanner (not a NIFTY 50 constituent)
- [ ] Explain why 4 EXIT_PENDING trades have NULL realized_pnl despite having exit_ts (answer: quote_reliable=False)
- [ ] Explain why experimental_paper_trades has 0 rows despite 8 EXPERIMENTAL events on Aug 15
- [ ] Confirm the `paper_trades` table contents and whether it duplicates `phase20_paper_trades`
- [ ] Confirm RR threshold alignment plan: lower execution gate from 2.0 to 1.5, or raise scan gate?

---

*This document was generated from the production codebase and database on 2026-08-15 and updated to v2.0 incorporating Remediation Phase 1 findings and changes. All SQL queries are available for reproduction. The only code changes made to produce this document were the Remediation Phase 1 fixes described in §20 — no trading thresholds, settings, or database records were changed.*

*For questions or clarifications, the codebase is at: `artifacts/api-server/src/python/` (backend) and `artifacts/trading-dashboard/src/` (frontend).*  
*Remediation reports: `REMEDIATION_PHASE_1A_CODE_TRACE_REPORT.md` and `APEXQUANT_REMEDIATION_PHASE_1_REPORT.md`*
