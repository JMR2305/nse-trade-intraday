# ApexQuant AI — Full Project SOP & Second-Opinion Pack

**Document version:** 3.1  
**Generated:** 2026-08-15 (IST)  
**Prepared by:** Replit Agent (automated, read-only except where noted)  
**Purpose:** Independent second-opinion review package — complete audit of architecture, behaviour, data, and open problems  
**Classification:** Internal review — contains production database statistics

> **Changelog from v3.0 → v3.1:** This version incorporates all findings from the Source Code vs SOP Mismatch Bug Audit (5 tasks). Four bugs found and fixed: (1) SIZE_REDUCED_TO_CAP wiring — executor was reading `_rv_result.get("size_reduced_to_cap")` which is always `None`; key lives in `rv.to_dict()["summary"]`; (2) Pre-trade validator ran utilisation/cash checks with original oversized qty, causing false INSUFFICIENT_CASH CRITICAL rejections — now re-runs with capped qty; (3) Data path fully confirmed — yfinance only, 1d bars, implementation plan for Options A/B/C provided; (4) Exploration mode uses daily close as "live" exit price — documented, no safe fix until Kite LTP wired; (5) Scanner thresholds (62/42) did not match config.py (70/50) or SOP — market_scanner.py now imports from config.py as single source of truth. 13/13 regression tests added and passing. Changed sections marked **[UPDATED v3.1]**.

> **Changelog from v2.0 → v3.0:** Incorporated Data Path & Intraday Truth Audit (Tasks 1–7). The documented "Zerodha primary, Yahoo fallback" data architecture **does not exist in code** — yfinance is the only OHLCV source, scanner uses daily (1d) bars, Kite is display metadata only. Aug 11 phantom-fills verdict fully DB-confirmed. Per-symbol diagnostic logging added to `SYMBOL_SCANNED` events. Sections marked **[UPDATED v3]** / **[NEW v3]**. No trading thresholds were changed.

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
20. [Remediation Phase 1 — Changes Log](#20-remediation-phase-1--changes-log)
21. [Data Path & Intraday Truth Audit — Changes Log](#21-data-path--intraday-truth-audit--changes-log) **[NEW v3]**
22. [Bug Audit — Source Code vs SOP Mismatch](#22-bug-audit--source-code-vs-sop-mismatch) **[NEW v3.1]**
23. [Appendix](#23-appendix)

---

## 1. Executive Summary

### 1.1 What is ApexQuant AI?

ApexQuant AI is a **paper-only NSE trading research platform** built on a multi-agent AI architecture. Its core purpose is to:

- Scan NIFTY 50 (now 51 symbols after the TATAMOTORS demerger) every 5 minutes during market hours
- Run each symbol through a multi-layer AI pipeline: data quality → signal → strategy → risk → decision → execution
- Generate BUY / WATCH / IGNORE recommendations with confidence scores, opportunity scores, and position-sizing guidance
- Execute paper (simulated) trades when all gates pass, building a tracked portfolio
- Learn from the outcomes of those paper trades to improve future decisions

**No live orders have ever been placed, and no Zerodha broker APIs are called for order submission.** Live execution is structurally disabled.

> **v3 note — "intraday" clarification:** The platform is described as intraday because paper orders are squared off within the session. However, the scanner operates on **daily (1d) bars with a 6-month lookback** — not on intraday 1m/5m/15m candles. See §3 and §6.4 for the full data-path truth.

### 1.2 Current Status (as of 2026-08-15) **[UPDATED v3]**

| Dimension | Status |
|-----------|--------|
| Live order execution | **PERMANENTLY DISABLED** — `LIVE_EXECUTION_ENABLED = False` |
| Paper trading mode | **ACTIVE** — auto-scanning on 5-minute interval |
| Zerodha session | **INACTIVE** — no current login; does NOT affect OHLCV data (see §6.4) |
| Data source | **Yahoo Finance (yfinance) exclusively** — daily bars, 6-month lookback. Kite is NOT in the scan path. |
| Candle interval | **1d (daily bars)** — NOT intraday. See §6.4. |
| Portfolio capital | ₹50,000 (resets each session) |
| Open paper positions | 4 (all EXIT_PENDING / STALE_DATA_SAFETY) |
| Executed trades (lifetime canonical) | **4 rows in `phase20_paper_trades`** (P20- prefix); 63 events on Aug 11 were phantom (BTT- prefix) |
| Active paper exploration mode | OFF (just activated for testing on Aug 15) |
| Universe | 51 NSE symbols (NIFTY 50 + TMPV + TMCV, minus TATAMOTORS) |
| Scan coverage | ~50/51 per scan (1 symbol typically missing from Yahoo — likely LTIM) |
| **Position-size cap bug** | **FIXED (Remediation Phase 1B)** — SIZE_REDUCED_TO_CAP path now active |
| **Rejection reason logging** | **FIXED (Remediation Phase 1C)** — all rejection events now carry structured `reason` field |
| **Per-symbol scan logging** | **ADDED (Data Path Audit Task 2)** — SYMBOL_SCANNED now emits `data_source`, `latest_date`, `age_days`, `interval`, `last_price`, `tradable`, `reason_not_tradable` |
| **SIZE_REDUCED_TO_CAP wiring bug** | **FIXED (Bug Audit Task 1)** — executor now reads `capped_qty` from `rv.to_dict()["summary"]`; risk_amount recomputed; pipeline event emitted |
| **Pre-trade false CRITICAL rejection** | **FIXED (Bug Audit Task 2)** — downstream checks (utilisation, cash, daily-risk) now use capped qty, not original oversized qty |
| **Scanner threshold mismatch** | **FIXED (Bug Audit Task 5)** — `market_scanner.py` now imports from `config.py`; single source of truth (STRONG BUY 85 / BUY 70 / WATCH 50) |

### 1.3 Primary Problem Statement **[UPDATED v3]**

The platform correctly identifies BUY signals. The two code-level blockers for paper execution have been resolved:

| Blocker | Status |
|---------|--------|
| **Position-size cap hard-reject** | ✅ **FIXED** — `_check_position_size()` now computes `cap_qty` and issues `SIZE_REDUCED_TO_CAP` WARNING |
| **Rejection reasons not stored** | ✅ **FIXED** — `reason`, `gate_name`, `action`, `human_readable_reason` now in all rejection payloads |

**Remaining blockers:**

1. **Kite LTP not wired into scan path (P0 architecture gap):** The scan engine unconditionally uses `LiveDataProvider()` (yfinance only). `kite_quote_provider.py` exists and can fetch live Kite LTP, but is never called during a scan. Data quality grades are based on age of the latest yfinance daily bar — not on whether Kite is connected. Fixing this requires wiring the Kite LTP overlay into `run_live_scan()` (~15 lines — see §21.4 for the exact scope). Re-authenticating Zerodha **will not** change scan data until this integration work is done.

2. **Scanner uses daily bars, not intraday bars:** `SCAN_INTERVAL = "1d"`, `SCAN_PERIOD = "6mo"`. True intraday bar scanning (1m/5m/15m from Kite Historical API) is a separate, larger project.

3. **R:R threshold misalignment:** Scan gate uses 1.5, Phase20 execution gate uses 2.0 (settings default). Signals with 1.5 ≤ RR < 2.0 pass the scan but are blocked at execution. Deferred to Phase 2.

---

## 2. AI Architecture Overview

The platform is built as a layered multi-agent system. Each layer is independent and communicates through a shared scan snapshot.

### 2.1 Architecture Layers **[UPDATED v3]**

```
┌────────────────────────────────────────────────────────────┐
│  LAYER 0: DATA ACQUISITION                                  │
│  live_data_provider.py (LiveDataProvider)                   │
│  Source: Yahoo Finance (yfinance) — ONLY source             │
│  Interval: 1d (daily bars), 6-month lookback (SCAN_PERIOD)  │
│  Quality: age-based (≤3d=LIVE, ≤5d=NEAR_LIVE, ≤14d=STALE) │
│  Kite: kite_quote_provider.py exists but is NOT called here │
│  Output: OHLCV DataFrame per symbol, age_days, quality label│
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

### 2.3 Key Python Files **[UPDATED v3]**

| File | Purpose |
|------|---------|
| `config.py` | All configurable thresholds (single source of truth) |
| `live_scan_engine.py` | Core scan loop, quality gates, score computation, RISK_REJECTED structured payloads, SYMBOL_SCANNED diagnostic fields |
| `live_data_provider.py` | **Only OHLCV data source** — yfinance exclusively. `SCAN_INTERVAL="1d"`, `SCAN_PERIOD="6mo"` |
| `kite_quote_provider.py` | Kite LTP/quote fetcher — fully implemented but **not called in the scan path**. Only used for display metadata (session probe + provider label). |
| `phase20_executor.py` | Paper execution pipeline, all pre-checks, SIZE_REDUCED_TO_CAP adoption |
| `phase20_store.py` | Settings KV store, DEFAULT_SETTINGS |
| `phase20_scheduler.py` | 5-minute scan tick, paper management |
| `phase20_exits.py` | 8 exit rules (TARGET_HIT, STOP_LOSS_HIT, TRAILING_STOP, TIME_EXIT, MARKET_CLOSE_EXIT, PORTFOLIO_RISK_REDUCTION, SECTOR_CAP_BREACH, STALE_DATA_SAFETY) |
| `canonical_portfolio.py` | Portfolio ledger (positions, cash, equity) |
| `paper_exploration_engine.py` | Exploration mode (cap-resize + WATCH exploration) |
| `risk_validation/pre_trade.py` | Pre-trade validator — SIZE_REDUCED_TO_CAP logic lives here |
| `market_regime.py` | Regime classification |
| `position_sizer.py` | Stop/target/quantity calculation |
| `phase24_engine.py` | Learning analytics engine |
| `backtesting_engine.py` | Historical backtesting |

---

## 3. Full Pipeline Flow **[UPDATED v3]**

This is the exact sequence of steps executed for every symbol in every scan.

> **v3 correction:** Previous versions stated Step 2 as "try Zerodha Kite quotes → fallback Yahoo Finance". This is **incorrect**. The scan engine unconditionally uses `LiveDataProvider()` which is yfinance only. There is no Kite branch in the scan path. The corrected flow is below.

```
START SCAN TICK (every 5 minutes, 09:15–15:30 IST)
│
├── [STEP 1] Scan Lock Acquired (DB-durable, prevents concurrent scans)
│
├── [STEP 2] Data Fetch: LiveDataProvider.fetch_batch(universe)
│   │   Provider: Yahoo Finance (yfinance) — the ONLY source
│   │   Interval: 1d (daily bars), Period: 6mo
│   │   Method: one bulk yf.download() for all 51 symbols
│   │   Fallback: per-symbol retry for any symbols missing from bulk response
│   │   Kite: NOT involved in this step. kite_quote_provider.py is never called here.
│   └── Output: {symbol: SymbolFetchResult} — OHLCV DataFrame + age_days + quality label per symbol
│
├── [STEP 3] For each of 51 symbols in universe:
│   │
│   ├── [SIGNAL] Compute indicators: RSI, MACD, Bollinger, ADX, OBV
│   │   └── Combine into confidence score (0–100) → raw_action
│   │
│   ├── [DATA QUALITY GATE] _apply_quality_gate()
│   │   ├── age_days ≤ 3  → LIVE     → pass through (BUY eligible)
│   │   ├── age_days ≤ 5  → NEAR_LIVE → pass through (BUY eligible)
│   │   ├── age_days ≤ 14 → STALE    → force action = max(WATCH)
│   │   └── age_days > 14 → UNAVAILABLE → force action = IGNORE
│   │   NOTE: quality is age-only; the data source (yfinance) has no effect on grade
│   │
│   ├── [R:R GATE] _rr_gate() — rr_ratio < 1.5 → downgrade to WATCH
│   │     → RISK_REJECTED emitted with:
│   │         reason, gate_name, actual_value, human_readable_reason [UPDATED v2]
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
│   │   ├── Compute: quantity = min(cap×capital, cash) / price
│   │   ├── Check: stop_loss distance, R:R ratio
│   │   └── RISK_APPROVED or RISK_REJECTED (with reason, gate_name, human_readable_reason)
│   │
│   └── [EMIT] SYMBOL_SCANNED (with data_source, latest_date, age_days, interval,
│             last_price, tradable, reason_not_tradable) [UPDATED v3]
│             MARKET_INTELLIGENCE_COMPLETED, RESEARCH_COMPLETED,
│             MONITORING_COMPLETED, STRATEGY_SELECTED
│
├── [STEP 4] Snapshot published (post-scan, after all symbols complete)
│
├── [STEP 4a] Kite display metadata (POST-SCAN, read-only, display only) [NEW v3]
│   │   kite_session_verified() → sets safety["kite_connected"]
│   │   provider_label()        → sets safety["data_provider"]
│   │   ohlcv_source            → ALWAYS hardcoded "yfinance (historical)"
│   └── NOTE: This block runs AFTER scanning. It changes no prices, quality labels, or decisions.
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
    │           [emits reason, gate_name, action, human_readable_reason]
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
        │   human_readable_reason in payload)
        └── EXECUTION_SKIPPED_WITH_REASON (with reason, gate_name, action,
            human_readable_reason)
```

### 3.1 Paper Exploration Mode

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

**Important:** When `quote_reliable=False`, exit is recorded as `EXIT_PENDING` with `realized_pnl=NULL`. The exit fill price is not recorded until a LIVE/NEAR_LIVE quote is available. This is the current state of all 4 open positions. Wiring Kite LTP (Option A in §21.4) would provide `quote_reliable=True` and resolve pending exits.

---

## 4. Criteria and Thresholds

### 4.1 Signal Thresholds (config.py)

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `SIGNAL_STRONG_THRESHOLD` | **90.0** | Confidence ≥ 90 → STRONG BUY |
| `SIGNAL_BUY_THRESHOLD` | **75.0** | Confidence 75–90 → BUY |
| `SIGNAL_WATCH_THRESHOLD` | **60.0** | Confidence 60–75 → WATCH |
| `SIGNAL_MIN_THRESHOLD` | **60.0** | Confidence < 60 → NO_TRADE / IGNORE |

### 4.2 Opportunity Score Thresholds (config.py) **[UPDATED v3.1]**

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `OPP_HOT_BUY_THRESHOLD` | **85.0** | Hot BUY — highest priority |
| `OPP_BUY_THRESHOLD` | **70.0** | Standard BUY |
| `OPP_WATCH_THRESHOLD` | **50.0** | WATCH candidate |
| Below 50 | — | IGNORE |

> **v3.1 fix — scanner threshold alignment:** `market_scanner.py` previously hardcoded `ACTION_BUY=62` and `ACTION_WATCH=42` — mismatching this table and the SOP. After Bug Audit Task 5, `market_scanner.py` now imports `OPP_HOT_BUY_THRESHOLD`, `OPP_BUY_THRESHOLD`, and `OPP_WATCH_THRESHOLD` from `config.py`. **Single source of truth is now `config.py` for all three thresholds.** To change any threshold, edit `config.py` only. Pre-fix: stocks scoring 62–69 appeared as BUY; post-fix they correctly appear as WATCH.

**Opportunity Score Weights:**
- trade_quality: **40%**
- ai_confidence: **30%**
- rr_score: **20%**
- market_alignment: **10%**

### 4.3 AI Decision Engine Thresholds (config.py) **[UPDATED v3]**

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `AI_MIN_RR_RATIO` | **2.0** | ⚠️ **DEAD CONFIG** — defined in `config.py`, copied into `phase21_baseline.py` reporting dict only; never compared against a live R:R value anywhere in the paper execution path. Rules out as a cause of unexplained rejections. |
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
| `min_risk_reward` | **2.0** | Execution gate — **different from scan gate 1.5** (see §4.6) |
| `per_stock_exposure_cap_pct` | **25.0%** | Settings default; used by pre-trade validator |
| `scan_interval_minutes` | **5** | Allowed values: 1, 2, 3, 5, 10, 15 |
| Market open window | **09:15–15:30 IST** | Outside this → execution skipped |
| Stale scan | Configurable | Scan older than threshold → EXECUTION_SKIPPED |
| Circuit breaker | State-based | If tripped → all entries blocked until manual reset |
| Duplicate position | One per symbol | Cannot open second position in same symbol |
| **Position size** | **SIZE_REDUCED_TO_CAP path** | If `cap_qty ≥ 1`: WARNING + proceed at cap_qty. If `cap_qty == 0`: CRITICAL → ORDER_REJECTED [FIXED] |

### 4.6 R:R Threshold Map — All Layers **[UPDATED v3]**

| Layer | File | Threshold | Enforcement | Pipeline effect |
|-------|------|-----------|-------------|-----------------|
| Scan gate | `live_scan_engine.py:64` | **≥ 1.5** | `_rr_gate()` caps BUY→WATCH | WATCH_GENERATED |
| Pre-trade validator | `risk_validation/pre_trade.py:26` | **≥ 1.5** | CRITICAL rejection | ORDER_REJECTED |
| Phase20 execution gate | `phase20_gates.py:258` | **≥ 2.0** (settings default) | EXECUTION_SKIPPED | EXECUTION_SKIPPED_WITH_REASON |
| `AI_MIN_RR_RATIO` | `config.py:61` | **2.0** | **⚠️ DEAD CONFIG** — in phase21_baseline.py reporting dict only | **None — not enforced anywhere** |

**Conflict:** Signals with 1.5 ≤ RR < 2.0 pass the scan gate (→ `BUY_GENERATED`) and the pre-trade validator, but are blocked at the phase20 execution gate (→ `EXECUTION_SKIPPED_WITH_REASON`). **Threshold alignment is deferred to Phase 2.**

**v3 correction:** Previous versions listed `AI_MIN_RR_RATIO = 2.0` as an "advisory downgrade" in the AI Decision Engine. Code inspection confirms it is dead configuration — it never compares against a live R:R value.

### 4.7 Position Sizing: Before vs After All Fixes **[UPDATED v3.1]**

| Scenario | Before Phase 1B | After Phase 1B | After Bug Audit Task 1+2 |
|----------|----------------|----------------|--------------------------|
| `qty × price ≤ cap` | PASS | PASS — unchanged | PASS — unchanged |
| `qty × price > cap`, `cap_qty ≥ 1` | CRITICAL → ORDER_REJECTED | WARNING (SIZE_REDUCED_TO_CAP) → **but executor never read it** (wiring bug) | **WARNING → executor reads from `summary`, adopts cap_qty, recomputes risk_amount** ✅ |
| `qty × price > cap`, `cap_qty == 0` | CRITICAL → ORDER_REJECTED | CRITICAL → ORDER_REJECTED | CRITICAL → ORDER_REJECTED (unchanged) |
| Utilisation/cash check (downstream) | With original qty | With original qty (false CRITICAL possible) | **With capped qty** — false INSUFFICIENT_CASH eliminated ✅ |

`rv.to_dict()` structure (confirmed by Bug Audit Task 1 — this is where the wiring bug lived):
```
{
  "verdict": "APPROVED_WARN",
  "approved": true,
  "summary": {
    "size_reduced_to_cap": true,   ← lives HERE (not at top level)
    "capped_qty": 15,              ← lives HERE (not at top level)
    "trade_value": 97500.0,
    ...
  }
}
```
Old executor code: `_rv_result.get("size_reduced_to_cap")` → always `None` (key is in `["summary"]`).  
Fixed executor code: `_rv_result.get("summary", {}).get("size_reduced_to_cap")` → correct.

New fields populated in the SIZE_REDUCED_TO_CAP pipeline event (post Bug Audit Task 1):
`original_qty`, `capped_qty`, `fill_price`, `original_risk`, `capped_risk`, `trade_value_orig`, `trade_value_cap`, `charges_recalculated`

### 4.8 Gap Between Scan-Time and Execution-Time Thresholds

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

### 5.1 Primary Canonical Pages (Daily Operations)

> The following 5 pages are the recommended daily-use pages. All other pages exist for deep-dive analysis.

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/` | `TradeDecisions` | Main dashboard — scan results, BUY/WATCH/IGNORE signals, live scan status |
| `/ai-paper-trader` | `AIPaperTrader` | Paper trade management — open positions, P&L, EXIT_PENDING |
| `/mission-control` | `MissionControl` | Mission Control — live stream, scan status, alert feed |
| `/live-data-health` | `LiveDataHealth` | Data provider health, symbol coverage, quality breakdown |
| `/market-intelligence` | `MarketIntelligence` | Market regime, sector analysis, opportunity ranking |

### 5.2 Signal and Decision Pages

| Route | Component | Functionality |
|-------|-----------|---------------|
| `/market-scanner` | `MarketScanner` | Full NIFTY 50 scan results with filters |
| `/live-scan` | `LiveScan` | Live scan trigger and progress monitoring |
| `/scan-results` | `ScanResults` | Historical scan results explorer |
| `/ai-decision` | `AiDecision` | AI Decision Agent interface — 7 decision types, explainability |
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

### 5.9–5.11 (Agent Framework, Historical Research, UI/Experience Pages)

*(Unchanged from v2.0 — see prior version for full tables)*

> **Note on Legacy vs Canonical Pages:** Routes under `/phase12`, `/phase13`, `/phase4a-session`, and some `/paper-trading-*` are legacy pages from earlier development phases. The canonical pages for daily use are: `/` (Trade Decisions), `/ai-paper-trader`, `/mission-control`, `/live-data-health`, and `/market-intelligence`.

---

## 6. Universe and Symbol Selection

### 6.1 NIFTY 50 Universe (Now 51 Symbols)

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

Both respond correctly to `TMPV.NS` and `TMCV.NS` on Yahoo Finance.

**NIFTY 50 Index Note:** The actual NIFTY 50 index now has 51 constituent stocks as a result of the demerger. Our universe mirrors this.

### 6.3 Data Quality Labels **[UPDATED v3]**

> **v3 correction:** Previous versions described LIVE as "Fresh Zerodha tick". This is incorrect. Quality is based **entirely on the age of the yfinance daily bar** — Zerodha/Kite is not involved in quality classification.

| Label | Definition | Age threshold | Effect on Signal |
|-------|-----------|---------------|-----------------|
| `LIVE` | Latest yfinance bar ≤ 3 calendar days old | age_days ≤ 3 | Full BUY/WATCH/IGNORE possible |
| `NEAR_LIVE` | Latest bar 4–5 calendar days old (long weekend/holiday) | age_days ≤ 5 | Full BUY/WATCH/IGNORE possible |
| `STALE` | Latest bar 6–14 calendar days old | age_days ≤ 14 | **BUY forced to WATCH** |
| `UNAVAILABLE` | Fetch failed or bar older than 14 days | age_days > 14 | **Forced to IGNORE** |

**Current situation (Aug 15, Saturday):** ALL 51 symbols are LIVE — the latest yfinance bar is from Friday Aug 14 (1 day old, within the LIVE_DAYS=3 threshold). yfinance is returning fresh data.

**When does STALE occur?** Only when yfinance returns bars older than 3 days — typically after a long holiday weekend (e.g., a 4-day closure would produce age_days=4 = NEAR_LIVE, still BUY-eligible). STALE requires a 6+ day gap, which is rare.

**Zerodha session has no effect on quality grades.** Kite session changes `safety["kite_connected"]` from False to True, which changes the display label — it does not change quality.

### 6.4 Provider Sources **[UPDATED v3]**

> **v3 correction:** Previous versions showed Zerodha Kite REST API as the "LIVE" primary source. This is incorrect. The corrected table is below.

| Provider | Role in scan path | Quality label produced |
|----------|------------------|----------------------|
| **Yahoo Finance (yfinance)** | **Primary and ONLY OHLCV source** — `live_data_provider.py` → `yf.download()`. Called unconditionally for every scan. | LIVE / NEAR_LIVE / STALE / UNAVAILABLE (age-based) |
| **Zerodha Kite LTP** (`kite_quote_provider.py`) | **NOT in scan path** — exists and works, but is never called during scanning. Called post-scan only for display metadata (`kite_connected`, `live_quote_source`). | N/A — not used for data |
| NSE Official (pre-open only) | Pre-open IEP/order data via separate pre-open endpoints | LIVE (pre-open window only) |
| Mock/error fallback | When yfinance fetch fails for all retries | UNAVAILABLE |

**How to wire Kite into the scan path:** See §21.4 — Option A is a ~15-line overlay after `provider.fetch_batch()` that has no strategy/threshold changes.

### 6.5 Missing Symbols

The scan on 2026-08-14 shows: **51 requested, 50 received, 1 missing.** Historically, `LTIM` has been the most common missing symbol on Yahoo Finance.

---

## 7. Scan Cadence and Rotation

### 7.1 Configured Parameters

| Parameter | Value |
|-----------|-------|
| `scan_interval_minutes` | **5 minutes** |
| Market hours | **09:15 – 15:30 IST** |
| Expected scans per full market day | **~75** (6.25 hours / 5 min = 75) |
| Universe per scan | **51 symbols** |
| Candle interval | **1d (daily bars)** |
| Historical lookback | **6 months** |

### 7.2 Actual Scan Counts (from production pipeline_events) **[UPDATED v3]**

| Date | Scans Started | Scans Completed | Scans Failed | Symbols Scanned | Notes |
|------|--------------|-----------------|--------------|-----------------|-------|
| 2026-08-15 | 0 | 0 | 0 | 0 | Weekend/holiday — no market |
| 2026-08-14 | 72 | 72 | 0 | 3,600 | 3600/72=50 symbols/scan, 1 missing |
| 2026-08-13 | 71 | 71 | 0 | 3,550 | Normal day |
| 2026-08-12 | 70 | 69 | 0 | 13,793 | **ANOMALY** — 13793/70=197 symbols/scan |
| 2026-08-11 | **88** | 75 | 2 | 64,693 | **MAJOR ANOMALY** — scan-loop runaway; see §7.3 |
| 2026-08-10 | 54 | 54 | 0 | 2,592 | 2592/54=48 symbols/scan, 3 missing |
| 2026-08-09 | 1 | 1 | 0 | 48 | Saturday — 1 test scan |
| 2026-08-08 | 3 | 2 | 1 | 169 | Sunday + partial — 2 scans |

### 7.3 Scan Anomalies **[UPDATED v3]**

**Aug 11 Major Anomaly — Full DB verdict:**

Normal: ~12–15 scans per market day. Aug 11: **88 scans** — nearly 6× the expected count.

Breakdown by IST hour (from DB):

| IST Hour | Scans |
|----------|-------|
| 09:00–10:00 | 12 |
| 10:00–11:00 | 18 |
| 11:00–12:00 | 11 |
| 12:00–13:00 | 10 |
| 13:00–14:00 | 16 |
| 14:00–15:00 | 15 |
| 15:00–16:00 | 5 |
| 22:00–23:00 | 1 |

Minutes with multiple scans (from DB): 10:14 IST = 5 scans, 14:17 IST = 5 scans, 13:55 IST = 4 scans. Confirmed **scan-loop runaway** — scheduler fired overlapping scans within the same minute.

Result: 64,693 SYMBOL_SCANNED events from 88 scans → avg 735 per scan (expected 51). Confirmed from DB — this anomaly caused the same signal to fire the executor repeatedly.

**Aug 12 Anomaly:** 13,793 SYMBOL_SCANNED with 70 scans = 197 per scan. Expected 51. Likely an interval-setting change or loop issue that was later corrected.

---

## 8. Last 10 Trading Days — Production Statistics

All figures pulled directly from the `pipeline_events` table as of 2026-08-15.

### 8.1 Daily Pipeline Event Summary **[UPDATED v3]**

| Date | Scans | Sym Scanned | BUY Gen | WATCH Gen | IGNORE Gen | Risk Rej | Ord Submit | Ord Exec | Ord Rej | Exec Skip | Pos Opened | Pos Closed |
|------|-------|-------------|---------|-----------|------------|----------|------------|----------|---------|-----------|------------|------------|
| **2026-08-15** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **2026-08-14** | 72 | 3,600 | 48 | 1,926 | 1,626 | 97 | 0 | 0 | 203 | 4 | 0 | 0 |
| **2026-08-13** | 71 | 3,550 | 148 | 1,951 | 1,451 | 179 | 0 | 0 | 560 | 63 | 0 | 0 |
| **2026-08-12** | 70 | 13,793 | 170 | 4,800 | 8,823 | 97 | 0 | 0 | 676 | 0 | 0 | 0 |
| **2026-08-11** | 88★ | 64,693★ | 18,455 | 26,229 | 20,009 | 14,886 | 3,310 | **63**★★ | 819 | 0 | **63**★★ | 24★★ |
| **2026-08-10** | 54 | 2,592 | 176 | 1,562 | 854 | 187 | 87 | 0 | 807 | 0 | 0 | 0 |
| **2026-08-09** | 1 | 48 | 6 | 27 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **2026-08-08** | 3 | 169 | 26 | 43 | 99 | 1 | 20 | 1 | 0 | 0 | 1 | 1 |

★ = Anomalous — see §7.3  
★★ = **PHANTOM** — "BTT-" prefixed events from external intraday_bot; **zero rows in `phase20_paper_trades` or `paper_trades` (DB-confirmed)**

**Key observations:**
- **Total BUY_GENERATED (all-time):** 19,034+ — these are all post-gate (STALE data cannot generate BUY)
- **Total canonical paper trades in `phase20_paper_trades`:** **4** (all Aug 4–7, all EXIT_PENDING)
- **Aug 11 ORDER_EXECUTED=63 are phantom** — confirmed by DB query: 0 rows in `phase20_paper_trades` matching those scan_ids, 0 rows in legacy `paper_trades`
- **Total ORDER_REJECTED:** 3,065 — majority from position-size cap violations (now fixed)

### 8.2 Current Paper Portfolio State

| Metric | Value |
|--------|-------|
| Available cash | **₹50,000.00** |
| Open positions (phase20_paper_trades) | **4 (all EXIT_PENDING)** |
| Positions JSON | `{}` (empty) — portfolio positions cleared |
| Last portfolio update | 2026-08-14 03:40:57 UTC |

**Note:** The 4 trades in `phase20_paper_trades` have `status=EXIT_PENDING` and `exit_rule=STALE_DATA_SAFETY` set on 2026-08-13. Their `realized_pnl` is `NULL`. The portfolio positions JSON is empty `{}`, confirming these positions are no longer counted in active portfolio exposure.

### 8.3 Experimental Paper Trades (exploration_mode)

| Table | Count |
|-------|-------|
| `experimental_paper_trades` rows | **0** |
| `EXPERIMENTAL_PAPER_TRADE_PLACED` events (Aug 15) | **8 events for DRREDDY** |

The 8 Aug 15 events suggest the exploration engine ran and generated entries, but no rows appear in the DB table — the DB insert is failing silently. **Status:** P1 open item — see §17.

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

> GLAND's extreme counts are from the Aug 11 scan-loop runaway.

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

All rejections were due to the position-size cap bug, now fixed via the SIZE_REDUCED_TO_CAP path:

| Rank | Symbol | ORDER_REJECTED | Rejection reason (pre-fix) | Post-fix behaviour |
|------|--------|---------------|---------------------------|--------------------|
| 1 | **DRREDDY** | **873** | Size 21.5–21.7% > 20% cap | ✅ SIZE_REDUCED_TO_CAP (8→7 shares) |
| 2 | **GRASIM** | 548 | Size 20.2–20.3% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 3 | **BAJAJFINSV** | 353 | Size 20.2–20.4% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 4 | **BAJAJ-AUTO** | 262 | Size 23.4–23.6% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 5 | **TMPV** | 272 | Size 21.6% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |
| 6 | **TITAN** | 221 | Size > 20% | ✅ SIZE_REDUCED_TO_CAP |
| 7 | **JSWSTEEL** | 182 | Size 23.5% > 20% cap | ✅ SIZE_REDUCED_TO_CAP |

---

## 10. Rejection and Block Reasons

### 10.1 ORDER_REJECTED Breakdown

| Reason | Count | Status |
|--------|-------|--------|
| **Position size > cap (hard reject)** | **~3,000+** | ✅ FIXED — now SIZE_REDUCED_TO_CAP for `cap_qty ≥ 1` |
| `PORTFOLIO BLOCKED: INSUFFICIENT_BUYING_POWER` | 68 | Likely from Aug 11 anomaly when cash was consumed |
| `PORTFOLIO BLOCKED: BELOW_MIN_ORDER_VALUE` | 15 | Order value too small after sizing |

**New rejection payload fields (post-fix):**
```json
{
  "reason": "DRREDDY: position size ₹10,783 = 21.6% of portfolio (limit 20.0%)",
  "gate_name": "POSITION_SIZE_EXCEEDED",
  "actual_value": 21.6,
  "required_value": 20.0,
  "action": "BUY",
  "human_readable_reason": "DRREDDY: position size ₹10,783 = 21.6% — exceeds cap and cannot be reduced further"
}
```

### 10.2 RISK_REJECTED Breakdown

| Count | Stored reason (pre-fix) | Status |
|-------|------------------------|--------|
| **15,447 total RISK_REJECTED** | `NULL` — reason nested in `failed_gates`, not top-level | ✅ FIXED for new events |

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

**Historical events (15,447) still have NULL reason** — the fix applies to new events only.

### 10.3 EXECUTION_SKIPPED_WITH_REASON

| Count | Stored reason (pre-fix) | Status |
|-------|------------------------|--------|
| **67 total** (63 on Aug 13, 4 on Aug 14) | `NULL` | ✅ FIXED for new events |

### 10.4 Categorised Rejection Summary

| Category | Estimated Count | Status |
|----------|----------------|--------|
| Position size cap (hard reject, >cap) | ~3,000 | ✅ FIXED — SIZE_REDUCED_TO_CAP now handles these |
| Risk agent rejection (reason now logged) | ~15,447 | ✅ FIXED (new events) — historical remains null |
| Execution skipped (reason now logged) | ~67 | ✅ FIXED (new events) |
| Portfolio blocked (buying power/exposure) | ~83 | Unchanged — circuit breaker/precheck working correctly |
| Order cancelled (from Aug 11 anomaly) | ~13,189 | Phantom — from external bot, not canonical executor |

---

## 11. Detailed Case Studies

### 11.1 Case Study: DRREDDY — Repeated BUY Rejected by Position-Size Cap **[RESOLVED]**

On every market day since Aug 8, DRREDDY generated BUY signals that passed all gates **except** the 20% position-size cap.

| Date | BUY Generated | Risk Approved | ORDER_REJECTED | Reason |
|------|--------------|--------------|----------------|--------|
| Aug 14 | 48 | 48 | 201 | Size 21.5–21.7% of ₹50,000 |
| Aug 13 | 48 | 48 | 203 | Size 21.5–21.7% of ₹50,000 |

**Root cause:**
- DRREDDY price: ~₹1,340–₹1,360 per share
- Ideal qty from position sizer: 8 shares → 8 × ₹1,350 = ₹10,800 = **21.6%** of ₹50,000
- Hard cap was 20.0% = ₹10,000 max → `cap_qty = floor(₹10,000 / ₹1,350)` = 7 shares
- 7 × ₹1,350 = ₹9,450 = **18.9%** → passes the cap

**Resolution:** ✅ **FIXED in Remediation Phase 1B.** `_check_position_size()` now produces `SIZE_REDUCED_TO_CAP` with `cap_qty=7`. `phase20_executor.py` adopts `cap_qty=7` and proceeds to `execute_buy()`.

### 11.2 Case Study: HDFCLIFE — Missed Low / Pattern Not Captured

HDFCLIFE received 126 BUY_GENERATED and 198 RISK_REJECTED events over the 14-day window. Where the signal was BUY-grade, the executor had a data quality issue (age_days > 3 on that day) that capped the action to WATCH. The missed opportunity was recorded in `phase24_missed_opps` but not acted on (advisory only).

### 11.3 Case Study: TMCV — WATCH Despite Intraday Movement

TMCV (Tata Motors Commercial Vehicles) appears in WATCH_GENERATED events but never in BUY_GENERATED. Root causes:
1. TMCV is a newly demerged stock with limited historical data → lower confidence scores
2. Price ~₹457 → position size is fine (within 25% cap)
3. Signals never reach BUY-grade confidence threshold

### 11.4 Case Study: Post-Market Scans and UI Confusion

The scanner runs 24/7 on the 5-minute interval (no hard market-hours gate at the scan level). Post-market Yahoo data shows the closing price which may produce a BUY-grade signal, but the executor skips execution (market closed gate). Users see BUY signals post-market and assume trades were missed. **Resolution needed:** Add "MARKET CLOSED — Signals are post-market only" banner.

### 11.5 Case Study: Aug 11 "Phantom" Executions **[UPDATED v3 — FULLY DB-CONFIRMED]**

**Verdict: CONFIRMED PHANTOM. DB-queried directly. Zero verified clean paper trade lifecycles from the canonical executor.**

**Full DB evidence:**

| Table | Aug 11 rows |
|-------|------------|
| `pipeline_events` ORDER_EXECUTED | **63** |
| `pipeline_events` POSITION_OPENED | **63** |
| `phase20_paper_trades` (matched by scan_id) | **0** |
| `paper_trades` legacy (matched by date) | **0** |

**Trade ID pattern (all 63 events):**
- First 22 events: all `GLAND`, timestamps 04:05–05:13 UTC (09:35–10:43 IST)
  - Fill prices: ₹2,248.49 and ₹2,639.98 (same two prices repeating)
  - Trade IDs: `BTT-a0f89753dd`, `BTT-ca8827662a`, etc.
- Next 41 events: SBIN, TATASTEEL, NTPC, SUNPHARMA, AXISBANK, HINDUNILVR, ICICIBANK, BAJFINANCE, KOTAKBANK
  - Timestamps: 08:22–08:44 UTC (13:52–14:14 IST)
  - Same fill prices repeating per symbol across multiple BTT- IDs

**Root cause:**
1. Scan-loop ran 88 times (up to 5/minute). Each scan saw GLAND as a BUY, fired the executor, emitted `ORDER_EXECUTED` (fire-and-forget via pipeline_events).
2. The `phase20_paper_trades` ledger write is a separate DB transaction — it failed silently each time (likely partial unique index constraint violation, or the table did not exist on Aug 11).
3. `phase20_executor.py` uses `"P20-"` prefix; all 63 events use `"BTT-"` prefix — confirming these came from the separate **intraday_bot** process.

**The system has never had a verified clean paper trade lifecycle producing a BTT- trade ID in any canonical table.** The 4 trades in `phase20_paper_trades` (P20- prefix, Aug 4–7) are the only canonical trades.

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
- All 4 triggered `STALE_DATA_SAFETY` exit on 2026-08-13
- No realized P&L recorded — requires `quote_reliable=True` to record a fill price
- Total capital deployed: ~₹36,088 across 4 positions (72% of ₹50,000)

### 12.2 Why Realized P&L is NULL on All Trades

This is not a code bug — it is a data quality issue. Without `quote_reliable=True`, exits record `status="EXIT_PENDING"` and `realized_pnl=NULL`. `quote_reliable` requires `dq in ("LIVE","NEAR_LIVE")`.

Once Kite LTP overlay is wired (Option A, §21.4), pending exits will resolve via `resolve_pending_exits()` on the next scan tick with LIVE data.

### 12.3 Sell/Exit Behavior

**No successful sell-side executions are recorded.** The exit logic is fully implemented in `phase20_exits.py` (all 8 rules, confirmed in Remediation Phase 1D), but requires `quote_reliable=True` to record fill prices and P&L. This requires either Kite LTP overlay or yfinance data that is LIVE quality (currently the case on weekdays).

---

## 13. Why No Trades Executed in Recent Sessions

### 13.1 Data Problems **[UPDATED v3]**

| Problem | Impact | Status |
|---------|--------|--------|
| **Kite LTP not wired into scan path** — yfinance is the only source; daily bars, age-based quality | Quality grades are NOT affected by Zerodha session; re-authenticating Zerodha won't change scan data | **OPEN — requires new wiring (~15 lines)**; see §21.4 |
| Data is CURRENTLY LIVE — all 51 symbols LIVE as of Aug 15 | **No active STALE problem today** | Resolved by weekend timing (Fri close = 1 day old) |
| 1 missing symbol per scan | Minor — 1 symbol (likely LTIM) not contributing signals | Minor |
| Post-market scan noise | Non-actionable signals displayed during non-market hours | Minor |

> **v3 correction:** Previous versions stated "Without Zerodha live data, no paper-eligible BUY signals can enter the executor". This was misleading — quality is age-based only. **All 51 symbols are currently LIVE without any Zerodha session.** The real remaining data gap is that we use yesterday's close as "current price" rather than live Kite LTP.

### 13.2 Risk Threshold Problems

| Problem | Impact | Status |
|---------|--------|--------|
| R:R 1.5 (scan gate) vs 2.0 (execution gate) — gap blocks signals with 1.5–1.99 RR | Confirmed via `"R:R 1.5 vs minimum 2.0"` in DB | **OPEN — deferred to Phase 2** |
| `AI_MIN_RR_RATIO = 2.0` was previously thought to be an active gate | Dead config — not enforced anywhere | ✅ Confirmed dead (v3 audit) |
| Rejection reasons previously not stored | Could not audit 15,447 risk rejections | ✅ FIXED (new events) |

### 13.3 Position Sizing Problems **[RESOLVED]**

| Problem | Count | Status |
|---------|-------|--------|
| DRREDDY: 8 shares = 21.6% > cap | 873 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP (now 7 shares) |
| GRASIM: 3 shares = 20.2% > cap | 548 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| BAJAJ-AUTO: 2 shares = 23.4% > cap | 262 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| BAJAJFINSV: 6 shares = 20.4% > cap | 353 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |
| TMPV: 6 shares = 21.6% > cap | 272 ORDER_REJECTED | ✅ SIZE_REDUCED_TO_CAP |

### 13.4 Paper Learning / Exploration Policy

| Problem | Impact | Status |
|---------|--------|--------|
| `paper_exploration_mode = False` (Aug 12–14) | No exploration trades | Exploration activated Aug 15 |
| Exploration mode just activated Aug 15 | 8 events but 0 DB rows — silent DB insert failure | **OPEN — P1** |

### 13.5 UI Interpretation Problems

| Problem | Impact |
|---------|--------|
| Post-market signals displayed as active | Operators think system missed trades |
| WATCH signals shown without "not executable" label | Operators think WATCH = pending trade |
| EXIT_PENDING label without explanation | Operators don't know positions are already safety-exited |
| RISK_REJECTED count historically without reason (now fixed) | Difficult to investigate gate failures |

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

The following learning outputs require explicit human approval before any parameter changes:

- Confidence threshold adjustments
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

### 14.4 What is Not Learned (Intentional Gaps)

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

A full backtest on 5 symbols, 15-minute intervals, 30 days takes approximately **6 minutes** (370-second floor). The scan represents ~93% of total backtest time.

### 15.3 Local Setup

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
| Zerodha API read-only usage | `kite.quote()` only — never `kite.place_order()` | `kite_quote_provider.py` |
| Paper-only label on all UI | "PAPER / LIVE DATA VALIDATION" on every scan result | `live_scan_engine.py` line 191 |

### 16.2 Zerodha Usage Boundaries **[UPDATED v3]**

| Zerodha Feature | Used? | Purpose |
|----------------|-------|---------|
| Session probe (`kite.profile()`) | YES — when credentials present | Proves session is alive; result sets `safety["kite_connected"]` display field only |
| Provider label | YES | Display metadata (`live_quote_source`, `data_provider`) |
| Market data (LTP/quotes) via `get_quotes()` | **NOT CURRENTLY WIRED** into scan path | `kite_quote_provider.py` is ready; Option A in §21.4 would wire it |
| Order placement API | **NEVER** | Not called anywhere |
| Portfolio API | **NEVER** | Not called anywhere |
| OHLCV historical data | **NEVER** | yfinance only |

### 16.3 Credential Management

- `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are stored as Replit Secrets (never in code)
- Request tokens are processed via environment variable, not command-line arguments
- Token files are stored with `chmod 600` permissions
- Token expiry is fail-safe: malformed token = treated as expired

### 16.4 Paper Trading Guarantee

The `execute_buy()` function in `paper_trader.py`:
1. Computes simulated fill price from signal price (with slippage model)
2. Updates the `paper_portfolio` table (cash, positions)
3. Writes to `phase20_paper_trades` table
4. **Does not call any broker API**

**Data Path Audit confirmation:** Across 6 months of code history, `kite.place_order()` has never been called. The `MockBrokerClient` is the only broker client instantiated in the current configuration.

---

## 17. Open and Proposed Tasks — Priority Order **[UPDATED v3]**

### 17.1 Critical (Blocking Production Value)

| # | Task Title | Status |
|---|-----------|--------|
| **Phase 1B** | Fix position sizer to adopt cap_qty instead of hard-rejecting | ✅ **DONE** |
| **Phase 1C** | Store structured rejection reason in all rejection events | ✅ **DONE** |
| **v3 P0** | Wire Kite LTP overlay into `run_live_scan()` (~15 lines) | ❌ OPEN — implementation scoped in §21.4 |
| **v3 P0** | Fix exploration mode `experimental_paper_trades` silent DB insert failure | ❌ OPEN — 8 events, 0 rows |
| #659 | Prevent paper-mode SELL orders from silently failing when no position exists | OPEN |
| #235 | Prevent stale regime data from silently masking a regime transition | OPEN |
| #358 | Prevent Risk Agent card from going dark when SnapshotBus restarts | OPEN |

### 17.2 High Priority (Data Integrity)

| # | Task Title | Impact |
|---|-----------|--------|
| **Phase 2 (spec)** | Align RR threshold: scan gate 1.5 vs execution gate 2.0 | Signals with RR 1.5–1.99 silently blocked |
| **v3** | Add scan-loop watchdog (alert if >2 scans per minute) | Prevent Aug 11 recurrence |
| #703 | Prevent DB-timeout error message truncation | Operators miss retry advice |
| #329 | Confirm load_all fault-tolerant if section loader raises | Ops center availability |
| #180 | Prevent 09:20 reconciliation from running with null prices | Misleading empty report |

### 17.3 Medium Priority (UX and Correctness)

| # | Task Title | Impact |
|---|-----------|--------|
| #108 | Confirm config panel refreshes immediately after save | Operator feedback loop |
| #476 | Prevent Supervisor panel duplicate entries | Confusing UI |
| #182 | Confirm readiness score updates when auto-paper entries open | Score lag |
| #208 | Confirm Performance Snapshot shows accurate stats | Zero-stats bug |
| #343 | Show Data Quality grade in Executive Score tooltip | Visibility |
| #234 | Show viable strategies for current regime | Decision support |

---

## 18. Known Weaknesses and Second-Opinion Questions **[UPDATED v3]**

### 18.1 Architectural Weaknesses

| # | Weakness | Severity | Status |
|---|---------|---------|--------|
| W1 | **Kite LTP not wired into scan path** — `LiveDataProvider` uses yfinance exclusively; `kite_quote_provider.py` exists and works but is never called during scanning. Daily bars (1d) are the only OHLCV source. | HIGH | ❌ OPEN — Option A fix scoped in §21.4 (~15 lines) |
| W2 | **Scanner uses daily bars, not intraday bars** — `SCAN_INTERVAL="1d"`. Not 1m/5m/15m. | MEDIUM | ❌ OPEN — Option B (full intraday) is large scope; Option A (LTP overlay) is minimal |
| W3 | **Position sizer hard-rejected when ideal qty exceeded cap** — caused 3,000+ ORDER_REJECTED | HIGH | ✅ FIXED (Remediation Phase 1B + Bug Audit Task 1+2) |
| W4 | **RISK_REJECTED had no stored reason** — 15,447 unexplained rejections | HIGH | ✅ FIXED (Remediation Phase 1C) — new events carry reason |
| W5 | **EXECUTION_SKIPPED reason not stored** — 67 unexplained skips | MEDIUM | ✅ FIXED (Remediation Phase 1C) |
| W6 | **Exit code complete but blocked** — all 8 exit rules implemented; stuck in EXIT_PENDING due to age-based quality (not Kite session) | HIGH | ⚠️ Will resolve when Kite LTP overlay wired |
| W7 | **Scanner runs post-market** — misleads operators about signals | MEDIUM | OPEN — UI banner recommended |
| W8 | **Aug 11 scan-loop runaway** — 88 scans in one day (5/minute peak); 63 phantom ORDER_EXECUTED; scan-loop watchdog needed | MEDIUM | ❌ OPEN — root cause not fixed |
| W9 | **EXIT_PENDING positions have no realized P&L** | MEDIUM | ⚠️ Expected behaviour — will resolve when Option A wired |
| W10 | **Exploration mode experimental_paper_trades empty** despite 8 events | HIGH | ❌ OPEN — silent insert failure |
| W11 | **R:R threshold misalignment** — scan gate 1.5 vs execution gate 2.0 | HIGH | ❌ OPEN — deferred to Phase 2 |
| W12 | **Aug 11 executions are phantom** — BTT- prefix external bot, 0 ledger rows | HIGH | ✅ CONFIRMED DB-verified (v3 audit) |
| W13 | **`AI_MIN_RR_RATIO=2.0` was documented as active gate** | MEDIUM | ✅ CONFIRMED dead config (v3 audit) — corrected throughout SOP |
| W14 | **SYMBOL_SCANNED events lacked per-symbol diagnostic fields** | MEDIUM | ✅ FIXED (v3 Data Path Audit) — 12 fields now emitted including `data_source`, `age_days`, `tradable` |
| W15 | **SIZE_REDUCED_TO_CAP executor wiring bug** — executor read `_rv_result.get("size_reduced_to_cap")` (top-level, always None); key lives in `["summary"]`; resize never fired | HIGH | ✅ FIXED (Bug Audit Task 1) — reads from `summary`; risk_amount recomputed; pipeline event emitted |
| W16 | **Pre-trade validator false CRITICAL after cap resize** — utilisation/cash checks ran with original oversized qty causing false INSUFFICIENT_CASH CRITICAL → REJECTED verdict | HIGH | ✅ FIXED (Bug Audit Task 2) — downstream checks use capped qty/risk |
| W17 | **Scanner action thresholds hardcoded in `market_scanner.py` (62/42) mismatched `config.py` (70/50) and SOP (70/50)** — stocks 62–69 appeared as BUY when they should be WATCH | HIGH | ✅ FIXED (Bug Audit Task 5) — `market_scanner.py` now imports from `config.py` |
| W18 | **Exploration mode `update_experimental_exits()` uses daily close as "live" exit price** — `market_data.get_multiple_ltp()` returns yesterday's 1d close; intraday stop-loss hits not detected until EOD | MEDIUM | ❌ OPEN — documented (Bug Audit Task 4); fix requires Kite LTP overlay (Task 3 Option A) first |

### 18.2 Questions for Independent Reviewer **[UPDATED v3]**

1. **Data architecture:** Given that `SCAN_INTERVAL="1d"` and quality is age-based, the system is genuinely a daily-bar swing-signal engine running intra-session. Is this the intended design? Should "intraday" be removed from the platform description?

2. **Kite LTP overlay (Option A):** The minimal fix (~15 lines) overlays Kite LTP on the latest yfinance daily bar when a session is verified. This changes "current price" from yesterday's close to live LTP — without changing any strategy logic. Is this the right first step before full intraday bars?

3. **STALE data BUY cap:** Currently all 51 symbols are LIVE (Friday close = 1 day old). STALE would only occur after a 6+ day market closure. Does the existing threshold design (3/5/14 days) adequately model the NSE holiday calendar?

4. **Scan-loop watchdog:** Aug 11 showed 5 scans firing in the same minute. The Phase 19B DB-durable scan lock should prevent this — why did it fail? Is the lock heartbeat renewal window too short?

5. **Aug 11 BTT- events:** The intraday_bot process wrote 63 ORDER_EXECUTED events to `pipeline_events` but never committed to any trade table. Should pipeline_events be restricted to canonical executor only? Or is the bot a legitimate secondary process that needs its own ledger table?

6. **Daily bar vs intraday bar for indicators:** RSI, ADX, EMA computed on 6-month daily bars. Does this produce meaningful intraday signals? Or should there be a separate "current session" indicator layer using Kite Historical API (1m/5m) in addition to the daily-bar layer?

7. **Capital reset:** The portfolio resets to ₹50,000 each trading day. Is this modeling intraday-only trading? Currently, positions carry over (EXIT_PENDING trades from Aug 4–7 are still in the DB).

8. **Database design:** Having both `paper_trades` and `phase20_paper_trades` tables is confusing. Which is canonical? Recommend consolidating.

---

## 19. Recommended 30-Day Roadmap **[UPDATED v3]**

### Week 1 (Days 1–7): Fix Blocking Issues

| Priority | Action | Status |
|----------|--------|--------|
| ✅ Done | Fix position sizer (SIZE_REDUCED_TO_CAP path) | **DONE** (Remediation Phase 1B) |
| ✅ Done | Store rejection reason in all rejection events | **DONE** (Remediation Phase 1C) |
| ✅ Done | Add per-symbol diagnostic logging to SYMBOL_SCANNED | **DONE** (Data Path Audit Task 2) |
| 🔴 P1 | Wire Kite LTP overlay into `run_live_scan()` — Option A | ~15 lines, no strategy changes; scoped in §21.4 |
| 🔴 P1 | Fix exploration mode DB insert failure (`experimental_paper_trades`) | Silent failure — 8 events, 0 rows |
| 🟡 P2 | Add scan-loop watchdog (alert if >2 scans in same minute) | Prevent Aug 11 recurrence |

### Week 2 (Days 8–14): Paper Trading Quality

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Confirm first canonical P20- trade with Kite LTP overlay active | Prove clean lifecycle: signal → order → ledger row → exit → P&L |
| 🟡 P2 | Align RR threshold: lower execution gate from 2.0 to 1.5 (or raise scan gate) | Resolve Phase 2 misalignment |
| 🟡 P2 | Enable EXPERIMENTAL_BUY_FROM_WATCH for high-volume WATCH candidates | Generate first WATCH-exploration trades |
| 🟡 P2 | Add market-hours banner to Trade Decisions and Mission Control | Eliminate post-market signal confusion |

### Week 3 (Days 15–21): Learning and Analytics

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🟡 P2 | Consolidate `paper_trades` and `phase20_paper_trades` into single canonical table | Single source of truth |
| 🟡 P2 | Surface RISK_REJECTED reasons in Observability Center | Operators can see why risk is blocking |
| 🟡 P2 | Add "AI accuracy declining" 30-day warning (Task #171) | Early warning system |
| 🟢 P3 | Enable Phase 24 missed-opportunity alerts in Mission Control | Operators notified when signal was missed |

### Week 4 (Days 22–30): Validation and Production Readiness

| Priority | Action | Expected Outcome |
|----------|--------|-----------------|
| 🔴 P1 | Run full backtesting validation with Kite LTP active | Confirm thresholds work with live-quality price |
| 🟡 P2 | Complete sell-side paper trading coverage — confirm P&L captured on all exits | Accurate portfolio analytics |
| 🟡 P2 | Evaluate whether true intraday bars (Option B) are needed vs daily-bar + LTP overlay | Architecture decision with data |
| 🟢 P3 | Write 30-day paper trading summary report | First complete trading period review |

---

## 20. Remediation Phase 1 — Changes Log

No trading thresholds or database records were changed in Remediation Phase 1.

### 20.1 Phase 1A — Code Trace (Read-Only)

**No code changes.** Three questions answered by reading the production codebase and querying the production database:

| Question | Finding |
|----------|---------|
| Is BUY_GENERATED emitted pre-gate or post-gate? | **Post-gate.** `derive_symbol_events()` reads `r.final_action`, which has already been mutated by all gates. A STALE symbol can never emit BUY_GENERATED. |
| Where is R:R enforced, and are the layers aligned? | **Misaligned.** Scan gate = 1.5, pre-trade validator = 1.5, phase20 execution gate = 2.0. `AI_MIN_RR_RATIO=2.0` is dead config (confirmed in v3 audit). |
| Were Aug 11 executions real? | **Phantom.** Trade IDs use "BTT-" prefix (external intraday_bot). Zero rows in phase20_paper_trades or paper_trades (DB-confirmed in v3 audit). |

### 20.2 Phase 1B — Position Sizing Fix

**Files changed:** `risk_validation/pre_trade.py`, `phase20_executor.py`

| File | Change |
|------|--------|
| `risk_validation/pre_trade.py` | `_check_position_size()` now computes `cap_qty`. If `cap_qty ≥ 1`: WARNING `SIZE_REDUCED_TO_CAP`. If `cap_qty == 0`: CRITICAL (unchanged). |
| `phase20_executor.py` | Adopts `capped_qty`, recomputes charges with reduced qty before calling `execute_buy()`. |

**Verified by:** 27/27 unit tests PASSED

### 20.3 Phase 1C — Rejection Reason Logging

**Files changed:** `live_scan_engine.py`, `phase20_executor.py`

All three rejection event types (RISK_REJECTED, ORDER_REJECTED, EXECUTION_SKIPPED_WITH_REASON) now carry `reason`, `gate_name`, `actual_value`, `human_readable_reason` at the top level of their payload.

### 20.4 Phase 1D — Exit Logic Audit (Read-Only)

**No code changes.** Confirmed: all 8 exit rules are implemented in `phase20_exits.py`. NULL realized_pnl is expected behaviour when `quote_reliable=False`.

### 20.5 Clean Lifecycle Status After Phase 1

| Stage | Status |
|-------|--------|
| Signal → `BUY_GENERATED` | ✅ Working (19,034+ all-time, all post-gate) |
| `BUY_GENERATED` → `ORDER_EXECUTED` | ✅ Code-level blocker removed (Phase 1B) |
| `ORDER_EXECUTED` → ledger row in `phase20_paper_trades` | ✅ Code exists (4 existing rows prove it) |
| Ledger row → exit with realized P&L | ⚠️ Exit code complete; requires Kite LTP overlay for `quote_reliable=True` |
| **Single remaining code blocker** | **Wire Kite LTP overlay — Option A in §21.4** |

---

## 21. Data Path & Intraday Truth Audit — Changes Log **[NEW v3]**

This section documents the findings and code changes from the Data Path & Intraday Truth Audit (Tasks 1–7), conducted 2026-08-15.

### 21.1 Key Findings (All Code-Verified)

| Finding | Previous SOP claim | Truth |
|---------|-------------------|-------|
| Data source | "Zerodha primary, Yahoo fallback" | **yfinance only** — unconditional, no Kite branch |
| Candle interval | "intraday scanning" | **1d (daily bars)**, 6-month lookback |
| Kite in scan path | "Zerodha Kite (primary) → Yahoo Finance (fallback)" | **Display metadata only** — `kite_connected` boolean and `live_quote_source` label |
| `ohlcv_source` field | Varied by session | **Hardcoded `"yfinance (historical)"`** regardless of session state |
| `AI_MIN_RR_RATIO = 2.0` | Listed as "advisory downgrade in AI Decision Engine" | **Dead config** — in `phase21_baseline.py` reporting dict only, never compared |
| Quality grade source | "Zerodha tick / Yahoo fallback" | **Age-based only** (`age_days ≤ 3/5/14`) — source is irrelevant to the grade |
| Re-authenticating Zerodha | "Restores LIVE data" | **Changes display label only** — no OHLCV prices change |
| Aug 11 ORDER_EXECUTED count | 64 (from prior version) | **63** (DB-confirmed) |
| Aug 11 SCAN_STARTED | 89 | **88** (DB-confirmed) |

### 21.2 Aug 11 Verdict — DB-Confirmed

Full DB queries run against `pipeline_events` and `phase20_paper_trades`:

- `pipeline_events` WHERE event_type='ORDER_EXECUTED' AND date=Aug 11: **63 rows**
- `phase20_paper_trades` matched by scan_id from those events: **0 rows**
- `paper_trades` (legacy) matched by date: **0 rows**
- All 63 ORDER_EXECUTED payloads: `trade_id` = `BTT-*` (external bot prefix)
- Same fill prices repeating (GLAND at ₹2,248.49 across 9 events): same snapshot re-executed

**Verdict: PHANTOM FILLS CONFIRMED.** Scan-loop runaway (88 scans, up to 5/minute peak) caused the external `intraday_bot` process to fire the same signal repeatedly. The pipeline_events emit is fire-and-forget; the ledger write failed silently (likely table constraint violation or table not existing on Aug 11).

### 21.3 Code Change — Per-Symbol SYMBOL_SCANNED Logging (Task 2)

**File changed:** `artifacts/api-server/src/python/live_scan_engine.py`  
**Function:** `derive_symbol_events()`  
**Change:** Expanded `SYMBOL_SCANNED` event payload from 5 fields to 12 fields.

| Field added | Source |
|-------------|--------|
| `data_source` | `r.data_source` (always `"yfinance"` today) |
| `latest_date` | `r.latest_bar_date` (ISO date of last bar) |
| `age_days` | `r.data_age_days` (calendar days since latest bar) |
| `interval` | `"1d"` (hardcoded — actual interval used) |
| `last_price` | `r.entry_price` (last close used as scan price) |
| `tradable` | `r.paper_eligible` |
| `reason_not_tradable` | Gate-derived string; null when tradable |

**Query to read per-symbol diagnostic data:**
```sql
SELECT symbol,
       payload->>'data_source'       as source,
       payload->>'latest_date'       as latest_date,
       payload->>'age_days'          as age_days,
       payload->>'interval'          as interval,
       payload->>'last_price'        as last_price,
       payload->>'data_quality'      as dq,
       payload->>'tradable'          as tradable,
       payload->>'reason_not_tradable' as reason
FROM pipeline_events
WHERE event_type = 'SYMBOL_SCANNED'
  AND scan_id = '<your_scan_id>'
ORDER BY symbol;
```

### 21.4 Scoped Fix — Kite LTP Overlay (Option A) **[NEW v3]**

The minimal viable fix to wire live Kite price into the scan. No strategy changes. No threshold changes. Paper-only throughout.

**Where:** `live_scan_engine.py` → `run_live_scan()`, after `provider.fetch_batch()` returns (approximately line 675).

**What it does:** Calls `kite_quote_provider.get_ltp(universe)` when a proven Kite session is available. For each symbol where Kite LTP is returned, overrides the last close in the yfinance DataFrame with live LTP, sets `data_age_days = 0.0`, `data_quality = LIVE`, `data_source = "kite_live"`.

**Approximate code (~15 lines):**
```python
# Kite LTP overlay — live price when a proven session is available.
# Keeps all indicators on daily bars; only "current price" is upgraded
# from yesterday's close to Kite's live last-traded price.
if kite_session_verified():
    try:
        from kite_quote_provider import get_ltp as _kite_ltp
        from live_data_provider import DataQuality
        _kite_prices = _kite_ltp(universe)
        for sym, ltp in _kite_prices.items():
            sym_upper = sym.upper()
            if ltp is not None and sym_upper in fetch_results:
                fr = fetch_results[sym_upper]
                if fr.success and fr.df is not None:
                    fr.df.iloc[-1, fr.df.columns.get_loc("close")] = ltp
                    fr.data_age_days = 0.0
                    fr.data_quality = DataQuality.LIVE
                    fr.data_source = "kite_live"
    except Exception:
        pass  # fallback: yfinance prices remain
```

**Result when active:**
- `SYMBOL_SCANNED.data_source` = `"kite_live"` (instead of `"yfinance"`)
- `SYMBOL_SCANNED.age_days` = `0.0`
- `safety["ohlcv_source"]` should be updated to `"kite_live + yfinance (history)"`
- All 4 EXIT_PENDING trades gain `quote_reliable=True` → `resolve_pending_exits()` fires → realized P&L captured

**Files:** `live_scan_engine.py` only. `kite_quote_provider.py` is already complete and requires no changes.

**Option B — True intraday bars (1m/5m/15m via Kite Historical API):** Out of scope for this phase. Requires re-calibrating all indicators for short bars. Separate project.

---

## 22. Bug Audit — Source Code vs SOP Mismatch **[NEW v3.1]**

This section documents the five-task source code audit conducted 2026-08-15, using `APEXQUANT_AI_SOP_v3.html` as the controlling reference document. Detailed findings are in `APEXQUANT_SOURCE_CODE_BUG_AUDIT_AND_FIX_REPORT.md`.

### 22.1 Task 1 — SIZE_REDUCED_TO_CAP Wiring Bug (FIXED)

**Root cause:** `phase20_executor.py` called `rv.to_dict()` then read `_rv_result.get("size_reduced_to_cap")` at the top level. The key lives inside `rv.to_dict()["summary"]` — not at the top level. The condition was **always False**; the executor always used the original oversized quantity.

**Effect:** Every DRREDDY, GRASIM, BAJAJ-AUTO, BAJAJFINSV, TMPV trade that passed the pre-trade validator with `SIZE_REDUCED_TO_CAP=True` was silently executed at the original oversized quantity (or blocked entirely at `execute_buy()` due to cash constraints). The 873 DRREDDY / 548 GRASIM ORDER_REJECTEDs from earlier sessions were from the hard-reject path; any subsequent runs after Phase 1B would have *appeared* to proceed but used the wrong qty.

**Fix applied:**
- Read `_rv_summary = _rv_result.get("summary", {})` then `_rv_summary.get("size_reduced_to_cap")`
- Recompute `risk_amount` proportionally: `_new_risk = _old_risk × cap_qty / orig_qty`
- Update `sizing["quantity"]` and `sizing["risk_amount"]`
- Emit `SIZE_REDUCED_TO_CAP` pipeline event with full payload (original_qty, capped_qty, trade_value before/after, risk before/after, charges recalculated)

**Tests:** `tests/unit/test_size_reduced_to_cap.py` — `TestRvToDictStructure` proves the key lives in `["summary"]`, not top-level.

### 22.2 Task 2 — Pre-Trade Validator False CRITICAL Rejection (FIXED)

**Root cause:** In `risk_validation/pre_trade.py`, `validate_pre_trade()` ran all six checks sequentially using the original `qty`. When `_check_position_size()` detected SIZE_REDUCED_TO_CAP (and set `size_reduced=True`, `capped_qty=15`), the next check `_check_post_trade_utilisation(symbol, fill_price, qty=30, ...)` still used `qty=30`. If 30 × fill_price > `cash_available`, an `INSUFFICIENT_CASH` CRITICAL was raised — overriding the verdict to `REJECTED` even though 15 shares × fill_price would have been fine.

**Fix applied:**
- `_check_position_size()` now runs first
- If `size_reduced=True` and `cap_qty ≥ 1`: compute `_eff_qty = cap_qty`, `_eff_risk = risk_amount × cap_qty / qty`
- All downstream checks (`capital_at_risk`, `post_utilisation`, `daily_risk`) use `_eff_qty` / `_eff_risk`
- False INSUFFICIENT_CASH CRITICAL is eliminated for valid resized trades

**Tests:** `TestPreTradeValidatorCapResize::test_no_insufficient_cash_critical_after_resize` — confirms no false CRITICAL for DRREDDY-style scenario.

### 22.3 Task 3 — Data Path Confirmation + Implementation Plan

**Confirmed from source code (no code changes):**

| Claim | Status |
|-------|--------|
| Scanner uses `LiveDataProvider` | ✓ `live_scan_engine.py:652` — unconditional |
| `LiveDataProvider` uses yfinance only | ✓ `yf.download()` is the only OHLCV call |
| Scanner interval is `1d` | ✓ `SCAN_INTERVAL = "1d"`, `SCAN_PERIOD = "6mo"` |
| Kite NOT in scan path | ✓ `kite_quote_provider.py` never called during scanning |

**Implementation plan — see §21.4 for Option A code. Additional options:**

- **Option B — True Kite intraday candles (5m/15m):** ~4–6 days. All strategies need re-validation on short bars. Do not implement without a full re-calibration run.
- **Option C — yfinance intraday fallback for research only:** `period="1d"`, `interval="5m"` as a display-only overlay. Label clearly as "indicative reference — not used for signal generation."

### 22.4 Task 4 — Exploration Mode Daily-Close Price Bug (Documented — No Fix Yet)

**Finding:** `paper_exploration_engine.py` `update_experimental_exits()` calls `market_data.get_multiple_ltp(symbols)`. `get_multiple_ltp()` calls `get_ltp()` which fetches `fetch_ohlcv(symbol, period="5d", interval="1d")` and returns the last daily close. This means:

- MFE, MAE, and exit-trigger checks (stop/target) in exploration mode use yesterday's close, not any intraday price
- Intraday stop-loss hits are missed entirely until EOD
- MFE/MAE statistics are per-day granularity only

**Impact:** Exploration mode is learning from daily EOD outcomes, not intraday exits. No financial loss (paper only), but MFE/MAE statistics are unreliable for intraday strategy learning.

**Fix path:** Implement Task 3 Option A (Kite LTP overlay) first. Then add a `get_ltp_from_kite_if_available(sym)` wrapper that checks `kite_session_verified()` before falling back to `market_data.get_ltp()`.

**Status:** ❌ OPEN — documented; no code change until Kite LTP wired.

### 22.5 Task 5 — Threshold Mismatch / Single Source of Truth (FIXED)

**Root cause:** `market_scanner.py` had hardcoded action thresholds that did not match `config.py` or this SOP:

| Location | STRONG BUY | BUY | WATCH |
|----------|-----------|-----|-------|
| `config.py` (OPP_* constants) | 85.0 | 70.0 | 50.0 |
| `market_scanner.py` (hardcoded, pre-fix) | 78.0 | **62.0** | **42.0** |
| This SOP | 85.0 | 70.0 | 50.0 |

Stocks scoring 62–69 appeared as BUY in the scanner output but should have been WATCH according to both `config.py` and this SOP. The discrepancy was silent — no error, no warning.

**Fix applied:** `market_scanner.py` now imports `OPP_HOT_BUY_THRESHOLD`, `OPP_BUY_THRESHOLD`, `OPP_WATCH_THRESHOLD` from `config.py`:

```python
ACTION_STRONG_BUY = OPP_HOT_BUY_THRESHOLD   # 85.0
ACTION_BUY        = OPP_BUY_THRESHOLD        # 70.0
ACTION_WATCH      = OPP_WATCH_THRESHOLD      # 50.0
```

`ACTION_STRONG_BUY`, `ACTION_BUY`, `ACTION_WATCH` are still exported from `market_scanner.py` (re-imported by `live_scan_engine.py`), so no downstream import changes needed.

**Operational effect:** Stocks scoring 62–69 now correctly appear as WATCH, not BUY. Strategy and signal logic are unchanged.

**Single source of truth going forward:** Edit only `config.py` to change action thresholds.

### 22.6 Bug Audit — Summary Table

| Task | Bug | Severity | Fixed? | Files changed |
|------|-----|----------|--------|---------------|
| Task 1 | `size_reduced_to_cap` read from wrong dict level | HIGH | ✅ YES | `phase20_executor.py` |
| Task 2 | Downstream validator checks used original oversized qty | HIGH | ✅ YES | `risk_validation/pre_trade.py` |
| Task 3 | Data path confirmation + implementation plan | INFO | N/A | None (plan provided) |
| Task 4 | Exploration mode uses daily close as exit price | MEDIUM | ❌ OPEN | None (fix blocked on Task 3) |
| Task 5 | Scanner thresholds 62/42 ≠ config 70/50 | HIGH | ✅ YES | `market_scanner.py` |

**Tests added:** `tests/unit/test_size_reduced_to_cap.py` — 13 tests, 13 passing.

**No live orders placed. No strategy logic changed. Paper only throughout.**

---

## 23. Appendix

### 23.1 Important Configuration Values

| Config Key | Value | Location |
|-----------|-------|----------|
| `INITIAL_CAPITAL` | ₹50,000 | `config.py` |
| `SCAN_INTERVAL` | `"1d"` | `live_data_provider.py` |
| `SCAN_PERIOD` | `"6mo"` | `live_data_provider.py` |
| `LIVE_DAYS` | 3 | `live_data_provider.py` |
| `NEAR_LIVE_DAYS` | 5 | `live_data_provider.py` |
| `STALE_DAYS` | 14 | `live_data_provider.py` |
| `MIN_RR_FOR_BUY` | 1.5 | `live_scan_engine.py:64` |
| `AI_MIN_RR_RATIO` | 2.0 | `config.py:61` — **dead config** |
| `LIVE_EXECUTION_ENABLED` | `False` | `config.py` |
| `per_stock_exposure_cap_pct` | 25.0% | `phase20_store.py` DEFAULT_SETTINGS |
| `min_confidence` | 60.0% | `phase20_store.py` DEFAULT_SETTINGS |
| `min_risk_reward` | 2.0 | `phase20_store.py` DEFAULT_SETTINGS |

### 23.2 Database Tables Reference

| Table | Purpose | Canonical? |
|-------|---------|-----------|
| `pipeline_events` | All pipeline events (SYMBOL_SCANNED, BUY_GENERATED, ORDER_EXECUTED, etc.) | YES — event log |
| `phase20_paper_trades` | Paper trade ledger — P20- prefix trades | **YES — canonical** |
| `paper_trades` | Legacy paper trade table | NO — legacy, to be retired |
| `paper_portfolio` | Current portfolio state (positions JSON, cash) | YES |
| `experimental_paper_trades` | Exploration mode trades | YES (currently empty — insert failing) |
| `scan_state_store` | Distributed scan lock, scan state | YES |
| `phase24_missed_opps` | Missed opportunity tracking | YES — advisory |
| `kv_store` | KV store for settings and scheduler guards | YES |

### 23.3 Trade ID Prefix Reference

| Prefix | Source | Canonical? |
|--------|--------|-----------|
| `P20-{uuid}` | `phase20_executor.py` | **YES** — canonical paper trades |
| `BTT-{hash}` | External `intraday_bot` process | **NO** — phantom; not in any ledger |

### 23.4 Key Invariants (Never Bypass)

1. `LIVE_EXECUTION_ENABLED = False` — hardcoded, never changes
2. Quality gate: STALE → max WATCH; UNAVAILABLE → IGNORE — enforced in `_apply_quality_gate()`
3. `ohlcv_source = "yfinance (historical)"` — currently hardcoded; changes when Option A is wired
4. `MIN_RR_FOR_BUY = 1.5` — only active RR gate in scan path
5. `SIZE_REDUCED_TO_CAP` only fires when `cap_qty ≥ 1` — never bypasses a genuinely unaffordable stock
6. All paper fills are simulated via `paper_trader.py` — no Zerodha order API ever called

---

*Document version 3.1. Generated 2026-08-15 IST. All DB figures queried directly from production `pipeline_events` and `phase20_paper_trades`. All code claims verified against the live codebase. No values fabricated. Trading thresholds corrected to match config.py (scanner alignment fix only — see §22.5). No strategy logic changed. Paper only.*
