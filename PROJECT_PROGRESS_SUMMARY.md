# PROJECT PROGRESS SUMMARY
### NSE Paper Trading Platform — Release Candidate RC-7
**Prepared for:** Batch 8 onboarding (Kimi)
**Date:** 19 July 2026
**Status:** ✅ Production-ready execution engine. All 279 execution unit tests passing. RC-7 approved.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Completed Batches](#2-completed-batches)
3. [Current Architecture](#3-current-architecture)
4. [Execution Engine Capabilities](#4-execution-engine-capabilities)
5. [Database Layer](#5-database-layer)
6. [Test Status](#6-test-status)
7. [Design Principles](#7-design-principles)
8. [What Batch 8 Should Assume](#8-what-batch-8-should-assume)
9. [What Not To Do](#9-what-not-to-do)

---

## 1. Project Overview

### Project Name
**NSE Paper Trading Platform** — a simulation-grade paper execution engine for Indian equity markets (National Stock Exchange), built to operate against live Zerodha Kite Connect market data feeds.

### Primary Objective
Provide a complete, deterministic, crash-recoverable paper trading environment that faithfully simulates NSE order execution, fill matching, position accounting, and P&L tracking — without touching real money or real broker order books.

### Current Stage
**Release Candidate RC-7.** The execution engine (Batches 7A–7D) has passed production readiness audit. The market data foundation (Batch 6) is integrated. The system is ready for higher-level features to be built on top of the execution layer.

### High-Level Architecture

The platform is a Python backend service (`artifacts/api-server/src/python`) structured as a clean-layered monolith with four main packages:

```
src/
├── brokers/           # External data provider adapters (Zerodha Kite Connect)
├── database/          # ORM models + session-injected async repositories
│   ├── models/        # SQLAlchemy declarative models (shared Base)
│   └── repositories/  # Data access objects — no commit, no transaction ownership
├── execution/         # Paper execution engine (RC-7 production-ready)
│   ├── contracts.py   # Immutable domain types and enumerations
│   ├── state_machine.py
│   ├── matching.py
│   ├── fills.py
│   ├── trades.py
│   ├── portfolio.py
│   ├── position_engine.py
│   ├── pnl.py
│   ├── policies.py
│   ├── engine.py
│   ├── exceptions.py
│   └── recovery/      # Crash recovery, persistence adapters, deterministic replay
└── market_data/       # Market data pipeline (Batch 6)
```

The backend exposes a REST/WebSocket API (Node.js `api-server` layer, not described here). The Python engine is the computational core consumed by that API.

---

## 2. Completed Batches

---

### Batch 6 — Market Data Foundation

**Purpose:** Establish a production-quality market data pipeline capable of ingesting live ticks from Zerodha Kite Connect, assembling them into OHLCV bars, detecting data quality issues, and persisting bars to PostgreSQL. This is the feed layer that execution depends on for market snapshots.

**Key Modules:**

| Module | Responsibility |
|---|---|
| `market_data/contracts.py` | Immutable data types: `Tick`, `Quote`, `CompletedBar`, `DataQualityStatus`, `DataQualityEvent`, `SubscriptionRequest`, `DataGap` |
| `market_data/provider.py` | Abstract base class `MarketDataProvider` — implemented by broker adapters |
| `market_data/service.py` | `MarketDataService` — orchestrates the pipeline: connects provider, routes ticks, manages subscriptions |
| `market_data/subscription_manager.py` | `SubscriptionManager` — tracks per-instrument consumers, handles subscribe/unsubscribe lifecycle |
| `market_data/bar_builder.py` | `BarBuilder` — assembles inbound ticks into time-bucketed OHLCV bars; emits `CompletedBar` on bar close |
| `market_data/quality.py` | `DataQualityTracker` — detects stale data, gaps, and degraded feeds; emits quality events |
| `market_data/backfill.py` | `BackfillCoordinator` — fills historical gaps via Kite REST API on startup or reconnect |
| `market_data/instrument_sync.py` | `InstrumentSync` — synchronises the NSE instrument master from Kite Connect |
| `brokers/zerodha_market_data.py` | `ZerodhaMarketDataProvider` — concrete `MarketDataProvider` backed by KiteTicker WebSocket and Kite REST |

**Major Classes:** `MarketDataProvider` (ABC), `MarketDataService`, `SubscriptionManager`, `BarBuilder`, `DataQualityTracker`, `BackfillCoordinator`, `InstrumentSync`, `ZerodhaMarketDataProvider`

**Design Decisions:**
- Provider is an abstract interface — `ZerodhaMarketDataProvider` is swappable with any other exchange adapter without changing downstream consumers.
- `BarBuilder` is stateful per instrument; each instrument has its own bar state machine.
- Data quality tracking is decoupled from bar building — quality events are emitted separately so consumers can choose how to react.
- Backfill is triggered on startup and on reconnect, not on a schedule.
- `MinuteBarRepository` (in `database/repositories/`) persists completed bars to PostgreSQL.

**Current Status:** ✅ Integrated. Unit-tested. Used as the market data source for the matching engine.

---

### Batch 7A — Order Contracts & State Machine

**Purpose:** Define the immutable domain types that represent every order, action, and audit event in the system, and implement a concurrency-safe, idempotent order state machine that enforces the full NSE order lifecycle as a directed state graph.

**Key Modules:**

| Module | Responsibility |
|---|---|
| `execution/contracts.py` | All domain enums and Pydantic models |
| `execution/state_machine.py` | Order state machine with per-order async locking |
| `execution/exceptions.py` | Typed exception hierarchy |

**Major Classes:**

- `ExecutionOrderStatus` (Enum) — `CREATED → VALIDATED → ACCEPTED → OPEN → PARTIALLY_FILLED → FILLED / REJECTED / CANCELLED / EXPIRED / FAILED`
- `ExecutionOrderType` (Enum) — `MARKET`, `LIMIT`, `SL`, `SL_M`
- `ExecutionOrderSide` (Enum) — `BUY`, `SELL`
- `ExecutionOrderAction` (Enum) — 11 transition triggers (`SUBMIT`, `VALIDATE`, `ACCEPT`, `REJECT`, `OPEN`, `PARTIALLY_FILL`, `FILL`, `REQUEST_CANCEL`, `CANCEL`, `EXPIRE`, `FAIL`)
- `ExecutionOrder` (Pydantic, frozen) — the canonical order contract with field-level validation
- `FillRecord` (Pydantic, frozen) — broker fill acknowledgement embedded in audit events
- `ExecutionAuditEvent` (Pydantic, frozen) — immutable record of every state transition
- `OrderState` — mutable per-order state envelope managed by the state machine
- `TransitionResult` — result of every transition attempt (success, previous state, new state, audit event)
- `OrderStateMachine` — the central state machine; per-order `asyncio.Lock`; idempotency via `(client_order_id, action)` dedup set; full audit trail
- `ExecutionException`, `InvalidStateTransition`, `OrderValidationError`, `IdempotencyViolation`, `OverfillError`, `ConcurrentTransitionError`

**Design Decisions:**
- All domain types are Pydantic `BaseModel` with `frozen=True` — structurally immutable after construction.
- Enums are `str, Enum` — serialise to their string value natively, no custom JSON encoders needed.
- The state machine uses `WeakValueDictionary` for per-order locks — locks are garbage-collected when their order is no longer referenced.
- `PARTIALLY_FILL`, `FILL`, and `OPEN` are excluded from idempotency dedup — fill quantity guards provide equivalent safety.
- `submit()` is a convenience that combines `register()` + `validate()` in one call.
- Every transition produces an `ExecutionAuditEvent` — the audit trail is always complete.
- Terminal states (`FILLED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `FAILED`) reject all further transitions.

**Current Status:** ✅ Production-ready. 68 unit tests pass.

---

### Batch 7B — Matching & Fill Engine

**Purpose:** Implement the deterministic paper matching engine that evaluates open orders against incoming market snapshots and produces fills according to pluggable price, slippage, liquidity, and latency policies.

**Key Modules:**

| Module | Responsibility |
|---|---|
| `execution/matching.py` | Order evaluation logic and market snapshot normalization |
| `execution/fills.py` | `FillEvent` domain type and builder |
| `execution/policies.py` | Pluggable price selection, slippage, liquidity, and latency policies |
| `execution/engine.py` | `MatchingEngine` — the top-level paper execution orchestrator |

**Major Classes:**

- `MarketSnapshot` — normalised market data snapshot consumed by matchers (LTP, bid, ask, volume, timestamp)
- `MatchResult` — result of evaluating one order against one snapshot (matched/not-matched, executable price, fill quantity)
- `TriggerStateTracker` — sticky state machine for stop-loss trigger activation; once triggered, remains triggered
- `OrderMatcher` — stateless evaluator; routes each order type to the correct matching logic
- `EngineResult` — result of processing one market event through the full engine (fills produced, orders updated)
- `MatchingEngine` — registers orders, calls `OrderMatcher` per snapshot, drives the state machine on match
- `FillEvent` (Pydantic, frozen) — the internal fill event flowing into `PositionEngine`
- `FillEventBuilder` — constructs `FillEvent` from `MatchResult` + order context
- `PriceSelectionPolicy` (Protocol), `DefaultPriceSelectionPolicy` — BUY prefers ask; SELL prefers bid; LTP fallback
- `SlippagePolicy` (Protocol), `BasisPointsSlippagePolicy`, `FixedTicksSlippagePolicy` — deterministic slippage models
- `LiquidityPolicy` (Protocol), `DefaultLiquidityPolicy` — fill quantity capped by available market liquidity
- `LatencyPolicy` (Protocol), `ZeroLatencyPolicy`, `FixedLatencyPolicy` — market event eligibility window

**Design Decisions:**
- All policies are Protocols — any combination is injectable at engine construction time; defaults are provided for all.
- Matching is stateless per evaluation; state (trigger activation, fill quantity) lives in `OrderState` and `TriggerStateTracker`.
- The engine does not commit to the database — it produces `FillEvent` objects and drives state machine transitions; persistence is the caller's responsibility.
- `FillEvent` is distinct from `FillRecord` (broker acknowledgement in `contracts.py`) — `FillEvent` is an internal engine event, not a broker concept.
- `MatchingEngine.reset()` enables deterministic replay by clearing all in-memory state.

**Current Status:** ✅ Production-ready. 73 unit tests pass.

---

### Batch 7C — Position, Portfolio & P&L

**Purpose:** Implement the position accounting engine that processes fill events into position state, tracks realized and unrealized P&L, and maintains an aggregate portfolio snapshot.

**Key Modules:**

| Module | Responsibility |
|---|---|
| `execution/portfolio.py` | Core position and portfolio data structures |
| `execution/pnl.py` | Deterministic P&L calculation |
| `execution/trades.py` | Trade recording and the trade ledger |
| `execution/position_engine.py` | Async position engine — the integration point for fills |

**Major Classes:**

- `PositionSnapshot` (frozen dataclass) — per-instrument position state: net quantity, direction, average prices, total buy/sell quantities and values, realized P&L, unrealized P&L, market timestamp. Enforces structural invariants (direction/quantity consistency) in `__post_init__`.
- `PositionDirection` — `LONG`, `SHORT`, `FLAT` sentinel constants
- `CashLedger` — tracks available paper cash; `credit()` / `debit()` / `reset()`
- `PortfolioSnapshot` (frozen dataclass) — aggregate state: cash, equity, market value, realized/unrealized P&L, buying power, margin used, trade count, turnover, timestamp
- `PnLCalculator` — deterministic FIFO P&L calculator; computes realized P&L and new position state from a fill; also computes unrealized P&L from a position and current market price
- `ExecutionTrade` (Pydantic, frozen) — ledger entry recording one completed fill with P&L impact
- `TradeLedger` — append-only trade history; idempotent by `fill_id`; provides filtered views and aggregate turnover
- `PositionEngineResult` — result of `PositionEngine.on_fill()`: position impact (`OPEN`, `ADD`, `REDUCE`, `CLOSE`, `REVERSE`, `DUPLICATE`), realized P&L, updated position snapshot, trade-recorded flag
- `PositionEngine` — async, per-instrument locking; idempotent fill processing; maintains `_positions` dict, `CashLedger`, cumulative realized P&L, and `TradeLedger`

**Design Decisions:**
- P&L uses FIFO lot matching — each BUY lot is matched against subsequent SELL fills in order.
- All monetary arithmetic uses Python `Decimal` — no floats anywhere in the calculation chain.
- `PositionSnapshot` is a frozen dataclass, not Pydantic — chosen for the ability to use `object.__setattr__` in recovery tests to simulate DB-level corruption.
- `PositionEngine` uses per-instrument `asyncio.Lock` — fills for different instruments can be processed without blocking each other.
- `_on_fill_locked()` is deliberately synchronous — it holds the lock for its entire duration, which is safe because asyncio is single-threaded cooperative; no `await` inside the locked section means no interleaving is possible.
- Flat positions are evicted from `_positions` dict to keep memory clean across long sessions.

**Current Status:** ✅ Production-ready. 73 unit tests pass.

---

### Batch 7D — Recovery, Persistence & Deterministic Replay

**Purpose:** Add crash recovery and durable persistence to the execution engine. All engine state transitions, fills, and position snapshots are written to PostgreSQL via the repository layer. On restart, `RecoveryManager` reconstructs the full engine state deterministically by loading the latest snapshot and replaying events from that point forward.

**Key Modules:**

| Module | Responsibility |
|---|---|
| `execution/recovery/journal.py` | Append-only in-memory event journal |
| `execution/recovery/snapshot.py` | Engine state snapshot: creation, storage, and loading |
| `execution/recovery/replay_engine.py` | Deterministic replay of audit events, fills, and journal entries |
| `execution/recovery/recovery_manager.py` | Recovery orchestration pipeline |
| `execution/recovery/consistency_checker.py` | Post-recovery integrity validation |
| `execution/recovery/persistence_adapter.py` | Thin adapters that add DB persistence to existing engines |
| `database/models/` | Five SQLAlchemy ORM models for execution persistence |
| `database/repositories/` | Five async repositories (session-injected, no commit) |

**Major Classes:**

- `JournalEntryType` (Enum) — event categories: `ORDER_SUBMITTED`, `STATE_TRANSITION`, `FILL_GENERATED`, `POSITION_UPDATED`, `PORTFOLIO_UPDATED`, `SNAPSHOT_CREATED`
- `JournalEntry` (frozen dataclass) — one immutable journal record; idempotent by `entry_id` UUID
- `ExecutionJournal` — in-memory append-only log; per-order and global sequence numbering; dedup by `entry_id`
- `EngineSnapshot` (frozen dataclass) — point-in-time capture of all active order states, positions, portfolio, trades, and cash
- `SnapshotManager` — creates and loads `EngineSnapshot`; on load, uses `min(position_timestamp)` to anchor the replay window conservatively
- `ReplayEngine` — replays `ExecutionAuditEvent` objects (driving `OrderStateMachine`), `FillEvent` objects (driving `PositionEngine`), and journal entries; idempotent; errors captured without crashing
- `RecoveryResult` — structured result of recovery: orders/positions/trades restored, entries replayed, errors, timestamp
- `RecoveryManager` — five-step recovery pipeline: (1) load snapshot, (2) register active orders via direct state injection, (3) replay audit events after snapshot, (4) replay fills after snapshot, (5) consistency check
- `ConsistencyViolation`, `ConsistencyReport` — post-recovery integrity report
- `ConsistencyChecker` — validates portfolio equity/cash/P&L, per-position direction/quantity invariants, trade count, and portfolio ↔ ledger turnover consistency
- `OrderStateMachinePersistenceAdapter` — wraps `OrderStateMachine`; persists order state and audit events to DB on every transition (session-guarded)
- `PositionEnginePersistenceAdapter` — wraps `PositionEngine`; persists fills, trades, and position snapshots after each fill (session-guarded, no-op when `session=None`)
- **ORM Models:** `ExecutionOrderModel`, `AuditEventModel`, `FillEventModel`, `ExecutionTradeModel`, `PositionSnapshotModel` — all share a single SQLAlchemy `Base` (`database/models/base.py`)
- **Repositories:** `ExecutionOrderRepository`, `AuditEventRepository`, `FillEventRepository`, `ExecutionTradeRepository`, `PositionSnapshotRepository`, `MinuteBarRepository`

**Design Decisions:**
- The recovery layer wraps the existing engines — it does not modify `OrderStateMachine`, `PositionEngine`, or any 7A/7B/7C code.
- Direct private-field injection on `OrderState` (`_status`, `_filled_quantity`, etc.) is intentional in the recovery path — it bypasses transition idempotency checks that would incorrectly reject already-applied state.
- All five ORM models share one `declarative_base()` (in `database/models/base.py`) — a single `Base.metadata.create_all(engine)` creates the full schema.
- Session is always injected by the caller — no repository method commits or rolls back.
- `SnapshotManager.load_latest_snapshot()` uses `min(position_timestamp)` as the replay anchor (conservative) — ensures no fill is skipped for an earlier-persisted position; fill replay is idempotent so re-applying fills is safe.
- Audit events are stored ordered by `(order_id, sequence_number)`; fills are stored ordered by `fill_timestamp` — both orderings are deterministic and reproducible.

**Current Status:** ✅ Production-ready. 65 unit tests pass. RC-7 audit approved.

---

## 3. Current Architecture

### Package Responsibilities

```
src/
├── brokers/
│   └── zerodha_market_data.py    Zerodha Kite Connect adapter (read-only, market data only)
│
├── database/
│   ├── models/
│   │   ├── base.py               Shared SQLAlchemy declarative_base — imported by all models
│   │   ├── audit_event.py        execution_audit_events table
│   │   ├── execution_order.py    execution_orders table
│   │   ├── execution_trade.py    execution_trades table
│   │   ├── fill_event.py         execution_fills table
│   │   └── position_snapshot.py  position_snapshots table
│   └── repositories/
│       ├── minute_bars.py        Market data bar persistence (Batch 6)
│       ├── audit_event.py        Audit event read/write
│       ├── execution_order.py    Order upsert, active-order listing
│       ├── execution_trade.py    Trade insert, per-instrument/per-order queries
│       ├── fill_event.py         Fill insert, per-order and all-fills queries
│       └── position_snapshot.py  Position upsert, latest-per-instrument queries
│
├── execution/
│   ├── contracts.py              All enums and Pydantic domain types (frozen)
│   ├── exceptions.py             Typed exception hierarchy
│   ├── state_machine.py          OrderStateMachine — per-order async locking, audit trail
│   ├── matching.py               OrderMatcher — stateless order evaluation
│   ├── fills.py                  FillEvent + FillEventBuilder
│   ├── policies.py               Price/slippage/liquidity/latency policy protocols + defaults
│   ├── engine.py                 MatchingEngine — top-level paper execution orchestrator
│   ├── pnl.py                    PnLCalculator — deterministic FIFO P&L
│   ├── portfolio.py              PositionSnapshot, CashLedger, PortfolioSnapshot
│   ├── trades.py                 ExecutionTrade, TradeLedger
│   ├── position_engine.py        PositionEngine — async, per-instrument locked fill processor
│   └── recovery/
│       ├── journal.py            ExecutionJournal — in-memory append-only event log
│       ├── snapshot.py           SnapshotManager — create/load EngineSnapshot
│       ├── replay_engine.py      ReplayEngine — deterministic event replay
│       ├── recovery_manager.py   RecoveryManager — five-step recovery pipeline
│       ├── consistency_checker.py ConsistencyChecker — post-recovery integrity validation
│       └── persistence_adapter.py OrderStateMachinePersistenceAdapter,
│                                   PositionEnginePersistenceAdapter
│
└── market_data/
    ├── contracts.py              Tick, Quote, CompletedBar, DataQualityStatus, etc.
    ├── provider.py               MarketDataProvider (ABC)
    ├── service.py                MarketDataService — pipeline orchestration
    ├── subscription_manager.py   SubscriptionManager — per-instrument consumer tracking
    ├── bar_builder.py            BarBuilder — tick → OHLCV bar assembly
    ├── quality.py                DataQualityTracker — gap/stale detection
    ├── backfill.py               BackfillCoordinator — historical gap filling
    └── instrument_sync.py        InstrumentSync — NSE instrument master sync
```

### Data Flow (Happy Path)

```
Zerodha KiteTicker
       │
       ▼
ZerodhaMarketDataProvider
       │  (Tick)
       ▼
MarketDataService → SubscriptionManager → BarBuilder
                                              │  (CompletedBar)
                                              ▼
                                        MinuteBarRepository ──► PostgreSQL
                                              │
                                              ▼ (MarketSnapshot)
                                        MatchingEngine
                                         │         │
                             (MatchResult)         │
                                 │                 │
                                 ▼                 ▼
                          FillEventBuilder   OrderStateMachinePersistenceAdapter
                                 │                 │
                          (FillEvent)        (transition → AuditEventRepository)
                                 │
                                 ▼
                    PositionEnginePersistenceAdapter
                         │           │
                         ▼           ▼
                  PositionEngine   FillEventRepository
                  TradeLedger      ExecutionTradeRepository
                  CashLedger       PositionSnapshotRepository
                         │
                         ▼
                   PortfolioSnapshot (in-memory, queryable)
```

### Recovery Flow (On Restart)

```
RecoveryManager.recover(session)
       │
       ├─► SnapshotManager.load_latest_snapshot()     → EngineSnapshot (or None)
       ├─► _restore_from_snapshot()                   → registers orders, logs positions
       ├─► ExecutionOrderRepository.list_active()     → injects DB state onto OrderState
       ├─► AuditEventRepository.get_all_events()      → sorted by (order_id, sequence_number)
       │    └─► ReplayEngine.replay_audit_events()
       ├─► FillEventRepository.get_all_fills()        → sorted by fill_timestamp
       │    └─► ReplayEngine.replay_fill_events()
       ├─► ExecutionTradeRepository.list_all()        → restore TradeLedger
       └─► ConsistencyChecker.validate()              → ConsistencyReport
```

---

## 4. Execution Engine Capabilities

### Order Lifecycle

An order moves through the following state graph, enforced by `OrderStateMachine`:

```
CREATED → VALIDATED → ACCEPTED → OPEN → PARTIALLY_FILLED ─┐
                │         │               └─────────────────┼→ FILLED
                │         └──────────────────────────────────→ REJECTED
                │
                └────────── (any non-terminal) ────────────→ CANCELLED
                                                           → EXPIRED
                                                           → FAILED
```

Every transition is: (a) guarded by a per-order async lock, (b) idempotent via `(client_order_id, action)` dedup, (c) atomic — a failed transition leaves order state unchanged, (d) audited — every successful transition produces an `ExecutionAuditEvent`.

### Matching

`MatchingEngine` processes incoming `MarketSnapshot` objects against all orders in `OPEN` or `PARTIALLY_FILLED` state. For each order:
- `OrderMatcher` evaluates whether the order is executable against the current snapshot.
- For LIMIT orders: price must cross the limit. For MARKET orders: always executable. For stop orders: trigger must first activate via `TriggerStateTracker`.
- If matched, `FillEventBuilder` constructs a `FillEvent` applying the configured price selection, slippage, and liquidity policies.
- The state machine is driven: `PARTIALLY_FILL` or `FILL` based on whether the order is fully completed.

### Fill Processing

`PositionEngine.on_fill(fill_event)` processes each `FillEvent`:
- Acquires the per-instrument async lock.
- Deduplicates by `fill_id` — replaying a fill is always safe.
- Calls `PnLCalculator.compute_realized_pnl()` to compute position impact and realized P&L.
- Updates `CashLedger` (debit on BUY, credit on SELL).
- Accumulates `_cumulative_realized_pnl` on position close or reversal.
- Stores updated `PositionSnapshot` (or evicts it if position is now flat).
- Records `ExecutionTrade` in `TradeLedger`.
- Returns `PositionEngineResult` with impact category, realized P&L, and the new position snapshot.

### Position Management

Each active position is a `PositionSnapshot` keyed by `instrument_token`. Snapshots are frozen dataclasses capturing: net quantity, direction (LONG/SHORT), average buy/sell prices, total buy/sell quantities and values, realized P&L, unrealized P&L, and market timestamp. Flat positions are evicted from memory.

### Portfolio Tracking

`PositionEngine.snapshot()` computes an aggregate `PortfolioSnapshot` on demand: sums market values across all open positions, adds cash, computes total equity, and aggregates realized and unrealized P&L. Buying power equals available cash (simplified paper model).

### P&L

`PnLCalculator` uses FIFO lot matching. BUY fills open long lots at their fill price. SELL fills close lots in FIFO order, computing `(close_price - open_price) × quantity` as realized P&L for each closed lot. Unrealized P&L is `(current_market_price - average_buy_price) × net_quantity` for LONG positions (inverted for SHORT). All arithmetic is `Decimal`; no floating-point operations.

### Recovery

On service restart, `RecoveryManager.recover()` executes a five-step pipeline:
1. Load the latest engine snapshot from PostgreSQL.
2. Register all non-terminal active orders from DB; inject their persisted state directly (bypasses idempotency checks — safe in recovery context only).
3. Load all audit events ordered by `(order_id, sequence_number)`; filter to events after the snapshot timestamp; replay via `ReplayEngine`.
4. Load all fill events ordered by `fill_timestamp`; filter to fills after the snapshot timestamp; replay via `ReplayEngine`.
5. Run `ConsistencyChecker.validate()` to verify the reconstructed state matches DB-persisted invariants.

### Persistence

Two persistence adapters wrap the engines transparently:
- `OrderStateMachinePersistenceAdapter` — after every successful transition, persists the updated `ExecutionOrder` and the new `ExecutionAuditEvent` to PostgreSQL.
- `PositionEnginePersistenceAdapter` — after every fill, persists the `FillEvent`, `ExecutionTrade`, and updated `PositionSnapshot` to PostgreSQL. When `session=None`, DB writes are skipped (stateless mode).

All persistence is session-injected — the adapter never owns the transaction. Callers commit.

### Replay

`ReplayEngine` provides three replay entry points:
- `replay_audit_events(events)` — drives `OrderStateMachine` transitions; errors are collected, not raised.
- `replay_fill_events(fills)` — drives `PositionEngine.on_fill()`; fill dedup ensures idempotency.
- `replay_journal_entries(entries)` — replays `ExecutionJournal` entries by type dispatch.

### Audit

Every state transition produces an `ExecutionAuditEvent` (immutable Pydantic model) containing: `event_id`, `order_id`, `client_order_id`, `sequence_number`, `previous_state`, `new_state`, `action`, `actor`, `reason`, `event_timestamp`, and optionally `fill_record` (for fill transitions). Audit events are persisted to `execution_audit_events` and are the ground truth for replay.

---

## 5. Database Layer

### ORM Models

All five models inherit from a single shared `Base` (`database/models/base.py`). One `Base.metadata.create_all(engine)` call creates the full schema.

| Model | Table | Primary Key | Key Columns |
|---|---|---|---|
| `ExecutionOrderModel` | `execution_orders` | `id` (UUID) | `client_order_id` (unique), `instrument_token`, `status`, `filled_quantity`, `sequence_number` |
| `AuditEventModel` | `execution_audit_events` | `id` (UUID) | `order_id` (FK), `sequence_number`, unique on `(order_id, sequence_number)` |
| `FillEventModel` | `execution_fills` | `id` (fill_id, Text) | `order_id` (FK), `instrument_token`, `fill_timestamp`, `side`, `quantity`, `price` |
| `ExecutionTradeModel` | `execution_trades` | `id` (trade_id, Text) | `fill_id`, `order_id`, `instrument_token`, `realized_pnl`, `position_impact` |
| `PositionSnapshotModel` | `position_snapshots` | `id` (UUID) | `instrument_token` (unique), `position_timestamp`, `net_quantity`, `direction` |

All monetary columns use `Numeric(20, 8)` for `Decimal` fidelity. All timestamps are `DateTime(timezone=True)`. JSONB columns store metadata and fill records. All models use PostgreSQL UUID and JSONB dialect types.

### Repositories

| Repository | Key Methods |
|---|---|
| `ExecutionOrderRepository` | `save(order, session)`, `load(order_id, session)`, `list_active(session)`, `update_status(...)` |
| `AuditEventRepository` | `save(event, session)`, `get_for_order(order_id, session)`, `get_all_events(session)`, `get_latest_sequence(...)` |
| `FillEventRepository` | `save(fill, session)`, `get_for_order(order_id, session)`, `get_all_fills(session)` |
| `ExecutionTradeRepository` | `save(trade, session)`, `list_for_instrument(instrument_token, session)` |
| `PositionSnapshotRepository` | `save_snapshot(position, session)`, `get_latest(instrument_token, session)`, `get_all(session)` |
| `MinuteBarRepository` | `save_bar(bar, session)`, `load_bars(token, from_ts, to_ts, session)` |

### Repository Pattern

All repositories follow the same contract:
- **Session injected by caller** — the repository receives an `AsyncSession`; it never creates, commits, or closes sessions.
- **No auto-commit** — the caller decides transaction boundaries.
- **Upsert by select** — check for existence with `scalar_one_or_none()`, then insert (`.add()`) or update (mutate attributes). SQLAlchemy tracks changes automatically.
- **Hydration** — `_hydrate_*()` private methods reconstruct domain objects from ORM records; domain objects are never coupled to ORM models.
- **Ordered reads** — audit events returned `ORDER BY (order_id, sequence_number)`; fills `ORDER BY fill_timestamp`; positions by `instrument_token`.

### Async Database Usage

All repository methods are `async def` using `AsyncSession` from `sqlalchemy.ext.asyncio`. Queries use `await session.execute(stmt)` + `result.scalars()`. The SQLAlchemy async extension is used throughout — no synchronous blocking DB calls anywhere in the repository layer.

### Transaction Ownership

Transaction ownership is always with the **caller** (persistence adapter or service layer), never with the repository. This allows multiple repository operations to participate in a single DB transaction — critical for atomic recovery checkpointing.

---

## 6. Test Status

### Test Results (RC-7)

| Scope | Tests | Status |
|---|---|---|
| Batch 7A — Contracts & State Machine | 68 | ✅ All pass |
| Batch 7B — Matching & Fill Engine | 73 | ✅ All pass |
| Batch 7C — Position, Portfolio & P&L | 73 | ✅ All pass |
| Batch 7D — Recovery, Persistence & Replay | 65 | ✅ All pass |
| **Execution subsystem total** | **279** | ✅ **279 / 279** |
| Batch 6 — Market Data (unit tests) | 57 | ✅ All pass |
| **Grand total (unit suite)** | **336** | ✅ **336 / 336** |

All tests run from `artifacts/api-server/src/python/` using:
```
python -m pytest tests/unit/execution/ -v
```

There are 19 root-level `test_phase*.py` files in the project root that cause pytest collection errors if run from the workspace root — always scope pytest to `tests/unit/` or `tests/unit/execution/` when running the execution suite.

### Release Status

**RC-7 — Approved for release.** Production readiness audit conducted. No critical issues found. Minor and technical debt items documented and tracked.

### Non-Blocking Technical Debt (Carried Into Batch 8)

The following items were identified in the RC-7 audit and are tracked but do not block release:

1. **O(N) linear scans** in `TradeLedger.get_trade_by_fill_id()` and `ExecutionJournal.append()` dedup path — should use secondary `dict` indexes for O(1) access as trade history grows.
2. **`TradeLedger.total_turnover`** recomputed on every access — should be a running accumulator.
3. **`get_all_events()` sort order** groups by `order_id` UUID, then `sequence_number` — not strict wall-clock order. Safe for independent orders; should be revisited if cross-order dependencies are introduced.
4. **No integration tests** — entire test suite is unit-level with mocked or `None` repositories. At least one integration test per recovery path (using in-memory SQLite) is recommended.
5. **`OrderState` private fields** (`_status`, `_filled_quantity`, etc.) used as the recovery injection interface — should be documented as an intentional contract or replaced with a `restore_from_snapshot()` classmethod.
6. **Missing composite DB indexes** — `(instrument_token, status)` on `execution_orders`, `(order_id, fill_timestamp)` on `execution_fills`.
7. **`ConsistencyChecker` emits no logs** on violations — discrepancies are only visible if the caller inspects the returned `ConsistencyReport`.
8. **No `OrderNotFoundError`** in the exception hierarchy — `transition()` returns a soft failure rather than raising a typed exception.

---

## 7. Design Principles

The following principles are established as the architectural rules of this project. All future batches — including Batch 8 — must uphold them.

### 1. Deterministic Behaviour
The execution engine must produce identical output given identical input, regardless of restart history. Fill matching, P&L calculation, and state transitions are all deterministic functions of their inputs. Time-dependent operations use injected timestamps, never `datetime.now()` in core logic.

### 2. Idempotent Processing
Every operation that can be replayed — fills, state transitions, journal appends — must be idempotent. Replaying an event that has already been applied must be a no-op with no side effects. This is the foundation of the crash recovery guarantee.

### 3. Decimal for All Monetary Values
`decimal.Decimal` is mandatory for every monetary quantity: prices, quantities (if fractional), gross values, P&L, cash balances, margin. Python `float` is prohibited in all execution and P&L code paths. This prevents rounding drift across large numbers of trades.

### 4. Repository-Only Persistence
Database access is permitted only through the repository classes in `src/database/repositories/`. No ORM model, domain object, or execution engine class may import or use `AsyncSession` directly. Persistence adapters mediate between engines and repositories. Repositories never commit.

### 5. Async-First Design
All I/O-bound operations — database access, market data ingestion, broker communication — are `async def` using `asyncio`. Synchronous operations within an async context must be CPU-light (no blocking I/O, no `time.sleep()`). Per-resource `asyncio.Lock` objects protect shared mutable state.

### 6. Immutable Events
All domain events (`ExecutionAuditEvent`, `FillEvent`, `ExecutionTrade`, `ExecutionOrder`) are Pydantic models with `frozen=True` or frozen dataclasses. Once created, they cannot be mutated. This guarantees audit trail integrity and safe sharing across coroutines.

### 7. Session Injection / Caller-Owned Transactions
No function below the service layer may create, commit, or close a database session. Sessions are passed as parameters. Transaction boundaries are owned by the caller. This allows multiple operations to participate in a single atomic transaction when needed.

### 8. Layered Architecture — No Upward Dependencies
Domain types (`contracts.py`) have no dependencies on the state machine, engine, or repositories. The state machine does not import from the matching engine. The recovery layer depends on the execution engines but the execution engines have zero knowledge of the recovery layer. Dependencies flow strictly downward.

### 9. Backward Compatibility
New batches add capabilities; they do not alter existing behaviour. Any change to a module in `src/execution/` (7A–7C) requires explicit justification and must be validated against the full 279-test suite. The 7A–7C engines are treated as a stable API contract.

### 10. Explicit Failure — No Silent Swallowing
Exceptions propagate unless explicitly caught with documented intent. Recovery paths that swallow errors must log them and record them in a structured error list (e.g., `RecoveryResult.errors`). The system must be explicit about what succeeded, what failed, and what was skipped.

### 11. Type Safety
All public function signatures carry full type annotations. Pydantic models enforce field types at construction time. `str, Enum` enumerations are used for all domain status and action values — no bare string literals for states.

### 12. Paper Trading Boundary
The execution engine is a simulation. It must never construct or submit a real broker order. The broker package (`src/brokers/`) is read-only (market data only). Any future broker integration for order submission must be implemented behind a clearly named adapter with an explicit "live trading" guard.

---

## 8. What Batch 8 Should Assume

### The Execution Engine Is Production-Ready

Batch 8 inherits a fully functional, audited, crash-recoverable paper execution engine. The following are stable and must be treated as a fixed foundation:

- `OrderStateMachine` — all state transitions, idempotency, audit trail ✅
- `MatchingEngine` + `OrderMatcher` — all order types, slippage policies, trigger activation ✅
- `PositionEngine` + `PnLCalculator` — fill processing, FIFO P&L, cash ledger ✅
- `RecoveryManager` — five-step recovery pipeline, consistency checker ✅
- `OrderStateMachinePersistenceAdapter` + `PositionEnginePersistenceAdapter` ✅
- All five ORM models and repositories ✅

### Batch 8 Must Build On Top — Not Modify

Batch 8 should consume execution engine outputs (fills, positions, portfolio snapshots, audit events) through the existing APIs. It must not alter the internal logic of any engine, repository, or domain type. New features should be implemented as new modules that call into — not into — the execution layer.

### The Repository Pattern Must Be Followed

Any new data entities introduced by Batch 8 require:
- A new SQLAlchemy ORM model inheriting from the shared `Base` in `database/models/base.py`
- A new repository in `database/repositories/` following the session-injection pattern
- No direct SQL or session usage in any layer above the repository

### The Test Suite Is the Regression Guard

Before completing Batch 8, the full existing test suite must still pass: **279/279 execution unit tests** and **336/336 total unit tests**. Any failure in existing tests is a blocker.

---

## 9. What Not To Do

The following components are **frozen**. Batch 8 must not alter them unless a verified critical production defect is discovered and the fix is reviewed and approved.

### ❌ Do Not Modify — State Machine (`execution/state_machine.py`)
- The state transition graph (which states are reachable from which)
- The idempotency dedup mechanism (`_seen_transitions` set)
- The per-order lock pattern (`WeakValueDictionary[int, asyncio.Lock]`)
- The audit event generation logic
- Terminal state protection logic
- `OrderState` field names (used by recovery injection in `recovery_manager.py`)

### ❌ Do Not Modify — Matching Logic (`execution/matching.py`, `execution/engine.py`)
- The `OrderMatcher.evaluate()` decision logic for any order type
- Trigger state activation logic in `TriggerStateTracker`
- The policy protocol interfaces (`PriceSelectionPolicy`, `SlippagePolicy`, `LiquidityPolicy`, `LatencyPolicy`)
- `MatchingEngine.reset()` — used by replay to achieve determinism

### ❌ Do Not Modify — P&L Formulas (`execution/pnl.py`)
- The FIFO lot-matching algorithm in `PnLCalculator.compute_realized_pnl()`
- The unrealized P&L formula
- The `_build_position()` helper that assembles `PositionSnapshot` from FIFO state
- Any change to P&L calculation would invalidate all historical P&L records

### ❌ Do Not Modify — Fill Processing (`execution/fills.py`, `execution/position_engine.py`)
- `FillEvent` field definitions — audit events and fill records reference these fields
- `PositionEngine._on_fill_locked()` internal logic
- The fill dedup mechanism (`_seen_fill_ids` set)
- `PositionEngineResult` field definitions — used by persistence adapters

### ❌ Do Not Modify — Replay Semantics (`execution/recovery/replay_engine.py`)
- The idempotent replay contract — replaying any event must be safe to call twice
- `ReplayEngine.reset()` — used by deterministic replay tests
- The error-collection pattern — replay errors are collected, not raised

### ❌ Do Not Modify — Domain Contracts (`execution/contracts.py`)
- `ExecutionOrderStatus` enum values — stored in DB as strings; renaming breaks existing records
- `ExecutionOrderAction` enum values — same reason; also used in replay action map
- `ExecutionAuditEvent` field names — replay hydrates these from DB records
- `ExecutionOrder` validation logic — all field constraints are production-verified

### ❌ Do Not Modify — ORM Models (`database/models/`)
- Column names on any existing model — renaming a column requires a migration; the recovery layer reads these columns by name
- `execution_audit_events` unique constraint on `(order_id, sequence_number)`
- `position_snapshots` unique constraint on `instrument_token`
- The shared `Base` in `database/models/base.py` — all models must import from here

### ❌ Do Not Modify — Repository Contracts (`database/repositories/`)
- Method signatures on any existing repository — persistence adapters depend on these
- The no-commit rule — repositories must never call `session.commit()`
- The hydration methods — recovery depends on correct domain object reconstruction

---

*End of document.*

---
**Document version:** 1.0  
**Project stage:** RC-7  
**Execution tests:** 279 / 279 ✅  
**Total unit tests:** 336 / 336 ✅  
**Audit verdict:** ✔ APPROVED WITH MINOR OBSERVATIONS
