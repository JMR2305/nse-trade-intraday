# NSE Trader Intraday — Master Architecture Design

**Version:** 1.0  
**Date:** 2026-07-18  
**Status:** Documentation Only — No code modified  
**Scope:** Proposed design for a separate Intraday Trading platform  

---

## Document Conventions

| Marker | Meaning |
|--------|---------|
| `[OBSERVED]` | Directly confirmed by reading existing code |
| `[PROPOSED]` | Design decision — not yet implemented |
| `[ABSENT]` | Confirmed absent from existing codebase |
| `[PARTIAL]` | Exists in a limited or swing-specific form |

---

## Table of Contents

1. [Project Isolation Architecture](#1-project-isolation-architecture)
2. [Target System Architecture — 25 Layers](#2-target-system-architecture)
3. [Runtime and Service Boundaries](#3-runtime-and-service-boundaries)
4. [Mid-Session Recovery Architecture](#4-mid-session-recovery-architecture)
5. [Continuous Trade Monitoring](#5-continuous-trade-monitoring)
6. [Independent Watchdog](#6-independent-watchdog)
7. [Kill-Switch Policy](#7-kill-switch-policy)
8. [Square-Off Escalation](#8-square-off-escalation)
9. [Data Architecture](#9-data-architecture)
10. [Feature and Strategy Architecture](#10-feature-and-strategy-architecture)
11. [Expected Value and Probability Definition](#11-expected-value-and-probability-definition)
12. [Calibration Separation](#12-calibration-separation)
13. [Broker Adapter](#13-broker-adapter)
14. [Latency Budgets](#14-latency-budgets)
15. [Alert and Incident Levels](#15-alert-and-incident-levels)
16. [Dashboard Architecture](#16-dashboard-architecture)
17. [Text Architecture Diagram](#17-text-architecture-diagram)
18. [Dependency Map](#18-dependency-map)
19. [Risk Register](#19-risk-register)
20. [Unresolved Decisions](#20-unresolved-decisions)
21. [Recommended Implementation Sequence](#21-recommended-implementation-sequence)

---

## 1. Project Isolation Architecture

### 1.1 Observed Coupling Points in the Existing Platform

The following coupling points were identified by direct code inspection and must be understood before the intraday project can operate safely in the same environment or in a fork.

| Coupling Point | Location | Risk |
|---|---|---|
| `DATABASE_URL` shared env var | All Python files, `lib/db/` | `[OBSERVED]` Any Python process writing to the shared DB can corrupt swing data |
| `ZERODHA_API_KEY / SECRET` shared env vars | `kite_session_manager.py`, `kite_token_store.py` | `[OBSERVED]` Same Kite session used for both projects — token refresh from one project invalidates the other |
| `ZERODHA_ACCESS_TOKEN` written to local file | `kite_token_store.py` | `[OBSERVED]` File-system token may be overwritten if both projects run on the same container |
| `phase11_kill_switch.json` | `phase11_risk.py` | `[OBSERVED]` JSON file kill switch — path-dependent, could be the same path in a fork |
| `scanScheduler.ts` (Node.js) | `artifacts/api-server/src/lib/scanScheduler.ts` | `[OBSERVED]` In-process scheduler; triggers Python scan pipeline |
| `phase20_scheduler.py` | `artifacts/api-server/src/python/` | `[OBSERVED]` Python-side scheduler; writes to `scan_state` and `signals_cache` tables |
| `paper_portfolio.json` | fallback in `paper_trader.py` | `[OBSERVED]` Flat-file fallback; same filename could collide if two projects share a filesystem |
| `watchlist.json` | `main.py` L49 | `[OBSERVED]` Read from a relative path in the Python working directory |
| `alert_deliveries` PostgreSQL table | `alertQueue.ts` | `[OBSERVED]` Shared DB table; intraday alerts would mix with swing alerts |
| `push_subscriptions` PostgreSQL table | `pushNotifier.ts` | `[OBSERVED]` Shared push tokens; intraday alerts could be delivered on swing subscriptions |

### 1.2 Isolation Requirements

#### Replit Project and Deployment
- `[PROPOSED]` The Intraday project runs in a **separate Replit repl** with its own container, secrets store, and deployment target.
- The Swing repl is never imported, linked, or called from the Intraday repl.

#### Git Repository and Branches
- `[PROPOSED]` A separate Git repository (or an isolated long-lived branch with explicit merge gates) for the Intraday codebase.
- If using branches: a merge protection rule must prevent any Intraday branch from being merged into the Swing main branch without manual human approval.
- A baseline tag `intraday-baseline-v0.0` must be created before any Intraday code is written.

#### Environment Variables and Secrets
- `[PROPOSED]` All secrets are stored in the Intraday Replit Secrets store, completely separate from the Swing store.
- Secret names use an `INTRADAY_` prefix where they share the same underlying service (e.g., `INTRADAY_DATABASE_URL`, `INTRADAY_ZERODHA_ACCESS_TOKEN`).
- The Swing project's `DATABASE_URL` must never appear in the Intraday environment.

#### PostgreSQL Database
- `[PROPOSED]` A **separate PostgreSQL database instance** (separate Replit database or a separate logical database on the same Postgres server with distinct credentials).
- If using the same Postgres server: create a separate role with `GRANT CONNECT ON DATABASE intraday_db TO intraday_user` and ensure the Swing role cannot connect to the intraday database.

#### Database Tables and Migrations
- `[PROPOSED]` All intraday tables live in the `intraday_db` database (or a dedicated schema `intraday` within a shared server).
- No shared tables. No cross-database foreign keys.
- Drizzle migration history stored in a separate `drizzle_migrations_intraday` table.

#### Scheduled Jobs
- `[PROPOSED]` The Intraday project has its own scheduler (a persistent FastAPI service with an internal scheduler loop), completely independent of `scanScheduler.ts` and `phase20_scheduler.py`.
- The Swing `scanScheduler.ts` must not be imported or called from intraday code.

#### Background Workers
- `[PROPOSED]` The Intraday Python engine runs as a **long-running FastAPI process** (see §3) — not a per-request spawn. This is a new process, not an extension of the existing `main.py` CLI.

#### Model Artifacts
- `[PROPOSED]` Intraday model artifacts stored in `artifacts/api-server/src/python/intraday_models/`.
- Swing model artifacts remain in their current paths (e.g., `models/`, `calibration/`).
- No code in the Intraday engine may import from or write to the Swing model directory.

#### Calibration Models
- `[PROPOSED]` A separate `Intraday_Calibration_v{N}.pkl` artifact.
- The Swing `Swing_Calibration_v{N}.pkl` must never be loaded by the Intraday engine (see §12).

#### Trade Records
- `[PROPOSED]` Separate `intraday_paper_orders`, `intraday_paper_fills`, `intraday_positions` tables in the intraday database.
- The Swing `paper_trades` and `paper_portfolio` tables `[OBSERVED]` must not be written by any intraday process.

#### Portfolio Records
- `[PROPOSED]` Separate `intraday_portfolio_state` table. No shared portfolio state.

#### Alerts and Notifications
- `[PROPOSED]` Separate `intraday_alert_deliveries` and `intraday_push_subscriptions` tables.
- Intraday alerts must never be routed through the Swing `alertQueue.ts`.

#### Zerodha Tokens
- `[PROPOSED]` Intraday Kite session uses its own token storage table (`intraday_kite_tokens` in the intraday database).
- The Swing `kite_token_store.py` must not be imported by the Intraday engine.
- If both projects use the same Zerodha account, the Kite access token is shared — this is an **unresolved decision** (see §20). Using the same account with two active sessions can cause session invalidation.

#### Paper-Trading State
- `[PROPOSED]` All paper-trading state is in the intraday PostgreSQL database. No `paper_portfolio.json` fallback.
- The `paper_portfolio.json` `[OBSERVED]` fallback in the Swing project must not exist in the Intraday project.

#### Cache and JSON State
- `[PROPOSED]` The Intraday project uses PostgreSQL for all durable state. No shared JSON flat files.
- `watchlist.json`, `paper_portfolio.json` must be absent from the Intraday engine.

#### Logging
- `[PROPOSED]` The Intraday API server uses a separate Pino log stream tagged with `service: "intraday-api"`.
- Python logs tagged with `service: intraday-engine`.
- Log file paths (if local) must use a distinct directory (e.g., `logs/intraday/`).

#### Analytics
- `[PROPOSED]` Intraday analytics queries run against the `intraday_db` database only.
- No SQL queries in the Intraday project may reference Swing tables.

#### Frontend Routes
- `[PROPOSED]` The Intraday dashboard is a separate web artifact with its own route namespace. It does not share routes with the Swing dashboard (`artifacts/trading-dashboard`).
- If co-hosted: Intraday routes use an `/intraday/` prefix.

#### API Endpoints
- `[PROPOSED]` The Intraday API server runs on a distinct port and/or URL path. API routes namespaced under `/intraday/api/v1/`.
- No Swing API route (`/api/run-scan`, `/api/portfolio`, etc.) `[OBSERVED]` may be called from the Intraday frontend or engine.

---

## 2. Target System Architecture

The Intraday platform is composed of 25 logical layers. Each is described below.

---

### Layer 1 — Broker and Market Data Adapter

| Field | Detail |
|---|---|
| **Purpose** | Single entry point for all broker and market data communication. Shields all other layers from Zerodha-specific APIs. |
| **Inputs** | Connection credentials (API key, access token from intraday token store), symbol subscription lists |
| **Outputs** | Normalized tick events, order acknowledgements, position snapshots, price band data |
| **Dependencies** | Intraday Kite token store, `kiteconnect` Python SDK |
| **Storage** | Stateless; tokens read from `intraday_kite_tokens` table |
| **Failure behavior** | Log error, emit `BROKER_DISCONNECTED` event; all dependent layers enter degraded mode |
| **Recovery behavior** | Exponential backoff reconnect (1s, 2s, 4s, 8s … cap 60s); re-authenticate using stored token |
| **Implementation** | `[PROPOSED]` New module: `intraday_broker_adapter.py`. Implements `BrokerInterface` (see §13) |
| **Language/process** | Python (FastAPI process) |

---

### Layer 2 — Kite WebSocket Ingestion Service

| Field | Detail |
|---|---|
| **Purpose** | Maintains a persistent KiteTicker WebSocket connection. Receives raw tick events. Decodes, validates, and forwards to the Tick Normalizer. |
| **Inputs** | Kite WebSocket stream (`KiteTicker.on_ticks`) for subscribed instruments |
| **Outputs** | Raw tick dicts pushed to an in-process asyncio queue |
| **Dependencies** | Layer 1 (Broker Adapter) for connection and subscription; list of active instrument tokens |
| **Storage** | In-memory asyncio queue (bounded, ≤ 10 000 ticks). Compressed tick summaries written to `intraday_tick_summaries` (1-min retention) |
| **Failure behavior** | On disconnect: emit `WS_DISCONNECTED` event; pause bar building; alert Watchdog (Layer 20) |
| **Recovery behavior** | Auto-reconnect with exponential backoff; resume subscription to the same instrument list; emit `WS_RECONNECTED` event |
| **Implementation** | `[ABSENT]` — does not exist in the current platform `[OBSERVED]`. New module: `intraday_ws_ingestion.py` |
| **Language/process** | Python (FastAPI process, background asyncio task) |

---

### Layer 3 — Tick Normalizer

| Field | Detail |
|---|---|
| **Purpose** | Converts raw KiteTicker dicts into a canonical `Tick` dataclass. Validates required fields. Filters out-of-session ticks. Applies instrument-token-to-symbol mapping. |
| **Inputs** | Raw tick dicts from Layer 2 queue |
| **Outputs** | `Tick(symbol, timestamp, ltp, volume_traded, bid, ask, oi)` events |
| **Dependencies** | Instrument master cache (from `kite_instrument_cache.py` `[OBSERVED]`); NSE session boundaries from `market_hours.py` `[OBSERVED]` |
| **Storage** | Stateless; uses in-memory instrument map refreshed at session start |
| **Failure behavior** | Malformed ticks are logged and discarded; counter incremented for Watchdog visibility |
| **Recovery behavior** | Stateless — no recovery needed. Resumes processing after any upstream reconnect. |
| **Implementation** | `[PROPOSED]` New module: `intraday_tick_normalizer.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 4 — Session-Aware One-Minute Bar Builder

| Field | Detail |
|---|---|
| **Purpose** | Aggregates normalized ticks into 1-minute OHLCV bars. Resets all state at 09:15:00 IST each session. Emits a completed bar event exactly once per minute per symbol. |
| **Inputs** | `Tick` events from Layer 3 |
| **Outputs** | `Bar(symbol, session_id, bar_ts, open, high, low, close, volume, vwap_contribution)` events written to Layer 5 |
| **Dependencies** | Layer 3 (Tick Normalizer); active session ID from Layer 5; `market_hours.py` for session boundary |
| **Storage** | In-memory per-symbol bar accumulators. Completed bars persisted immediately to `minute_ohlcv_cache` |
| **Failure behavior** | On tick gap > 2 min: mark bar as `GAP_BAR`; emit with available data |
| **Recovery behavior** | On restart: reload latest bars from `minute_ohlcv_cache` for current session; resume from last complete bar |
| **Implementation** | `[ABSENT]` — no 1-min bar builder exists `[OBSERVED]`. New module: `intraday_bar_builder.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 5 — Intraday Session Store

| Field | Detail |
|---|---|
| **Purpose** | Authoritative source of truth for the current intraday session. Creates and manages session records. All other layers derive session context from this store. |
| **Inputs** | Session start/end events from `market_hours.py`; session_id from most tables |
| **Outputs** | `IntraSession(session_id, date, status, open_ts, close_ts, regime, risk_used_pct)` |
| **Dependencies** | `market_hours.py` `[OBSERVED]`; PostgreSQL `intraday_sessions` table |
| **Storage** | `intraday_sessions` table (see §9) |
| **Failure behavior** | If session record cannot be created, block all entries for the day |
| **Recovery behavior** | On restart: load the session record for today's date; resume with existing `session_id` |
| **Implementation** | `[PROPOSED]` New module: `intraday_session_store.py` |
| **Language/process** | Python / PostgreSQL |

---

### Layer 6 — Data Quality and Freshness Gates

| Field | Detail |
|---|---|
| **Purpose** | Classifies the quality of per-symbol market data. Blocks downstream layers when data is stale or unreliable. Replaces the swing-specific freshness logic with intraday-appropriate thresholds. |
| **Inputs** | Latest tick timestamp and last-bar timestamp per symbol from Layers 3–4 |
| **Outputs** | `DataQuality(symbol, status, last_tick_age_ms, last_bar_age_s)` where status ∈ {`LIVE`, `RECENT`, `STALE`, `DEGRADED`, `UNAVAILABLE`} |
| **Dependencies** | Layer 2 (WS state), Layer 4 (bar timestamps) |
| **Storage** | In-memory map; published to a PostgreSQL view or materialized table for dashboard consumption |
| **Failure behavior** | If data quality drops below `RECENT`, block signal generation for that symbol; alert Warning level |
| **Recovery behavior** | Quality status recovers automatically once fresh ticks resume |
| **Implementation** | `[PARTIAL]` — `live_data_provider.py` `[OBSERVED]` has a similar concept with daily TTLs. Intraday version uses different thresholds: LIVE ≤ 5s, RECENT ≤ 30s, STALE ≤ 120s, DEGRADED ≤ 300s, UNAVAILABLE > 300s |
| **Language/process** | Python (FastAPI process) |

---

### Layer 7 — Intraday Feature Store

| Field | Detail |
|---|---|
| **Purpose** | Computes and caches all technical features for each active symbol after each completed bar. Provides a snapshot of features at any point in time for signal generation and model inference. |
| **Inputs** | Completed bars from Layer 4; tick stream for live bid-ask; NIFTY index bars; session metadata from Layer 5 |
| **Outputs** | `FeatureSnapshot(symbol, session_id, bar_ts, features: dict)` stored in `feature_snapshots` |
| **Dependencies** | Layers 4, 5, 6; VWAP Engine, ORB Detector, RVOL Calculator, Gap Analyser (see §10) |
| **Storage** | `feature_snapshots` table; in-memory latest-snapshot cache per symbol |
| **Failure behavior** | If a required feature cannot be computed, emit the snapshot with `feature_missing: true` flag; block signal generation |
| **Recovery behavior** | On restart: reload latest feature snapshot per symbol from `feature_snapshots`; recompute missing features from bar history |
| **Implementation** | `[ABSENT]` New module: `intraday_feature_store.py` with sub-modules for each indicator |
| **Language/process** | Python (FastAPI process) |

---

### Layer 8 — Heuristic Market Regime Tagger

| Field | Detail |
|---|---|
| **Purpose** | Classifies the current market regime using transparent heuristic rules (no ML classifier in v1). Tags each session and each feature snapshot with a regime label that gates strategy selection. |
| **Inputs** | NIFTY 50 bars from Layer 4; India VIX (daily, from yfinance at session start); ADX and ATR features from Layer 7 |
| **Outputs** | `Regime(session_id, bar_ts, label, confidence)` where label ∈ {`TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `VOLATILE`, `UNCERTAIN`} |
| **Dependencies** | Layer 7 (Feature Store); Layer 5 (Session Store) |
| **Storage** | Latest regime written to `intraday_sessions.regime`; history in `regime_snapshots` |
| **Failure behavior** | If NIFTY data is unavailable, tag as `UNCERTAIN`; log warning; allow only conservative strategies |
| **Recovery behavior** | On restart: reload latest regime from session store; recompute from bar history if needed |
| **Implementation** | `[PROPOSED]` New module: `intraday_regime_tagger.py`. V1 uses heuristic rules; a learned classifier is explicitly deferred |
| **Language/process** | Python (FastAPI process) |

**V1 Heuristic Rules (proposed):**

| Condition | Regime |
|---|---|
| ADX > 25 AND NIFTY slope positive | `TRENDING_UP` |
| ADX > 25 AND NIFTY slope negative | `TRENDING_DOWN` |
| ADX < 20 AND ATR percentile < 40th | `RANGING` |
| VIX > 20 OR ATR percentile > 85th | `VOLATILE` |
| None of the above | `UNCERTAIN` |

---

### Layer 9 — Strategy Selection Engine

| Field | Detail |
|---|---|
| **Purpose** | Maps the current market regime to a ranked list of eligible intraday strategies. Enforces time-of-day restrictions. Returns the active strategy set for the current bar. |
| **Inputs** | Current regime from Layer 8; time-of-day from session clock; strategy performance history from `strategy_performance_cache` |
| **Outputs** | Ordered list of `StrategyConfig` objects eligible for the current market state |
| **Dependencies** | Layer 8 (Regime Tagger); Layer 5 (Session Store); strategy registry |
| **Storage** | Strategy configuration in `intraday_config` table; performance cache in memory |
| **Failure behavior** | If regime is `UNCERTAIN`, return only the most conservative strategy (e.g., VWAP Reversion with tight parameters) |
| **Recovery behavior** | Strategy list is stateless — recomputed from current regime and time on each bar |
| **Implementation** | `[PROPOSED]` New module: `intraday_strategy_selector.py` |
| **Language/process** | Python (FastAPI process) |

**V1 Regime → Strategy Mapping:**

| Regime | Eligible Strategies |
|---|---|
| `TRENDING_UP` | ORB, Momentum Burst, Gap-and-Go, Trend Pullback |
| `TRENDING_DOWN` | ORB (short bias), Gap-Fill |
| `RANGING` | VWAP Reversion |
| `VOLATILE` | None (no entries); or VWAP Reversion with reduced size |
| `UNCERTAIN` | VWAP Reversion only, conservative parameters |

---

### Layer 10 — Intraday Strategy Modules

| Field | Detail |
|---|---|
| **Purpose** | Independent, self-contained strategy implementations that each produce entry candidates, stop levels, targets, and thesis invalidation rules. |
| **Inputs** | `FeatureSnapshot` from Layer 7; `StrategyConfig` from Layer 9 |
| **Outputs** | `EntryCandidate(symbol, strategy_id, direction, entry_price, stop, target, thesis, features_frozen)` |
| **Dependencies** | Layer 7 (Feature Store); Layer 9 (Strategy Selector) |
| **Storage** | Entry candidates are ephemeral (in-memory); not stored until confirmed by Signal Engine |
| **Failure behavior** | If a strategy module raises an exception, log error and skip that strategy for this bar |
| **Recovery behavior** | Stateless — recomputed on next bar |
| **Implementation** | `[ABSENT]` — swing strategies in `strategies.py` `[OBSERVED]` are hardcoded for daily bars and cannot be reused. New module: `intraday_strategies/` package |
| **Language/process** | Python (FastAPI process) |

**V1 Strategy Interface (proposed):**
```python
class IntradayStrategy(ABC):
    strategy_id: str
    eligible_regimes: list[str]
    min_rvol: float
    max_spread_pct: float
    no_entry_after: time  # e.g. 14:45 IST

    @abstractmethod
    def generate_candidates(
        self, snapshot: FeatureSnapshot, session: IntraSession
    ) -> list[EntryCandidate]: ...

    @abstractmethod
    def get_exit_rules(
        self, position: IntradayPosition
    ) -> ExitRules: ...

    @abstractmethod
    def is_thesis_intact(
        self, position: IntradayPosition, snapshot: FeatureSnapshot
    ) -> ThesisCheck: ...
```

---

### Layer 11 — Signal Engine

| Field | Detail |
|---|---|
| **Purpose** | Evaluates all entry candidates from Layer 10. Applies data quality gates (Layer 6) and risk gates (Layer 16). Produces confirmed signals with frozen feature snapshots and metadata. |
| **Inputs** | `EntryCandidate` list from Layer 10; `DataQuality` from Layer 6; risk headroom from Layer 16 |
| **Outputs** | `Signal(signal_id, symbol, strategy_id, direction, entry_price, stop, target, features_frozen, created_at)` written to `intraday_signals` |
| **Dependencies** | Layers 6, 10, 16 |
| **Storage** | `intraday_signals` table |
| **Failure behavior** | If no candidates pass all gates, emit no signal; log gate rejection reason |
| **Recovery behavior** | Stateless per bar — recomputed on next bar |
| **Implementation** | `[ABSENT]` — `signal_engine.py` `[OBSERVED]` is hardcoded for daily data. New module: `intraday_signal_engine.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 12 — Expected-Value Ranking Engine

| Field | Detail |
|---|---|
| **Purpose** | Computes the expected net value for each confirmed signal using the formula defined in §11. Ranks signals by EV. Filters out negative-EV signals. |
| **Inputs** | `Signal` list from Layer 11; calibrated win probabilities from Layer 14; cost model from Layer 18 |
| **Outputs** | Ranked list of `EVRankedSignal(signal_id, ev, win_prob, expected_reward, expected_loss, total_cost)` |
| **Dependencies** | Layers 11, 14, 18 |
| **Storage** | EV values persisted to `intraday_signals.ev` column |
| **Failure behavior** | If calibration service is unavailable, use uncalibrated heuristic win probability (clearly labelled `UNCALIBRATED`) |
| **Recovery behavior** | Stateless — recomputed on next bar |
| **Implementation** | `[PROPOSED]` New module: `intraday_ev_ranker.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 13 — Confidence Aggregator

| Field | Detail |
|---|---|
| **Purpose** | Single authoritative module that produces the final confidence score for each signal. Prevents multiple independent modules from modifying confidence separately — a known flaw in the swing platform `[OBSERVED]`. |
| **Inputs** | Raw heuristic score from strategy module; calibrated win probability from Layer 14; data quality penalty from Layer 6; regime confidence from Layer 8 |
| **Outputs** | `ConfidenceResult(signal_id, raw_score, calibrated_prob, quality_penalty, regime_weight, final_confidence, model_version, is_calibrated)` |
| **Dependencies** | Layers 8, 11, 14 |
| **Storage** | Written to `intraday_signals.confidence` and `model_predictions` |
| **Failure behavior** | If calibration unavailable: emit confidence with `is_calibrated: false`; use raw heuristic score |
| **Recovery behavior** | Stateless — recomputed per signal |
| **Implementation** | `[PROPOSED]` New module: `intraday_confidence_aggregator.py`. This is the ONLY place confidence is modified. |
| **Language/process** | Python (FastAPI process) |

**Confidence formula (proposed v1):**
```
final_confidence = calibrated_prob
    × quality_weight(data_quality)
    × regime_weight(regime)
```

---

### Layer 14 — Intraday Calibration Service

| Field | Detail |
|---|---|
| **Purpose** | Maintains and serves the intraday-specific Isotonic regression calibration model. Never shares a model artifact with the swing calibration. |
| **Inputs** | Raw heuristic win probability from strategy layer |
| **Outputs** | Calibrated win probability ∈ [0, 1]; model version; `is_calibrated` flag |
| **Dependencies** | `intraday_models/Intraday_Calibration_v{N}.pkl`; `calibration_predictions` table |
| **Storage** | Model artifacts in `intraday_models/`; predictions logged to `calibration_predictions` |
| **Failure behavior** | If model file missing (cold start): return `is_calibrated: false`; use raw score; emit Warning alert |
| **Recovery behavior** | Reload model artifact from disk on startup; no training or retraining happens at runtime |
| **Implementation** | `[PARTIAL]` — `confidence_calibration.py` `[OBSERVED]` exists for swing. Intraday needs a separate instance with a separate model artifact. New module: `intraday_calibration_service.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 15 — Portfolio Allocation Engine

| Field | Detail |
|---|---|
| **Purpose** | Determines position size for each approved signal. Accounts for MIS leverage, per-trade capital risk, session risk cap, and open position count. |
| **Inputs** | `EVRankedSignal` from Layer 12; current session risk usage from Layer 16; account capital from session store |
| **Outputs** | `SizedOrder(signal_id, symbol, quantity, entry_price, stop, target, capital_at_risk, leverage_used)` |
| **Dependencies** | Layers 12, 16 |
| **Storage** | Stateless; allocation written to `intraday_paper_orders` |
| **Failure behavior** | If risk headroom is zero, return zero quantity; do not create an order |
| **Recovery behavior** | Recomputes from current risk state on next signal |
| **Implementation** | `[PARTIAL]` — `position_sizer.py` `[OBSERVED]` exists for swing (daily risk). Intraday version needs MIS-leverage-aware sizing. New module: `intraday_position_sizer.py` |
| **Language/process** | Python (FastAPI process) |

**Sizing formula (proposed v1):**
```
capital_at_risk = session_capital × per_trade_risk_pct   # e.g. 0.5%
quantity = floor(capital_at_risk / (entry_price - stop_price))
mis_margin_required = (entry_price × quantity) / mis_leverage  # e.g. ÷ 5
```

---

### Layer 16 — Intraday Risk Engine

| Field | Detail |
|---|---|
| **Purpose** | Enforces all pre-trade and portfolio-level risk limits. Prevents entries that would breach any limit. Also provides ongoing risk accounting for Layer 15. |
| **Inputs** | `SizedOrder` from Layer 15; current session P&L, open positions, capital from Layer 5; time-of-day |
| **Outputs** | `RiskDecision(approved: bool, reason: str)`; `RiskSnapshot` written to `risk_snapshots` |
| **Dependencies** | Layers 5, 15; `intraday_positions` table |
| **Storage** | `risk_snapshots` table; in-memory session P&L accumulator |
| **Failure behavior** | On any risk engine error: DENY entry (fail-closed); alert Critical |
| **Recovery behavior** | On restart: recompute risk state from `intraday_positions` and `intraday_paper_fills` |
| **Implementation** | `[PARTIAL]` — `phase20_gates.py` `[OBSERVED]` has swing-specific gate logic. New module: `intraday_risk_engine.py` |
| **Language/process** | Python (FastAPI process) |

**V1 hard limits (proposed):**

| Limit | Value |
|---|---|
| Per-trade capital risk | 0.5% of session capital |
| Session daily loss cap | 2.0% of session capital |
| Max open positions | 3 |
| Max sector concentration | 60% of open risk in any sector |
| No new entries after | 14:45 IST |
| Mandatory square-off | 15:15 IST (see §8) |

---

### Layer 17 — Paper Execution Simulator

| Field | Detail |
|---|---|
| **Purpose** | Simulates order fills with realistic latency, slippage, and partial fill behavior. Records every fill with cost breakdown. Never submits real orders. |
| **Inputs** | `SizedOrder` from Layer 15 (approved by Layer 16); live tick data from Layer 3 |
| **Outputs** | `Fill(order_id, symbol, quantity, fill_price, slippage_pct, brokerage, taxes, net_cost, fill_ts)` |
| **Dependencies** | Layers 3, 15, 18 |
| **Storage** | `intraday_paper_orders`, `intraday_paper_fills` tables |
| **Failure behavior** | If a tick is stale (> 2s): mark order as `AWAITING_FILL`; do not fabricate a fill price |
| **Recovery behavior** | On restart: reload all `PENDING` orders from `intraday_paper_orders`; resume fill simulation from next available tick |
| **Implementation** | `[PARTIAL]` — `phase20_executor.py` `[OBSERVED]` has a fill model. Intraday version needs MIS mode and intraday slippage model. Modified module: `intraday_executor.py` |
| **Language/process** | Python (FastAPI process) |

---

### Layer 18 — NSE Cost and Slippage Engine

| Field | Detail |
|---|---|
| **Purpose** | Computes the complete cost of each trade: brokerage, STT, exchange charges, SEBI fee, GST, stamp duty, spread, and slippage. Used by Layers 12 and 17. |
| **Inputs** | `quantity`, `entry_price`, `exit_price`, `direction`, `product_type = "MIS"`, current bid-ask spread |
| **Outputs** | `CostBreakdown(brokerage, stt, exchange_charge, sebi_fee, gst, stamp_duty, spread_cost, slippage_cost, total_cost_per_trade)` |
| **Dependencies** | None (pure computation) |
| **Storage** | Stateless; cost breakdown attached to each `Fill` record |
| **Failure behavior** | None — pure computation cannot fail |
| **Recovery behavior** | N/A |
| **Implementation** | `[ABSENT]` — no NSE cost engine exists `[OBSERVED]`. New module: `intraday_cost_engine.py` |
| **Language/process** | Python |

**NSE MIS cost rates (verify against current Zerodha schedule before implementing):**

| Component | Rate |
|---|---|
| Brokerage | ₹20 per order (Zerodha flat) |
| STT | 0.025% of sell-side turnover |
| Exchange (NSE) | 0.00345% of total turnover |
| SEBI fee | 0.0001% of total turnover |
| GST | 18% of (brokerage + exchange charges) |
| Stamp duty | 0.003% of buy-side turnover |

---

### Layer 19 — Continuous Position Monitor

| Field | Detail |
|---|---|
| **Purpose** | Evaluates every open position on every tick (tick-level checks) and on every completed bar (bar-level checks). Triggers exits when thresholds are breached. Operates independently of the strategy that created the entry. |
| **Inputs** | Tick events from Layer 3; completed bars from Layer 4; feature snapshots from Layer 7; current positions from `intraday_positions`; session risk from Layer 16 |
| **Outputs** | `MonitorEvent(position_id, check_type, result, action)` written to `position_monitor_events`; exit orders submitted to Layer 17 |
| **Dependencies** | Layers 3, 4, 7, 16, 17 |
| **Storage** | `position_monitor_events` table; exit orders in `intraday_paper_orders` |
| **Failure behavior** | If monitor cannot evaluate a position (e.g., stale data), emit Critical alert; do NOT assume position is safe |
| **Recovery behavior** | On restart: reload all open positions from `intraday_positions`; reattach all monitoring rules from `entry_features_frozen` |
| **Implementation** | `[PROPOSED]` New module: `intraday_position_monitor.py`. Independent of strategy modules. |
| **Language/process** | Python (FastAPI process) |

See §5 for the full check list.

---

### Layer 20 — Independent System Watchdog

| Field | Detail |
|---|---|
| **Purpose** | Monitors the health of all other layers and external dependencies. Operates in a separate thread or process, independent of all strategy logic. |
| **Inputs** | Heartbeat timestamps from Layers 2, 4, 11, 17, 19; system resource metrics; PostgreSQL health probe |
| **Outputs** | `HeartbeatRecord` to `system_heartbeats`; alerts via Layer 21; kill-switch trigger if escalation threshold reached |
| **Dependencies** | `system_heartbeats` table; `intraday_alert_manager.py` |
| **Storage** | `system_heartbeats`, `reconciliation_events` tables |
| **Failure behavior** | If the Watchdog itself fails to write a heartbeat, this constitutes an Incident-level event |
| **Recovery behavior** | Watchdog restarts automatically; reads last known state from `system_heartbeats` |
| **Implementation** | `[PARTIAL]` — `phase20_scheduler.py` `[OBSERVED]` has a basic heartbeat using owner/pid fields. Full independent Watchdog is `[PROPOSED]` as a new module: `intraday_watchdog.py` |
| **Language/process** | Python (separate thread within FastAPI) or Node.js (separate process) |

See §6 for full specification.

---

### Layer 21 — Incident and Alert Manager

| Field | Detail |
|---|---|
| **Purpose** | Receives structured alert events from all layers. Deduplicates, stores, and routes alerts to delivery channels (Expo push, email). Manages incidents separately from alerts. |
| **Inputs** | `AlertEvent(kind, severity, symbol, message, auto_action)` from any layer |
| **Outputs** | Persisted `intraday_alert_deliveries` records; push notifications; incident records in `intraday_incidents` |
| **Dependencies** | `intraday_alert_deliveries`, `intraday_push_subscriptions` tables; Expo push API |
| **Storage** | `intraday_alert_deliveries`, `intraday_incidents` tables |
| **Failure behavior** | Alert delivery failure is retried with exponential backoff; never drops an alert without recording it |
| **Recovery behavior** | On restart: resume retry queue from `intraday_alert_deliveries` where `status != DELIVERED` |
| **Implementation** | `[PARTIAL]` — `alert_queue.py` and `alertQueue.ts` `[OBSERVED]` exist for swing. Intraday needs separate tables and separate instances. New module: `intraday_alert_manager.py` + `intradayAlertQueue.ts` |
| **Language/process** | Python (alert creation) + Node.js (delivery) |

---

### Layer 22 — Trade Journal and Audit Trail

| Field | Detail |
|---|---|
| **Purpose** | Write-once, append-only record of every decision, signal, order, fill, exit, and monitoring event. Records the exact feature snapshot frozen at entry time. |
| **Inputs** | Events from every other layer |
| **Outputs** | Records in `intraday_audit_logs`; `trade_journal_entries` |
| **Dependencies** | All layers (event listener) |
| **Storage** | `intraday_audit_logs` table (append-only, never updated) |
| **Failure behavior** | If audit write fails, log to stderr and continue; do NOT block trade execution for audit |
| **Recovery behavior** | Audit log is immutable; no recovery needed |
| **Implementation** | `[PARTIAL]` — `trade_intelligence.py` `[OBSERVED]` has feature freezing for swing. New module: `intraday_audit.py` |
| **Language/process** | Python / PostgreSQL |

---

### Layer 23 — Learning and Model Governance Pipeline

| Field | Detail |
|---|---|
| **Purpose** | Collects outcomes for completed intraday trades. Trains and evaluates updated calibration models. Enforces governance gates before any model update. |
| **Inputs** | Completed trades from `intraday_paper_fills`; feature snapshots from `feature_snapshots` |
| **Outputs** | Updated `Intraday_Calibration_v{N}.pkl`; drift reports; governance approval requests |
| **Dependencies** | Layer 14 (Calibration Service); `intraday_models/`; governance configuration |
| **Storage** | Model artifacts; `model_governance_log` table |
| **Failure behavior** | If validation metrics fail, reject new model; keep current version |
| **Recovery behavior** | Always rolls back to previous model version if new model validation fails |
| **Implementation** | `[PARTIAL]` — `phase14_governance.py` `[OBSERVED]` provides governance framework for swing. Intraday needs a separate model pipeline. New module: `intraday_governance.py` |
| **Language/process** | Python (offline/batch — not in the hot path) |

**Retraining prerequisites (proposed):**
- Minimum 200 completed intraday paper trades with known outcomes
- Calibration Brier score < 0.25 on validation set
- Human approval gate before deployment

---

### Layer 24 — Intraday Dashboard

| Field | Detail |
|---|---|
| **Purpose** | Real-time web interface for monitoring the intraday session, positions, system health, and manual controls. |
| **Inputs** | WebSocket feed from Node.js WebSocket server; REST API from Intraday API server |
| **Outputs** | Rendered UI for operator |
| **Dependencies** | Node.js WebSocket server; Intraday API server; React/Vite build system |
| **Storage** | Stateless (reads from API) |
| **Failure behavior** | Reconnect WebSocket with backoff; show stale-data indicator |
| **Recovery behavior** | Reconnect and re-fetch state from API |
| **Implementation** | `[PROPOSED]` New React/Vite artifact. See §16 for page specification. |
| **Language/process** | React/Vite (Node.js dev server) |

---

### Layer 25 — Session Replay and Reporting

| Field | Detail |
|---|---|
| **Purpose** | Post-session analysis tool. Replays all bars, signals, entries, exits, and monitoring events for a completed session in chronological order. |
| **Inputs** | `minute_ohlcv_cache`, `intraday_signals`, `intraday_paper_orders`, `position_monitor_events` for a given `session_id` |
| **Outputs** | Rendered time-series chart with overlaid signals and events; session performance summary |
| **Dependencies** | PostgreSQL query layer; charting library |
| **Storage** | Reads from existing tables; no additional storage |
| **Failure behavior** | If bar data is missing, show gap indicator; do not fabricate bars |
| **Recovery behavior** | N/A — replay is read-only |
| **Implementation** | `[PROPOSED]` New page: `SessionReplay.tsx` in the Intraday Dashboard |
| **Language/process** | React/Vite |

---

## 3. Runtime and Service Boundaries

### 3.1 Current Problem

`[OBSERVED]` The existing platform spawns Python as a child process per request using `child_process.spawn` in `src/routes/trading.ts`, `src/routes/kite.ts`, and `src/routes/phase22.ts`. Cold-start overhead is 400–800 ms per invocation. This is acceptable for swing trading (scans run every few minutes) but unacceptable for intraday, which requires:

- Persistent WebSocket connection to Kite
- Sub-second tick processing
- Per-minute bar building across 50–100 symbols
- Continuous position monitoring on every tick

### 3.2 Option Comparison

| Factor | Long-running FastAPI | gRPC Python Service |
|---|---|---|
| Latency | ~5–10 ms HTTP overhead | ~1–3 ms protobuf overhead |
| Setup complexity | Low — standard HTTP | High — proto schemas, codegen, streaming setup |
| Debugging | Standard HTTP tools (curl, Postman) | Requires gRPC tooling |
| Node.js integration | Standard `fetch` or `axios` | Requires `@grpc/grpc-js` + generated stubs |
| Streaming support | SSE or WebSocket bridging needed | Native bidirectional streaming |
| Operational visibility | Standard health endpoints | Needs reflection or separate health endpoint |
| V1 fit | ✅ Sufficient — latency budget is 2s end-to-end | ❌ Premature — latency gains not needed at this scale |

**Recommendation: Long-running FastAPI service for v1.**

FastAPI's asyncio model handles concurrent tick processing and bar building naturally. The 2-second end-to-end latency budget is achievable with HTTP. gRPC should be reconsidered only if tick volume exceeds 10 000 ticks/second per symbol or if the latency budget tightens below 500 ms.

### 3.3 Service Boundary Definitions

#### Node.js API Server (`artifacts/api-server`)
- Serves the Intraday REST API at `/intraday/api/v1/`
- Authentication and request validation
- Proxies strategy commands to the Python FastAPI service
- Runs the Node.js WebSocket server for frontend real-time updates
- Manages the alert delivery queue (`intradayAlertQueue.ts`)
- Health endpoint: `GET /intraday/api/v1/health`

#### Python FastAPI Trading Engine (new — `intraday_engine.py`)
- Runs as a **persistent process** (not spawned per request)
- Owns Layers 1–23 of the trading pipeline
- Exposes internal REST endpoints on `localhost:8001` (not internet-facing)
- Manages the KiteTicker WebSocket connection
- Runs the bar builder, feature store, signal engine, position monitor, and watchdog as async background tasks
- Health endpoint: `GET http://localhost:8001/health`

#### Node.js WebSocket Server
- Subscribes to internal events from the Python FastAPI engine (via Redis pub/sub or direct HTTP SSE — unresolved, see §20)
- Broadcasts session updates, tick snapshots, position changes, and alerts to connected dashboard clients
- Endpoint: `ws://[host]/intraday/ws`

#### Watchdog (Layer 20)
- Runs as an asyncio background task within the FastAPI process in v1
- If FastAPI process crashes, the Watchdog also dies — this is an acceptable v1 limitation
- V2: consider a separate watchdog process or systemd-style supervisor

#### PostgreSQL
- Source of truth for all durable state
- Recovery source for all mid-session restarts
- Never bypassed by in-memory state for any durable decision

#### Frontend Real-Time Communication
- Dashboard connects to Node.js WebSocket server
- Tick rate: position updates ≤ every 1s; system health ≤ every 5s; bars on completion
- Stale data indicator if WebSocket silent for > 5s

#### Health-Check Endpoints

| Endpoint | Owner | Checks |
|---|---|---|
| `GET /intraday/api/v1/health` | Node.js | DB connectivity, FastAPI reachability, scheduler state |
| `GET http://localhost:8001/health` | FastAPI | WS state, last tick age, open position count, bar builder state |
| `GET /intraday/api/v1/watchdog` | Node.js (proxied) | Watchdog last heartbeat age, alert backlog depth |

#### Startup Sequence

```
1. PostgreSQL available (pre-condition)
2. FastAPI engine starts
   → Loads session store (create or load today's session)
   → Starts bar builder (loads last complete bar from DB)
   → Reconnects to Kite WebSocket
   → Starts position monitor (loads open positions from DB)
   → Starts watchdog
   → Marks engine as READY
3. Node.js API server starts
   → Probes FastAPI /health
   → Starts Node WebSocket server
   → Starts alert delivery queue
4. Frontend connects to WebSocket
```

#### Shutdown Sequence

```
1. SIGTERM received by FastAPI
2. Pause new entries (kill-switch: PAUSE_ENTRIES)
3. Write engine state to intraday_sessions (status=SHUTDOWN_PENDING)
4. Flush pending audit log writes
5. Close KiteTicker WebSocket gracefully
6. FastAPI exits
7. Node.js receives SIGTERM, drains alert queue, exits
```

---

## 4. Mid-Session Recovery Architecture

### 4.1 Recovery Source of Truth

PostgreSQL is the exclusive recovery source. No JSON file state may be used for recovery.

### 4.2 State That Must Be Recoverable

| State | PostgreSQL Location |
|---|---|
| Current intraday session | `intraday_sessions` (keyed by today's date) |
| Open paper positions | `intraday_positions WHERE status = 'OPEN'` |
| Pending paper orders | `intraday_paper_orders WHERE status IN ('PENDING', 'PARTIALLY_FILLED')` |
| Stop and target levels | `intraday_positions.stop_price`, `.target_price` |
| Entry-time frozen features | `intraday_positions.entry_features_frozen` (JSONB) |
| Maximum holding timer | `intraday_positions.max_hold_exit_at` |
| Square-off timer | Derived from `intraday_sessions.date` + hard-coded 15:15 |
| Latest completed bars | `minute_ohlcv_cache` (last N bars per symbol) |
| WS subscription state | Derived from `intraday_positions.symbol` (symbols with open positions must be subscribed) |
| Risk usage | Derived from `intraday_positions` (open risk) + `intraday_paper_fills` (realized P&L) |
| Session P&L | Derived from `intraday_paper_fills WHERE session_id = current_session_id` |

### 4.3 Restart Flow

```
FastAPI process starts
│
├─ 1. LOAD SESSION
│   Query intraday_sessions WHERE date = today()
│   If found → resume with existing session_id
│   If not found → create new session record (pre-market only)
│   If status = 'INCIDENT' → enter SAFE_MODE (see below)
│
├─ 2. RESTORE STATE
│   Load open positions (intraday_positions WHERE status = 'OPEN')
│   Load pending orders (intraday_paper_orders WHERE status = 'PENDING')
│   Recompute in-memory risk state (open risk, realized P&L)
│   Load latest completed bars from minute_ohlcv_cache
│   Reload frozen entry features from intraday_positions.entry_features_frozen
│
├─ 3. RECONNECT MARKET DATA
│   Connect KiteTicker WebSocket (Layer 2)
│   Subscribe to: (a) symbols with open positions, (b) configured watchlist
│   Wait for first tick per subscribed symbol (max 30s)
│   If tick not received for a position symbol → alert WARNING
│
├─ 4. RECONCILE POSITIONS AND ORDERS
│   For each open position: verify symbol is subscribed and ticks are flowing
│   For each pending order: check if fill should have occurred during downtime
│     → If LTP crossed entry price during gap: simulate fill at last known price
│     → If ambiguous: mark as NEEDS_REVIEW, do not fill automatically
│   Write reconciliation results to reconciliation_events
│
├─ 5. RESTORE MONITORING
│   Attach position monitoring rules to all open positions (from entry_features_frozen)
│   Start watchdog
│   Start bar builder (resumes from last complete bar)
│
└─ 6. RESUME OR SAFE MODE
    If reconciliation has no NEEDS_REVIEW items → resume normal operation
    If NEEDS_REVIEW items exist → enter SAFE_MODE:
      - Block all new entries
      - Continue monitoring open positions
      - Alert operator to review reconciliation_events
      - Operator manually approves or rejects each NEEDS_REVIEW item
```

### 4.4 Safe Mode

Safe mode allows the session to continue monitoring existing positions while blocking new entries. It is the default state after any non-clean restart. A dashboard control allows the operator to exit safe mode once reconciliation is reviewed.

---

## 5. Continuous Trade Monitoring

The Position Monitor (Layer 19) is a first-class service independent from strategy logic.

### 5.1 Tick-Level Checks (every tick, per open position)

| Check | Logic | Action on Breach |
|---|---|---|
| Stop-loss | `ltp ≤ position.stop_price (long) or ltp ≥ position.stop_price (short)` | Immediate exit order |
| Profit target | `ltp ≥ position.target_price (long) or ltp ≤ position.target_price (short)` | Immediate exit order |
| Abnormal spread | `(ask - bid) / bid > spread_threshold_pct` | Pause exit via limit; use market if spread persists > 30s |
| Tradability | Last tick age > 120s for this symbol | Alert WARNING; block new entries for symbol |
| NSE circuit | Tick has `lower_circuit` or `upper_circuit` flag from KiteTicker | Alert CRITICAL; attempt immediate exit; log if exit blocked by circuit |

### 5.2 Completed-Bar Checks (on each completed 1-min bar, per open position)

| Check | Logic | Action on Breach |
|---|---|---|
| Maximum holding time | `now() > position.max_hold_exit_at` | Exit at market |
| Thesis invalidation | `strategy.is_thesis_intact()` returns False | Exit at limit (aggressive) |
| VWAP failure | Long: `close < vwap` for 3 consecutive bars | Exit at limit |
| ORB failure | Price re-enters opening range after breakout | Exit at limit |
| Momentum deterioration | ADX < 15 for 3 consecutive bars on a trend trade | Exit at limit |
| Regime deterioration | Regime changes from entry regime to `VOLATILE` or `UNCERTAIN` | Exit at limit |
| Time-of-day exit | `time >= 14:45` and position unrealized P&L < 0 | Exit at limit |

### 5.3 Portfolio-Level Checks (on each completed bar)

| Check | Logic | Action on Breach |
|---|---|---|
| Daily loss cap | `session_realized_pnl < -(capital × daily_loss_cap_pct)` | Trigger PAUSE_ENTRIES; alert CRITICAL |
| Max open positions | `open_positions_count > max_open_positions` | Block new entries |
| Sector exposure | Any sector > 60% of total open risk | Block new entries in that sector |
| Correlation exposure | Two highly correlated positions open simultaneously | Alert WARNING |
| Capital at risk | `total_open_risk > session_capital × max_total_risk_pct` | Block new entries |
| Mandatory square-off boundary | `time >= 15:15` | Trigger square-off escalation (see §8) |

---

## 6. Independent Watchdog

### 6.1 Monitored Dimensions

| Dimension | Stale Threshold | Escalation |
|---|---|---|
| Trading engine heartbeat | 30s | WARNING → CRITICAL at 60s → Incident at 120s |
| Market data service heartbeat | 30s | WARNING → CRITICAL at 60s |
| WebSocket state | `WS_DISCONNECTED` event | WARNING immediately; CRITICAL if not reconnected in 60s |
| Last tick age per active symbol | 30s | WARNING; if position open → CRITICAL |
| Last completed-bar age | 90s during market hours | WARNING |
| FastAPI liveness | `GET localhost:8001/health` fails | WARNING; CRITICAL at 60s |
| Node API liveness | `GET /intraday/api/v1/health` fails | WARNING |
| PostgreSQL health | `SELECT 1` fails | CRITICAL immediately |
| Memory usage | RSS > 80% of container limit | WARNING |
| Position reconciliation | Open position count in DB ≠ in-memory count | CRITICAL |
| Square-off completion | Position still open at 15:20 IST | INCIDENT |
| Watchdog's own heartbeat | Written every 15s | If gap > 45s in `system_heartbeats`: INCIDENT |

### 6.2 Heartbeat Specification

- **Frequency:** Every 15 seconds
- **Source:** `intraday_watchdog.py` background async task
- **Target:** `system_heartbeats` PostgreSQL table
- **Fields:** `ts`, `component`, `status`, `details_json`

### 6.3 Escalation Behavior

```
WARNING   → Log + Expo push notification to operator
CRITICAL  → Log + Expo push + attempt automatic mitigation (e.g., trigger reconnect)
INCIDENT  → Log + Expo push + email + disable new trading + write to intraday_incidents
```

---

## 7. Kill-Switch Policy

### 7.1 Pause New Entries

**Effect:** All new entry signals are blocked. Existing open positions continue to be monitored normally.

| Property | Specification |
|---|---|
| Trigger (automatic) | Daily loss cap breached; engine heartbeat CRITICAL; risk engine error |
| Trigger (manual) | Operator clicks "Pause Entries" on dashboard; API call with valid auth token |
| Authentication | Bearer token required for API call; dashboard requires session auth |
| Confirmation | No confirmation required — non-destructive action |
| Idempotency | Setting PAUSE when already PAUSED is a no-op |
| Reversible? | Yes — operator can resume via "Resume Entries" control |
| Audit | Every state change written to `intraday_audit_logs` with timestamp and actor |
| Dashboard | Status pill "PAUSED" displayed in session status header; resume button visible |

### 7.2 Cancel Pending Orders

**Effect:** All orders with status `PENDING` in `intraday_paper_orders` are cancelled. Open positions continue to be monitored and protected.

| Property | Specification |
|---|---|
| Trigger (automatic) | Square-off at 15:15:30 (step 2); WebSocket disconnected for > 60s |
| Trigger (manual) | Operator clicks "Cancel Pending Orders" on dashboard |
| Authentication | Bearer token required |
| Confirmation | One-click confirmation dialog in dashboard |
| Idempotency | Cancelling when no pending orders is a no-op |
| Reversible? | No — cancelled orders must be re-created manually |
| Audit | Each cancellation written to `intraday_audit_logs` |
| Dashboard | Pending orders section shows count; button enabled only when count > 0 |

### 7.3 Flatten All

**Effect:** Cancels all pending orders AND submits exit orders for every open position using the emergency execution policy. This is the most destructive action.

| Property | Specification |
|---|---|
| Trigger (automatic) | 15:20 IST (any position still open); position mismatch INCIDENT; watchdog INCIDENT |
| Trigger (manual) | Operator clicks "Flatten All" on dashboard |
| Authentication | Bearer token required |
| Confirmation | Two-step confirmation: "Type FLATTEN to confirm" |
| Idempotency | Flatten when no open positions: only cancels pending orders |
| Reversible? | No — exit fills cannot be undone |
| Audit | Full audit record: who triggered, when, positions affected, fills executed |
| Dashboard | Red "FLATTEN ALL" button in emergency controls panel; requires confirmation modal |

---

## 8. Square-Off Escalation

All times are IST. All times are enforced by the position monitor (Layer 19) and the watchdog (Layer 20), independently. A process restart cannot bypass square-off — the restart flow reloads open positions and immediately checks the time.

### Step 1 — 15:15:00 IST

- For every open position: submit an exit limit order at `LTP ± 0.05%` (favorable limit).
- Trigger `PAUSE_ENTRIES` if not already active.
- Write event to `position_monitor_events`.

### Step 2 — 15:15:30 IST

- For each position where Step 1 order is still `PENDING` or `PARTIALLY_FILLED`:
  - Cancel the limit order.
  - Resubmit as a market order (emergency execution policy).
  - Alert: CRITICAL — "Square-off retry: market order submitted for {symbol}".

### Step 3 — 15:16:00 IST

- Repeat Step 2 for any remaining open positions.
- Alert: CRITICAL — "Square-off escalation step 3 for {symbol}".
- Write incident record if any position remains.

### Step 4 — 15:20:00 IST

- For any position still marked `OPEN`:
  - Write INCIDENT record to `intraday_incidents`.
  - Disable all new trading until the incident is manually resolved.
  - Alert: INCIDENT — "Position {symbol} open after market close. Manual review required."

### Edge Cases

| Scenario | Behavior |
|---|---|
| Exchange outage | Order cannot be submitted; mark as `SUBMIT_FAILED`; retry at next step; escalate to Incident at 15:20 |
| Broker outage | Same as exchange outage |
| Stock in price band (circuit) | Exit order cannot fill; alert CRITICAL; mark as `CIRCUIT_BLOCKED`; escalate to Incident |
| No liquidity | Market order may partially fill; mark remaining as `PARTIAL_FILL`; retry fill for remainder at each step |
| Rejected order | Log rejection reason; resubmit without the rejected parameter |
| Partial fill | Track filled quantity separately; submit exit order only for remaining open quantity |
| Network failure | If FastAPI cannot reach the DB to submit the order: watchdog detects and escalates independently |
| Process restart during square-off | Recovery flow (§4) detects position is still open AND time > 15:15; immediately executes square-off escalation from the appropriate step |

---

## 9. Data Architecture

All tables belong to the intraday database. No shared tables with the swing platform.

> **Note:** This section defines the intended schema. No migrations have been created. Primary keys, indexes, and retention are specified here as requirements.

---

### `intraday_sessions`

| Column | Type | Notes |
|---|---|---|
| `session_id` | UUID PK | Generated at session creation |
| `date` | DATE UNIQUE | NSE trading date; UNIQUE constraint prevents duplicate sessions |
| `status` | TEXT | `PRE_OPEN`, `OPEN`, `CLOSED`, `INCIDENT` |
| `open_ts` | TIMESTAMPTZ | Actual market open (09:15 IST) |
| `close_ts` | TIMESTAMPTZ | Actual market close (15:30 IST) |
| `regime` | TEXT | Last known regime tag |
| `session_capital` | NUMERIC(15,2) | Capital allocated for this session |
| `realized_pnl` | NUMERIC(15,2) | Running realized P&L |
| `risk_used_pct` | NUMERIC(5,4) | Fraction of risk cap consumed |
| `square_off_completed` | BOOLEAN | True when all positions exited |
| `created_at` | TIMESTAMPTZ | Auto |

**Indexes:** `date` (unique); `status`  
**Retention:** Permanent  
**Recovery importance:** Critical — primary recovery anchor

---

### `minute_ohlcv_cache`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK → `intraday_sessions` | |
| `symbol` | TEXT | NSE symbol |
| `bar_ts` | TIMESTAMPTZ | Start of the 1-minute bar |
| `open` | NUMERIC(10,2) | |
| `high` | NUMERIC(10,2) | |
| `low` | NUMERIC(10,2) | |
| `close` | NUMERIC(10,2) | |
| `volume` | BIGINT | |
| `vwap` | NUMERIC(10,4) | Cumulative session VWAP at bar close |
| `is_gap_bar` | BOOLEAN | True if tick gap > 2 min |

**Indexes:** `(session_id, symbol, bar_ts)` unique; `(symbol, bar_ts DESC)`  
**Retention:** 90 days (older bars can be archived)  
**Recovery importance:** High — used to reconstruct feature snapshots on restart

---

### `intraday_tick_summaries`

Compressed per-second tick summaries (not raw ticks — raw tick volume at 100 symbols × 1 tick/s is too large for v1).

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK | |
| `symbol` | TEXT | |
| `ts` | TIMESTAMPTZ | Tick timestamp (truncated to second) |
| `ltp` | NUMERIC(10,2) | |
| `bid` | NUMERIC(10,2) | |
| `ask` | NUMERIC(10,2) | |
| `volume_traded` | BIGINT | Cumulative volume |

**Indexes:** `(session_id, symbol, ts)`  
**Retention:** 7 days  
**Recovery importance:** Low — bars are the recovery source

---

### `feature_snapshots`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK | |
| `symbol` | TEXT | |
| `bar_ts` | TIMESTAMPTZ | Timestamp of the completed bar that triggered this snapshot |
| `features` | JSONB | All computed features: VWAP, RVOL, ATR, ADX, ORB status, gap, TOD encoding, etc. |
| `regime` | TEXT | Regime at time of snapshot |
| `data_quality` | TEXT | Data quality status at time of snapshot |
| `created_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, symbol, bar_ts DESC)` unique; `(session_id, bar_ts DESC)`  
**Retention:** 30 days  
**Recovery importance:** Medium — used to restore feature context on restart

---

### `intraday_signals`

| Column | Type | Notes |
|---|---|---|
| `signal_id` | UUID PK | |
| `session_id` | UUID FK | |
| `symbol` | TEXT | |
| `strategy_id` | TEXT | Strategy that generated this signal |
| `direction` | TEXT | `LONG` or `SHORT` |
| `entry_price` | NUMERIC(10,2) | Signal entry price |
| `stop_price` | NUMERIC(10,2) | |
| `target_price` | NUMERIC(10,2) | |
| `confidence` | NUMERIC(5,4) | Final calibrated confidence |
| `is_calibrated` | BOOLEAN | |
| `ev` | NUMERIC(10,4) | Expected net value |
| `features_frozen` | JSONB | Feature snapshot at signal creation |
| `data_quality` | TEXT | |
| `status` | TEXT | `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED` |
| `rejection_reason` | TEXT | |
| `created_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, symbol, created_at DESC)`; `strategy_id`; `status`  
**Retention:** Permanent  
**Recovery importance:** Medium

---

### `strategy_decisions`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `signal_id` | UUID FK → `intraday_signals` | |
| `session_id` | UUID FK | |
| `decision` | TEXT | `APPROVE`, `REJECT` |
| `gate_results` | JSONB | Result of each gate check |
| `risk_snapshot_id` | BIGINT FK → `risk_snapshots` | Risk state at decision time |
| `decided_at` | TIMESTAMPTZ | |

**Indexes:** `signal_id`; `session_id`  
**Retention:** Permanent  
**Recovery importance:** Low

---

### `intraday_paper_orders`

| Column | Type | Notes |
|---|---|---|
| `order_id` | UUID PK | |
| `session_id` | UUID FK | |
| `signal_id` | UUID FK → `intraday_signals` | |
| `symbol` | TEXT | |
| `direction` | TEXT | `BUY` / `SELL` |
| `order_type` | TEXT | `LIMIT` / `MARKET` |
| `quantity` | INT | |
| `limit_price` | NUMERIC(10,2) | Null for MARKET |
| `status` | TEXT | `PENDING`, `FILLED`, `PARTIALLY_FILLED`, `CANCELLED`, `REJECTED`, `SUBMIT_FAILED` |
| `is_exit_order` | BOOLEAN | True for stop/target/square-off orders |
| `exit_reason` | TEXT | `STOP_HIT`, `TARGET_HIT`, `THESIS_INVALID`, `SQUARE_OFF`, `MANUAL` |
| `submitted_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, symbol, status)`; `signal_id`; `is_exit_order`  
**Retention:** Permanent  
**Recovery importance:** Critical

---

### `intraday_paper_fills`

| Column | Type | Notes |
|---|---|---|
| `fill_id` | UUID PK | |
| `order_id` | UUID FK → `intraday_paper_orders` | |
| `session_id` | UUID FK | |
| `symbol` | TEXT | |
| `quantity` | INT | |
| `fill_price` | NUMERIC(10,2) | |
| `slippage_pct` | NUMERIC(6,5) | |
| `cost_breakdown` | JSONB | Full NSE cost breakdown |
| `net_cost` | NUMERIC(10,4) | Total cost in ₹ |
| `filled_at` | TIMESTAMPTZ | |

**Indexes:** `order_id`; `session_id`; `(session_id, symbol)`  
**Retention:** Permanent  
**Recovery importance:** Critical — source for P&L reconstruction

---

### `intraday_positions`

| Column | Type | Notes |
|---|---|---|
| `position_id` | UUID PK | |
| `session_id` | UUID FK | |
| `signal_id` | UUID FK → `intraday_signals` | |
| `symbol` | TEXT | |
| `direction` | TEXT | `LONG` / `SHORT` |
| `quantity` | INT | |
| `entry_price` | NUMERIC(10,2) | |
| `stop_price` | NUMERIC(10,2) | |
| `target_price` | NUMERIC(10,2) | |
| `entry_features_frozen` | JSONB | Feature snapshot at entry — immutable |
| `max_hold_exit_at` | TIMESTAMPTZ | Time-based exit deadline |
| `status` | TEXT | `OPEN`, `CLOSED`, `INCIDENT` |
| `exit_price` | NUMERIC(10,2) | Null until closed |
| `exit_reason` | TEXT | |
| `realized_pnl` | NUMERIC(10,4) | Net P&L after all costs |
| `opened_at` | TIMESTAMPTZ | |
| `closed_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, status)`; `(session_id, symbol)` partial unique where status = `OPEN`; `signal_id`  
**Retention:** Permanent  
**Recovery importance:** Critical

---

### `position_monitor_events`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `position_id` | UUID FK → `intraday_positions` | |
| `session_id` | UUID FK | |
| `check_type` | TEXT | e.g., `STOP_LOSS`, `THESIS_CHECK`, `VWAP_FAILURE` |
| `check_level` | TEXT | `TICK` or `BAR` |
| `result` | TEXT | `PASS`, `BREACH`, `WARNING` |
| `action` | TEXT | `NONE`, `EXIT_SUBMITTED`, `ALERT_RAISED` |
| `details` | JSONB | Values at time of check |
| `checked_at` | TIMESTAMPTZ | |

**Indexes:** `(position_id, checked_at DESC)`; `(session_id, result)`  
**Retention:** 30 days  
**Recovery importance:** Low

---

### `risk_snapshots`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK | |
| `snapshot_at` | TIMESTAMPTZ | |
| `open_positions_count` | INT | |
| `total_open_risk_pct` | NUMERIC(5,4) | |
| `session_realized_pnl` | NUMERIC(12,2) | |
| `daily_loss_cap_pct` | NUMERIC(5,4) | |
| `risk_headroom_pct` | NUMERIC(5,4) | |
| `entries_paused` | BOOLEAN | |
| `pause_reason` | TEXT | |

**Indexes:** `(session_id, snapshot_at DESC)`  
**Retention:** 30 days  
**Recovery importance:** Low — reconstructed from positions on restart

---

### `model_predictions`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `signal_id` | UUID FK → `intraday_signals` | |
| `session_id` | UUID FK | |
| `model_version` | TEXT | e.g., `Intraday_Calibration_v3` |
| `raw_score` | NUMERIC(5,4) | Pre-calibration heuristic score |
| `calibrated_prob` | NUMERIC(5,4) | Post-calibration probability |
| `is_calibrated` | BOOLEAN | |
| `predicted_at` | TIMESTAMPTZ | |

**Indexes:** `signal_id`; `model_version`  
**Retention:** Permanent (training data)  
**Recovery importance:** Low

---

### `calibration_predictions`

Mirrors `model_predictions` with outcome linkage for training data collection.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `signal_id` | UUID FK | |
| `model_version` | TEXT | |
| `calibrated_prob` | NUMERIC(5,4) | |
| `actual_outcome` | TEXT | `WIN`, `LOSS`, `BREAKEVEN` — populated after position close |
| `outcome_pnl` | NUMERIC(10,4) | |
| `outcome_recorded_at` | TIMESTAMPTZ | |

**Indexes:** `signal_id`; `(model_version, actual_outcome)`  
**Retention:** Permanent  
**Recovery importance:** Low

---

### `system_heartbeats`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `component` | TEXT | `watchdog`, `bar_builder`, `ws_ingestion`, `position_monitor`, etc. |
| `status` | TEXT | `HEALTHY`, `DEGRADED`, `DOWN` |
| `details` | JSONB | Component-specific health data |
| `ts` | TIMESTAMPTZ | |

**Indexes:** `(component, ts DESC)`  
**Retention:** 24 hours  
**Recovery importance:** Low (monitoring only)

---

### `reconciliation_events`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK | |
| `position_id` | UUID FK | |
| `event_type` | TEXT | `FILL_GAP_DETECTED`, `POSITION_MISMATCH`, `ORDER_STATUS_UNKNOWN` |
| `status` | TEXT | `NEEDS_REVIEW`, `RESOLVED_AUTO`, `RESOLVED_MANUAL` |
| `details` | JSONB | |
| `detected_at` | TIMESTAMPTZ | |
| `resolved_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, status)`  
**Retention:** Permanent  
**Recovery importance:** High

---

### `intraday_incidents`

| Column | Type | Notes |
|---|---|---|
| `incident_id` | UUID PK | |
| `session_id` | UUID FK | |
| `kind` | TEXT | `POSITION_OPEN_AFTER_CLOSE`, `RECONCILIATION_FAILURE`, `WATCHDOG_FAILURE` |
| `severity` | TEXT | `INCIDENT` |
| `description` | TEXT | |
| `auto_action_taken` | TEXT | |
| `status` | TEXT | `OPEN`, `ACKNOWLEDGED`, `RESOLVED` |
| `created_at` | TIMESTAMPTZ | |
| `resolved_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, status)`; `kind`  
**Retention:** Permanent  
**Recovery importance:** High

---

### `intraday_alert_deliveries`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `idempotency_key` | TEXT UNIQUE | Prevents duplicate delivery |
| `session_id` | UUID FK | |
| `kind` | TEXT | Alert category |
| `severity` | TEXT | `INFO`, `WARNING`, `CRITICAL`, `INCIDENT` |
| `symbol` | TEXT | Nullable |
| `message` | TEXT | |
| `channel` | TEXT | `PUSH`, `EMAIL`, `LOG` |
| `status` | TEXT | `PENDING`, `DELIVERED`, `FAILED`, `DEAD_LETTER` |
| `attempts` | INT | |
| `next_retry_at` | TIMESTAMPTZ | |
| `delivered_at` | TIMESTAMPTZ | |

**Indexes:** `idempotency_key` (unique); `(status, next_retry_at)`; `session_id`  
**Retention:** 30 days  
**Recovery importance:** Medium

---

### `intraday_audit_logs`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `session_id` | UUID FK | |
| `event_type` | TEXT | `SIGNAL_CREATED`, `ORDER_SUBMITTED`, `FILL_RECORDED`, `GATE_REJECTED`, `KILL_SWITCH`, etc. |
| `actor` | TEXT | `system`, `watchdog`, `operator:{user_id}` |
| `entity_type` | TEXT | `signal`, `order`, `position`, `session` |
| `entity_id` | TEXT | UUID of the referenced entity |
| `payload` | JSONB | Full event payload — immutable |
| `created_at` | TIMESTAMPTZ | |

**Indexes:** `(session_id, created_at DESC)`; `(entity_type, entity_id)`; `event_type`  
**Retention:** Permanent (write-once, append-only)  
**Recovery importance:** Low (audit, not recovery source)

---

## 10. Feature and Strategy Architecture

### 10.1 V1 Feature Set

| Feature | Description | Implementation |
|---|---|---|
| Session-reset VWAP | `Σ(price × volume) / Σ(volume)` from 09:15 each session | New: `intraday_vwap_engine.py` |
| VWAP standard-deviation bands | ±1σ and ±2σ bands from VWAP | Same module |
| Relative volume by time slot | Volume vs. 20-day rolling average for the same 5-min slot | New: `intraday_rvol_calculator.py` |
| Opening range (15-min) | High and low of bars from 09:15 to 09:30 | New: `intraday_orb_detector.py` |
| Opening range (30-min) | High and low of bars from 09:15 to 09:45 | Same module |
| Gap percentage | `(today open - yesterday close) / yesterday close` | New: `intraday_gap_analyser.py` |
| Gap type | `GAP_UP`, `GAP_DOWN`, `FLAT` (< 0.3% gap) | Same module |
| Time-of-day encoding | Minute-of-session / total session minutes (0.0–1.0) | Feature store |
| ATR (14-bar) | Average True Range on 1-min bars | Feature store |
| ATR volatility percentile | ATR rank in 20-day rolling distribution | Feature store |
| ADX (14-bar) | Average Directional Index on 1-min bars | Feature store |
| Directional movement (+DI, -DI) | DI components of ADX | Feature store |
| Bid-ask spread pct | `(ask - bid) / bid` from live tick | Feature store |
| Liquidity gate | `volume_last_bar > min_liquidity_threshold` | Feature store |
| NIFTY trend | NIFTY 50 1-min slope (linear regression, 5-bar) | Feature store |
| NIFTY volatility | NIFTY ATR | Feature store |
| Sector-relative strength | Symbol return vs. sector ETF return (intraday) | Deferred — no sector ETF data source confirmed |

### 10.2 V1 Strategy Specifications

#### Opening Range Breakout (ORB)
- Entry: Price closes above (long) or below (short) the 15-min or 30-min opening range
- Filter: RVOL ≥ 1.5; ATR percentile ≥ 50th; ADX > 20
- Stop: Midpoint of opening range
- Target: 1.5× risk (minimum 0.5% move)
- Regime: `TRENDING_UP` (long), `TRENDING_DOWN` (short)
- No entry after: 11:00 IST

#### Momentum Burst
- Entry: 3 consecutive bullish bars with increasing volume; RVOL ≥ 2.0
- Filter: Price > VWAP; not in price band
- Stop: Low of the 3-bar sequence
- Target: 1.5× risk
- Regime: `TRENDING_UP`
- No entry after: 13:00 IST

#### Trend Pullback
- Entry: Price pulls back to VWAP (±0.1%) in a trending regime; first bar that closes away from VWAP
- Filter: ADX > 25; price above 20-bar EMA
- Stop: Below VWAP − 1σ band
- Target: Prior swing high
- Regime: `TRENDING_UP` or `TRENDING_DOWN`
- No entry after: 14:00 IST

#### VWAP Reversion
- Entry: Price touches VWAP ± 2σ band and shows a reversal candle
- Filter: RVOL ≥ 1.0; ADX < 20 (ranging market); spread pct < 0.15%
- Stop: Outside the 2σ band
- Target: VWAP midline
- Regime: `RANGING`
- No entry after: 14:30 IST

#### Gap-and-Go
- Entry: Gap up ≥ 0.5%; ORB breakout in the gap direction in first 30 min; RVOL ≥ 2.0
- Stop: Previous day close
- Target: Gap × 1.5 extension
- Regime: `TRENDING_UP`
- No entry after: 10:30 IST

#### Gap-Fill
- Entry: Gap up/down ≥ 0.3%; price reverses below (gap up) or above (gap down) previous day close; RVOL ≥ 1.2
- Stop: 0.5% beyond gap high/low
- Target: Gap fill level (previous close)
- Regime: `RANGING` or `UNCERTAIN`
- No entry after: 12:00 IST

---

## 11. Expected Value and Probability Definition

### 11.1 V1 Probability Model

```
Loss Probability = 1 − Win Probability
```

A separate multi-outcome model (e.g., classifying wins, losses, and breakevens independently) is explicitly deferred until calibration data from ≥ 500 intraday trades is available.

### 11.2 Expected Net Value Formula

```
EV = (P_win × Expected_Reward) − (P_loss × Expected_Loss) − Total_Cost

where:
  P_win            = Calibrated Win Probability (from Layer 14)
  P_loss           = 1 − P_win
  Expected_Reward  = (target_price − entry_price) × quantity  (long)
  Expected_Loss    = (entry_price − stop_price) × quantity    (long)
  Total_Cost       = Σ(brokerage + STT + exchange + SEBI + GST + stamp_duty + spread + slippage)
                     for both entry and exit legs
```

**No event-risk penalty is included.** An event-risk penalty (earnings, RBI announcements, index rebalancing) will be added only when a real event-data source is integrated.

### 11.3 Signal Approval Gate

A signal is approved for allocation (Layer 15) only if:
- `EV > 0` (after all costs)
- `P_win ≥ 0.45`
- `Expected_Reward / Expected_Loss ≥ 1.5` (minimum reward-to-risk ratio)

---

## 12. Calibration Separation

### 12.1 Strict Separation Requirements

| Requirement | Specification |
|---|---|
| Separate model artifacts | Swing: `models/Swing_Calibration_v{N}.pkl` / Intraday: `intraday_models/Intraday_Calibration_v{N}.pkl` |
| Separate versioning | Version counters are independent. Intraday starts at v1. |
| Separate training queries | Intraday training queries filter `product_type = 'MIS'` AND `timeframe = '1min'` |
| `product_type` required at DB level | `intraday_signals.product_type` is a NOT NULL column defaulting to `'MIS'` |
| No fallback to swing model | If the intraday model is missing, the calibration service returns `is_calibrated: false`. It never loads the swing model. |
| Cold-start labelling | All predictions during cold start are labelled `UNCALIBRATED` in `model_predictions.is_calibrated` and on the dashboard |
| Model version recording | Every prediction records `model_version` in `model_predictions` |
| Retraining governance | Retraining is controlled by `intraday_governance.py`; requires drift detection + human approval |

### 12.2 Confidence Aggregator (Single Modification Point)

The Confidence Aggregator (Layer 13) is the **single module permitted to compute the final confidence score**. No strategy module, risk engine, or governance module may modify confidence directly.

```
Final Confidence = calibrated_prob
    × quality_weight[data_quality]    # 1.0=LIVE, 0.9=RECENT, 0.6=STALE, 0.0=UNAVAILABLE
    × regime_weight[regime]           # 1.0=TRENDING, 0.85=RANGING, 0.6=VOLATILE, 0.5=UNCERTAIN
```

---

## 13. Broker Adapter

### 13.1 BrokerInterface (Proposed)

```python
class BrokerInterface(ABC):
    """
    Thin interface for all broker communication.
    V1 implementation: ZerodhaAdapter.
    No multi-broker plugin framework in V1.
    """

    @abstractmethod
    async def connect_market_data(self) -> None: ...

    @abstractmethod
    async def subscribe_symbols(self, symbols: list[str], mode: str = "full") -> None: ...

    @abstractmethod
    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    @abstractmethod
    async def submit_order(self, order: OrderRequest) -> OrderResponse: ...

    @abstractmethod
    async def modify_order(self, order_id: str, modifications: dict) -> OrderResponse: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> CancelResponse: ...

    @abstractmethod
    async def get_orders(self) -> list[Order]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_instruments(self, exchange: str = "NSE") -> list[Instrument]: ...

    @abstractmethod
    async def get_price_bands(self, symbol: str) -> PriceBand: ...

    @abstractmethod
    async def disconnect(self) -> None: ...
```

### 13.2 V1 Implementation: ZerodhaAdapter

- Implements `BrokerInterface` using `kiteconnect` SDK.
- All Zerodha-specific logic (instrument tokens, mode constants, order variety codes) is contained within this class.
- No other module may import `kiteconnect` directly.
- Token management delegates to `intraday_kite_token_store.py` (not the swing `kite_token_store.py`).

---

## 14. Latency Budgets

### 14.1 Target Budgets

| Stage | Budget | Measurement Point |
|---|---|---|
| Tick received → market-state update (Layer 3 output) | < 250 ms | `tick_ts` to `normalizer_output_ts` |
| Completed bar → feature update (Layer 7 output) | < 500 ms | `bar_close_ts` to `feature_snapshot_created_at` |
| Feature update → signal and risk decision (Layer 11 output) | < 750 ms | `feature_snapshot_created_at` to `signal.created_at` |
| Approved decision → paper-order submission (Layer 17) | < 500 ms | `strategy_decision.decided_at` to `order.submitted_at` |
| **Total: completed bar → paper-order submission** | **< 2 000 ms** | `bar_close_ts` to `order.submitted_at` |

### 14.2 Measurement Implementation

Every processing event must emit a structured log entry containing:

```json
{
  "event": "bar_processed",
  "session_id": "...",
  "symbol": "RELIANCE",
  "bar_ts": "2026-01-15T09:16:00+05:30",
  "stage": "signal_engine",
  "elapsed_ms": 312,
  "cumulative_ms": 841
}
```

These logs are aggregated into `system_heartbeats.details` with rolling P50/P95/P99 latency per stage. Dashboard displays P95 latency per stage with a red indicator if any budget is exceeded.

---

## 15. Alert and Incident Levels

### Informational

- Normal session events: scan started, session opened, session closed, position entered, position exited, square-off completed
- Delivery: Dashboard feed only (no push notification for INFO in normal operation)

### Warning

- Single WebSocket reconnect
- Elevated bid-ask spread (> 0.2% for > 30s)
- Data staleness approaching threshold (last tick 20–30s ago)
- Approaching daily loss cap (> 80% consumed)
- Single gate rejection in position monitoring

Delivery: Dashboard + Expo push notification

### Critical

- Heartbeat loss (any component)
- WebSocket disconnected > 60s
- Position mismatch (DB count ≠ in-memory count)
- Risk breach (daily loss cap exceeded)
- Square-off retry triggered (Step 2 or Step 3)
- Reconciliation NEEDS_REVIEW item detected
- Calibration service unavailable

**Automatic mitigation:** CRITICAL events trigger automatic mitigation where possible (reconnect attempt, PAUSE_ENTRIES), not only notifications.

Delivery: Dashboard + Expo push + (optionally) email

### Incident

- Position still open at 15:20 IST
- Repeated reconciliation failure (> 3 in one session)
- Watchdog failure (watchdog heartbeat gap > 45s)
- Manual trading disabled until resolved

**Automatic action:** Write to `intraday_incidents`; disable all new trading; require operator acknowledgement before resuming.

Delivery: Dashboard + Expo push + email

---

## 16. Dashboard Architecture

The Intraday Dashboard is a future React/Vite artifact. This section defines the required sections only — no frontend implementation has been created.

### Required Dashboard Sections

| Section | Key Data | Update Frequency |
|---|---|---|
| Session Status | Date, status (OPEN/CLOSED/INCIDENT), market hours, square-off countdown | 5s |
| System Health | Watchdog status, FastAPI liveness, WS state, PostgreSQL, Node API | 5s |
| WebSocket State | Connected/disconnected, last reconnect, active subscriptions, ticks/s | 1s |
| Data Quality Per Symbol | Quality status per active symbol, last tick age | 5s |
| Market Regime | Current regime label, confidence, NIFTY trend | On bar completion |
| Session P&L | Realized P&L, unrealized P&L, total, vs. daily loss cap | 5s |
| Open Positions | Symbol, direction, entry, current LTP, stop, target, unrealized P&L, hold time | 1s |
| Stop & Target Status | Distance to stop (%), distance to target (%), risk:reward live | 1s |
| Max-Hold Countdown | Time remaining before forced exit per position | 1s |
| Square-Off Countdown | Time until 15:15 IST mandatory square-off | 1s |
| Risk Utilization | % of daily loss cap used, open risk per position, total capital at risk | 5s |
| Pending Orders | Symbol, direction, type, limit price, age | 5s |
| Alerts & Incidents | Severity-sorted list, unresolved incidents highlighted | Real-time |
| **Manual: Pause Entries** | Toggle button; shows current state; no confirmation required | — |
| **Manual: Cancel Pending Orders** | Button; disabled when none pending; one-click confirmation | — |
| **Manual: Flatten All** | Red button; requires typed confirmation "FLATTEN" | — |
| Session Replay | Link to SessionReplay page for any completed session | — |

---

## 17. Text Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        NSE TRADER — INTRADAY PLATFORM                               │
│                        (Isolated from Swing Platform)                               │
└─────────────────────────────────────────────────────────────────────────────────────┘

  MARKET DATA PLANE
  ─────────────────
  Zerodha Kite API
        │
        │  KiteTicker WebSocket (persistent)
        ▼
  ┌─────────────────────────┐
  │  L2: WS Ingestion       │──── in-memory asyncio queue ────►
  └─────────────────────────┘
        │
        ▼
  ┌─────────────────────────┐         ┌──────────────────────────┐
  │  L3: Tick Normalizer    │────────►│  L6: Data Quality Gates  │
  └─────────────────────────┘         └──────────────────────────┘
        │                                        │
        ▼                                        │ quality status
  ┌─────────────────────────┐                   │
  │  L4: Bar Builder        │──writes──►  minute_ohlcv_cache
  └─────────────────────────┘
        │  completed bar event
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                     L7: Feature Store                        │──writes──► feature_snapshots
  │  (VWAP · ORB · RVOL · Gap · ATR · ADX · TOD · Spread)      │
  └─────────────────────────────────────────────────────────────┘
        │
        ├────────────────────────────────────┐
        ▼                                    ▼
  ┌──────────────────┐              ┌──────────────────────┐
  │  L8: Regime      │              │  L5: Session Store   │◄── intraday_sessions
  │  Tagger          │              └──────────────────────┘
  └──────────────────┘
        │ regime
        ▼
  ┌──────────────────────────┐
  │  L9: Strategy Selector   │
  └──────────────────────────┘
        │ eligible strategies
        ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  L10: Strategy Modules                                        │
  │  ORB · Momentum · Trend Pullback · VWAP Rev · Gap-Go · Fill  │
  └──────────────────────────────────────────────────────────────┘
        │ entry candidates
        ▼
  ┌──────────────────────────┐   ┌──────────────────────────────┐
  │  L11: Signal Engine      │──►│  L16: Risk Engine            │
  └──────────────────────────┘   └──────────────────────────────┘
        │ confirmed signals              │ risk headroom
        ▼                               │
  ┌──────────────────────────┐          │
  │  L14: Calibration Svc    │          │
  └──────────────────────────┘          │
        │ calibrated prob               │
        ▼                               │
  ┌──────────────────────────┐          │
  │  L13: Confidence Aggreg. │          │
  └──────────────────────────┘          │
        │ final confidence              │
        ▼                               │
  ┌──────────────────────────┐          │
  │  L12: EV Ranker          │◄─────────┘
  └──────────────────────────┘
        │ ranked signals
        ▼
  ┌──────────────────────────┐
  │  L15: Allocation Engine  │
  └──────────────────────────┘
        │ sized orders
        ▼
  ┌──────────────────────────┐   ┌──────────────────────────────┐
  │  L17: Paper Executor     │──►│  L18: Cost Engine            │
  └──────────────────────────┘   └──────────────────────────────┘
        │ fills
        ▼
  intraday_paper_orders
  intraday_paper_fills
  intraday_positions
        │
        │  (all open positions)
        ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  L19: Position Monitor                                        │
  │  tick-level: stop · target · spread · circuit                │
  │  bar-level:  thesis · VWAP · ORB · regime · time             │
  │  portfolio:  loss cap · concentration · square-off           │
  └──────────────────────────────────────────────────────────────┘
        │ exit orders ──► L17 Paper Executor
        │ events ──────► position_monitor_events
        │
  ┌──────────────────────────────────────────────────────────────┐
  │  L20: Independent Watchdog                                    │
  │  Monitors all components · Writes system_heartbeats          │
  └──────────────────────────────────────────────────────────────┘
        │ alerts / escalations
        ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  L21: Incident & Alert Manager                               │
  │  intraday_alert_deliveries · intraday_incidents              │
  └──────────────────────────────────────────────────────────────┘
        │
        ├──► Expo Push
        ├──► Email
        └──► Dashboard

  ┌──────────────────────────────────────────────────────────────┐
  │  L22: Trade Journal & Audit Trail                            │
  │  intraday_audit_logs (append-only, write-once)               │
  └──────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │  L23: Learning & Model Governance (offline/batch)            │
  │  Calibration retraining · Drift detection · Human approval   │
  └──────────────────────────────────────────────────────────────┘

  PRESENTATION PLANE
  ──────────────────
  Node.js API Server (/intraday/api/v1/)
        │  REST
        └──► L24: Intraday Dashboard (React/Vite)
        │  WebSocket (/intraday/ws)
        └──► L25: Session Replay
```

---

## 18. Dependency Map

```
L1 (Broker Adapter)
  └─ required by: L2, L13

L2 (WS Ingestion)
  └─ requires: L1
  └─ required by: L3, L6, L20

L3 (Tick Normalizer)
  └─ requires: L2
  └─ required by: L4, L6, L7, L17, L19

L4 (Bar Builder)
  └─ requires: L3, L5
  └─ required by: L7, L19, L20

L5 (Session Store)
  └─ requires: market_hours.py, PostgreSQL
  └─ required by: L4, L7, L8, L9, L12, L15, L16, L17

L6 (Data Quality)
  └─ requires: L2, L3, L4
  └─ required by: L7, L11, L13

L7 (Feature Store)
  └─ requires: L3, L4, L5, L6
  └─ required by: L8, L10, L11, L12, L19

L8 (Regime Tagger)
  └─ requires: L7, L5
  └─ required by: L9, L13

L9 (Strategy Selector)
  └─ requires: L8
  └─ required by: L10

L10 (Strategy Modules)
  └─ requires: L7, L9
  └─ required by: L11

L11 (Signal Engine)
  └─ requires: L6, L10, L16
  └─ required by: L12, L13

L12 (EV Ranker)
  └─ requires: L11, L13, L14, L16, L18
  └─ required by: L15

L13 (Confidence Aggregator)
  └─ requires: L6, L8, L11, L14
  └─ required by: L12

L14 (Calibration Service)
  └─ requires: intraday_models/
  └─ required by: L12, L13

L15 (Allocation Engine)
  └─ requires: L12, L16
  └─ required by: L17

L16 (Risk Engine)
  └─ requires: L5, L15, intraday_positions table
  └─ required by: L11, L12, L15

L17 (Paper Executor)
  └─ requires: L3, L15, L18
  └─ required by: L19

L18 (Cost Engine)
  └─ requires: nothing (pure computation)
  └─ required by: L12, L17

L19 (Position Monitor)
  └─ requires: L3, L4, L7, L16, L17
  └─ required by: L20, L21

L20 (Watchdog)
  └─ requires: L2, L4, L19, PostgreSQL, system_heartbeats
  └─ required by: L21

L21 (Alert Manager)
  └─ requires: L20, intraday_alert_deliveries table
  └─ required by: nothing (terminal — delivers to operator)

L22 (Audit Trail)
  └─ requires: PostgreSQL (intraday_audit_logs)
  └─ required by: nothing (receiver of events from all layers)

L23 (Governance)
  └─ requires: intraday_paper_fills, feature_snapshots, intraday_models/
  └─ required by: L14 (produces models consumed by L14)

L24 (Dashboard)
  └─ requires: Node.js API, WebSocket server
  └─ required by: nothing

L25 (Session Replay)
  └─ requires: minute_ohlcv_cache, intraday_signals, intraday_paper_orders, position_monitor_events
  └─ required by: nothing
```

---

## 19. Risk Register

| Risk | Severity | Confidence | Mitigation |
|---|---|---|---|
| Kite WebSocket reconnect storm overwhelms reconnect logic | High | High | Exponential backoff cap at 60s; max 20 reconnects per session; after 20 → Incident |
| yfinance 7-day intraday data limit causes history loss | High | High | Persist every bar to PostgreSQL immediately; historical bars never re-fetched from yfinance |
| Swing calibration model accidentally loaded for intraday | High | High | No fallback path; strict `product_type` column; model path is configuration-driven |
| MIS square-off failure leaves overnight position | High | High | 4-step escalation (§8); independent watchdog; process restart reloads open positions |
| Two Zerodha projects invalidate each other's Kite session | High | Medium | Unresolved — see §20 |
| Slippage underestimation in paper simulation | Medium | High | Conservative slippage model (0.15%+); measure fill quality vs. signal price in analytics |
| No API authentication on internal endpoints | Medium | High | Add bearer token middleware before cloud exposure |
| Confidence mis-calibration during cold start | Medium | High | Label all UNCALIBRATED predictions clearly; do not approve entries when uncalibrated and confidence < 0.6 |
| Feature computation error produces wrong signal | Medium | Medium | Feature snapshot integrity check before signal generation; unit tests for each indicator |
| PostgreSQL single point of failure | Medium | Low | Replit-managed PostgreSQL has automated backups; v1 accepts this risk; v2 consider read replica |
| Python asyncio task crash silently kills position monitor | High | Medium | Watchdog monitors all async tasks; crash → Critical alert |
| Partial fill handling incorrect | Medium | Medium | Track filled and remaining quantities separately in `intraday_paper_orders` |

---

## 20. Unresolved Decisions

| Decision | Options | Recommendation | Owner |
|---|---|---|---|
| **Shared Zerodha account** | (A) Same Kite account for both projects (risk: session collision). (B) Separate Kite accounts | Strongly prefer (B). If only one account is available, document that both platforms cannot run simultaneously. | Project owner |
| **WebSocket bridge between FastAPI and Node.js** | (A) Redis pub/sub. (B) FastAPI SSE endpoint. (C) In-process Python → Node.js WebSocket relay | (B) SSE is simplest for v1; Redis adds operational complexity | Architecture |
| **Watchdog process isolation** | (A) Async task within FastAPI (dies with FastAPI). (B) Separate Python process | (B) is safer but adds deployment complexity; acceptable as (A) for v1 with documented limitation | Architecture |
| **Sector ETF data source** | (A) yfinance NIFTY sector indices. (B) Custom sector mapping. (C) Defer feature | Defer sector-relative strength to v2 until data source is confirmed | Architecture |
| **Real order placement** | (A) Paper-only forever. (B) Live orders after extended paper validation | Paper-only for v1. Live order route must be an explicit Phase gate with regulatory review. | Project owner |
| **Mobile app for intraday** | (A) Reuse existing Expo app with intraday tab. (B) Separate mobile artifact | Defer to after dashboard is complete | Architecture |
| **Historical 1-min data beyond 7 days** | (A) yfinance 7-day limit only. (B) Purchase historical data. (C) Build from live data over time | (C) for v1 — accept that backtesting on 1-min data requires live accumulation | Architecture |
| **Alert email provider** | (A) Resend. (B) SMTP. (C) No email in v1 | (A) Resend matches swing platform pattern; confirm API key availability | Architecture |

---

## 21. Recommended Implementation Sequence

See `docs/PHASE_A_TECHNICAL_DESIGN.md` for Phase A detail.

| Phase | Focus | Prerequisite |
|---|---|---|
| **Phase 0** | Isolation verification checklist | None |
| **Phase A** | Infrastructure: DB, FastAPI, WS ingestion, bar builder, recovery | Phase 0 complete |
| **Phase B** | Indicators: VWAP, ORB, RVOL, Gap, ATR, ADX | Phase A complete |
| **Phase C** | Signal engine: strategies, EV ranker, confidence aggregator | Phase B complete |
| **Phase D** | Risk and execution: risk engine, cost engine, paper executor, square-off | Phase C complete |
| **Phase E** | AI calibration: collect 200+ paper trades, train, validate, deploy | Phase D complete |
| **Phase F** | Dashboard: real-time UI, session replay | Phase D complete (can parallel with E) |
| **Phase G** | Production readiness: auth, audit, watchdog hardening, Phase 0 re-check | Phases E + F complete |

---

*End of Master Architecture Document*  
*Version 1.0 — July 18, 2026 — Documentation only. No code was modified.*
