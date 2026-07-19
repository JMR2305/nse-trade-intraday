# BATCH_7D_KIMI_CONTEXT.md
## Reference Package for Kimi — Batch 7D Design

**Batch 7D: Execution Recovery, Persistence and Deterministic Replay**

---

## 1. Project Status

The following batches are merged, tested and committed to `main`:

| Batch | Description | Test Count |
|---|---|---|
| Batch 6 | Market Data Foundation | 57 unit tests (tests/unit/ — market data suite) |
| Batch 7A | Execution Contracts and Order State Machine | 148 unit tests |
| Batch 7B / 7BA | Paper Matching and Fill Engine | included in 7A count above |
| Batch 7C / 7CA | Position, Portfolio and P&L Engine | 214 execution tests total |

**Verified test count (last confirmed run):**
- `tests/unit/execution/`: **214 / 214 passed**
- `tests/unit/` (full structured suite): **271 / 271 passed**

Test command: `python -m pytest tests/unit/ -q`

Source tree: `artifacts/api-server/src/python/`

---

## 2. Exact Included File Manifest

All paths are relative to `artifacts/api-server/src/python/`.

### Execution Source (12 files)

| File | Batch | Description |
|---|---|---|
| `src/execution/__init__.py` | 7C | Package exports — all public symbols |
| `src/execution/contracts.py` | 7A | ExecutionOrder, ExecutionAuditEvent, FillRecord, enums, TERMINAL_STATES |
| `src/execution/exceptions.py` | 7A | ExecutionException hierarchy |
| `src/execution/state_machine.py` | 7A/7BA | OrderStateMachine, OrderState, TransitionResult, TRANSITION_GRAPH |
| `src/execution/fills.py` | 7B | FillEvent (immutable), FillEventBuilder (deterministic SHA-256 fill_id) |
| `src/execution/matching.py` | 7B | OrderMatcher, MarketSnapshot, MatchResult, TriggerStateTracker |
| `src/execution/engine.py` | 7B/7BA | MatchingEngine, EngineResult |
| `src/execution/policies.py` | 7B | PriceSelectionPolicy, SlippagePolicy, LiquidityPolicy, LatencyPolicy + implementations |
| `src/execution/pnl.py` | 7C/7CA | PnLCalculator — realized and unrealized P&L, all 10 position transitions |
| `src/execution/portfolio.py` | 7C | PositionSnapshot, CashLedger, PortfolioSnapshot, PositionDirection |
| `src/execution/position_engine.py` | 7C/7CA | PositionEngine, PositionEngineResult |
| `src/execution/trades.py` | 7C | ExecutionTrade, TradeLedger |

### Execution Tests (11 files)

| File | Tests |
|---|---|
| `tests/unit/execution/__init__.py` | — |
| `tests/unit/execution/conftest.py` | Shared fixtures |
| `tests/unit/execution/test_contracts.py` | ExecutionOrder, FillRecord, enums |
| `tests/unit/execution/test_state_machine.py` | OrderStateMachine transitions, idempotency, locking |
| `tests/unit/execution/test_fills.py` | (not present — fills covered in test_engine.py) |
| `tests/unit/execution/test_engine.py` | MatchingEngine, dedup, concurrent orders |
| `tests/unit/execution/test_matching.py` | OrderMatcher for all 4 order types |
| `tests/unit/execution/test_policies.py` | Slippage, liquidity, latency policies |
| `tests/unit/execution/test_pnl.py` | PnLCalculator — all 10 transitions |
| `tests/unit/execution/test_portfolio.py` | PositionSnapshot, CashLedger, PortfolioSnapshot |
| `tests/unit/execution/test_trades.py` | ExecutionTrade, TradeLedger, idempotency |
| `tests/unit/execution/test_position_engine.py` | PositionEngine — cumulative P&L, reversal, multi-instrument |

### ORM Models

**None exist for execution entities.** The execution package uses Pydantic models exclusively (frozen dataclasses and Pydantic BaseModels). No SQLAlchemy ORM models are defined for orders, fills, positions, trades, portfolio, or audit events.

The only ORM/repository that exists is for market data:

| File | Description |
|---|---|
| `src/database/__init__.py` | Empty sub-package root |
| `src/database/repositories/__init__.py` | Exports MinuteBarRepository |
| `src/database/repositories/minute_bars.py` | MinuteBarRepository — CRUD for minute bars (market data only) |

### Repositories

**No execution-domain repositories exist.** The MinuteBarRepository (above) is the only repository implementation in the project. It is included as a reference for the existing repository pattern:
- Constructor accepts an injected model class (`self._model`)
- All methods accept an `AsyncSession` argument — caller controls transaction boundaries
- No commit inside repository methods (service-level commit responsibility)

### Database Infrastructure

**No async engine, session factory, or session dependency found in `artifacts/api-server/src/python/`.**

The `intraday-trading-bot/` directory (a separate, non-active codebase) contains a full SQLAlchemy async stack (`sqlalchemy[asyncio]==2.0.30`, `alembic==1.13.1`, `asyncpg==0.29.0`) but it is **not imported or used** by the active `artifacts/api-server` Python code.

Batch 7D will need to define or adopt a database infrastructure layer.

### Recovery / Audit / Operational References

These files exist in the legacy Phase 8–20 layer and are included as context for the current operational model (not as 7D dependencies):

| File | Description |
|---|---|
| `readiness_checker.py` | Phase 8 — Live Readiness Score (12 checks, required/advisory) |
| `phase20_gates.py` | Phase 20 — Entry eligibility gates (broker, market hours, kill switch, etc.) |

### Migrations

**No Alembic configuration or migration files exist in `artifacts/api-server/src/python/`.**

The `intraday-trading-bot/pyproject.toml` references `alembic==1.13.1` but there are no `alembic.ini`, `env.py`, or version files in the active api-server source tree.

### Metadata

| File | Description |
|---|---|
| `pyproject.toml` | Workspace root — project dependencies (pydantic, fastapi, sqlalchemy, etc. via intraday-trading-bot/ reference) |

---

## 3. Execution Architecture Summary

The current execution data flow (all in-memory):

```
MarketSnapshot
    │  instrument_token, timestamp, LTP, bid/ask, event_id
    ▼
MatchingEngine.on_market_data(snapshot: MarketSnapshot) → EngineResult
    │
    ├─ _executable_orders_for_instrument()
    │      calls OrderStateMachine.get_executable_orders_for_instrument()
    │      returns [UUID, ...]  for OPEN / PARTIALLY_FILLED orders
    │
    ├─ per-order: OrderMatcher.match(order, status, filled_qty, remaining_qty, snapshot)
    │      → MatchResult(executable, fill_event: FillEvent | None)
    │      FillEvent.fill_id = SHA-256(order_id:market_event_id:seq)[:32]
    │
    └─ per-fill: OrderStateMachine.fill() / .partially_fill()
           async with per-order asyncio.Lock
           → TransitionResult(success, audit_event: ExecutionAuditEvent, order: OrderState)
           ExecutionAuditEvent recorded in-memory on OrderState._seen_transitions

FillEvent (immutable)
    │  fill_id, order_id, client_order_id, instrument_token, side,
    │  quantity, price, gross_value, market_event_id, market_timestamp
    ▼
PositionEngine.on_fill(fill: FillEvent) → PositionEngineResult
    │  async with per-instrument asyncio.Lock
    │
    ├─ Idempotency: fill_id in self._seen_fill_ids → return DUPLICATE
    │
    ├─ PnLCalculator.compute_realized_pnl(current_position, fill_side, qty, price)
    │      → (realized_pnl: Decimal, new_position: PositionSnapshot, impact: str)
    │      impact ∈ {OPEN, ADD, REDUCE, CLOSE, REVERSE}
    │
    ├─ CashLedger.debit/credit(fill.gross_value)
    │
    ├─ _cumulative_realized_pnl updated only on CLOSE or REVERSE
    │      += current_pos.realized_pnl + realized_pnl
    │
    ├─ _positions dict updated or pruned (flat positions removed)
    │
    └─ TradeLedger.record(ExecutionTrade)
           Idempotent by fill_id

PositionEngine.snapshot() → PortfolioSnapshot
    realized_pnl = _cumulative_realized_pnl + Σ(pos.realized_pnl for open positions)
    equity = cash.balance + Σ(pos.market_value)
```

---

## 4. Key Public Contracts

### ExecutionOrder
**File:** `src/execution/contracts.py`
**Status:** Immutable (Pydantic frozen model)

```python
class ExecutionOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: UUID            # identity — default_factory=uuid4
    client_order_id: str      # idempotency key — caller-assigned, min_length=1
    instrument_token: int     # gt=0
    side: ExecutionOrderSide  # BUY | SELL
    order_type: ExecutionOrderType  # MARKET | LIMIT | STOP_MARKET | STOP_LIMIT
    quantity: int             # gt=0
    limit_price: Decimal | None    # required for LIMIT, STOP_LIMIT
    trigger_price: Decimal | None  # required for STOP_MARKET, STOP_LIMIT
    product: str              # default "CNC"
    validity: str             # default "DAY"
    created_at: datetime      # tz-aware, default=now(utc)
    exchange: str             # default "NSE"
    metadata: dict[str, Any] | None

    def is_terminal(self, status: ExecutionOrderStatus) -> bool: ...
```

**Enums:**
- `ExecutionOrderStatus`: CREATED → VALIDATED → ACCEPTED → OPEN → PARTIALLY_FILLED → FILLED (terminal)
  also: REJECTED, CANCELLED, EXPIRED, FAILED (all terminal)
- `ExecutionOrderSide`: BUY | SELL
- `ExecutionOrderType`: MARKET | LIMIT | STOP_MARKET | STOP_LIMIT
- `ExecutionOrderAction`: submit | validate | accept | reject | open | partially_fill | fill | request_cancel | cancel | expire | fail
- `TERMINAL_STATES: frozenset` = {REJECTED, FILLED, CANCELLED, EXPIRED, FAILED}

---

### ExecutionAuditEvent
**File:** `src/execution/contracts.py`
**Status:** Immutable (Pydantic frozen model) — generated by state machine on every accepted transition

```python
class ExecutionAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID            # identity — default_factory=uuid4
    order_id: UUID            # foreign key to ExecutionOrder
    client_order_id: str      # denormalized for query
    sequence_number: int      # ge=0 — monotonically increasing per order
    previous_state: ExecutionOrderStatus
    new_state: ExecutionOrderStatus
    action: ExecutionOrderAction
    reason: str | None
    event_timestamp: datetime  # tz-aware, default=now(utc)
    actor: str                # default "system"
    metadata: dict[str, Any] | None
    fill_record: FillRecord | None  # non-None only for PARTIALLY_FILL / FILL transitions
```

**Note:** Audit events are generated in-memory within `OrderStateMachine._transition_locked()` but are **not persisted** anywhere. They exist only in the `TransitionResult` returned to the caller.

---

### OrderStateMachine
**File:** `src/execution/state_machine.py`
**Status:** Mutable, async-safe (per-order `asyncio.Lock` via `WeakValueDictionary`)

```python
class OrderStateMachine:
    def __init__(self) -> None: ...

    # Registration
    def register(self, order: ExecutionOrder) -> OrderState: ...
    def get_state(self, order_id: UUID) -> OrderState | None: ...
    def get_executable_orders_for_instrument(self, instrument_token: int) -> list[UUID]: ...

    # Core transition (async, per-order lock)
    async def transition(
        self,
        order_id: UUID,
        action: ExecutionOrderAction,
        reason: str | None = None,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
        fill_quantity: int | None = None,
        fill_price: Decimal | None = None,
        fill_metadata: dict[str, Any] | None = None,
    ) -> TransitionResult: ...

    # Convenience wrappers
    async def submit(self, order, actor) -> TransitionResult: ...
    async def validate(self, order_id, actor) -> TransitionResult: ...
    async def accept(self, order_id, actor) -> TransitionResult: ...
    async def reject(self, order_id, reason, actor) -> TransitionResult: ...
    async def open_order(self, order_id, actor) -> TransitionResult: ...
    async def partially_fill(self, order_id, quantity, price, actor, metadata) -> TransitionResult: ...
    async def fill(self, order_id, quantity, price, actor, metadata) -> TransitionResult: ...
    async def request_cancel(self, order_id, actor) -> TransitionResult: ...
    async def cancel(self, order_id, actor) -> TransitionResult: ...
    async def expire(self, order_id, actor) -> TransitionResult: ...
    async def fail(self, order_id, reason, actor) -> TransitionResult: ...
```

**Idempotency:** `(client_order_id, action.value)` dedup key committed to `OrderState._seen_transitions` **after** successful mutation. Fill and OPEN actions are excluded from dedup (naturally idempotent via quantity checks).

**Transition graph:** Defined in `TRANSITION_GRAPH: dict[ExecutionOrderStatus, set[ExecutionOrderAction]]`

---

### OrderState (mutable runtime state)
**File:** `src/execution/state_machine.py`
**Status:** Mutable dataclass — lives inside the state machine, not exposed externally

```python
@dataclass
class OrderState:
    order: ExecutionOrder      # immutable original contract
    status: ExecutionOrderStatus = CREATED
    filled_quantity: int = 0
    remaining_quantity: int    # = order.quantity at init
    average_fill_price: Decimal | None = None
    fill_records: list[FillRecord] = []
    sequence_number: int = 0   # monotonic, incremented on every transition
    _seen_transitions: set[tuple[str, str, int]]  # idempotency set

    @property def order_id(self) -> UUID: ...
    @property def client_order_id(self) -> str: ...
    def is_terminal(self) -> bool: ...
    def to_dict(self) -> dict[str, Any]: ...
```

---

### TransitionResult
**File:** `src/execution/state_machine.py`
**Status:** Immutable frozen dataclass

```python
@dataclass(frozen=True)
class TransitionResult:
    success: bool
    previous_state: ExecutionOrderStatus
    new_state: ExecutionOrderStatus
    audit_event: ExecutionAuditEvent | None  # None if transition failed
    order: OrderState | None                 # None if order not found
    reason: str | None = None
```

---

### FillEvent
**File:** `src/execution/fills.py`
**Status:** Immutable (Pydantic frozen model) — matching engine output

```python
class FillEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    fill_id: str               # identity — deterministic SHA-256[:32] of (order_id:market_event_id:seq)
    event_id: UUID             # unique per build call — default_factory=uuid4
    order_id: UUID
    client_order_id: str
    instrument_token: int      # gt=0
    side: ExecutionOrderSide
    quantity: int              # gt=0
    price: Decimal             # gt=0
    gross_value: Decimal       # invariant: == quantity * price, gt=0
    market_event_id: str       # sourced from MarketSnapshot.event_id
    market_timestamp: datetime # tz-aware
    fill_timestamp: datetime   # tz-aware, default=now(utc)
    cumulative_filled_quantity: int  # ge=0
    remaining_quantity: int    # ge=0
    liquidity_source: str      # default "paper"
    slippage_bps: Decimal      # default 0
    metadata: dict[str, Any] | None
```

**FillEventBuilder:**
```python
class FillEventBuilder:
    def build(self, order_id, client_order_id, instrument_token, side, quantity, price,
              market_event_id, market_timestamp, cumulative_filled_quantity,
              remaining_quantity, slippage_bps, liquidity_source, metadata) -> FillEvent: ...
    def reset(self) -> None: ...  # for deterministic replay
```

---

### MarketSnapshot
**File:** `src/execution/matching.py`
**Status:** Immutable frozen dataclass — normalized market data for execution

```python
@dataclass(frozen=True)
class MarketSnapshot:
    instrument_token: int
    timestamp: datetime          # tz-aware
    last_traded_price: Decimal
    event_id: str                # REQUIRED — used for dedup and fill_id derivation
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    bid_quantity: int | None = None
    ask_quantity: int | None = None
    traded_volume: int | None = None
    tick_size: Decimal = Decimal("0.05")  # NSE default
    metadata: dict[str, Any] | None = None
```

---

### MatchingEngine
**File:** `src/execution/engine.py`
**Status:** Mutable, async-safe

```python
class MatchingEngine:
    def __init__(
        self,
        state_machine: OrderStateMachine,
        price_policy: PriceSelectionPolicy | None = None,
        slippage_policy: SlippagePolicy | None = None,
        liquidity_policy: LiquidityPolicy | None = None,
        latency_policy: LatencyPolicy | None = None,
    ) -> None: ...

    def register_order(self, order: ExecutionOrder) -> None: ...
    async def activate_order(self, order_id: UUID, actor: str = "matching_engine") -> None: ...
    async def on_market_data(self, snapshot: MarketSnapshot) -> EngineResult: ...
    def reset(self) -> None: ...  # clears _processed_events and trigger tracker

    # Dedup state (in-memory):
    _processed_events: set[tuple[UUID, str]]  # (order_id, market_event_id)
```

---

### PositionEngine
**File:** `src/execution/position_engine.py`
**Status:** Mutable, async-safe (per-instrument `asyncio.Lock` via `WeakValueDictionary`)

```python
class PositionEngine:
    def __init__(self, initial_cash: Decimal = Decimal("1000000")) -> None: ...

    # Fill processing (async, per-instrument lock)
    async def on_fill(self, fill: FillEvent) -> PositionEngineResult: ...

    # Market price update (for unrealized P&L)
    async def update_market_price(
        self, instrument_token: int, market_price: Decimal, market_timestamp: datetime
    ) -> PositionSnapshot | None: ...

    # Snapshot (sync)
    def snapshot(self) -> PortfolioSnapshot: ...

    # Read-only accessors
    def get_position(self, instrument_token: int) -> PositionSnapshot | None: ...
    def get_all_positions(self) -> dict[int, PositionSnapshot]: ...
    def get_cash(self) -> Decimal: ...
    def get_trade_ledger(self) -> TradeLedger: ...

    # Reset for deterministic replay
    def reset(self) -> None: ...

    # Internal state (all in-memory, lost on restart):
    _positions: dict[int, PositionSnapshot]
    _cash: CashLedger
    _trades: TradeLedger
    _seen_fill_ids: set[str]           # global dedup across all instruments
    _cumulative_realized_pnl: Decimal  # from closed + reversed positions
```

---

### PositionEngineResult
**File:** `src/execution/position_engine.py`
**Status:** Immutable frozen dataclass

```python
@dataclass(frozen=True)
class PositionEngineResult:
    fill_id: str
    instrument_token: int
    position_impact: str  # OPEN | ADD | REDUCE | CLOSE | REVERSE | DUPLICATE
    realized_pnl: Decimal
    new_position: PositionSnapshot
    trade_recorded: bool
```

---

### PositionSnapshot
**File:** `src/execution/portfolio.py`
**Status:** Immutable frozen dataclass

```python
@dataclass(frozen=True)
class PositionSnapshot:
    instrument_token: int
    net_quantity: int           # positive=LONG, negative=SHORT, zero=FLAT
    direction: str              # PositionDirection.LONG | SHORT | FLAT
    average_buy_price: Decimal
    average_sell_price: Decimal
    total_buy_quantity: int
    total_sell_quantity: int
    total_buy_value: Decimal
    total_sell_value: Decimal
    realized_pnl: Decimal       # running total for open position (reduces)
    unrealized_pnl: Decimal     # recalculated by update_market_price()
    market_price: Decimal | None
    market_timestamp: datetime | None
    position_timestamp: datetime  # default=now(utc)
    metadata: dict[str, Any] | None

    @property def is_long(self) -> bool: ...
    @property def is_short(self) -> bool: ...
    @property def is_flat(self) -> bool: ...
    @property def market_value(self) -> Decimal: ...  # net_quantity * market_price
    @property def exposure(self) -> Decimal: ...      # abs(net_quantity) * avg_price
```

---

### PortfolioSnapshot
**File:** `src/execution/portfolio.py`
**Status:** Immutable frozen dataclass

```python
@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Decimal
    equity: Decimal            # cash + market_value
    positions: tuple[PositionSnapshot, ...]
    market_value: Decimal      # Σ pos.market_value
    realized_pnl: Decimal      # _cumulative + Σ open pos.realized_pnl
    unrealized_pnl: Decimal    # Σ pos.unrealized_pnl
    total_pnl: Decimal         # realized + unrealized
    buying_power: Decimal      # paper: == cash
    margin_used: Decimal       # Σ pos.exposure
    trade_count: int
    turnover: Decimal          # Σ trade.gross_value
    timestamp: datetime        # default=now(utc)
    metadata: dict[str, Any] | None
```

---

### PnLCalculator
**File:** `src/execution/pnl.py`
**Status:** Pure static methods — no state, no side effects

```python
class PnLCalculator:
    @staticmethod
    def compute_realized_pnl(
        current_position: PositionSnapshot,
        fill_side: ExecutionOrderSide,
        fill_quantity: int,
        fill_price: Decimal,
    ) -> tuple[Decimal, PositionSnapshot, str]:
        """Returns (realized_pnl, new_position, impact).
        impact ∈ {OPEN, ADD, REDUCE, CLOSE, REVERSE}"""
        ...

    @staticmethod
    def compute_unrealized_pnl(
        position: PositionSnapshot,
        market_price: Decimal,
    ) -> Decimal: ...
```

**Transition table:**

| Current | Fill side | Qty vs position | Impact |
|---|---|---|---|
| FLAT | BUY or SELL | any | OPEN |
| LONG | BUY | any | ADD |
| LONG | SELL | qty < net_qty | REDUCE |
| LONG | SELL | qty == net_qty | CLOSE |
| LONG | SELL | qty > net_qty | REVERSE (→ SHORT) |
| SHORT | SELL | any | ADD |
| SHORT | BUY | qty < abs(net_qty) | REDUCE |
| SHORT | BUY | qty == abs(net_qty) | CLOSE |
| SHORT | BUY | qty > abs(net_qty) | REVERSE (→ LONG) |

**Realized P&L formulas:**
- LONG REDUCE/CLOSE: `realized = (fill_price - avg_buy_price) * qty`
- SHORT REDUCE/CLOSE: `realized = (avg_sell_price - fill_price) * qty`
- REVERSE: `realized = close_qty portion only; new position starts with realized_pnl=Decimal("0")`

---

### ExecutionTrade
**File:** `src/execution/trades.py`
**Status:** Immutable (Pydantic frozen model)

```python
class ExecutionTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_id: str              # identity — f"T-{fill_id}"
    fill_id: str               # idempotency key — from FillEvent.fill_id
    order_id: UUID
    client_order_id: str
    instrument_token: int      # gt=0
    side: ExecutionOrderSide
    quantity: int              # gt=0
    price: Decimal             # gt=0
    gross_value: Decimal       # gt=0
    position_impact: str       # OPEN|ADD|REDUCE|CLOSE|REVERSE
    realized_pnl: Decimal      # this fill's P&L contribution
    cumulative_realized_pnl: Decimal  # running total at time of trade
    market_timestamp: datetime # tz-aware
    trade_timestamp: datetime  # tz-aware, default=now(utc)
    metadata: dict[str, Any] | None
```

**TradeLedger:**
```python
class TradeLedger:
    def record(self, trade: ExecutionTrade) -> bool: ...  # True=new, False=duplicate
    def get_trades(self, instrument_token: int | None = None) -> tuple[ExecutionTrade, ...]: ...
    def get_trade_by_fill_id(self, fill_id: str) -> ExecutionTrade | None: ...
    def reset(self) -> None: ...
    @property def trade_count(self) -> int: ...
    @property def total_turnover(self) -> Decimal: ...
```

---

## 5. Current Persistence Capabilities

**All execution state is in-memory only. Nothing survives a process restart.**

| Entity | ORM model | Repository | Persisted | Recovery support |
|---|---|---|---|---|
| Orders (`ExecutionOrder`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Order state (`OrderState`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Transitions / audit events (`ExecutionAuditEvent`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Fill events (`FillEvent`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Positions (`PositionSnapshot`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Trades (`ExecutionTrade`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Portfolio / cash (`PortfolioSnapshot`, `CashLedger`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Processed-event markers (`_processed_events`, `_seen_fill_ids`) | ❌ No | ❌ No | ❌ No | ❌ No |
| Journals | ❌ No | ❌ No | ❌ No | ❌ No |
| Snapshots | In-memory only | ❌ No | ❌ No | ❌ No |

**Idempotency is enforced in-memory only:**
- `OrderStateMachine`: `OrderState._seen_transitions: set[tuple]` — lost on restart
- `MatchingEngine`: `_processed_events: set[tuple[UUID, str]]` — lost on restart
- `PositionEngine`: `_seen_fill_ids: set[str]` — lost on restart
- `TradeLedger`: `_seen_fill_ids: set[str]` — lost on restart

---

## 6. Repository and Transaction Conventions

**Existing pattern** (from `MinuteBarRepository` — the only current repository):

- Constructor takes `model_class: Any | None = None` — injected at runtime
- All methods take `session: AsyncSession` as a required argument
- **No commit inside any repository method** — caller (service layer) is responsible
- Methods are named `insert_*`, `get_*`, `upsert_*`
- Duplicate handling via `upsert_*` policies: `INSERT_ONLY`, `UPSERT` (select-then-update)
- No unit-of-work pattern currently used
- No rollback conventions defined — assumed to be handled by FastAPI/endpoint layer

**No async engine or session factory is defined** in the active source tree. Batch 7D must define or reference one.

---

## 7. Existing Recovery and Audit Behaviour

### Restart Recovery
**Absent.** There is no reconciliation, replay, or state restore logic for any execution entity. On process restart, `OrderStateMachine`, `MatchingEngine`, and `PositionEngine` all start empty.

### Reconciliation
**Absent** for the new execution engine. The Phase 8 layer (`readiness_checker.py`) has a readiness gate that checks broker connectivity, token validity, kill switch state, and market hours — but it operates on the legacy `execution_engine.py` (Phase 8 paper broker), not on `src/execution/`.

### Event Journaling
**Absent.** `ExecutionAuditEvent` is generated by the state machine but is returned only in `TransitionResult` and is not stored anywhere.

### Audit Logging
**Absent** in the new execution package. The legacy Phase 13/14 layer has `phase13_audit.py` and `phase14_audit_log.json` but these are unrelated to `src/execution/`.

### Snapshot Support
**Absent** for persistence. `PositionEngine.snapshot()` returns a `PortfolioSnapshot` (in-memory, point-in-time) but does not write it anywhere.

### Watchdog / Startup Gates
**Absent** for the new execution engine. `readiness_checker.py` and `phase20_gates.py` apply to the legacy Phase 8/20 paper broker, not to `src/execution/`.

---

## 8. Known Constraints and Deferred Items

1. **Paper-only execution** — The execution package is explicitly paper-only. `FillEvent.liquidity_source` defaults to `"paper"`. No live Zerodha order placement code exists in `src/execution/`.

2. **No live broker integration** — `src/execution/` has zero imports from `src/brokers/`. The `zerodha_market_data.py` module exists in `src/brokers/` but is not wired to the matching engine.

3. **No modification of Batch 6 market data** — `src/market_data/` is isolated. `MarketSnapshot` is an execution-layer abstraction and does not import from `src/market_data/`.

4. **No risk engine integration** — There is no position-size limit, drawdown limit, or per-trade risk check wired into `MatchingEngine` or `PositionEngine`.

5. **No strategy integration** — No signal → order pipeline exists. Orders are submitted manually.

6. **Reversal accounting limitation** (documented in `position_engine.py` module docstring):
   Reversals (LONG→SHORT or SHORT→LONG in a single fill) report realized P&L for the closed portion only. The new reversed position starts at `realized_pnl=Decimal("0")`. In-session reduces are tracked in `pos.realized_pnl` separately from `_cumulative_realized_pnl` (which only accumulates on CLOSE/REVERSE). This is a documented, tested limitation.

7. **All idempotency is in-memory** — `_seen_transitions`, `_processed_events`, `_seen_fill_ids` are all lost on restart. A duplicate fill submitted after a restart will be re-processed.

8. **No ORM or migration infrastructure** — No SQLAlchemy declarative base, no async engine, no `alembic.ini`, no migration versions exist in `artifacts/api-server/src/python/`.

9. **`main.py` not wired** — The new `src/execution/` package is not imported or used by `main.py`. Integration is deferred.

10. **`kiteconnect` not in `pyproject.toml`** — It is a lazy import in `src/brokers/zerodha_market_data.py`.

---

## 9. Batch 7D Design Boundaries

### Batch 7D may propose:

- Execution journal contracts (append-only event log for all state transitions and fills)
- Snapshot contracts (position, portfolio, and engine snapshots for recovery)
- Repository interfaces (orders, fills, positions, trades, journals, snapshots, idempotency markers)
- Recovery manager (replays journal from last snapshot to restore in-memory state)
- Replay engine (deterministic re-run of fill stream against `PositionEngine`)
- Consistency validator (cross-checks in-memory state against persisted state)
- Recovery coordinator / startup gate (blocks engine from accepting fills until recovery completes)
- Tests (unit and integration level, without hitting live DB)
- ORM model additions — only after architecture is approved by reviewer
- Migration additions — only after ORM models are approved

### Batch 7D must NOT:

- Modify matching semantics in `OrderMatcher` or `MatchingEngine`
- Modify order transition rules in `TRANSITION_GRAPH` or `OrderStateMachine`
- Modify P&L formulas in `PnLCalculator`
- Modify `MarketSnapshot` or any Batch 6 market data contract
- Implement live broker order placement (no `kiteconnect` order calls)
- Integrate `src/execution/` with `main.py` in the first implementation
- Bypass repositories (no direct DB calls from engine classes)
- Bypass idempotency protections (recovery must use the same `_seen_fill_ids` / dedup pattern)
- Introduce float arithmetic for monetary values (all monetary values must use `Decimal`)

---

## 10. Questions and Missing Dependencies

Kimi must address the following during design:

1. **No database infrastructure** — No async engine, session factory, or session dependency exists in the active source tree. Batch 7D must specify: Does it define a new SQLAlchemy async stack, or adopt the `intraday-trading-bot/` conventions? The choice determines the migration path.

2. **No ORM models for execution entities** — All entities (orders, fills, positions, trades, audit events) need ORM models before any persistence can be implemented. What is the preferred table design? Primary keys, idempotency columns, timestamp conventions?

3. **Idempotency column conventions** — The current in-memory dedup uses `fill_id` (SHA-256 deterministic string) and `(client_order_id, action)` tuples. The persisted form must define unique constraints. Should these be partial unique indexes or full unique constraints?

4. **Audit event persistence strategy** — `ExecutionAuditEvent` has a UUID `event_id` and a `sequence_number` per order. Should it be stored in an append-only `execution_audit_log` table? Or embedded in an event-sourced order journal?

5. **Snapshot granularity** — Should snapshots be per-instrument (PositionSnapshot), per-portfolio (PortfolioSnapshot), or both? What is the trigger for snapshotting — time-based, trade-count-based, or explicit?

6. **Recovery scope** — After restart, does recovery replay from the beginning of time, or only from the last checkpoint? The current `FillEvent` + `ExecutionAuditEvent` design supports full replay, but the volume may be impractical without compaction.

7. **Transaction boundaries** — For a single fill, the state machine transition, position update, trade record, and journal write must be atomic. What is the unit-of-work boundary? Single session commit?

8. **Test isolation** — Batch 7B/7C tests are pure in-memory with no DB fixtures. Batch 7D tests that touch repositories need a strategy for test DB isolation (e.g., per-test transactions rolled back, SQLite in-memory, or dedicated test schema).

9. **`_cumulative_realized_pnl` persistence** — On recovery, this Decimal accumulator must be restored. It is derived from the trade ledger (sum of closed positions' realized P&L), so it can be recomputed from persisted trades — but this must be explicitly modelled in the recovery procedure.

10. **`MatchingEngine._processed_events` recovery** — This set contains `(order_id, market_event_id)` pairs. On recovery, if any market events are re-delivered, they must be deduplicated. The set must be seeded from the journal on startup.
