# RC-10 Reference Document
## Project Background & Implementation Requirements

**Version:** 1.0  
**Date:** 2026-07-23  
**Baseline:** RC-9 Complete (`RC-9-complete` tag)  
**Audience:** Kimi — implementing agent

> This document is the authoritative reference for RC-10. Read it in full before writing a single line of code. It describes what exists, what must not change, and what must be built.

---

# TABLE OF CONTENTS

- [Part 1 — Project Background](#part-1--project-background)
  - [1. Overall Architecture](#1-overall-architecture)
  - [2. Folder Structure](#2-folder-structure)
  - [3. Major Modules](#3-major-modules)
  - [4. Data Flow](#4-data-flow)
  - [5. Runtime Lifecycle](#5-runtime-lifecycle)
  - [6. Dependency Relationships](#6-dependency-relationships)
  - [7. Design Principles](#7-design-principles)
  - [8. Extension Points](#8-extension-points)
  - [9. Public APIs](#9-public-apis)
  - [10. Coding Conventions](#10-coding-conventions)
  - [11. Testing Approach](#11-testing-approach)
  - [12. Error Handling](#12-error-handling)
  - [13. Logging](#13-logging)
  - [14. Recovery](#14-recovery)
  - [15. Session Management](#15-session-management)
  - [16. Persistence](#16-persistence)
  - [17. Metrics](#17-metrics)
  - [18. Health Monitoring](#18-health-monitoring)
  - [19. Fault Isolation](#19-fault-isolation)
  - [20. Graceful Shutdown](#20-graceful-shutdown)
  - [21. Current Limitations](#21-current-limitations)
  - [22. Frozen APIs](#22-frozen-apis)
- [Part 2 — RC-10 Requirements](#part-2--rc-10-requirements)
- [Part 3 — External Repository Insights](#part-3--external-repository-insights)
- [Part 4 — Implementation Roadmap](#part-4--implementation-roadmap)

---

# PART 1 — PROJECT BACKGROUND

## 1. Overall Architecture

The system is a **paper-mode intraday trading bot** for NSE/BSE equities. It is a FastAPI application backed by PostgreSQL, structured as a strict layered architecture where data flows in only one direction: market data → strategy engine → execution engine → risk gate → broker adapter.

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI HTTP API                         │
│   /orders  /positions  /sessions  /risk  /health  /auth        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ REST calls (operator-initiated)
┌───────────────────────────▼─────────────────────────────────────┐
│                   Strategy Engine (RC-9)                        │
│  StrategyCoordinator → StrategyRuntime → StrategyStateMachine   │
│  ContextBuilder → SignalRouter → StrategyFillTracker            │
│  Persistence / Recovery / Metrics / Health / FaultIsolator      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Signal (validated trading intent)
┌───────────────────────────▼─────────────────────────────────────┐
│              Risk Integration Layer (RC-8)                      │
│  RiskIntegrationLayer → RiskEngine → 20 RiskRules               │
│  per-account asyncio.Lock → serial evaluation per account       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Risk-approved ExecutionOrder only
┌───────────────────────────▼─────────────────────────────────────┐
│                  Execution Engine (RC-7)                        │
│  ExecutionEnginePort (abstract) → PaperBroker / ZerodhaReadonly │
│  FillEventBus → publishes FillEvent to subscribers              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ FillEvent
┌───────────────────────────▼─────────────────────────────────────┐
│                     PostgreSQL (Alembic)                        │
│  Sessions, Orders, Positions, Risk State, Strategy State,        │
│  Signals, Snapshots, Audit Trail, Ledger, Instruments           │
└─────────────────────────────────────────────────────────────────┘
```

**Key structural invariants that must never be violated:**
1. No execution without passing through `RiskIntegrationLayer.submit_order()`.
2. No commit/rollback/close on an `AsyncSession` except inside `SessionContext.__aexit__`.
3. `account_id == session_id` — these are the same identifier throughout.
4. All monetary values use Python `Decimal`.
5. LIVE mode is structurally blocked at startup (`TradingSettings.enforce_paper_mode` validator).
6. The strategy layer has no direct dependency on the database — only on repositories injected through `StrategyPersistenceAdapter`.

---

## 2. Folder Structure

```
intraday-trading-bot/
├── src/
│   ├── main.py                      # FastAPI app factory + lifespan
│   ├── api/
│   │   ├── dependencies.py          # get_db_session, get_current_user, etc.
│   │   ├── middleware/
│   │   │   ├── audit.py             # AuditMiddleware — logs every request/response
│   │   │   ├── correlation_id.py    # CorrelationIdMiddleware — injects X-Correlation-ID
│   │   │   └── cors.py              # setup_cors()
│   │   └── routers/
│   │       ├── auth.py              # POST /auth/login, /auth/refresh, /auth/logout
│   │       ├── health.py            # GET /health, /health/ready, /health/live
│   │       ├── orders.py            # POST /orders, GET /orders/{id}
│   │       ├── positions.py         # GET /positions
│   │       ├── risk.py              # GET /risk/state, POST /risk/kill-switch
│   │       ├── sessions.py          # POST /sessions, GET /sessions/{id}
│   │       └── (strategy.py)        # NOT YET EXISTS — planned for RC-10
│   ├── brokers/
│   │   ├── interface.py             # BrokerInterface ABC + OrderRequest/Response/Position/Margin
│   │   ├── paper_broker.py          # PaperBroker — in-memory simulation
│   │   └── zerodha_readonly.py      # ZerodhaReadonly — read-only quote fetching
│   ├── core/
│   │   ├── config.py                # Settings (Pydantic Settings v2), singleton: settings
│   │   ├── exceptions.py            # Application-level exception hierarchy
│   │   ├── idempotency.py           # Idempotency key helpers
│   │   ├── kill_switch.py           # Async kill switch with audit trail
│   │   ├── logging.py               # Structured JSON logging setup
│   │   └── market_calendar.py       # NSE market hours (IST), holiday list
│   ├── database/
│   │   ├── connection.py            # AsyncEngine + Base + get_db_session
│   │   ├── models.py                # All SQLAlchemy ORM models (596 lines)
│   │   └── repositories/
│   │       ├── audit.py             # AuditRepository
│   │       ├── fills.py             # FillsRepository
│   │       ├── heartbeats.py        # HeartbeatRepository
│   │       ├── idempotency.py       # IdempotencyRepository
│   │       ├── incidents.py         # IncidentRepository
│   │       ├── instruments.py       # InstrumentRepository
│   │       ├── ledger.py            # LedgerRepository
│   │       ├── orders.py            # OrderRepository
│   │       ├── positions.py         # PositionRepository
│   │       ├── risk_state.py        # RiskStateRepository
│   │       ├── sessions.py          # SessionRepository
│   │       ├── strategy.py          # StrategyRepository (RC-9C)
│   │       ├── strategy_signal.py   # StrategySignalRepository (RC-9C)
│   │       └── strategy_state.py    # StrategyStateRepository (RC-9C)
│   ├── execution/
│   │   ├── contracts.py             # ExecutionOrder, FillRecord, enums (frozen RC-7)
│   │   ├── exceptions.py            # ExecutionError hierarchy
│   │   ├── fills.py                 # FillEvent dataclass
│   │   └── portfolio.py             # PortfolioSnapshot, PositionSnapshot
│   ├── market_data/
│   │   ├── contracts.py             # Tick, CompletedBar, Quote, DataGap (frozen RC-6)
│   │   └── service.py               # MarketDataService — subscription + bar publishing
│   ├── risk/
│   │   ├── contracts.py             # RiskRequest/Result/Context/Config + 20 limit types
│   │   ├── engine.py                # RiskEngine — per-account state, rule evaluation
│   │   ├── exceptions.py            # KillSwitchActive, EmergencyHaltActive, etc.
│   │   ├── execution_adapter.py     # ProjectExecutionAdapter (implements ExecutionEnginePort)
│   │   ├── fill_event_bus.py        # FillEventBus — async pub/sub for fill events
│   │   ├── integration_layer.py     # RiskIntegrationLayer — the non-bypassable gate
│   │   ├── kill_switch.py           # Risk-level kill switch wiring
│   │   ├── persistence.py           # RiskEnginePersistenceAdapter
│   │   ├── rules.py                 # 20 rule implementations + RULE_REGISTRY
│   │   └── state.py                 # RiskState — per-account in-memory state
│   └── strategy/
│       ├── __init__.py              # Public exports (see §22)
│       ├── contracts.py             # Signal, StrategyConfig, StrategyContext, etc.
│       ├── context_builder.py       # ContextBuilder — assembles StrategyContext
│       ├── coordinator.py           # StrategyCoordinator — global lifecycle manager
│       ├── exceptions.py            # StrategyNotFoundError, LifecycleTransitionError, etc.
│       ├── fault_isolation.py       # FaultIsolator, FaultBudget, FaultAction
│       ├── fill_tracker.py          # StrategyFillTracker
│       ├── health.py                # StrategyHealthMonitor, HealthReport
│       ├── metrics.py               # MetricsCollector, StrategyMetrics
│       ├── persistence.py           # StrategyPersistenceAdapter + DTOs
│       ├── recovery.py              # StrategyRecoveryManager
│       ├── runtime.py               # StrategyRuntime — per-strategy async task
│       ├── session_context.py       # SessionContext — sole commit site
│       ├── signal_router.py         # SignalRouter — validates + submits to execution
│       ├── state_machine.py         # StrategyStateMachine — enforces valid transitions
│       ├── strategy_protocol.py     # Strategy Protocol (on_bar/on_tick/on_fill)
│       └── built_in/
│           └── sma_crossover.py     # SMA crossover reference strategy
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py    # Sessions, Orders, Positions, Instruments, Ledger
│       ├── 0002_rc8b_risk_state_fields.py   # Risk state snapshot columns
│       └── 0003_rc9c_strategy_persistence.py # strategy_configs, strategy_signals, strategy_state_snapshots
├── tests/
│   ├── conftest.py                  # DB fixtures, JWT auth, TestClient
│   ├── unit/
│   │   ├── risk/                    # 100+ risk engine tests
│   │   └── strategy/                # 292 strategy engine tests (13 files)
│   ├── integration/
│   │   ├── test_orders.py
│   │   ├── test_positions.py
│   │   └── test_sessions.py
│   └── mocks/
│       └── execution_engine.py
├── reviews/                         # Closure reports and audit docs
│   ├── RC9_freeze_certificate.md
│   └── Batch9D_closure.md (+ others)
├── docs/
│   └── RC10_Reference.md            # THIS FILE
├── pyproject.toml
└── ARCHITECTURE_REFERENCE.md
```

---

## 3. Major Modules

### 3.1 `src/core/config.py` — Settings

**Purpose:** Single source of truth for all runtime configuration.

**Important class:** `Settings(BaseSettings)` — singleton, imported as `from src.core.config import settings`.

Nested sub-settings: `TradingSettings`, `BrokerSettings`, `RiskSettings`, `ExecutionSettings`, `StrategySettings`, `LoggingSettings`, `IdempotencySettings`, `APISettings`, `PaperSettings`.

**Key fields:**
- `database_url` (alias: `INTRADAY_DATABASE_URL`) — async PostgreSQL
- `database_url_sync` (alias: `INTRADAY_DATABASE_URL_SYNC`) — sync URL for Alembic
- `jwt_secret_key` — operator JWT signing key
- `trading.mode` — only PAPER/REPLAY/SHADOW/SIMULATION; LIVE raises `ValueError` at startup
- `risk.*` — default limits (max leverage, daily loss, drawdown, etc.)
- `paper.initial_capital` — default 1,000,000 INR

**Integration point:** Every module that needs configuration imports `settings` directly from this module. RC-10 modules should follow the same pattern — add new sub-settings classes here, never create separate config files.

---

### 3.2 `src/market_data/` — Market Data (RC-6, frozen)

**Purpose:** Provides typed tick and bar data to the strategy engine. In paper mode, data comes from Zerodha Kite WebSocket (readonly) or synthetic injection during tests.

**Important classes:**

`MarketDataService`
- `subscribe(instrument_token: str) -> None` — registers interest
- `unsubscribe(instrument_token: str) -> None`
- `publish_bar(bar: CompletedBar) -> None` — used by test injection and real feed
- `on_bar(callback: Callable[[CompletedBar], Awaitable[None]]) -> None` — subscribe to bars
- `on_tick(callback: Callable[[Tick], Awaitable[None]]) -> None` — subscribe to ticks

**Frozen domain contracts:**
```python
class Tick(BaseModel, frozen=True):
    instrument_token: str; timestamp: datetime; last_price: Decimal
    last_quantity: Decimal; volume: Decimal
    buy_price: Decimal; buy_quantity: Decimal
    sell_price: Decimal; sell_quantity: Decimal
    ohlc_open/high/low/close: Optional[Decimal]

class CompletedBar(BaseModel, frozen=True):
    instrument_token: str; timestamp: datetime
    open/high/low/close: Decimal; volume: Decimal; interval: str

class Quote(BaseModel, frozen=True):          # bid/ask/depth
class DataGap(BaseModel, frozen=True):        # gap detection
class SubscriptionRequest(BaseModel, frozen=True)
```

**Extension point:** RC-10 multi-timeframe analysis subscribes to multiple intervals (1m, 5m, 15m, 1h) — each is a separate `MarketDataService` subscription with the interval embedded in `CompletedBar.interval`. The existing `CompletedBar` model already carries the `interval` field.

---

### 3.3 `src/execution/` — Execution Contracts (RC-7, frozen)

**Purpose:** Defines the order lifecycle and fill tracking data structures used by the risk and strategy layers.

**Frozen domain contracts:**
```python
class ExecutionOrder(BaseModel, frozen=True):
    client_order_id: str; instrument_token: str
    side: ExecutionOrderSide   # BUY | SELL
    order_type: ExecutionOrderType  # MARKET | LIMIT | SL | SL_M
    quantity: Decimal; limit_price/trigger_price: Optional[Decimal]
    status: ExecutionOrderStatus; filled_quantity: Decimal

class FillRecord(BaseModel, frozen=True): fill_id, order_id, side, qty, price, ts

class PortfolioSnapshot(BaseModel, frozen=True):
    equity/cash/buying_power/available_margin/total_market_value: Decimal

class PositionSnapshot(BaseModel, frozen=True):
    instrument_token: str; net_quantity: Decimal; direction: str; market_value: Decimal
```

**`FillEvent` (dataclass, mutable):** fill_id, account_id, instrument_token, side, quantity, fill_price, current_equity, fill_timestamp, order_id, broker_fill_id.

---

### 3.4 `src/risk/` — Risk Engine (RC-8, frozen)

**Purpose:** Non-bypassable pre-trade gate. Every order must pass `RiskIntegrationLayer.submit_order()`.

**Important classes:**

`RiskEngine`
- Stateful: holds per-account `RiskState` in `_states: Dict[str, RiskState]`
- `evaluate(request, context, limits) -> RiskResult` — runs all enabled rules
- `record_fill(account_id, fill_id, realized_pnl, turnover, current_equity, ts)` — updates daily P&L/turnover/equity state
- `get_state_snapshot(account_id) -> RiskStateSnapshot`
- `activate_kill_switch(account_id, reason)` / `deactivate_kill_switch(account_id)`
- Per-account `asyncio.Lock` — serial evaluation

`RiskIntegrationLayer`
- `submit_order(account_id, order, limits?) -> RiskIntegrationResult` — the gate
- Flow: acquire lock → collect context → build RiskRequest+RiskContext → evaluate → if approved call adapter.submit_order → publish FillEvent
- `enabled: bool` — when False, bypasses risk checks (RC-7 backward compat only)
- `add_limit(limit)` / `set_limits(limits)` / `limits` property

**20 risk rule types** (all in `RiskCheckType` enum):
Pre-trade: `ORDER_QUANTITY`, `ORDER_VALUE`, `TICK_SIZE`, `PRICE_BAND`  
Position: `MAX_POSITION_SIZE`, `INSTRUMENT_EXPOSURE`, `NET_EXPOSURE`, `CONCENTRATION_LIMIT`  
Portfolio: `CASH_AVAILABILITY`, `BUYING_POWER`, `PORTFOLIO_EXPOSURE`, `MARGIN_AVAILABILITY`  
Daily: `DAILY_LOSS_LIMIT`, `DAILY_PROFIT_TARGET_LOCK`, `MAX_TRADES_PER_DAY`, `MAX_ORDERS_PER_MINUTE`  
Safety: `KILL_SWITCH`, `EMERGENCY_HALT`, `CIRCUIT_BREAKER`  
Additional: `DUPLICATE_ORDER`, `SELF_TRADE`, `DRAWDOWN`, `TURNOVER_VELOCITY`

**`ExecutionEnginePort` (ABC)** — the interface the execution adapter must implement:
- `get_portfolio_snapshot(account_id) -> Optional[Dict]`
- `get_position_snapshots(account_id) -> Dict[str, Any]`
- `get_open_orders(account_id) -> List[Any]`
- `get_market_price(instrument_token) -> Optional[Decimal]`
- `submit_order(account_id, order) -> Dict[str, Any]`

**`FillEventBus`** — async pub/sub:
- `subscribe(handler: Callable[[FillEvent], Awaitable[None]])` — subscribe to fills
- `publish_nowait(event: FillEvent)` — fire-and-forget publication
- `build_fill_event(...)` — static factory for FillEvent creation

---

### 3.5 `src/strategy/` — Strategy Engine (RC-9, frozen)

This is the core of RC-9. It is described exhaustively in sections §4–§22. Summary of important classes:

| Class | File | Purpose |
|-------|------|---------|
| `Strategy` | `strategy_protocol.py` | Protocol all strategies must satisfy |
| `StrategyCoordinator` | `coordinator.py` | Global lifecycle manager (singleton per app) |
| `StrategyRuntime` | `runtime.py` | Per-strategy async task |
| `StrategyStateMachine` | `state_machine.py` | Enforces valid lifecycle transitions |
| `ContextBuilder` | `context_builder.py` | Assembles `StrategyContext` from live state |
| `SignalRouter` | `signal_router.py` | Validates signals and routes to execution |
| `StrategyFillTracker` | `fill_tracker.py` | Tracks fills per strategy |
| `SessionContext` | `session_context.py` | Sole DB commit site |
| `StrategyPersistenceAdapter` | `persistence.py` | Bridges strategy engine to DB |
| `StrategyRecoveryManager` | `recovery.py` | Crash recovery orchestrator |
| `MetricsCollector` | `metrics.py` | In-process runtime counters |
| `StrategyHealthMonitor` | `health.py` | Derives health from metrics |
| `FaultIsolator` | `fault_isolation.py` | Error budget enforcement |
| `SmaCrossoverStrategy` | `built_in/sma_crossover.py` | Reference strategy |

---

### 3.6 `src/brokers/` — Broker Layer

**Purpose:** Abstract broker interface and concrete implementations.

`BrokerInterface` (ABC) — defines:
- `place_order(OrderRequest) -> OrderResponse`
- `modify_order(order_id, **kwargs) -> OrderResponse`
- `cancel_order(order_id) -> bool`
- `get_positions() -> List[Position]`
- `get_orders() -> List[Dict]`
- `get_margins() -> Margin`
- `get_instruments(exchange) -> List[Dict]`
- `get_quote(symbols) -> Dict`

`PaperBroker` — simulates fills in-memory; used by `ExecutionEnginePort` implementation in PAPER mode.

`ZerodhaReadonly` — read-only Kite API calls (quotes, instruments). Does not place live orders in current codebase.

---

### 3.7 `src/database/` — Persistence

See §16 for full detail.

**Important tables** (from `models.py`):

| Table | Purpose |
|-------|---------|
| `instrument_master` | Instrument reference data (token, symbol, exchange, type, tick_size) |
| `trading_sessions` | Session lifecycle, recovery snapshots |
| `orders` | All orders with full lifecycle history |
| `positions` | Current positions per session |
| `fills` | Fill records linked to orders |
| `risk_state_snapshots` | Point-in-time risk state per account |
| `strategy_configs` | Strategy registration records (RC-9C) |
| `strategy_signals` | Signal records with routing status (RC-9C) |
| `strategy_state_snapshots` | Strategy state snapshots (RC-9C) |
| `paper_account_ledger` | Ledger entries for paper P&L tracking |
| `audit_log` | Every DB mutation audited |
| `incidents` | Operational incidents and alerts |
| `system_heartbeats` | Component liveness tracking |

---

### 3.8 `src/api/` — HTTP API

**Middleware stack** (applied in order):
1. `CorrelationIdMiddleware` — injects/propagates `X-Correlation-ID`
2. `AuditMiddleware` — logs every request and response with operator identity

**Routers:**
- `POST /auth/login` — returns JWT access + refresh tokens
- `POST /sessions` — create trading session (idempotency key required)
- `GET /health`, `/health/ready`, `/health/live`
- `POST /orders` — submit order through risk gate
- `GET /positions`
- `GET /risk/state` — current risk snapshot
- `POST /risk/kill-switch` — activate/deactivate

Authentication: JWT bearer tokens, HS256, 30-minute access / 7-day refresh. All endpoints require `Authorization: Bearer <token>` except `/health/*` and `/auth/login`.

---

## 4. Data Flow

### 4.1 Bar-Driven Strategy Signal Path

```
MarketDataService.publish_bar(CompletedBar)
  → StrategyRuntime._process_bar()
      → ContextBuilder.build(config, state_snapshot) → StrategyContext
      → strategy.on_bar(bar, context) → Optional[Signal]
      → if Signal:
          → StrategyPersistenceAdapter.save_signal(session, record)   ← write-before-route
          → SignalRouter.route(signal) → SignalRoutingResult
              → validate signal (quantity, instrument, direction conflicts)
              → RiskIntegrationLayer.submit_order(account_id, order)
                  → RiskEngine.evaluate(request, context, limits)
                  → if approved: PaperBroker.place_order(request) → OrderResponse
                  → if filled: FillEventBus.publish_nowait(FillEvent)
          → StrategyPersistenceAdapter.mark_signal_routed/rejected(session, ...)
      → MetricsCollector.record_bar(sid, latency_ms)
      → asyncio.create_task(_push_state_snapshot_safe())   ← fire-and-forget
```

### 4.2 Fill-Back Path

```
FillEventBus.publish_nowait(FillEvent)
  → StrategyRuntime._on_fill(fill_event)
      → StrategyFillTracker.record_fill(fill_event)
      → strategy.on_fill(fill_event, context) → Optional[Signal]
      → if follow-up Signal: route as above
  → RiskEngine.record_fill(...)   ← updates daily P&L, turnover, equity state
```

### 4.3 REST API Order Path (operator-initiated)

```
POST /orders  { instrument_token, side, quantity, order_type, ... }
  → auth middleware → idempotency check
  → OrderRepository.save(pending order)
  → RiskIntegrationLayer.submit_order(account_id, order)
      [same risk gate as strategy path]
  → return OrderResponse
```

---

## 5. Runtime Lifecycle

### 5.1 Application Startup (`src/main.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Validate PAPER mode (raises LiveModeBlockedError if LIVE)
    # 2. Create DB connection pool (AsyncEngine)
    # 3. Register default admin operator (if not present)
    # 4. (Future: start StrategyCoordinator, MarketDataService)
    yield
    # Shutdown: graceful stop
```

### 5.2 Strategy Lifecycle States

```
REGISTERED ──start()──→ STARTING ──ready──→ ACTIVE
    │                                          │
    │                                       pause()
    │                                          │
    └──────────────────────────────────→ PAUSED ──resume()──→ ACTIVE
                                              │
                                           stop()
                                              │
                                          STOPPING ──→ STOPPED (terminal)
                                              │
                                    any error ──→ ERROR ──stop()──→ STOPPED
```

**State machine rules:**
- Only `ACTIVE` state can emit signals (`can_emit_signals == True`)
- `STOPPED` is the only terminal state — no transitions out
- Each `StrategyRuntime` owns one `StrategyStateMachine`
- All transitions are async-lock-protected

### 5.3 Coordinator Lifecycle

```
StrategyCoordinator.register(config, strategy_instance)
  → per-strategy asyncio.Lock acquired
  → StrategyRuntime created
  → state persisted as REGISTERED (if persistence wired)
  → StrategyRegistrationResult returned

StrategyCoordinator.start(strategy_id)
  → runtime.start() → REGISTERED → STARTING → ACTIVE
  → MarketDataService subscriptions created
  → state persisted as ACTIVE

StrategyCoordinator.pause(strategy_id)  /  .resume(strategy_id)
  → runtime.pause() / .resume()
  → state persisted

StrategyCoordinator.shutdown(timeout_seconds=30)
  → _shutting_down = True (new registrations rejected)
  → pause all ACTIVE strategies
  → drain in-flight tasks (brief wait)
  → flush final state snapshots
  → stop all strategies
  → return ShutdownResult
```

---

## 6. Dependency Relationships

```
market_data  ──────────────────────────────────────────────┐
                                                            ↓
execution.contracts ──→ strategy.contracts ──→ strategy.runtime
                              ↓                       ↓
risk.contracts ──→ strategy.contracts           strategy.coordinator
                                                      ↓
                                          strategy.persistence (DB)
                                                      ↓
                                            database.repositories
                                                      ↓
                                              database.models (ORM)
                                                      ↓
                                                  PostgreSQL
```

**Upward-dependency prohibition:** No lower-layer module may import from a higher-layer module.

```
OK:   strategy → execution.contracts (stubs)
OK:   strategy → risk.contracts (RiskStateSnapshot in StrategyContext)
OK:   strategy → market_data.contracts (CompletedBar, Tick)
NEVER: risk → strategy
NEVER: execution → strategy
NEVER: market_data → strategy or risk
NEVER: database.repositories → strategy (only vice versa)
```

**Circular import exception:** `strategy/__init__.py` does NOT re-export `StrategyPersistenceAdapter`, `StrategyRecoveryManager`, etc. — those create circular imports via `src.strategy.persistence → src.strategy.__init__`. Import them directly:
```python
from src.strategy.persistence import StrategyPersistenceAdapter
from src.strategy.recovery import StrategyRecoveryManager
```

---

## 7. Design Principles

1. **All domain types are frozen Pydantic v2 models.** `frozen=True` on every `BaseModel` in `contracts.py` files. Use `dataclasses.replace(...)` or create new instances; never mutate.

2. **All monetary values use `Decimal`.** Never `float`. All Pydantic validators in domain contracts coerce to `Decimal(str(v))`.

3. **Repository pattern for all DB access.** Business logic never touches SQLAlchemy ORM directly. All DB operations go through repository classes injected by the service or adapter layer.

4. **Session ownership via `SessionContext`.** Only `SessionContext.__aexit__` calls `commit()`, `rollback()`, or `close()`. An AST audit test (`TestNoCommitInCoordinator`) enforces this. Any future code that calls `session.commit()` directly will fail this test.

5. **Write-before-route for signals.** A signal must be persisted to the DB (as `PENDING`) before the routing callback fires. If persistence fails, routing still proceeds (DB failure must not drop signals).

6. **Fire-and-forget state snapshots.** After each bar, state is snapshotted via `asyncio.create_task(...)` — never awaited in the hot path. Failures are logged at DEBUG level.

7. **Optional injection, backward-compatible constructors.** All new dependencies (persistence, metrics, health, fault isolator) are optional kwargs defaulting to `None`. When `None`, the new behaviour is silently skipped. The original positional-argument constructor forms are permanent.

8. **Idempotent operations.** Order submissions require idempotency keys. Signal persistence uses the signal UUID as the idempotency key (UPSERT logic in repositories).

9. **No silent fallbacks on configuration errors.** The app raises at startup if required environment variables are missing or LIVE mode is requested.

10. **Structured JSON logging throughout.** Every log call includes structured context fields (correlation_id, account_id, strategy_id, etc.).

11. **Per-account serialisation in the risk layer.** `RiskIntegrationLayer` holds one `asyncio.Lock` per `account_id`. All risk evaluation for an account is serial.

12. **Pydantic v2 `Literal` pattern for frozen limit configs.** Each `RiskConfiguration` subclass uses `check_type: Literal[RiskCheckType.X] = RiskCheckType.X` so mypy can narrow the union type safely.

---

## 8. Extension Points

RC-10 must use these extension points. Never bypass them.

| Extension Point | How to Use |
|----------------|-----------|
| `Strategy` Protocol | Implement `on_bar`, `on_tick`, `on_fill`, `validate_config`, `strategy_type`. Register with `StrategyCoordinator.register(config, instance)`. |
| `ExecutionEnginePort` (ABC) | Implement all 5 abstract methods to create a new broker adapter. Pass to `RiskIntegrationLayer.__init__`. |
| `BrokerInterface` (ABC) | Implement `place_order`, `modify_order`, `cancel_order`, `get_positions`, `get_orders`, `get_margins`, `get_instruments`, `get_quote`. |
| `FillEventBus.subscribe(handler)` | Subscribe any component to fill events (analytics, portfolio tracking, notifications). |
| `RiskIntegrationLayer.add_limit(limit)` | Add new risk rules at runtime without modifying the engine. |
| `MetricsCollector` | Inject into `StrategyCoordinator` and `StrategyRuntime` for per-strategy runtime metrics. |
| `StrategyHealthMonitor` | Inject into `StrategyCoordinator`; call `get_health(strategy_id)` for health reports. |
| `FaultIsolator` | Inject into `StrategyRuntime`; configure per-strategy budgets via `configure_budget(sid, budget)`. |
| `SessionContext(engine)` | Use as async context manager for any new code that needs a database transaction. |
| `StrategyConfig.parameters: Dict[str, Any]` | Strategy-specific configuration lives here. RC-10 strategies read their parameters from this dict. |
| `Signal.metadata: Dict[str, Any]` | Attach RC-10 enrichment (forecast confidence, regime, indicator values) to signals here. |
| `StrategyContext.market_snapshots: Dict[str, Any]` | Attach multi-timeframe data here via `ContextBuilder` extension. |
| Alembic migrations | All schema changes go through new migration files in `migrations/versions/`. Use prefix `0004_`, `0005_`, etc. |

---

## 9. Public APIs

### 9.1 Strategy Engine Public API (`src/strategy/__init__.py`)

```python
# Contracts
from strategy import (
    Signal, SignalAction, StrategyConfig, StrategyContext,
    StrategyLifecycleState, StrategyStateSnapshot,
    StrategyPerformanceSnapshot, SignalRoutingResult,
    StrategyRegistrationResult, ConflictResolution,
)

# Engine
from strategy import StrategyCoordinator, StrategyRuntime

# Session
from strategy import SessionContext

# Metrics & Health
from strategy import (
    MetricsCollector, StrategyMetrics,
    StrategyHealthMonitor, StrategyHealthStatus, HealthReport,
)

# Fault isolation
from strategy import (
    FaultIsolator, FaultAction, FaultBudget,
    FaultIsolationStatus, ShutdownResult,
)

# NOT exported from __init__ (import directly):
# from src.strategy.persistence import StrategyPersistenceAdapter, StrategyConfigRecord, ...
# from src.strategy.recovery import StrategyRecoveryManager
# from src.strategy.strategy_protocol import Strategy
```

### 9.2 Risk Layer Public API

```python
from risk.integration_layer import RiskIntegrationLayer, RiskIntegrationResult, ExecutionEnginePort
from risk.engine import RiskEngine
from risk.fill_event_bus import FillEventBus
from risk.contracts import (
    RiskRequest, RiskResult, RiskContext, RiskConfiguration,
    RiskViolation, RiskSeverity, RiskCheckType, RiskStateSnapshot,
    # + all 20 limit configuration classes
)
```

### 9.3 REST API

All endpoints return JSON. Authentication required (Bearer JWT) except health checks.

```
POST   /auth/login                         → { access_token, refresh_token }
POST   /sessions                           → TradingSession
GET    /sessions/{session_id}              → TradingSession
POST   /orders                             → OrderResponse
GET    /orders/{order_id}                  → Order
GET    /positions                          → List[Position]
GET    /risk/state                         → RiskStateSnapshot
POST   /risk/kill-switch                   → { activated: bool }
GET    /health                             → { status, version, timestamp }
GET    /health/ready                       → 200 | 503
GET    /health/live                        → 200
```

---

## 10. Coding Conventions

1. **Python 3.12, async-first.** All I/O is async (`async def`, `await`, `asyncio.Lock`). No `threading`, no `concurrent.futures` in business logic.

2. **Type annotations everywhere.** All function signatures, class attributes, and local variables with non-obvious types. `from __future__ import annotations` at the top of every file.

3. **Pydantic v2 style.** Use `model_config = ConfigDict(frozen=True)` or `class Model(BaseModel, frozen=True)`. Use `@field_validator` (not `@validator`). Use `Literal[EnumValue.X]` for discriminated unions.

4. **Dataclasses for non-Pydantic frozen types.** `@dataclass(frozen=True)` for internal DTOs that don't need Pydantic validation (e.g., `StrategyConfigRecord`, `StrategyMetrics`, `ShutdownResult`).

5. **Logging** via `logger = logging.getLogger(__name__)`. Structured fields passed as `extra={"key": value}` kwargs. Log level: DEBUG for hot-path internals, INFO for lifecycle events, WARNING for recoverable errors, ERROR for failures with impact.

6. **`Decimal` for money.** Never `float`. Use `Decimal(str(value))` to convert from external inputs.

7. **Import style:** stdlib → third-party → local, separated by blank lines. All local imports use package-relative paths (`from strategy.contracts import ...`). Never `import *`.

8. **Black-formatted** (line length 100). `mypy --strict` compatible.

9. **Test naming:** `test_<what>_<condition>_<expected>` or `test_<what>_<scenario>`. Classes named `Test<ComponentName>`.

10. **No hard-coded instrument tokens or account IDs** in business logic. All come from `StrategyConfig.instrument_tokens` or the session context.

11. **Environment variables** for all secrets and deployment-specific config. No `.env` files committed. Use `Settings` with `validation_alias` to avoid collisions with other env var namespaces.

---

## 11. Testing Approach

### Structure

```
tests/
├── conftest.py           # session-scoped DB engine + function-scoped session (rollback after each test)
│                         # async_client (httpx), auth_headers (JWT), db_session override
├── unit/                 # No network, no real DB; mock or in-memory
│   ├── risk/             # 100+ tests: rules, state, integration layer
│   └── strategy/         # 292 tests: 13 files covering all RC-9 components
│       ├── test_contracts.py
│       ├── test_state_machine.py
│       ├── test_fill_tracker.py
│       ├── test_signal_router.py
│       ├── test_context_builder.py
│       ├── test_coordinator.py
│       ├── test_runtime.py
│       ├── test_integration.py       # strategy + risk wired together
│       ├── test_exceptions.py
│       ├── built_in/test_sma_crossover.py
│       ├── test_batch9c.py           # persistence layer
│       ├── test_batch9d_a.py         # coordinator wiring, recovery
│       └── test_batch9d_b.py         # metrics, health, fault isolation
└── integration/          # Uses real (test) PostgreSQL; full HTTP path
    ├── test_orders.py
    ├── test_positions.py
    └── test_sessions.py
```

### Patterns

- **Async tests:** `@pytest.mark.asyncio` with `asyncio_mode = "auto"` in `pyproject.toml`
- **Mocking:** `unittest.mock.AsyncMock` / `MagicMock` for all external dependencies. Strategy tests mock `MarketDataService`, `FillEventBus`, `ContextBuilder`.
- **Patching:** For SessionContext tests, patch `strategy.coordinator.SessionContext` (top-level import path, not the submodule).
- **DB isolation:** Integration tests use function-scoped sessions that always rollback. Unit tests never touch the DB.
- **AST audit:** `TestNoCommitInCoordinator` parses `coordinator.py` and `runtime.py` source with `ast.parse` to assert `session.commit()` never appears.
- **Determinism:** SMA crossover tests assert that identical input sequences produce identical signal sequences.

### RC-10 test requirements

- All new modules must have unit tests. Minimum: one test class per class, covering normal path + one error path + one boundary case.
- All new Alembic migrations must be tested by applying them to a test DB and verifying the schema.
- Never write integration tests that hit the live Zerodha API. Always use the paper broker or a mock.
- New strategies must have a determinism test (same inputs → same outputs).

---

## 12. Error Handling

### Hierarchy

```
BaseException
└── Exception
    ├── StrategyError (src/strategy/exceptions.py)
    │   ├── StrategyNotFoundError
    │   ├── StrategyAlreadyRegisteredError
    │   ├── LifecycleTransitionError
    │   └── StrategyRuntimeError
    ├── RiskError (src/risk/exceptions.py)
    │   ├── KillSwitchActive
    │   ├── EmergencyHaltActive
    │   └── IntegrationLayerError
    └── ApplicationError (src/core/exceptions.py)
        └── LiveModeBlockedError
```

### Rules

1. **Persistence failures never drop signals.** `_persist_signal_safe()` wraps the entire persistence call in `try/except Exception`, logs at WARNING, and always returns. The signal routing callback fires regardless.

2. **State snapshot failures never interrupt bar processing.** `_push_state_snapshot_safe()` wraps in try/except, logs at DEBUG.

3. **Recovery errors are collected, not raised.** `StrategyRecoveryManager.recover()` accumulates errors in `StrategyRecoveryResult.errors`; callers decide whether to treat them as fatal.

4. **Risk evaluation errors bubble up.** `RiskIntegrationLayer` raises `IntegrationLayerError` if context collection fails. This is intentional — missing risk context means we cannot safely evaluate the order.

5. **Lifecycle transition errors are raised immediately.** `LifecycleTransitionError` is not caught internally — callers must handle it.

---

## 13. Logging

All modules use `logger = logging.getLogger(__name__)`.

Configured via `src/core/logging.py` using `LoggingSettings` from config:
- Format: `structured_json` (default) or `text`
- Level: INFO (default)
- `audit_all_sensitive: True` — all sensitive operations (orders, kills, session events) are audited
- `include_trace_id: True` — correlation IDs propagated through all log entries

**Structured log example:**
```python
logger.info(
    "Signal routed",
    extra={
        "strategy_id": config.strategy_id,
        "signal_id": str(signal.signal_id),
        "action": signal.action.value,
        "instrument_token": signal.instrument_token,
        "correlation_id": correlation_id,
    }
)
```

**RC-10 convention:** Add `strategy_id`, `instrument_token`, and `regime` (if applicable) to all structured log entries from RC-10 components.

---

## 14. Recovery

### Strategy Engine Recovery (`StrategyRecoveryManager`)

**Trigger:** Called during application startup after a crash or restart.

**Process:**
1. `_persistence.list_non_terminal_strategies(session)` — loads all non-STOPPED strategy records
2. For each record: factory creates a strategy instance, coordinator re-registers it
3. PAUSED strategies: re-registered in PAUSED state (no signal generation)
4. ACTIVE strategies: re-registered and re-started (market data re-subscribed)
5. `_persistence.list_signals_for_strategy(session, sid)` — loads all signals
6. Already-routed signals (status != PENDING): skipped (deduplication by signal UUID)
7. Genuinely PENDING signals: re-enqueued via signal router

**Result:** `StrategyRecoveryResult` — contains `strategies_restored`, `strategies_skipped`, `signals_requeued`, `errors`.

**Key guarantee:** Recovery is idempotent. Calling `recover()` twice on the same DB state is safe.

### Session Recovery

`TradingSession` model includes `previous_session_id`, `recovery_reason`, `recovery_snapshot` fields. On restart, the session router creates a new session with `recovery_reason` set, allowing analytics to distinguish crash restarts from clean restarts.

---

## 15. Session Management

**Trading Session = Account.** `account_id == session_id` is a hard invariant throughout the codebase.

`TradingSession` model:
- `session_id: str` — unique, idempotency-safe UUID
- `status: SessionStatus` — INITIALIZING → ACTIVE → PAUSED → RECOVERING → SHUTTING_DOWN → CLOSED
- `trading_mode: TradingMode` — PAPER only in current version
- `idempotency_key: str` — prevents duplicate session creation

Sessions are created via `POST /sessions` with an idempotency key. The response includes the session_id that becomes the account_id for all subsequent operations.

`SessionContext(engine)` — database transaction scoping (see §16). This is a different concept from trading sessions; the name collision is resolved by context.

---

## 16. Persistence

### Database Connection (`src/database/connection.py`)

```python
AsyncEngine  ← created from settings.database_url
Base         ← SQLAlchemy declarative base (all models inherit)
get_db_session()  ← FastAPI dependency; yields AsyncSession; app code calls SessionContext for commits
```

### Repository Pattern

All repositories have the same call signature: `method(session: AsyncSession, ...)`. They never commit, rollback, or close. All take a session as their first argument.

Key repositories:
- `StrategyRepository` — `save_strategy(session, record)`, `get_strategy(session, sid)`, `update_lifecycle_state(session, sid, state)`, `list_non_terminal(session, terminal_states)`
- `StrategySignalRepository` — `save_signal(session, record)`, `update_routing_status(session, signal_id, status, ...)`, `list_signals_for_strategy(session, sid)`
- `StrategyStateRepository` — `save_snapshot(session, record)`, `get_latest_snapshot(session, sid)`
- `OrderRepository`, `PositionRepository`, `FillsRepository` — CRUD for order lifecycle
- `RiskStateRepository` — risk state snapshots

### Strategy Persistence DTOs

```python
@dataclass(frozen=True)
class StrategyConfigRecord:
    strategy_id: str; strategy_type: str; name: str
    account_id: Optional[str]  # currently None — future batch
    configuration: Dict[str, Any]; instrument_tokens: List[str]
    lifecycle_state: str; enabled: bool

@dataclass(frozen=True)
class StrategySignalRecord:
    signal_id: UUID; strategy_id: str; account_id: Optional[str]
    instrument_token: str; action: str; side: str; quantity: Decimal
    order_type: str; routing_status: str = "PENDING"
    routed_client_order_id: Optional[str]; rejection_reason: Optional[str]

@dataclass(frozen=True)
class StrategyStateSnapshotRecord:
    strategy_id: str; lifecycle_state: str
    pending_order_ids: List[str]; latest_signal_timestamp: Optional[datetime]
    emitted_signal_count: int; routed_signal_count: int
    rejected_signal_count: int; fill_count: int
```

### Alembic Migrations

Located in `migrations/versions/`. Apply with `alembic upgrade head`.

| Migration | Tables |
|-----------|--------|
| `0001_initial_schema.py` | `instrument_master`, `trading_sessions`, `orders`, `positions`, `fills`, `paper_account_ledger`, `audit_log`, `incidents`, `system_heartbeats`, `idempotency_keys` |
| `0002_rc8b_risk_state_fields.py` | Added columns to risk state snapshot table |
| `0003_rc9c_strategy_persistence.py` | `strategy_configs`, `strategy_signals`, `strategy_state_snapshots` |

---

## 17. Metrics

**`MetricsCollector`** (`src/strategy/metrics.py`)

In-process only. No I/O. asyncio.Lock-protected writes.

```python
mc = MetricsCollector()
mc.initialize(strategy_id)          # sync — called by coordinator on register
mc.remove(strategy_id)              # sync — called on deregister
await mc.record_bar(sid, latency_ms)    # resets consecutive_errors streak
await mc.record_tick(sid)
await mc.record_signal(sid)
await mc.record_signal_rejected(sid)
await mc.record_fill(sid)
await mc.record_error(sid)           # increments consecutive_errors streak
await mc.record_success(sid)         # resets consecutive_errors streak
mc.get_metrics(sid) → Optional[StrategyMetrics]  # lock-free snapshot
mc.get_all_metrics() → Dict[str, StrategyMetrics]
```

**`StrategyMetrics`** (frozen dataclass):
- `bars_processed`, `ticks_processed`
- `signals_emitted`, `signals_rejected`, `fill_count`
- `error_count`, `consecutive_errors`
- `last_bar_latency_ms`, `avg_bar_latency_ms`
- `started_at`, `last_bar_at`, `last_error_at`

---

## 18. Health Monitoring

**`StrategyHealthMonitor`** (`src/strategy/health.py`)

Pure read — no side effects. Computes `HealthReport` from `MetricsCollector` snapshots on demand.

```python
monitor = StrategyHealthMonitor(
    metrics=mc,
    degraded_consecutive_errors=3,    # constructor-overridable
    unhealthy_consecutive_errors=5,
    degraded_latency_ms=500.0,
    unhealthy_latency_ms=2000.0,
)
monitor.compute_health(strategy_id) → HealthReport
monitor.get_all_health(sids) → Dict[str, HealthReport]
monitor.is_healthy(strategy_id) → bool
monitor.any_unhealthy(sids) → bool
```

**`StrategyHealthStatus` enum:** `HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN`

**`HealthReport`** (frozen dataclass): status, reason, consecutive_errors, last_bar_latency_ms, bars_processed, signals_emitted, error_count, last_checked.

**Threshold logic (ordered, first match wins):**
1. consecutive_errors ≥ unhealthy → UNHEALTHY
2. consecutive_errors ≥ degraded → DEGRADED
3. last_bar_latency_ms ≥ unhealthy → UNHEALTHY
4. last_bar_latency_ms ≥ degraded → DEGRADED
5. no metrics recorded → UNKNOWN
6. otherwise → HEALTHY

---

## 19. Fault Isolation

**`FaultIsolator`** (`src/strategy/fault_isolation.py`)

Per-strategy error budget enforcement. Isolation is sticky until explicitly cleared by an operator.

```python
fi = FaultIsolator(default_budget=FaultBudget(
    max_consecutive_errors=5,
    max_errors_per_minute=10,
    auto_pause_on_breach=True,   # PAUSE action; False → STOP
))
fi.configure_budget(strategy_id, custom_budget)   # sync
fi.remove(strategy_id)                            # sync — on deregister
await fi.record_error(strategy_id) → FaultAction  # NONE | PAUSE | STOP
await fi.record_success(strategy_id)              # resets consecutive streak
await fi.reset_isolation(strategy_id)             # operator-initiated
fi.is_isolated(strategy_id) → bool                # sync, lock-free
fi.get_isolation_reason(strategy_id) → Optional[str]
fi.get_status(strategy_id) → FaultIsolationStatus
```

**`FaultAction` enum:** `NONE | PAUSE | STOP`

**Isolation semantics:**
- Once isolated, `record_error()` returns `PAUSE` immediately (sticky)
- Only `reset_isolation()` clears it — this is an explicit operator action
- `StrategyRuntime._record_error_and_maybe_isolate()` checks the returned action and calls `coordinator.pause(strategy_id)` if `PAUSE` or `coordinator.stop(strategy_id)` if `STOP`

---

## 20. Graceful Shutdown

**`coordinator.shutdown(timeout_seconds=30) → ShutdownResult`**

Shutdown sequence:
1. `_shutting_down = True` — new `register()` and `start()` calls raise immediately
2. Pause all currently ACTIVE strategies
3. Brief drain wait (asyncio.sleep) for in-flight routing tasks
4. Flush final state snapshots for all strategies
5. Stop all strategies (STOPPING → STOPPED)
6. Return `ShutdownResult(strategies_stopped, strategies_failed, snapshots_flushed, completed_at)`

This is integrated into FastAPI's lifespan context manager — the `yield` block can be extended to call `await coordinator.shutdown()`.

---

## 21. Current Limitations

| Limitation | Notes |
|-----------|-------|
| `account_id` is always `None` in strategy persistence | Waiting for session context wiring (RC-10+) |
| `_NullStrategyFactory` in `coordinator.recover()` | No real strategy factory registry; recovery can load state but not reconstruct logic |
| LIVE mode structurally blocked | `TradingSettings.enforce_paper_mode` raises at startup |
| No HTTP endpoints for strategy management | No `GET /strategies`, `POST /strategies`, `POST /strategies/{id}/start` etc. |
| No multi-timeframe market data aggregation | `MarketDataService` serves bars at one timeframe per subscription |
| No indicator library | Each strategy must compute its own indicators from raw OHLCV |
| No portfolio-level risk across strategies | `RiskIntegrationLayer` evaluates each order independently |
| No sector/correlation limits | Risk rules exist for `CONCENTRATION_LIMIT` but no sector metadata |
| No AI/ML forecast layer | Strategy logic is purely rule-based |
| No real broker integration | `ZerodhaReadonly` exists; full write integration not wired |
| Strategy engine not wired into API | Coordinator lifecycle not exposed via REST |
| `GET /health` does not include strategy health | Strategy-level health not surfaced in HTTP health check |

---

## 22. Frozen APIs

The following contracts, interfaces, and call forms **must not be modified** in RC-10. Any change requires a new batch closure report and a new freeze certificate.

### Frozen — `src/market_data/contracts.py`
`Tick`, `CompletedBar`, `Quote`, `DataGap`, `SubscriptionRequest`, `DataQualityStatus`, `DataQualityEvent` — all fields frozen.

### Frozen — `src/execution/contracts.py`
`ExecutionOrder`, `FillRecord`, `ExecutionAuditEvent`, `ExecutionOrderStatus`, `ExecutionOrderSide`, `ExecutionOrderType`, `ExecutionOrderAction` — all fields frozen.

### Frozen — `src/execution/fills.py`
`FillEvent` dataclass — all fields frozen.

### Frozen — `src/execution/portfolio.py`
`PortfolioSnapshot`, `PositionSnapshot` — all fields frozen.

### Frozen — `src/risk/contracts.py`
All 20+ classes — all fields frozen. New risk rules must add new `RiskConfiguration` subclasses; existing ones must not change.

### Frozen — `src/risk/integration_layer.py`
`RiskIntegrationLayer.submit_order(account_id, order, limits?) → RiskIntegrationResult` — signature frozen.  
`ExecutionEnginePort` ABC — all 5 abstract method signatures frozen.

### Frozen — `src/strategy/contracts.py`
`Signal`, `StrategyConfig`, `StrategyContext`, `StrategyStateSnapshot`, `StrategyLifecycleState`, `SignalAction`, `SignalRoutingResult`, `StrategyRegistrationResult`, `ConflictResolution`, `StrategyPerformanceSnapshot` — all frozen.

### Frozen — `src/strategy/strategy_protocol.py`
`Strategy` Protocol — `on_bar`, `on_tick`, `on_fill`, `validate_config`, `strategy_type` — signatures frozen.

### Frozen — `src/strategy/session_context.py`
`SessionContext.__init__(engine)`, `__aenter__`, `__aexit__` — frozen. Only commit site.

### Frozen — Constructor forms
```python
# These exact call forms must remain valid forever:
StrategyCoordinator(mds, feb, context_builder, signal_router)
StrategyRuntime(config, strategy, context_builder, market_data_service, fill_event_bus)
```

### Frozen — `src/strategy/state_machine.py`
`_VALID_TRANSITIONS` dict — the state transition graph. Adding new states requires a batch review.

### Frozen — Database schema (migrations 0001–0003)
All columns in `instrument_master`, `trading_sessions`, `orders`, `positions`, `fills`, `paper_account_ledger`, `audit_log`, `strategy_configs`, `strategy_signals`, `strategy_state_snapshots` — frozen. New columns must be added via new Alembic migrations.

---

# PART 2 — RC-10 REQUIREMENTS

## 2.1 Goals Summary

RC-10 makes the bot **market-intelligent, AI-augmented, and production-ready**. It builds five capability layers on top of RC-9's stable foundation. None of these layers bypasses the Risk Engine or Execution Engine.

```
                           ┌────────────────────────────┐
                           │      Operations (RC-10E)    │
                           │  Dashboard · Analytics ·    │
                           │  Alerts · Reports · Soak    │
                           └───────────┬────────────────┘
                                       │
           ┌───────────────────────────▼────────────────────────────┐
           │                  Broker Layer (RC-10D)                  │
           │     Zerodha Kite full write · Order sync · Reconcile   │
           └───────────────────────────┬────────────────────────────┘
                                       │
    ┌──────────────────────────────────▼──────────────────────────────┐
    │                 Portfolio Management (RC-10C)                    │
    │  Dynamic sizing · Allocation · Sector exposure · Correlation    │
    └──────────────────────────────────┬──────────────────────────────┘
                                       │
   ┌───────────────────────────────────▼───────────────────────────────┐
   │                    AI Forecast Layer (RC-10B)                      │
   │      Kronos adapter · Confidence · Volatility · Features          │
   └───────────────────────────────────┬───────────────────────────────┘
                                       │
  ┌────────────────────────────────────▼────────────────────────────────┐
  │                  Market Intelligence Layer (RC-10A)                  │
  │  Multi-timeframe · Regime detection · Ranking · Scoring · Indicators │
  │  Corporate announcement intelligence (BSE/NSE via MarkAnn-Bot)       │
  └──────────────────────────────────────────────────────────────────────┘
                                       │ feeds into
                           ┌───────────▼────────────────┐
                           │    RC-9 Strategy Engine     │  (frozen, unchanged)
                           │   StrategyCoordinator +    │
                           │   StrategyRuntime + Risk    │
                           └────────────────────────────┘
```

---

## 2.2 RC-10A — Market Intelligence Layer

### 2.2.1 Multi-Timeframe Analysis

**Goal:** Give strategies access to indicator values computed on 1m, 5m, 15m, 1h, and daily bars simultaneously.

**What must be built:**
- `src/market_intelligence/timeframe.py` — `TimeframeAggregator`: receives 1m `CompletedBar` events from `MarketDataService` and emits aggregated bars for higher timeframes
- `src/market_intelligence/indicator_engine.py` — `IndicatorEngine`: computes a configurable set of technical indicators (SMA, EMA, RSI, VWAP, MACD, Bollinger Bands, ATR, ADX) on a rolling window of bars per timeframe
- `src/market_intelligence/multi_timeframe_context.py` — `MultiTimeframeContext` (frozen Pydantic model): snapshot of indicator values across all subscribed timeframes for one instrument. This is attached to `StrategyContext.market_snapshots[instrument_token]`.

**Integration:** `ContextBuilder` is extended (not replaced) to populate `StrategyContext.market_snapshots` with `MultiTimeframeContext` objects. Existing strategies that do not use `market_snapshots` are unaffected.

**Constraints:**
- Timeframe aggregation is purely in-process. No DB persistence of intermediate bars.
- The `CompletedBar` model must not change.
- Indicator computation must be deterministic (same input sequence → same output).

### 2.2.2 Market Regime Detection

**Goal:** Classify the current market state for each instrument and expose it to strategies so they can adapt their logic.

**What must be built:**
- `src/market_intelligence/regime.py` — `MarketRegimeDetector`: classifies regime from OHLCV history and indicator state. Uses ADX + ATR + price-MA relationship. Emits one of the existing `MARKET_REGIME` enum values (already in `models.py`): `UNKNOWN | RANGING | UPTREND | DOWNTREND | STRONG_UPTREND | STRONG_DOWNTREND | EXPANDING_RANGE`.
- `MarketRegimeSnapshot` (frozen Pydantic model): `instrument_token`, `regime`, `confidence: Decimal`, `detected_at: datetime`.
- Regime is included in `MultiTimeframeContext` and surfaces in `StrategyContext.market_snapshots`.

**Constraints:** Regime detection must be non-blocking (pure computation, no I/O). The `MARKET_REGIME` DB enum values are frozen — do not add new values without a migration.

### 2.2.3 Watchlist Ranking

**Goal:** Rank all instruments in the watchlist by opportunity quality at each bar cycle.

**What must be built:**
- `src/market_intelligence/ranking.py` — `WatchlistRanker`: scores each instrument on multiple factors (regime quality, volume, momentum, spread, volatility ratio) and returns a ranked list.
- `InstrumentScore` (frozen Pydantic model): `instrument_token`, `composite_score: Decimal`, `factor_scores: Dict[str, Decimal]`, `rank: int`, `computed_at: datetime`.
- `WatchlistRankingSnapshot`: list of `InstrumentScore`, `ranking_timestamp`.
- Published via an internal event or made available to the coordinator for strategy routing decisions.

### 2.2.4 Strategy Scoring

**Goal:** Score each active strategy's alignment with the current market conditions.

**What must be built:**
- `src/market_intelligence/strategy_scoring.py` — `StrategyScorer`: takes a `StrategyConfig` and a `WatchlistRankingSnapshot` + `MarketRegimeSnapshot` and returns a `StrategyScore`.
- `StrategyScore` (frozen Pydantic model): `strategy_id`, `score: Decimal`, `regime_alignment: Decimal`, `instrument_suitability: Decimal`, `computed_at: datetime`.
- Used by the coordinator to prioritise or throttle strategies.

### 2.2.5 Corporate Announcement Intelligence (MarkAnn-Bot integration)

**Goal:** Feed BSE/NSE corporate announcement data into the strategy context so strategies can avoid trading into earnings or bonus announcements.

**What must be built:**
- `src/market_intelligence/announcements.py` — `AnnouncementIntelligenceService`:
  - Polls/subscribes to BSE/NSE announcement feed (see Part 3 for MarkAnn-Bot design)
  - Classifies announcements: `EARNINGS`, `DIVIDEND`, `BONUS`, `SPLIT`, `MERGER`, `RESULTS`, `OTHER`
  - Maintains an in-memory index keyed by `instrument_token` with a TTL
  - Exposes `get_active_announcements(instrument_token) -> List[AnnouncementRecord]`
- `AnnouncementRecord` (frozen Pydantic model): `announcement_id`, `instrument_token`, `classification`, `headline`, `exchange`, `published_at`, `effective_date`, `raw_metadata: Dict`
- Announcements are attached to `StrategyContext.market_snapshots[instrument_token].active_announcements`.

**Risk gate integration:** A new risk rule `ANNOUNCEMENT_BLACKOUT` (new `RiskCheckType` value) blocks entries during configurable windows before/after material announcements.

---

## 2.3 RC-10B — AI Forecast Layer

### 2.3.1 Kronos Adapter

**Goal:** Integrate the Kronos AI forecasting system (see Part 3) as an optional signal enrichment layer.

**What must be built:**
- `src/ai_forecast/kronos_adapter.py` — `KronosAdapter`:
  - Accepts `MultiTimeframeContext` and `InstrumentScore` as input
  - Calls Kronos inference API (HTTP, async) or runs a local model
  - Returns `ForecastResult`
  - Must be **non-blocking**: if Kronos is unavailable, strategies fall back to non-enriched signals
  - Must be **read-only**: Kronos never generates orders. It only produces forecasts.

- `ForecastResult` (frozen Pydantic model): `instrument_token`, `forecast_horizon: str` (e.g. "15m"), `direction: str` (UP/DOWN/NEUTRAL), `confidence: Decimal` (0–1), `price_target: Optional[Decimal]`, `forecast_error: Optional[str]`, `model_version: str`, `computed_at: datetime`.

**Constraint:** `KronosAdapter` must never call `RiskIntegrationLayer.submit_order()` or any execution method. It is a pure read path.

### 2.3.2 Forecast Confidence Gating

**Goal:** Optionally filter strategy signals by minimum forecast confidence.

**What must be built:**
- `src/ai_forecast/confidence_gate.py` — `ForecastConfidenceGate`:
  - `should_allow_signal(signal: Signal, forecast: ForecastResult, min_confidence: Decimal) -> bool`
  - Integrated into `SignalRouter` as an optional pre-routing filter (not the risk gate)
  - When `KronosAdapter` is unavailable, gate passes all signals (fail-open)

### 2.3.3 Volatility Forecasting

**Goal:** Provide intraday volatility forecasts to inform position sizing.

**What must be built:**
- `src/ai_forecast/volatility.py` — `VolatilityForecaster`:
  - Takes rolling OHLCV history and computes ATR-based and GARCH-lite volatility estimates
  - Returns `VolatilityForecast` (frozen Pydantic): `instrument_token`, `predicted_atr: Decimal`, `predicted_range_pct: Decimal`, `confidence: Decimal`, `forecast_horizon: str`, `computed_at: datetime`
  - Used by Portfolio Management (RC-10C) for dynamic position sizing

### 2.3.4 Feature Generation

**Goal:** Generate ML-ready feature vectors from market data.

**What must be built:**
- `src/ai_forecast/features.py` — `FeatureGenerator`:
  - Accepts `MultiTimeframeContext` → returns `FeatureVector` (frozen Pydantic): ordered `Decimal` values with feature names
  - Feature set: returns, momentum, volume ratios, volatility, MACD crossover flags, RSI zones, regime one-hot encoding
  - Used by `KronosAdapter` as input

### 2.3.5 Benchmark Framework

**Goal:** Track forecast accuracy over time to detect model degradation.

**What must be built:**
- `src/ai_forecast/benchmark.py` — `ForecastBenchmark`:
  - Records `ForecastResult` at time T and actual outcome at time T + horizon
  - Computes directional accuracy, calibration, and Sharpe of following forecasts
  - Persisted in a new `forecast_benchmark` PostgreSQL table (migration 0004)
  - Exposes `get_accuracy_report(instrument_token?, last_n_forecasts=100) -> BenchmarkReport`

---

## 2.4 RC-10C — Portfolio Management

### 2.4.1 Dynamic Position Sizing

**Goal:** Compute optimal trade quantities based on risk parameters, volatility, and available capital.

**What must be built:**
- `src/portfolio/sizing.py` — `PositionSizer`:
  - `compute_quantity(signal, portfolio_snapshot, volatility_forecast, risk_config) -> Decimal`
  - Implements Kelly Criterion (fractional), fixed-risk (1% per trade default), and volatility-adjusted sizing
  - Respects `StrategyConfig.max_position_quantity` as hard cap
  - Returns `SizingResult` (frozen Pydantic): `recommended_quantity`, `sizing_method`, `rationale: str`, `risk_fraction_used: Decimal`

**Integration:** Called inside `SignalRouter` after risk approval, before order submission. The signal's quantity may be adjusted downward (never upward) based on the sizing result.

### 2.4.2 Portfolio Allocation

**Goal:** Enforce capital allocation limits across simultaneous strategies.

**What must be built:**
- `src/portfolio/allocation.py` — `PortfolioAllocator`:
  - Tracks capital reserved per strategy
  - `can_allocate(strategy_id, quantity, current_price) -> bool` — checks against per-strategy capital limit
  - `reserve(strategy_id, notional)` / `release(strategy_id, notional)` — on signal route / on fill or rejection
  - Thread-safe via asyncio.Lock
  - Injected into coordinator (optional kwarg)

### 2.4.3 Sector Exposure

**Goal:** Limit total exposure to any single NIFTY sector.

**What must be built:**
- `src/portfolio/sector.py` — `SectorExposureTracker`:
  - Reads sector classification from `instrument_master` (sector field — must be added in migration 0004)
  - `get_sector_exposure(portfolio_snapshot) -> Dict[str, Decimal]` — notional by sector
  - `check_sector_limit(sector, proposed_notional, max_pct) -> bool`
  - Used as a new risk rule input (`SECTOR_EXPOSURE` check type — migration adds this to the enum)

### 2.4.4 Correlation Limits

**Goal:** Prevent holding highly correlated instruments simultaneously.

**What must be built:**
- `src/portfolio/correlation.py` — `CorrelationMonitor`:
  - Maintains a rolling correlation matrix from recent bar data
  - `check_correlation(new_instrument_token, current_positions, threshold) -> bool` — returns False if new position would exceed correlation threshold with any existing position
  - `correlation_threshold` default from `settings.risk.correlation_threshold` (already in config: 0.7)

### 2.4.5 Capital Allocation Engine

**Goal:** Divide total capital between strategies based on scores and regime alignment.

**What must be built:**
- `src/portfolio/capital.py` — `CapitalAllocationEngine`:
  - Accepts `List[StrategyScore]` + total equity → returns `Dict[strategy_id, Decimal]` (capital per strategy)
  - Allocation methods: equal weight, score-proportional, risk-adjusted
  - Re-allocation triggered on each scan cycle (not on each bar)

---

## 2.5 RC-10D — Broker Layer

### 2.5.1 Full Zerodha Kite Integration

**Goal:** Enable real order placement via Zerodha Kite Connect API.

**What must be built:**
- `src/brokers/zerodha_kite.py` — `ZerodhaKiteClient` (implements `BrokerInterface`):
  - OAuth2 login with `ZERODHA_API_KEY` / `ZERODHA_API_SECRET` (already in `Settings` and Replit secrets)
  - `place_order`, `modify_order`, `cancel_order`, `get_positions`, `get_orders`, `get_margins`, `get_instruments`, `get_quote`
  - Uses `kiteconnect` Python library
  - Session token stored in DB (`zerodha_sessions` table — migration 0005)
  - Retry logic with exponential backoff on Kite API rate limits (rate limit: 3 req/s per API key)

**Safety constraint:** Live orders must still pass through `RiskIntegrationLayer`. `ZerodhaKiteClient` implements `BrokerInterface`, not `ExecutionEnginePort`. A new `ZerodhaExecutionAdapter` wraps it and implements `ExecutionEnginePort`. This adapter is used only when `settings.trading.mode != "PAPER"`. In PAPER mode, `PaperBroker` is used. Note: LIVE mode validator must be relaxed (currently hard-blocked) — this is a planned change in RC-10D.

### 2.5.2 Order Synchronisation

**Goal:** Reconcile internal order state with Kite's order book every N seconds.

**What must be built:**
- `src/brokers/order_sync.py` — `OrderSyncService`:
  - Background asyncio task: polls `ZerodhaKiteClient.get_orders()` on a configurable interval
  - Detects discrepancies between internal DB order state and Kite's reported state
  - On mismatch: emits `OrderSyncEvent` and updates internal state
  - Handles PARTIAL_FILL → COMPLETE transitions
  - Publishes `FillEvent` via `FillEventBus` when Kite reports a fill not yet in DB

### 2.5.3 Position Reconciliation

**Goal:** Ensure internal position state matches Kite's position data.

**What must be built:**
- `src/brokers/position_reconciler.py` — `PositionReconciler`:
  - Runs at session open and on-demand
  - Calls `ZerodhaKiteClient.get_positions()` and compares with `PositionRepository` data
  - On mismatch: logs critical alert, sets a reconciliation flag on the session, stops all strategies pending operator review
  - Persists reconciliation audit records

### 2.5.4 Account Management

**Goal:** Expose account-level information (margins, limits, holdings) via the API.

**What must be built:**
- `src/api/routers/account.py` — new router:
  - `GET /account/margins` → current margins from Kite
  - `GET /account/holdings` → long-term holdings
  - `GET /account/profile` → account metadata
- Data flows through `ZerodhaKiteClient` only when Kite is connected; returns paper data otherwise.

---

## 2.6 RC-10E — Operations

### 2.6.1 Strategy Management Dashboard (API)

**Goal:** Expose the `StrategyCoordinator` via REST.

**What must be built:**
- `src/api/routers/strategies.py` — new router:
  - `POST /strategies` — register a strategy (body: `StrategyConfig` + strategy_type)
  - `GET /strategies` — list all registered strategies with their `HealthReport` and `StrategyMetrics`
  - `GET /strategies/{strategy_id}` — detailed strategy status
  - `POST /strategies/{strategy_id}/start` — start
  - `POST /strategies/{strategy_id}/pause` — pause
  - `POST /strategies/{strategy_id}/resume` — resume
  - `POST /strategies/{strategy_id}/stop` — stop
  - `GET /strategies/{strategy_id}/signals` — recent signals
  - `GET /strategies/{strategy_id}/health` — `HealthReport`
  - `GET /strategies/{strategy_id}/metrics` — `StrategyMetrics`

### 2.6.2 Analytics

**Goal:** Provide P&L, win rate, and trade analytics per strategy and per session.

**What must be built:**
- `src/analytics/performance.py` — `PerformanceAnalytics`:
  - Computes `StrategyPerformanceSnapshot` from fills (FIFO P&L matching — already established in project)
  - Tracks drawdown from peak equity per strategy
  - `GET /analytics/performance` — session-level P&L summary
  - `GET /analytics/strategies/{strategy_id}/performance` — strategy-level metrics

### 2.6.3 Alerts

**Goal:** Push-notify operators on critical events.

**What must be built:**
- `src/alerts/` — alert dispatcher:
  - Subscribes to: `FillEventBus`, strategy health state changes (UNHEALTHY), kill switch activations, reconciliation mismatches
  - Dispatches via: structured log (always), webhook (if configured), WebSocket push (for dashboard)
  - `AlertRecord` (frozen Pydantic): `alert_id`, `severity` (INFO/WARNING/CRITICAL), `category`, `message`, `strategy_id?`, `instrument_token?`, `triggered_at`
  - `POST /alerts/subscribe` (WebSocket endpoint) for real-time dashboard feed
  - Persisted to `incidents` table (already in schema)

### 2.6.4 Performance Reporting

**Goal:** Generate session-end and daily summary reports.

**What must be built:**
- `src/analytics/reports.py` — `ReportGenerator`:
  - End-of-session report: total P&L, max drawdown, trade count, win rate, strategy breakdown
  - Persisted as a `SessionReport` in a new `session_reports` table (migration 0006)
  - `GET /reports/{session_id}` — fetch a session report
  - Reports are generated automatically on session close

### 2.6.5 Long-Duration Soak Testing

**Goal:** Validate the bot can run for hours/days without memory leaks, deadlocks, or data corruption.

**What must be built:**
- `tests/soak/` — soak test suite:
  - `test_24h_paper_simulation.py`: replays 24 hours of synthetic bar data through the full stack
  - Checks: memory growth, DB connection pool health, asyncio task accumulation, signal persistence integrity, P&L consistency
  - Configurable via `SOAK_DURATION_HOURS` env var
  - CI-gated: soak tests run weekly, not on every PR

---

# PART 3 — EXTERNAL REPOSITORY INSIGHTS

## 3.1 MarkAnn-Bot — Corporate Announcement Intelligence

### What it does
MarkAnn-Bot polls BSE and NSE announcement feeds, classifies announcements using a rule-based classifier (+ optional AI summarisation), and publishes structured events.

### Architecture to adopt

**Event intelligence model:**
- Each announcement is a domain event: `AnnouncementPublished(announcement_id, exchange, symbol, classification, headline, body_text, published_at, effective_date)`
- Events are deduplicated by `(exchange, announcement_id)` within a configurable TTL window
- Classifications: `EARNINGS_RESULT`, `DIVIDEND`, `BONUS`, `STOCK_SPLIT`, `MERGER_ACQUISITION`, `BOARD_MEETING`, `REGULATORY`, `OTHER`

**Integration pattern for this project:**
1. `AnnouncementPoller` (background task) polls BSE/NSE announcement APIs on a 1-minute interval
2. New announcements are classified and stored in the `announcements` table (migration 0004)
3. `AnnouncementIntelligenceService.get_active_announcements(instrument_token)` queries the table for announcements within the trading day
4. `ContextBuilder` includes active announcements in `StrategyContext.market_snapshots`

**AI summarisation:** Optional. Wrap a call to an LLM API to produce a 1-sentence summary of the announcement body. This is a best-effort enrichment; if unavailable, the raw headline is used.

**Notification architecture:** Significant announcements (EARNINGS_RESULT, MERGER_ACQUISITION) trigger an immediate `CRITICAL` alert via the alerts subsystem (RC-10E). All announcement events are also persisted to `audit_log`.

**Key decision:** MarkAnn-Bot's event classification logic must be deterministic for the same input text. The classification model must be versioned and recorded in the `AnnouncementRecord`.

---

## 3.2 Kronos — AI Forecasting

### What it does
Kronos is an AI forecasting service that takes multi-timeframe feature vectors as input and predicts short-horizon price direction and volatility.

### Architecture to adopt

**No direct order generation.** Kronos operates exclusively in the read path. It never calls `submit_order`, never reads the current portfolio state, and never interacts with the risk engine. Its only output is `ForecastResult`.

**Research isolation.** The ML model and training pipeline are completely separate from the bot's runtime. The bot only calls a stateless inference endpoint (HTTP REST or a local Python model call). Model updates are deployed independently of bot deployments.

**Forecast confidence gating.** Strategies can declare a `min_forecast_confidence` in their `StrategyConfig.parameters`. The `ForecastConfidenceGate` filters signals from strategies that have this set, allowing only signals where Kronos confidence ≥ threshold.

**Volatility prediction** feeds directly into `PositionSizer.compute_quantity()` — a high-volatility forecast reduces the recommended quantity.

**Benchmark framework** is critical for production use. Every forecast must be recorded with its inputs and later evaluated against the actual outcome. Model degradation must trigger an alert. This enforces accountability: if Kronos starts underperforming random signals, its forecasts should be disabled automatically.

**Feature generation contract:** Kronos consumes a fixed-schema `FeatureVector`. If the schema changes (new indicators, new timeframes), the model must be retrained and the version updated in `ForecastResult.model_version`. The bot must log `model_version` in every forecast record.

---

## 3.3 intraday-trading-ai-india — Market Intelligence Design

### What it does
This reference implementation provides multi-timeframe analysis, market regime detection, watchlist ranking, strategy scoring, and dynamic position sizing for NSE intraday trading.

### Architecture to adopt

**Multi-timeframe analysis design:**
- Primary timeframe: 1m (all strategy decisions)
- Confirmation timeframes: 5m (short-term trend), 15m (intermediate trend), 1h (regime filter)
- Rule: a ENTER_LONG signal from a 1m strategy is only acted upon if the 5m and 15m trends are not strongly bearish
- `TimeframeAggregator` buffers 1m bars and emits a 5m bar after every 5th 1m bar, etc.

**Market regime detection — specific algorithm:**
```
ADX > 25 and +DI > -DI → UPTREND (or STRONG_UPTREND if ADX > 40)
ADX > 25 and -DI > +DI → DOWNTREND (or STRONG_DOWNTREND if ADX > 40)
ADX < 20 and ATR/price < 0.005 → RANGING
ATR/price > 0.02 → EXPANDING_RANGE
otherwise → UNKNOWN
```

**Watchlist ranking scoring factors:**
1. Regime quality (STRONG_UPTREND = 1.0, UPTREND = 0.7, RANGING = 0.4, bearish = 0.1)
2. Relative volume (today's volume / 20-day avg volume)
3. Momentum score (RSI normalised 0–1)
4. ATR as percentage of price (opportunity proxy)
5. Spread / liquidity (bid-ask spread from `Quote`)

**Dynamic position sizing algorithm:**
```
risk_per_trade = settings.risk.risk_per_trade_pct / 100 * portfolio_equity
atr_stop = predicted_atr * 1.5   (from VolatilityForecaster)
quantity = risk_per_trade / (atr_stop * current_price)
quantity = min(quantity, config.max_position_quantity)
quantity = min(quantity, portfolio_allocator.available_capital(strategy_id) / current_price)
```

**Modular indicator architecture:** Each indicator is a pure function `compute_<name>(bars: List[CompletedBar], period: int) -> Decimal`. No class inheritance. Indicators are composed by `IndicatorEngine` which maintains rolling buffers per `(instrument_token, timeframe, indicator_name, period)`.

---

# PART 4 — IMPLEMENTATION ROADMAP

## Phase Overview

| Phase | Capability | Dependency | Estimated Complexity |
|-------|-----------|-----------|---------------------|
| 10A | Market Intelligence Layer | RC-9 stable | Medium |
| 10B | AI Forecast Layer | 10A (features, regime) | High |
| 10C | Portfolio Management | 10A (ranking), 10B (volatility) | Medium |
| 10D | Broker Layer | RC-9 (broker interface exists) | High |
| 10E | Operations | All above | Medium |

Phases 10A and 10D can be developed in parallel. 10B requires 10A features. 10C requires 10A ranking and 10B volatility. 10E requires all.

---

## Phase 10A — Market Intelligence Layer

### Objective
Provide every strategy with multi-timeframe indicator data, market regime context, watchlist ranking, and corporate announcement awareness through the existing `StrategyContext.market_snapshots` extension point.

### Files Affected (existing)
- `src/strategy/context_builder.py` — extend `build()` to populate `market_snapshots`
- `src/database/models.py` — add `sector` column to `instrument_master`, `announcements` table
- `pyproject.toml` — add `ta-lib` or `pandas-ta` for indicator computation

### New Modules
```
src/market_intelligence/
├── __init__.py
├── timeframe.py          # TimeframeAggregator
├── indicator_engine.py   # IndicatorEngine + pure indicator functions
├── multi_timeframe_context.py  # MultiTimeframeContext (frozen Pydantic)
├── regime.py             # MarketRegimeDetector + MarketRegimeSnapshot
├── ranking.py            # WatchlistRanker + InstrumentScore + WatchlistRankingSnapshot
├── strategy_scoring.py   # StrategyScorer + StrategyScore
└── announcements.py      # AnnouncementIntelligenceService + AnnouncementRecord

migrations/versions/
└── 0004_rc10a_announcements_sector.py
```

### Interfaces

```python
# TimeframeAggregator
class TimeframeAggregator:
    def __init__(self, instrument_token: str, target_interval: str): ...
    def on_bar(self, bar: CompletedBar) -> Optional[CompletedBar]: ...  # returns aggregated bar or None

# IndicatorEngine
class IndicatorEngine:
    def update(self, bar: CompletedBar, timeframe: str) -> None: ...
    def get_indicators(self, instrument_token: str, timeframe: str) -> Dict[str, Decimal]: ...

# MarketRegimeDetector
class MarketRegimeDetector:
    def detect(self, bars: List[CompletedBar], indicators: Dict[str, Decimal]) -> MarketRegimeSnapshot: ...

# WatchlistRanker
class WatchlistRanker:
    def rank(self, instrument_scores: List[InstrumentScore]) -> WatchlistRankingSnapshot: ...

# AnnouncementIntelligenceService
class AnnouncementIntelligenceService:
    async def get_active_announcements(self, instrument_token: str) -> List[AnnouncementRecord]: ...
    async def poll_and_classify(self) -> int: ...  # returns count of new announcements
```

### Test Plan

- `tests/unit/market_intelligence/test_timeframe.py` — aggregation correctness for 5m/15m/1h
- `tests/unit/market_intelligence/test_indicators.py` — each indicator function, known-value tests
- `tests/unit/market_intelligence/test_regime.py` — regime detection from synthetic OHLCV sequences
- `tests/unit/market_intelligence/test_ranking.py` — ranking order and score bounds
- `tests/unit/market_intelligence/test_announcements.py` — classification, deduplication, TTL
- Integration test: `ContextBuilder` with `MultiTimeframeContext` injected; assert `market_snapshots` populated correctly

### Risks

1. **Performance:** Computing indicators for 50+ instruments × 4 timeframes on every bar could be slow. Mitigation: `IndicatorEngine` maintains rolling buffers, never recomputes from scratch.
2. **BSE/NSE API availability:** Announcement polling requires public API access. Mitigation: `AnnouncementPoller` has configurable retry with exponential backoff; `AnnouncementIntelligenceService` returns empty list (not error) when data unavailable.
3. **`ContextBuilder` coupling:** Extending it must not break existing strategies. Mitigation: `market_snapshots` dict is already in `StrategyContext`; adding keys does not affect strategies that ignore them.

### Success Criteria

- All existing 445 unit tests still pass
- `MultiTimeframeContext` populated in `StrategyContext` for all instruments in `StrategyConfig.instrument_tokens`
- `MarketRegimeSnapshot` with confidence > 0 produced for each instrument in the watchlist
- `WatchlistRankingSnapshot` produced within 100ms of each scan cycle
- 20+ unit tests for each new module

---

## Phase 10B — AI Forecast Layer

### Objective
Integrate Kronos-style AI forecasting as an optional signal enrichment layer. Strategies can opt in via `StrategyConfig.parameters["min_forecast_confidence"]`.

### Files Affected (existing)
- `src/strategy/signal_router.py` — add optional `ForecastConfidenceGate` check before routing
- `src/strategy/contracts.py` — add `forecast: Optional[ForecastResult]` to `Signal.metadata` (via metadata dict, no schema change needed)
- `pyproject.toml` — add `httpx` (already used) for Kronos HTTP calls

### New Modules
```
src/ai_forecast/
├── __init__.py
├── kronos_adapter.py      # KronosAdapter (async HTTP or local model)
├── confidence_gate.py     # ForecastConfidenceGate
├── volatility.py          # VolatilityForecaster
├── features.py            # FeatureGenerator
└── benchmark.py           # ForecastBenchmark + BenchmarkReport

migrations/versions/
└── 0005_rc10b_forecast_benchmark.py
```

### Interfaces

```python
# KronosAdapter
class KronosAdapter:
    async def forecast(
        self,
        instrument_token: str,
        features: FeatureVector,
        horizon: str = "15m",
    ) -> Optional[ForecastResult]: ...  # returns None if unavailable

# ForecastConfidenceGate
class ForecastConfidenceGate:
    async def should_route(
        self,
        signal: Signal,
        adapter: KronosAdapter,
        features: FeatureVector,
        min_confidence: Decimal,
    ) -> Tuple[bool, Optional[ForecastResult]]: ...

# VolatilityForecaster
class VolatilityForecaster:
    def forecast(self, bars: List[CompletedBar]) -> VolatilityForecast: ...

# FeatureGenerator
class FeatureGenerator:
    def generate(self, context: MultiTimeframeContext) -> FeatureVector: ...

# ForecastBenchmark
class ForecastBenchmark:
    async def record_forecast(self, session: AsyncSession, forecast: ForecastResult) -> None: ...
    async def record_outcome(self, session: AsyncSession, instrument_token: str, horizon: str, actual_return: Decimal) -> None: ...
    async def get_accuracy_report(self, session: AsyncSession, instrument_token: Optional[str] = None, last_n: int = 100) -> BenchmarkReport: ...
```

### Test Plan

- `tests/unit/ai_forecast/test_features.py` — feature vector determinism and bounds
- `tests/unit/ai_forecast/test_volatility.py` — ATR computation, known-value tests
- `tests/unit/ai_forecast/test_confidence_gate.py` — gate open when confidence ≥ threshold, gate closed otherwise, fail-open when adapter unavailable
- `tests/unit/ai_forecast/test_benchmark.py` — record + outcome + accuracy report
- Mocked Kronos: `KronosAdapter` must be fully mockable for unit tests (no live API calls ever in unit tests)

### Risks

1. **Kronos unavailability:** Must fail open — all signals route normally when Kronos is down. The `ForecastConfidenceGate` must never block signals due to infrastructure unavailability.
2. **Latency:** Kronos HTTP call adds latency to the signal hot path. Mitigation: implement async prefetch — start Kronos call as soon as the bar arrives, before `on_bar` completes.
3. **Model drift:** Forecast accuracy degrades silently. Mitigation: `ForecastBenchmark` + weekly accuracy alert if directional accuracy drops below 52%.

### Success Criteria

- `ForecastResult` attached to signal metadata when Kronos available
- `ForecastConfidenceGate` correctly filters signals below threshold
- `ForecastBenchmark` persists forecast + outcome pairs
- No existing test regressions
- `KronosAdapter` returns `None` (not raises) when service unavailable

---

## Phase 10C — Portfolio Management

### Objective
Add dynamic position sizing, capital allocation across strategies, sector exposure limits, and correlation-based position filtering.

### Files Affected (existing)
- `src/strategy/signal_router.py` — call `PositionSizer` before order submission; adjust quantity
- `src/risk/contracts.py` — add `SECTOR_EXPOSURE` to `RiskCheckType` enum
- `src/risk/rules.py` — implement sector exposure rule
- `src/database/models.py` — add `sector` to `InstrumentMaster` (already planned in 10A migration)

### New Modules
```
src/portfolio/
├── __init__.py
├── sizing.py              # PositionSizer + SizingResult
├── allocation.py          # PortfolioAllocator
├── sector.py              # SectorExposureTracker
├── correlation.py         # CorrelationMonitor
└── capital.py             # CapitalAllocationEngine
```

### Interfaces

```python
# PositionSizer
class PositionSizer:
    def compute_quantity(
        self,
        signal: Signal,
        portfolio: PortfolioSnapshot,
        volatility: VolatilityForecast,
        config: StrategyConfig,
        risk_config: RiskSettings,
    ) -> SizingResult: ...

# PortfolioAllocator
class PortfolioAllocator:
    async def can_allocate(self, strategy_id: str, notional: Decimal) -> bool: ...
    async def reserve(self, strategy_id: str, notional: Decimal) -> None: ...
    async def release(self, strategy_id: str, notional: Decimal) -> None: ...
    def get_allocation(self, strategy_id: str) -> Decimal: ...

# SectorExposureTracker
class SectorExposureTracker:
    def get_exposures(self, portfolio: PortfolioSnapshot, instrument_sectors: Dict[str, str]) -> Dict[str, Decimal]: ...
    def check_limit(self, sector: str, proposed_notional: Decimal, total_equity: Decimal, max_pct: Decimal) -> bool: ...

# CorrelationMonitor
class CorrelationMonitor:
    def update(self, bar: CompletedBar) -> None: ...
    def check_correlation(self, new_token: str, current_tokens: List[str], threshold: Decimal) -> bool: ...

# CapitalAllocationEngine
class CapitalAllocationEngine:
    def allocate(self, strategy_scores: List[StrategyScore], total_equity: Decimal) -> Dict[str, Decimal]: ...
```

### Test Plan

- `tests/unit/portfolio/test_sizing.py` — Kelly, fixed-risk, volatility-adjusted; hard cap enforcement
- `tests/unit/portfolio/test_allocation.py` — reserve/release, concurrency (two coroutines competing for allocation)
- `tests/unit/portfolio/test_sector.py` — sector exposure calculation and limit checking
- `tests/unit/portfolio/test_correlation.py` — correlation matrix updates, threshold filtering
- `tests/unit/portfolio/test_capital.py` — equal weight, score-proportional allocation

### Risks

1. **Sizing reduces quantity below minimum:** When the computed quantity rounds to 0, the signal must be dropped (not sent with qty=0). `PositionSizer` must return `SizingResult.recommended_quantity = Decimal("0")` as a signal to skip.
2. **`PortfolioAllocator` state on crash:** Allocation state is in-process only. On restart, all allocations reset to zero. This is correct — the recovery system restores strategy state, and new signals re-acquire allocation.
3. **Sector data dependency:** `SectorExposureTracker` requires sector data in `instrument_master`. If sector is null for an instrument, the rule must default to PASS (never block on missing data).

### Success Criteria

- Position quantities adjusted by `PositionSizer` before execution
- `PortfolioAllocator` prevents strategies from collectively exceeding total capital
- New `SECTOR_EXPOSURE` risk rule blocks orders that would breach sector limit
- Correlation-filtered signals logged with reason
- No existing test regressions

---

## Phase 10D — Broker Layer

### Objective
Enable full Zerodha Kite write integration, with order synchronisation and position reconciliation.

### Files Affected (existing)
- `src/core/config.py` — relax `TradingSettings.enforce_paper_mode` to allow LIVE when Zerodha credentials present
- `src/brokers/paper_broker.py` — no changes (used in PAPER mode)
- `src/database/models.py` — add `zerodha_sessions` table
- `src/api/` — add account router

### New Modules
```
src/brokers/
├── zerodha_kite.py        # ZerodhaKiteClient (full BrokerInterface impl)
├── zerodha_adapter.py     # ZerodhaExecutionAdapter (ExecutionEnginePort impl)
├── order_sync.py          # OrderSyncService (background task)
└── position_reconciler.py # PositionReconciler

src/api/routers/
└── account.py             # GET /account/margins, /holdings, /profile

migrations/versions/
└── 0006_rc10d_zerodha_sessions.py
```

### Interfaces

```python
# ZerodhaKiteClient — implements BrokerInterface
class ZerodhaKiteClient(BrokerInterface):
    def __init__(self, api_key: str, api_secret: str, session_token: Optional[str] = None): ...
    async def login(self, request_token: str) -> str: ...  # returns access_token
    # ... all BrokerInterface methods

# ZerodhaExecutionAdapter — implements ExecutionEnginePort
class ZerodhaExecutionAdapter(ExecutionEnginePort):
    def __init__(self, kite: ZerodhaKiteClient): ...
    # ... all ExecutionEnginePort methods

# OrderSyncService
class OrderSyncService:
    def __init__(self, kite: ZerodhaKiteClient, order_repo: OrderRepository, fill_bus: FillEventBus): ...
    async def start(self, interval_seconds: int = 10) -> None: ...
    async def stop(self) -> None: ...
    async def sync_once(self) -> int: ...  # returns count of synced orders

# PositionReconciler
class PositionReconciler:
    def __init__(self, kite: ZerodhaKiteClient, position_repo: PositionRepository, coordinator: StrategyCoordinator): ...
    async def reconcile(self, session: AsyncSession) -> ReconciliationResult: ...
```

### Test Plan

- `tests/unit/brokers/test_zerodha_kite.py` — all methods mocked via `kiteconnect` mock; order placement, cancellation, position fetch
- `tests/unit/brokers/test_order_sync.py` — sync detects PENDING→COMPLETE transitions, publishes FillEvent
- `tests/unit/brokers/test_position_reconciler.py` — detects mismatches, stops strategies on mismatch
- **Never write tests that call the live Kite API.** All Kite interactions must be mockable.
- Integration test: paper mode with ZerodhaReadonly for quotes (no order placement)

### Risks

1. **Rate limiting:** Kite Connect allows 3 req/s. Mitigation: `ZerodhaKiteClient` enforces a token bucket rate limiter.
2. **Session token expiry:** Kite access tokens expire daily. Mitigation: `OrderSyncService` detects 403 errors and triggers re-login flow.
3. **Live mode safety:** The `enforce_paper_mode` validator is a safety gate. When relaxing it for LIVE, add a double-confirmation mechanism (`ENABLE_LIVE_TRADING=true` AND `LIVE_TRADING_CONFIRMED=true` env vars, both required).
4. **Position mismatch on partial fills:** Kite may report a position the bot has no record of (e.g., manual trade in Kite UI). Mitigation: `PositionReconciler` flags these as `EXTERNAL_POSITION` and excludes them from bot-managed P&L.

### Success Criteria

- `ZerodhaKiteClient.place_order()` routes through `RiskIntegrationLayer` without bypass
- `OrderSyncService` detects fill within 10 seconds of Kite reporting it
- `PositionReconciler` stops all strategies on position mismatch
- Session token persisted and re-used across restarts
- All Kite tests pass with mocked client; zero live API calls in test suite

---

## Phase 10E — Operations

### Objective
Wire all RC-10 capabilities together with a management API, analytics, alerting, reporting, and long-duration validation.

### Files Affected (existing)
- `src/main.py` — wire new routers, start background tasks (AnnouncementPoller, OrderSyncService)
- `src/api/` — include new routers in app

### New Modules
```
src/api/routers/
├── strategies.py          # Strategy management CRUD + lifecycle endpoints
└── account.py             # (already in 10D)

src/analytics/
├── performance.py         # PerformanceAnalytics
└── reports.py             # ReportGenerator + SessionReport

src/alerts/
├── dispatcher.py          # AlertDispatcher
└── websocket.py           # WebSocket /alerts/subscribe

migrations/versions/
└── 0007_rc10e_session_reports.py

tests/soak/
└── test_24h_paper_simulation.py
```

### Interfaces

```python
# PerformanceAnalytics
class PerformanceAnalytics:
    async def compute_strategy_performance(
        self, session: AsyncSession, strategy_id: str
    ) -> StrategyPerformanceSnapshot: ...
    async def compute_session_performance(
        self, session: AsyncSession, session_id: str
    ) -> SessionPerformanceReport: ...

# AlertDispatcher
class AlertDispatcher:
    def subscribe_fill_bus(self, fill_bus: FillEventBus) -> None: ...
    def subscribe_health_monitor(self, monitor: StrategyHealthMonitor) -> None: ...
    async def dispatch(self, alert: AlertRecord) -> None: ...

# ReportGenerator
class ReportGenerator:
    async def generate_session_report(
        self, session: AsyncSession, trading_session_id: str
    ) -> SessionReport: ...
```

### Test Plan

- `tests/unit/analytics/test_performance.py` — FIFO P&L matching, drawdown calculation, win rate
- `tests/unit/analytics/test_reports.py` — report generation, schema validation
- `tests/unit/alerts/test_dispatcher.py` — alert triggered on health transition, fill, kill switch
- `tests/integration/test_strategy_api.py` — full lifecycle via HTTP: register → start → signal → stop
- `tests/soak/test_24h_paper_simulation.py` — 24h replay with assertions on memory, connection pool, P&L integrity

### Risks

1. **WebSocket scaling:** Multiple operator dashboards subscribing simultaneously. Mitigation: use asyncio task per subscriber with a max-subscribers limit.
2. **Report generation on large datasets:** A session with 10,000 fills may cause slow report generation. Mitigation: reports are computed asynchronously on session close, not on-demand.
3. **Soak test flakiness:** Timing-sensitive assertions in long-running tests tend to be fragile. Mitigation: all soak assertions use absolute counts and states, not timing-based polling.

### Success Criteria

- All strategy lifecycle operations available via REST (`/strategies/*`)
- `StrategyPerformanceSnapshot` computed correctly for a simulated 100-trade session
- `AlertDispatcher` fires `CRITICAL` alert within 1 second of kill switch activation
- `ReportGenerator` produces non-empty report on session close
- Soak test runs for configured duration without OOM, deadlock, or P&L error
- Full suite: 600+ tests passing, 0 regressions

---

## Integration Constraints (All Phases)

The following constraints apply throughout RC-10 and are non-negotiable:

1. **All order flow must pass through `RiskIntegrationLayer.submit_order()`** — no exceptions, including Zerodha Kite orders.

2. **`SessionContext` is the sole commit site** — no new code may call `session.commit()`, `session.rollback()`, or `session.close()`.

3. **Frozen RC-9 contracts must not change** — if a new field is needed on `Signal`, add it to `Signal.metadata: Dict`. If a new field is needed on `StrategyContext`, add it to `StrategyContext.market_snapshots: Dict`.

4. **Kronos never generates orders** — `KronosAdapter` is read-only. It may not import from `execution`, `risk.integration_layer`, or `strategy.signal_router`.

5. **All tests must be unit-level unless they absolutely require I/O** — integration tests are for HTTP path validation only. No live Kite API, no live Kronos API, no live announcement feeds in test suite.

6. **New Alembic migrations must be additive** — never modify existing columns. Add new columns with defaults or nullable constraints.

7. **`account_id` wiring** — RC-10 should wire `account_id` from the trading session into `StrategyConfigRecord` and `StrategySignalRecord`. This unblocks per-account strategy isolation and P&L attribution.

8. **`StrategyFactory` implementation** — RC-10 must provide a concrete `StrategyFactory` that the `StrategyCoordinator.recover()` method can use to reconstruct strategy instances from DB records. The current `_NullStrategyFactory` is a stub.

---

*End of RC-10 Reference Document. Version 1.0, 2026-07-23.*
