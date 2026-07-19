# BATCH_7D_PUBLIC_API.md
## NSE Paper Execution Engine — Public API Reference
### State after Batch 7C/7CA merge · Generated 2026-07-19

---

## SECTION 1 — PROJECT STRUCTURE

```
src/execution/
├── __init__.py
├── contracts.py        # ExecutionOrder, ExecutionAuditEvent, FillRecord + enums
├── exceptions.py       # ExecutionException hierarchy
├── fills.py            # FillEvent, FillEventBuilder
├── matching.py         # OrderMatcher, MatchingEngine input, MarketSnapshot, MatchResult
├── engine.py           # MatchingEngine, EngineResult
├── pnl.py              # PnLCalculator (pure functions)
├── policies.py         # PriceSelection, Slippage, Liquidity, Latency protocols + impls
├── portfolio.py        # PositionSnapshot, CashLedger, PortfolioSnapshot, PositionDirection
├── position_engine.py  # PositionEngine, PositionEngineResult
├── state_machine.py    # OrderStateMachine, OrderState, TransitionResult
└── trades.py           # ExecutionTrade, TradeLedger

src/database/
├── __init__.py
└── repositories/
    ├── __init__.py
    └── minute_bars.py  # MinuteBarRepository (only existing repo — market data, not execution)

tests/unit/execution/
├── conftest.py
├── __init__.py
├── test_contracts.py       # ExecutionOrder / FillRecord / ExecutionAuditEvent validation
├── test_engine.py          # MatchingEngine integration (market data → fill → state)
├── test_matching.py        # OrderMatcher per order-type and policy
├── test_pnl.py             # PnLCalculator all position transitions
├── test_policies.py        # PriceSelection, Slippage, Liquidity, Latency policies
├── test_portfolio.py       # PositionSnapshot, CashLedger, PortfolioSnapshot
├── test_position_engine.py # PositionEngine fill pipeline + concurrency
├── test_state_machine.py   # OrderStateMachine all transitions + idempotency + concurrency
└── test_trades.py          # ExecutionTrade + TradeLedger
```

---

## SECTION 2 — PUBLIC CLASSES

### 2.1 `OrderStateMachine` — `state_machine.py`

**Purpose:** Deterministic, concurrent-safe order lifecycle manager. Maintains per-order runtime state, validates transitions against a fixed graph, enforces idempotency, and emits immutable audit events.

**Constructor:**
```python
OrderStateMachine()
```
No arguments. Initialises an empty order registry and a `WeakValueDictionary` of per-order `asyncio.Lock` objects.

**Thread safety:** Async-safe. Each order has its own `asyncio.Lock`; locks are garbage-collected when the order is no longer referenced.

**Mutability:** The machine itself is mutable (holds live `OrderState` objects). `OrderState` is mutable. `TransitionResult` and `ExecutionAuditEvent` are frozen.

**Public methods:**

| Method | Signature | Returns | Raises |
|---|---|---|---|
| `register` | `(order: ExecutionOrder) → OrderState` | New `OrderState` in CREATED | — |
| `get_state` | `(order_id: UUID) → OrderState \| None` | Current runtime state | — |
| `get_executable_orders_for_instrument` | `(instrument_token: int) → list[UUID]` | Snapshot of OPEN/PARTIALLY_FILLED IDs | — |
| `transition` | `async (order_id, action, reason?, actor?, metadata?, fill_quantity?, fill_price?, fill_metadata?) → TransitionResult` | Result with audit event | `InvalidStateTransition`, `OverfillError`, `IdempotencyViolation` |
| `submit` | `async (order, actor?) → TransitionResult` | register + VALIDATE in one call | same as `transition` |
| `validate` | `async (order_id, actor?) → TransitionResult` | CREATED → VALIDATED | same |
| `accept` | `async (order_id, actor?) → TransitionResult` | VALIDATED → ACCEPTED | same |
| `reject` | `async (order_id, reason, actor?) → TransitionResult` | → REJECTED | same |
| `open_order` | `async (order_id, actor?) → TransitionResult` | ACCEPTED → OPEN | same |
| `partially_fill` | `async (order_id, quantity, price, actor?, metadata?) → TransitionResult` | → PARTIALLY_FILLED | same |
| `fill` | `async (order_id, quantity, price, actor?, metadata?) → TransitionResult` | → FILLED | same |
| `request_cancel` | `async (order_id, actor?) → TransitionResult` | → CANCEL_PENDING | same |
| `cancel` | `async (order_id, actor?) → TransitionResult` | → CANCELLED | same |
| `expire` | `async (order_id, actor?) → TransitionResult` | → EXPIRED | same |
| `fail` | `async (order_id, reason, actor?) → TransitionResult` | → FAILED | same |

---

### 2.2 `MatchingEngine` — `engine.py`

**Purpose:** Deterministic paper matching engine. Consumes `MarketSnapshot` events, evaluates all executable orders for the instrument, applies fills through the state machine.

**Constructor:**
```python
MatchingEngine(
    state_machine: OrderStateMachine,
    price_policy: PriceSelectionPolicy | None = None,   # default: DefaultPriceSelectionPolicy
    slippage_policy: SlippagePolicy | None = None,       # default: None (no slippage)
    liquidity_policy: LiquidityPolicy | None = None,     # default: DefaultLiquidityPolicy
    latency_policy: LatencyPolicy | None = None,         # default: ZeroLatencyPolicy
)
```

**Thread safety:** Multiple orders on the same instrument are evaluated concurrently via `asyncio.gather`. Per-order mutation is serialised by the state machine's locks.

**Mutability:** Mutable (holds `_processed_events` dedup set). Reset via `reset()`.

**Public methods:**

| Method | Signature | Returns | Raises |
|---|---|---|---|
| `register_order` | `(order: ExecutionOrder) → None` | — | — |
| `activate_order` | `async (order_id: UUID, actor?) → None` | Transitions ACCEPTED → OPEN | `RuntimeError` if not registered |
| `on_market_data` | `async (snapshot: MarketSnapshot) → EngineResult` | Fills + errors for this event | — |
| `reset` | `() → None` | Clears dedup set and matcher state | — |

---

### 2.3 `OrderMatcher` — `matching.py`

**Purpose:** Stateless (except trigger tracker) evaluator. Determines whether a single order is executable against a `MarketSnapshot` and computes `FillEvent`.

**Constructor:**
```python
OrderMatcher(
    price_policy: PriceSelectionPolicy | None = None,
    slippage_policy: SlippagePolicy | None = None,
    liquidity_policy: LiquidityPolicy | None = None,
    trigger_tracker: TriggerStateTracker | None = None,
)
```

**Thread safety:** Not thread-safe. One per `MatchingEngine` instance.

**Mutability:** Mutable via trigger tracker and fill builder sequence counters.

**Public methods:**

| Method | Signature | Returns |
|---|---|---|
| `match` | `(order, status, filled_quantity, remaining_quantity, snapshot) → MatchResult` | Executable flag + optional `FillEvent` |
| `reset` | `() → None` | Clears trigger state and fill sequence counters |

---

### 2.4 `PositionEngine` — `position_engine.py`

**Purpose:** Deterministic position, cash, P&L, and trade ledger engine. Consumes `FillEvent` objects and maintains per-instrument positions and a global portfolio.

**Constructor:**
```python
PositionEngine(initial_cash: Decimal = Decimal("1000000"))
```

**Thread safety:** Async-safe. Per-instrument `asyncio.Lock` serialises fills on the same instrument; different instruments are processed concurrently.

**Mutability:** Mutable. Reset via `reset()`.

**Public methods:**

| Method | Signature | Returns |
|---|---|---|
| `on_fill` | `async (fill: FillEvent) → PositionEngineResult` | Impact, realized P&L, new position |
| `update_market_price` | `async (instrument_token, market_price, market_timestamp) → PositionSnapshot \| None` | Updated position with unrealized P&L |
| `snapshot` | `() → PortfolioSnapshot` | Immutable portfolio-wide snapshot |
| `get_position` | `(instrument_token: int) → PositionSnapshot \| None` | Current position or None |
| `get_all_positions` | `() → dict[int, PositionSnapshot]` | All open positions |
| `get_cash` | `() → Decimal` | Current cash balance |
| `get_trade_ledger` | `() → TradeLedger` | Full trade history |
| `reset` | `() → None` | Clears all state, restores initial cash |

---

### 2.5 `PnLCalculator` — `pnl.py`

**Purpose:** Pure stateless functions. No constructor. All methods are `@staticmethod`.

| Method | Signature | Returns |
|---|---|---|
| `compute_realized_pnl` | `(current_position, fill_side, fill_quantity, fill_price) → tuple[Decimal, PositionSnapshot, str]` | `(realized_pnl, new_position, impact_label)` |
| `compute_unrealized_pnl` | `(position, market_price) → Decimal` | Unrealized P&L at current price |

**Raises:** `ValueError` on non-positive fill_quantity or fill_price.

---

### 2.6 `TradeLedger` — `trades.py`

**Purpose:** Deterministic, append-only, idempotent trade history.

**Constructor:** `TradeLedger()` — no arguments.

**Thread safety:** Reads are safe; writes must hold the caller's per-instrument lock.

| Method | Signature | Returns |
|---|---|---|
| `record` | `(trade: ExecutionTrade) → bool` | `True` if newly recorded, `False` if duplicate |
| `get_trades` | `(instrument_token?: int) → tuple[ExecutionTrade, ...]` | All trades, optionally filtered |
| `get_trade_by_fill_id` | `(fill_id: str) → ExecutionTrade \| None` | Lookup by fill ID |
| `reset` | `() → None` | Clears history (replay tests) |
| `trade_count` | property `→ int` | Total number of trades |
| `total_turnover` | property `→ Decimal` | Sum of `gross_value` of all trades |

---

### 2.7 `TriggerStateTracker` — `matching.py`

**Purpose:** Sticky activation for stop orders. Once triggered, remains triggered for the order's lifetime.

**Constructor:** `TriggerStateTracker()` — no arguments.

| Method | Signature | Returns |
|---|---|---|
| `is_triggered` | `(order_id) → bool` | Whether order's trigger has fired |
| `mark_triggered` | `(order_id) → None` | Activate sticky trigger |
| `reset` | `() → None` | Clear all trigger state |

---

### 2.8 `FillEventBuilder` — `fills.py`

**Purpose:** Deterministic builder. Guarantees deterministic `fill_id` via SHA-256 of `(order_id, market_event_id, sequence)`. Validates `gross_value == quantity * price`.

**Constructor:** `FillEventBuilder()` — no arguments.

| Method | Signature | Returns |
|---|---|---|
| `build` | `(order_id, client_order_id, instrument_token, side, quantity, price, market_event_id, market_timestamp, cumulative_filled_quantity, remaining_quantity, slippage_bps?, liquidity_source?, metadata?) → FillEvent` | Validated, frozen `FillEvent` |
| `reset` | `() → None` | Clear sequence counters for replay |

---

### 2.9 `MinuteBarRepository` — `database/repositories/minute_bars.py`

**Purpose:** CRUD and gap-finding for the `minute_bars` table. Session is caller-controlled (no commit inside).

**Constructor:** `MinuteBarRepository(model_class: Any | None = None)`

| Method | Signature | Returns |
|---|---|---|
| `insert_completed_bar` | `async (bar: CompletedBar, session) → None` | — |
| `insert_many` | `async (bars: list[CompletedBar], session) → None` | — |
| `get_range` | `async (instrument_token, start, end, session) → list[CompletedBar]` | Bars in `[start, end)`, ascending |
| `get_latest` | `async (instrument_token, session, before?) → CompletedBar \| None` | Most recent bar |
| `find_gaps` | `async (instrument_token, start, end, session) → list[tuple[datetime, datetime]]` | Missing 1-min intervals |
| `upsert_backfilled_bar` | `async (bar, policy: "INSERT_ONLY"\|"OVERWRITE"\|"SKIP", session) → None` | Conflict-aware upsert |

---

## SECTION 3 — DATA CLASSES

### 3.1 `ExecutionOrder` — `contracts.py`

Immutable Pydantic model (`model_config = frozen=True`). Construction-time validated.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `order_id` | `UUID` | `uuid4()` | Unique system order ID | Identity field |
| `client_order_id` | `str` | required | Caller-provided idempotency key | Idempotency field |
| `instrument_token` | `int` | required, `> 0` | NSE instrument token | — |
| `side` | `ExecutionOrderSide` | required | BUY or SELL | — |
| `order_type` | `ExecutionOrderType` | required | MARKET/LIMIT/STOP_MARKET/STOP_LIMIT | — |
| `quantity` | `int` | required, `> 0` | Total order quantity | — |
| `limit_price` | `Decimal \| None` | `None` | Limit price (LIMIT, STOP_LIMIT only) | — |
| `trigger_price` | `Decimal \| None` | `None` | Stop trigger (STOP_MARKET, STOP_LIMIT only) | — |
| `product` | `str` | `"CNC"` | Zerodha product type | — |
| `validity` | `str` | `"DAY"` | Order validity | — |
| `created_at` | `datetime` | `utcnow()` | Creation timestamp | Timestamp field; must be tz-aware |
| `exchange` | `str` | `"NSE"` | Exchange | — |
| `metadata` | `dict \| None` | `None` | Arbitrary caller metadata | — |

**Cross-field validation rules:**
- MARKET: no `limit_price`
- LIMIT: `limit_price` required and `> 0`
- STOP_MARKET: `trigger_price` required and `> 0`; no `limit_price`
- STOP_LIMIT: both `trigger_price` and `limit_price` required and `> 0`

---

### 3.2 `FillRecord` — `contracts.py`

Immutable Pydantic model. Internal tracking structure used by `OrderStateMachine`.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `fill_id` | `UUID` | `uuid4()` | Unique fill identifier | Identity field |
| `quantity` | `int` | required, `> 0` | Shares filled in this record | — |
| `price` | `Decimal` | required, `> 0` | Fill price | — |
| `filled_at` | `datetime` | required | When fill occurred | Timestamp; must be tz-aware |
| `metadata` | `dict \| None` | `None` | Optional metadata | — |

---

### 3.3 `ExecutionAuditEvent` — `contracts.py`

Immutable Pydantic model. Emitted on every successful state transition.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `event_id` | `UUID` | `uuid4()` | Unique event ID | Identity field |
| `order_id` | `UUID` | required | Linked order | — |
| `client_order_id` | `str` | required | Caller's order key | Idempotency reference |
| `sequence_number` | `int` | required, `>= 0` | Monotonically increasing per order | Sequence field |
| `previous_state` | `ExecutionOrderStatus` | required | State before transition | — |
| `new_state` | `ExecutionOrderStatus` | required | State after transition | — |
| `action` | `ExecutionOrderAction` | required | Action that triggered transition | — |
| `reason` | `str \| None` | `None` | Human-readable reason | — |
| `event_timestamp` | `datetime` | `utcnow()` | When event was created | Timestamp; tz-aware |
| `actor` | `str` | `"system"` | Who/what triggered transition | — |
| `metadata` | `dict \| None` | `None` | Arbitrary metadata | — |
| `fill_record` | `FillRecord \| None` | `None` | Attached fill for fill-type actions | — |

---

### 3.4 `FillEvent` — `fills.py`

Immutable Pydantic model. The matching engine's output contract.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `fill_id` | `str` | required | Deterministic SHA-256 ID | Identity + idempotency field |
| `event_id` | `UUID` | `uuid4()` | Secondary unique ID | — |
| `order_id` | `UUID` | required | Source order | — |
| `client_order_id` | `str` | required | Caller's order key | — |
| `instrument_token` | `int` | required, `> 0` | NSE instrument | — |
| `side` | `ExecutionOrderSide` | required | BUY or SELL | — |
| `quantity` | `int` | required, `> 0` | Shares filled | — |
| `price` | `Decimal` | required, `> 0` | Fill price | — |
| `gross_value` | `Decimal` | required, `> 0` | Must equal `quantity * price` | Validated by model |
| `market_event_id` | `str` | required | Source market event ID | — |
| `market_timestamp` | `datetime` | required | Market event time | Timestamp; tz-aware |
| `fill_timestamp` | `datetime` | `utcnow()` | Fill creation time | Timestamp; tz-aware |
| `cumulative_filled_quantity` | `int` | required, `>= 0` | Running total fills for order | — |
| `remaining_quantity` | `int` | required, `>= 0` | Shares still open | — |
| `liquidity_source` | `str` | `"paper"` | Always "paper" in current impl | — |
| `slippage_bps` | `Decimal` | `Decimal("0")` | Slippage applied in basis points | — |
| `metadata` | `dict \| None` | `None` | Pass-through from matcher | — |

---

### 3.5 `ExecutionTrade` — `trades.py`

Immutable Pydantic model. The position engine's record of a completed fill.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `trade_id` | `str` | required | Format: `"T-{fill_id}"` | Identity field |
| `fill_id` | `str` | required | Originating fill ID | Idempotency field |
| `order_id` | `UUID` | required | Source order | — |
| `client_order_id` | `str` | required | Caller's order key | — |
| `instrument_token` | `int` | required, `> 0` | NSE instrument | — |
| `side` | `ExecutionOrderSide` | required | BUY or SELL | — |
| `quantity` | `int` | required, `> 0` | Shares | — |
| `price` | `Decimal` | required, `> 0` | Fill price | — |
| `gross_value` | `Decimal` | required, `> 0` | `quantity * price` | — |
| `position_impact` | `str` | required | OPEN / ADD / REDUCE / CLOSE / REVERSE | Constrained by regex |
| `realized_pnl` | `Decimal` | `Decimal("0")` | P&L realised by this trade | — |
| `cumulative_realized_pnl` | `Decimal` | `Decimal("0")` | Running total across all trades | — |
| `market_timestamp` | `datetime` | required | Market event time | Timestamp; tz-aware |
| `trade_timestamp` | `datetime` | `utcnow()` | Record creation time | Timestamp; tz-aware |
| `metadata` | `dict \| None` | `None` | Pass-through | — |

---

### 3.6 `PositionSnapshot` — `portfolio.py`

Immutable frozen dataclass. Point-in-time position state.

| Field | Type | Default | Description | Notes |
|---|---|---|---|---|
| `instrument_token` | `int` | required | NSE instrument | — |
| `net_quantity` | `int` | required | Positive=LONG, Negative=SHORT, 0=FLAT | — |
| `direction` | `str` | required | `PositionDirection.LONG/SHORT/FLAT` | Must be consistent with `net_quantity` |
| `average_buy_price` | `Decimal` | required | WAEP of all buys | — |
| `average_sell_price` | `Decimal` | required | WAEP of all sells | — |
| `total_buy_quantity` | `int` | required | Cumulative buy shares | — |
| `total_sell_quantity` | `int` | required | Cumulative sell shares | — |
| `total_buy_value` | `Decimal` | required | Cumulative buy gross value | — |
| `total_sell_value` | `Decimal` | required | Cumulative sell gross value | — |
| `realized_pnl` | `Decimal` | required | Realised on currently-open position | — |
| `unrealized_pnl` | `Decimal` | required | Unrealised at last market price | — |
| `market_price` | `Decimal \| None` | — | Last known market price | — |
| `market_timestamp` | `datetime \| None` | — | Timestamp of last market price | Timestamp |
| `position_timestamp` | `datetime` | `utcnow()` | Snapshot creation time | Timestamp |
| `metadata` | `dict \| None` | `None` | — | — |

**Computed properties:** `is_long`, `is_short`, `is_flat`, `market_value` (`net_quantity * market_price`), `exposure` (`abs(net_quantity) * avg_price`).

---

### 3.7 `PortfolioSnapshot` — `portfolio.py`

Immutable frozen dataclass. Portfolio-wide aggregate.

| Field | Type | Default | Description |
|---|---|---|---|
| `cash` | `Decimal` | required | Current cash balance |
| `equity` | `Decimal` | required | `cash + market_value` |
| `positions` | `tuple[PositionSnapshot, ...]` | required | All open positions |
| `market_value` | `Decimal` | required | Sum of `position.market_value` |
| `realized_pnl` | `Decimal` | required | Total across all closed + open trades |
| `unrealized_pnl` | `Decimal` | required | Sum of `position.unrealized_pnl` |
| `total_pnl` | `Decimal` | required | `realized_pnl + unrealized_pnl` |
| `buying_power` | `Decimal` | required | Paper: equals `cash` |
| `margin_used` | `Decimal` | required | Sum of `position.exposure` |
| `trade_count` | `int` | required | Total trades recorded |
| `turnover` | `Decimal` | required | Sum of all `trade.gross_value` |
| `timestamp` | `datetime` | `utcnow()` | Snapshot creation time |
| `metadata` | `dict \| None` | `None` | — |

---

### 3.8 `CashLedger` — `portfolio.py`

Mutable dataclass. Protected by per-instrument lock inside `PositionEngine`.

| Field | Type | Default | Description |
|---|---|---|---|
| `balance` | `Decimal` | `0` | Current cash |
| `total_credits` | `Decimal` | `0` | Cumulative inflows (SELL fills) |
| `total_debits` | `Decimal` | `0` | Cumulative outflows (BUY fills) |
| `transaction_count` | `int` | `0` | Total transactions |

Methods: `credit(amount)`, `debit(amount)`, `snapshot() → dict`, `reset()`. Both raise `ValueError` on non-positive amounts.

---

### 3.9 `EngineResult` — `engine.py`

Frozen dataclass. Output of one `MatchingEngine.on_market_data()` call.

| Field | Type | Default | Description |
|---|---|---|---|
| `market_event_id` | `str` | required | Source event ID |
| `fills` | `list[FillEvent]` | `[]` | All fills generated |
| `errors` | `list[str]` | `[]` | Non-fatal errors during evaluation |

---

### 3.10 `MatchResult` — `matching.py`

Frozen dataclass. Output of one `OrderMatcher.match()` call.

| Field | Type | Default | Description |
|---|---|---|---|
| `executable` | `bool` | required | Whether order can be filled |
| `fill_event` | `FillEvent \| None` | `None` | Fill if executable |
| `reason` | `str \| None` | `None` | Explanation if not executable |

---

### 3.11 `PositionEngineResult` — `position_engine.py`

Frozen dataclass. Output of one `PositionEngine.on_fill()` call.

| Field | Type | Description |
|---|---|---|
| `fill_id` | `str` | Fill that was processed |
| `instrument_token` | `int` | Affected instrument |
| `position_impact` | `str` | OPEN / ADD / REDUCE / CLOSE / REVERSE / DUPLICATE |
| `realized_pnl` | `Decimal` | P&L realised by this fill |
| `new_position` | `PositionSnapshot` | Updated position state |
| `trade_recorded` | `bool` | False if duplicate fill |

---

### 3.12 `TransitionResult` — `state_machine.py`

Frozen dataclass. Output of every `OrderStateMachine.transition()` call.

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Whether transition was applied |
| `previous_state` | `ExecutionOrderStatus` | State before attempt |
| `new_state` | `ExecutionOrderStatus` | State after attempt |
| `audit_event` | `ExecutionAuditEvent \| None` | Immutable record (None if failed) |
| `order` | `OrderState \| None` | Updated runtime state (None if order not found) |
| `reason` | `str \| None` | Explanation for failure |

---

## SECTION 4 — ENUMS

### `ExecutionOrderStatus` — `contracts.py`
String enum.

| Value | Meaning |
|---|---|
| `CREATED` | Registered, not yet validated |
| `VALIDATED` | Passed validation checks |
| `REJECTED` | Rejected (terminal) |
| `ACCEPTED` | Accepted by risk/compliance layer |
| `OPEN` | Active on simulated market |
| `PARTIALLY_FILLED` | Some quantity filled |
| `FILLED` | Fully filled (terminal) |
| `CANCEL_PENDING` | Cancel requested, not yet confirmed |
| `CANCELLED` | Cancelled (terminal) |
| `EXPIRED` | Expired by validity rule (terminal) |
| `FAILED` | Unrecoverable failure (terminal) |

**Terminal states (frozenset):** `REJECTED`, `FILLED`, `CANCELLED`, `EXPIRED`, `FAILED`

---

### `ExecutionOrderType` — `contracts.py`
| Value | Meaning |
|---|---|
| `MARKET` | Execute immediately at market price |
| `LIMIT` | Execute only at `limit_price` or better |
| `STOP_MARKET` | Trigger at `trigger_price`, then execute as MARKET |
| `STOP_LIMIT` | Trigger at `trigger_price`, then execute as LIMIT |

---

### `ExecutionOrderSide` — `contracts.py`
| Value | Meaning |
|---|---|
| `BUY` | Buy side |
| `SELL` | Sell side |

---

### `ExecutionOrderAction` — `contracts.py`
| Value | Description |
|---|---|
| `submit` | Initial submission (register + validate) |
| `validate` | CREATED → VALIDATED |
| `accept` | VALIDATED → ACCEPTED |
| `reject` | → REJECTED |
| `open` | ACCEPTED → OPEN |
| `partially_fill` | → PARTIALLY_FILLED |
| `fill` | → FILLED |
| `request_cancel` | → CANCEL_PENDING |
| `cancel` | CANCEL_PENDING → CANCELLED |
| `expire` | → EXPIRED |
| `fail` | → FAILED |

---

### `PositionDirection` — `portfolio.py`
String constants (not an Enum class):
| Value | Meaning |
|---|---|
| `"LONG"` | Net long (positive quantity) |
| `"SHORT"` | Net short (negative quantity) |
| `"FLAT"` | No open position |

---

## SECTION 5 — STATE MACHINE

### Order Lifecycle

```
CREATED → VALIDATED → ACCEPTED → OPEN ──┐
    │          │                │        ├─→ PARTIALLY_FILLED ──┐
    │          │                └──→ FAIL │        │             │
    │          └──→ REJECT                │        ├──→ FILL     │
    └──────────────→ FAIL                 │        ├──→ CANCEL_PENDING → CANCEL
                                         │        └──→ EXPIRE / FAIL
                                         └──→ EXPIRE / FAIL
```

### Transition Graph (complete)

| From State | Allowed Actions |
|---|---|
| `CREATED` | `validate`, `reject`, `fail` |
| `VALIDATED` | `accept`, `reject`, `fail` |
| `ACCEPTED` | `open`, `fail` |
| `OPEN` | `partially_fill`, `fill`, `request_cancel`, `expire`, `fail` |
| `PARTIALLY_FILLED` | `partially_fill`, `fill`, `request_cancel`, `expire`, `fail` |
| `CANCEL_PENDING` | `cancel`, `open` (cancel rejected), `partially_fill`, `fill`, `fail` |
| `REJECTED` | ∅ (terminal) |
| `FILLED` | ∅ (terminal) |
| `CANCELLED` | ∅ (terminal) |
| `EXPIRED` | ∅ (terminal) |
| `FAILED` | ∅ (terminal) |

### Rejected Transitions (examples)
- Any action on a terminal state → `TransitionResult(success=False)` (no exception)
- Action not in graph → `InvalidStateTransition` raised
- `fill` when `filled + fill_quantity > order.quantity` → `OverfillError` raised
- Same `(client_order_id, action)` applied twice (non-fill actions) → `IdempotencyViolation` raised

### `TransitionResult`
Returned by every transition method. `success=False` means the transition was not applied; state is unchanged. `audit_event` is `None` on failure.

### Sequence Numbering
`OrderState.sequence_number` starts at 0 and increments by 1 on every successful transition. It is embedded in every `ExecutionAuditEvent.sequence_number`. Monotonically increasing per order; used to detect ordering violations in replay.

---

## SECTION 6 — MATCHING ENGINE

### `OrderMatcher`
Stateless evaluation function (one method: `match`). Supports four order types:

**MARKET:** Price = `ask_price` (BUY) or `bid_price` (SELL), fallback to LTP. Slippage applied if policy present. Fill quantity = `min(remaining_quantity, available_liquidity)`.

**LIMIT:** BUY executes if `LTP ≤ limit_price`; fill price = `limit_price`. SELL executes if `LTP ≥ limit_price`; fill price = `limit_price`. Slippage applied but capped at limit price (never worse than limit).

**STOP_MARKET:** Trigger activates when `LTP ≥ trigger_price` (BUY) or `LTP ≤ trigger_price` (SELL). Once triggered, behaves as MARKET. Trigger is sticky (remains active via `TriggerStateTracker`).

**STOP_LIMIT:** Same trigger logic as STOP_MARKET; once triggered behaves as LIMIT.

### `MatchingEngine`
Orchestrates `OrderMatcher` across all OPEN/PARTIALLY_FILLED orders for an instrument in one `on_market_data()` call. Concurrent evaluation via `asyncio.gather`. Per-order `(order_id, market_event_id)` dedup prevents double-fills.

**Execution flow per market event:**
1. Look up all OPEN/PARTIALLY_FILLED orders for the instrument
2. For each order concurrently: check latency eligibility → call `OrderMatcher.match()` → if executable, apply fill via `OrderStateMachine` (fill or partially_fill based on remaining quantity)
3. Return `EngineResult` with all fills and any non-fatal errors

### `MarketSnapshot`
Input contract for the matching engine.

| Field | Type | Default | Description |
|---|---|---|---|
| `instrument_token` | `int` | required | NSE token |
| `timestamp` | `datetime` | required | Event timestamp (tz-aware) |
| `last_traded_price` | `Decimal` | required | LTP |
| `event_id` | `str` | required | Unique event ID (dedup key) |
| `bid_price` | `Decimal \| None` | `None` | Best bid |
| `ask_price` | `Decimal \| None` | `None` | Best ask |
| `bid_quantity` | `int \| None` | `None` | Bid depth |
| `ask_quantity` | `int \| None` | `None` | Ask depth |
| `traded_volume` | `int \| None` | `None` | Session volume |
| `tick_size` | `Decimal` | `Decimal("0.05")` | NSE tick size |
| `metadata` | `dict \| None` | `None` | Pass-through |

### Policies

| Protocol | Default Implementation | Behaviour |
|---|---|---|
| `PriceSelectionPolicy` | `DefaultPriceSelectionPolicy` | BUY→ask (fallback LTP); SELL→bid (fallback LTP) |
| `SlippagePolicy` | None (no slippage) | `BasisPointsSlippagePolicy(bps)` or `FixedTicksSlippagePolicy(ticks)` |
| `LiquidityPolicy` | `DefaultLiquidityPolicy` | Fill up to `min(remaining, available_liquidity * max_fill_ratio)` |
| `LatencyPolicy` | `ZeroLatencyPolicy` | `ZeroLatencyPolicy` (all events eligible) or `FixedLatencyPolicy(delay_seconds)` |

---

## SECTION 7 — POSITION ENGINE

### Position Lifecycle

A position starts FLAT and transitions through impacts as fills arrive:

| Fill | From | Impact | To |
|---|---|---|---|
| BUY | FLAT | OPEN | LONG |
| SELL | FLAT | OPEN | SHORT |
| BUY | LONG | ADD | LONG (larger) |
| SELL | LONG (partial) | REDUCE | LONG (smaller) |
| SELL | LONG (exact) | CLOSE | FLAT |
| SELL | LONG (excess) | REVERSE | SHORT |
| SELL | SHORT | ADD | SHORT (larger) |
| BUY | SHORT (partial) | REDUCE | SHORT (smaller) |
| BUY | SHORT (exact) | CLOSE | FLAT |
| BUY | SHORT (excess) | REVERSE | LONG |

### P&L Accumulation Rules

- **Realized P&L** is computed on REDUCE, CLOSE, REVERSE: `(exit_price − avg_entry_price) × quantity` (LONG) or `(avg_entry_price − exit_price) × quantity` (SHORT).
- **Unrealized P&L** is recomputed on `update_market_price()`: `net_quantity × (market_price − avg_buy_price)` (LONG) or `abs(net_quantity) × (avg_sell_price − market_price)` (SHORT).
- **Cumulative realized P&L** in `PositionEngine._cumulative_realized_pnl` accumulates on CLOSE and REVERSE only. For REDUCE, the position's `realized_pnl` field carries the running total until close.
- **REVERSAL limitation:** The realized P&L on a reversal reflects the closed portion only. The new reversed position starts with `realized_pnl = 0`.

### Portfolio Updates
`PositionEngine.snapshot()` computes:
- `equity = cash + sum(position.market_value)`
- `realized_pnl = _cumulative_realized_pnl + sum(position.realized_pnl)` (open positions)
- FLAT positions are evicted from `_positions` dict to keep memory clean.

### Trade Ledger Interaction
Every fill that passes idempotency check produces one `ExecutionTrade` recorded via `TradeLedger.record()`. Duplicate `fill_id` is silently ignored (returns `False`). The ledger is append-only; no deletion API.

---

## SECTION 8 — REPOSITORY INTERFACES

### 8.1 `MinuteBarRepository` — existing, for market data

```python
class MinuteBarRepository:
    def __init__(self, model_class: Any | None = None) -> None

    async def insert_completed_bar(self, bar: CompletedBar, session: AsyncSession) -> None
    async def insert_many(self, bars: list[CompletedBar], session: AsyncSession) -> None
    async def get_range(self, instrument_token: int, start: datetime, end: datetime, session: AsyncSession) -> list[CompletedBar]
    async def get_latest(self, instrument_token: int, session: AsyncSession, before: datetime | None = None) -> CompletedBar | None
    async def find_gaps(self, instrument_token: int, start: datetime, end: datetime, session: AsyncSession) -> list[tuple[datetime, datetime]]
    async def upsert_backfilled_bar(self, bar: CompletedBar, policy: str, session: AsyncSession) -> None
```

### 8.2 Repositories needed by Batch 7D (not yet created)

Batch 7D must design and implement the following repository interfaces following the same session-injection pattern:

```python
# --- To be designed by Batch 7D ---

class ExecutionOrderRepository:
    async def save(self, order: ExecutionOrder, state: OrderState, session: AsyncSession) -> None
    async def get_by_id(self, order_id: UUID, session: AsyncSession) -> OrderState | None
    async def get_by_client_order_id(self, client_order_id: str, session: AsyncSession) -> OrderState | None
    async def list_active(self, session: AsyncSession) -> list[OrderState]
    async def update_status(self, order_id: UUID, new_status: ExecutionOrderStatus, session: AsyncSession) -> None

class AuditEventRepository:
    async def save(self, event: ExecutionAuditEvent, session: AsyncSession) -> None
    async def get_events_for_order(self, order_id: UUID, session: AsyncSession) -> list[ExecutionAuditEvent]
    async def get_latest_sequence(self, order_id: UUID, session: AsyncSession) -> int

class FillEventRepository:
    async def save(self, fill: FillEvent, session: AsyncSession) -> None
    async def get_by_fill_id(self, fill_id: str, session: AsyncSession) -> FillEvent | None
    async def get_fills_for_order(self, order_id: UUID, session: AsyncSession) -> list[FillEvent]

class ExecutionTradeRepository:
    async def save(self, trade: ExecutionTrade, session: AsyncSession) -> None
    async def get_by_fill_id(self, fill_id: str, session: AsyncSession) -> ExecutionTrade | None
    async def get_trades_for_instrument(self, instrument_token: int, session: AsyncSession) -> list[ExecutionTrade]
    async def get_all(self, session: AsyncSession) -> list[ExecutionTrade]

class PositionSnapshotRepository:
    async def save_snapshot(self, snapshot: PositionSnapshot, session: AsyncSession) -> None
    async def get_latest(self, instrument_token: int, session: AsyncSession) -> PositionSnapshot | None
    async def get_all_open(self, session: AsyncSession) -> list[PositionSnapshot]
```

---

## SECTION 9 — ORM MODELS

### 9.1 Existing ORM models (market data only)

The only existing ORM model relevant to this domain is the `minute_bars` table (accessed via `MinuteBarRepository`). Its schema is:

| Column | Type | Constraints |
|---|---|---|
| `instrument_token` | Integer | PK (composite) |
| `timestamp` | DateTime (tz-aware) | PK (composite) |
| `open` | Numeric | NOT NULL |
| `high` | Numeric | NOT NULL |
| `low` | Numeric | NOT NULL |
| `close` | Numeric | NOT NULL |
| `volume` | Integer | NOT NULL |
| `oi` | Integer | NULLABLE |

Primary key: `(instrument_token, timestamp)`. No foreign keys.

### 9.2 ORM models required by Batch 7D (not yet created)

Batch 7D must design these tables. Suggested schema conventions:

**`execution_orders`**
- `id` UUID PK
- `client_order_id` TEXT UNIQUE (idempotency)
- `instrument_token` INTEGER NOT NULL
- `side` TEXT NOT NULL
- `order_type` TEXT NOT NULL
- `quantity` INTEGER NOT NULL
- `limit_price` NUMERIC NULLABLE
- `trigger_price` NUMERIC NULLABLE
- `product` TEXT NOT NULL
- `validity` TEXT NOT NULL
- `status` TEXT NOT NULL
- `filled_quantity` INTEGER NOT NULL DEFAULT 0
- `average_fill_price` NUMERIC NULLABLE
- `sequence_number` INTEGER NOT NULL DEFAULT 0
- `exchange` TEXT NOT NULL
- `created_at` TIMESTAMPTZ NOT NULL
- `updated_at` TIMESTAMPTZ NOT NULL

**`execution_audit_events`**
- `id` UUID PK
- `order_id` UUID FK → execution_orders
- `client_order_id` TEXT NOT NULL
- `sequence_number` INTEGER NOT NULL
- `previous_state` TEXT NOT NULL
- `new_state` TEXT NOT NULL
- `action` TEXT NOT NULL
- `actor` TEXT NOT NULL
- `reason` TEXT NULLABLE
- `event_timestamp` TIMESTAMPTZ NOT NULL
- `fill_record` JSONB NULLABLE
- `metadata` JSONB NULLABLE
- INDEX `(order_id, sequence_number)`; UNIQUE `(order_id, sequence_number)`

**`execution_fills`**
- `fill_id` TEXT PK (deterministic SHA-256 hash)
- `order_id` UUID FK → execution_orders
- `client_order_id` TEXT NOT NULL
- `instrument_token` INTEGER NOT NULL
- `side` TEXT NOT NULL
- `quantity` INTEGER NOT NULL
- `price` NUMERIC NOT NULL
- `gross_value` NUMERIC NOT NULL
- `market_event_id` TEXT NOT NULL
- `market_timestamp` TIMESTAMPTZ NOT NULL
- `fill_timestamp` TIMESTAMPTZ NOT NULL
- `slippage_bps` NUMERIC NOT NULL DEFAULT 0
- `metadata` JSONB NULLABLE

**`execution_trades`**
- `trade_id` TEXT PK
- `fill_id` TEXT UNIQUE FK → execution_fills
- `order_id` UUID FK → execution_orders
- `instrument_token` INTEGER NOT NULL
- `side` TEXT NOT NULL
- `quantity` INTEGER NOT NULL
- `price` NUMERIC NOT NULL
- `gross_value` NUMERIC NOT NULL
- `position_impact` TEXT NOT NULL CHECK IN ('OPEN','ADD','REDUCE','CLOSE','REVERSE')
- `realized_pnl` NUMERIC NOT NULL DEFAULT 0
- `cumulative_realized_pnl` NUMERIC NOT NULL DEFAULT 0
- `market_timestamp` TIMESTAMPTZ NOT NULL
- `trade_timestamp` TIMESTAMPTZ NOT NULL
- `metadata` JSONB NULLABLE

**`position_snapshots`** (latest per instrument; or append-only history)
- `id` BIGSERIAL PK
- `instrument_token` INTEGER NOT NULL
- `net_quantity` INTEGER NOT NULL
- `direction` TEXT NOT NULL
- `average_buy_price` NUMERIC NOT NULL
- `average_sell_price` NUMERIC NOT NULL
- `total_buy_quantity` INTEGER NOT NULL
- `total_sell_quantity` INTEGER NOT NULL
- `realized_pnl` NUMERIC NOT NULL
- `unrealized_pnl` NUMERIC NOT NULL
- `market_price` NUMERIC NULLABLE
- `snapshot_timestamp` TIMESTAMPTZ NOT NULL
- UNIQUE `(instrument_token)` if latest-only table

---

## SECTION 10 — DATABASE CONVENTIONS

### Session Management
The project uses SQLAlchemy async sessions (`AsyncSession`). Sessions are **never created inside repositories**. They are passed in by the caller (service layer or route handler) as arguments.

```python
# Repository pattern — session is injected, never created inside
async def insert_completed_bar(self, bar: CompletedBar, session: AsyncSession) -> None:
    ...
    session.add(record)
    # No commit here
```

### Transaction Ownership
Commit ownership lies with the **caller**, not the repository. A repository method calls `session.add()` or executes DML but never `session.commit()` or `session.rollback()`.

### Repository Pattern
Each repository wraps a single SQLAlchemy model class. The model is **injected at construction time** (`model_class` argument) to avoid import-time database dependencies and to simplify testing with mock models.

### Unit-of-Work Pattern
Not formally implemented as a class. The convention is:
1. The route handler or service function opens an `AsyncSession` via a context manager or dependency injection.
2. It calls one or more repository methods (all sharing the same session).
3. It calls `await session.commit()` once at the end if all operations succeed.
4. On exception, the session context manager calls `await session.rollback()`.

### Async Patterns
All database operations are `async def`. Never use synchronous SQLAlchemy calls. Use `session.execute(stmt)`, `result.scalars()`, `result.scalar_one_or_none()`.

---

## SECTION 11 — TEST COVERAGE

| Test File | What It Validates |
|---|---|
| `test_contracts.py` | `ExecutionOrder` construction for all 8 type×side combinations; invalid quantity/price/timestamp rejection; immutability; `FillRecord` and `ExecutionAuditEvent` field validation |
| `test_state_machine.py` | Every allowed transition (happy path); every forbidden transition (raises `InvalidStateTransition`); terminal-state protection; partial-fill progression and average price; overfill rejection (`OverfillError`); idempotency deduplication (`IdempotencyViolation`); monotonic sequence numbers; failed-transition atomicity (state unchanged on error); concurrent transition safety (asyncio concurrent tasks) |
| `test_matching.py` | MARKET order BUY/SELL price selection and fallback; LIMIT order BUY/SELL eligibility and price clamping; STOP_MARKET trigger activation (sticky); STOP_LIMIT trigger + limit evaluation; slippage with `BasisPointsSlippagePolicy` and `FixedTicksSlippagePolicy`; zero-liquidity rejection; instrument mismatch rejection; non-executable state rejection |
| `test_engine.py` | OPEN → PARTIALLY_FILLED → FILLED end-to-end; terminal order never matched; deduplication of identical market events; concurrent fills on multiple orders; multiple instruments isolated |
| `test_pnl.py` | FLAT→LONG (OPEN); LONG ADD; LONG REDUCE (partial); LONG CLOSE (exact); LONG REVERSE (excess sell); FLAT→SHORT (OPEN); SHORT ADD; SHORT REDUCE; SHORT CLOSE; SHORT REVERSE; unrealized P&L calculation |
| `test_policies.py` | `DefaultPriceSelectionPolicy` buy/sell with and without bid/ask; `BasisPointsSlippagePolicy` buy worsens up, sell worsens down, tick rounding; `FixedTicksSlippagePolicy` same; `DefaultLiquidityPolicy` with/without liquidity info; `FixedLatencyPolicy` delay enforcement |
| `test_portfolio.py` | `PositionSnapshot` flat/long/short construction; direction consistency validation; computed properties (`market_value`, `exposure`); `CashLedger` credit/debit/reset; `PortfolioSnapshot` construction |
| `test_position_engine.py` | BUY opens LONG position with cash debit; SELL opens SHORT with cash credit; ADD, REDUCE, CLOSE, REVERSE lifecycle; duplicate fill idempotency; `update_market_price` unrealized P&L; `snapshot()` portfolio aggregation; concurrent fills on different instruments; `reset()` |
| `test_trades.py` | `ExecutionTrade` construction and immutability; invalid `position_impact` rejected; `TradeLedger` append, deduplication, filtering, turnover |

---

## SECTION 12 — DESIGN CONSTRAINTS

| Constraint | Rule |
|---|---|
| **Decimal only** | All monetary values (`price`, `quantity`, `gross_value`, `pnl`, `balance`) use `decimal.Decimal`. Float is forbidden. |
| **Idempotent processing** | `FillEvent.fill_id` is a deterministic SHA-256 hash of `(order_id, market_event_id, sequence)`. Duplicate fills are silently ignored at both the `PositionEngine` and `TradeLedger` layers. |
| **Deterministic replay** | Given the same `FillEvent` stream in the same order, the system produces identical `PositionSnapshot`, `PortfolioSnapshot`, and `TradeLedger` state. `OrderMatcher.reset()` and `FillEventBuilder.reset()` support replay. |
| **Immutable FillEvents** | `FillEvent` is a Pydantic frozen model. Once created it cannot be mutated. `gross_value == quantity * price` is validated at construction. |
| **Repository-only persistence** | No domain class (`OrderStateMachine`, `PositionEngine`, etc.) calls the database directly. Persistence is always delegated to a repository, which accepts a caller-controlled session. |
| **No direct DB access** | Domain classes hold no `AsyncSession` reference and import no SQLAlchemy symbols. |
| **Async patterns** | All state-mutating operations on the engine and state machine are `async def`. Per-order and per-instrument `asyncio.Lock` objects serialise concurrent mutations without a global lock. |
| **No live broker integration** | No Zerodha/KiteConnect calls in any execution module. The paper engine is isolated from the live broker (`MockBrokerClient` pattern enforced at the auto-paper-trading layer). |
| **Terminal state immutability** | Once an order reaches a terminal state (`REJECTED`, `FILLED`, `CANCELLED`, `EXPIRED`, `FAILED`), all further transition attempts return `TransitionResult(success=False)` without raising. |
| **Tick-size rounding** | Slippage policies round prices to the nearest tick via `ROUND_HALF_UP`. Default NSE tick size is `Decimal("0.05")`. |

---

## SECTION 13 — KNOWN LIMITATIONS

1. **No persistence.** `OrderStateMachine`, `PositionEngine`, and `TradeLedger` are entirely in-memory. A process restart loses all order and position state. Batch 7D's primary mandate is to design and implement DB persistence for these components.

2. **No crash recovery.** There is no mechanism to replay events from a durable log on restart. The engine cannot resume mid-session. Batch 7D must provide this via the new repositories and ORM models.

3. **Reversal P&L accounting is simplified.** When a fill reverses a position (LONG→SHORT or SHORT→LONG in one fill), the realized P&L covers the closed portion only. The new reversed position's `realized_pnl` starts at zero. The total gross value and quantity are correctly tracked across the reversal, but the split is not separately accounted.

4. **No slippage by default.** `MatchingEngine` constructs `OrderMatcher` with `slippage_policy=None`, meaning zero slippage. This must be explicitly configured by the caller.

5. **Simplified buying power.** `PortfolioSnapshot.buying_power` equals `cash`. Margin, haircuts, and VaR-based limits are not modelled.

6. **No order expiry engine.** `expire` transitions must be triggered externally. There is no built-in scheduler to expire DAY orders at market close.

7. **`MarketDataService` not wired into `main.py`.** The `MarketDataService` is implemented but not connected to the live data pipeline in the main application entry point.

8. **`instrument_sync.py` never calls `update_refresh_timestamp()`.** This leaves the refresh timestamp stale after instrument sync.

9. **11 root-level `test_phase*.py` files crash pytest collection.** These are not part of the execution test suite but interfere with `pytest` when run from the workspace root.

10. **`kiteconnect` not in `pyproject.toml`.** The Kite OAuth integration imports `kiteconnect` but it is not declared as a dependency, causing import errors in clean environments.

11. **`MinuteBarRepository` model injection.** If `model_class=None` (the default), all methods raise `RuntimeError`. The model must always be injected at construction. There is no default model.

---

## SECTION 14 — BATCH 7D INTEGRATION POINTS

### What Batch 7D must build

Batch 7D's sole mandate is **persistence and crash recovery** for the paper execution engine. The in-memory engine (Batches 7A–7C) must remain **unchanged**. Batch 7D wraps it.

### Classes that must remain unchanged

| Class | Module | Reason |
|---|---|---|
| `ExecutionOrder` | `contracts.py` | Stable contract used by all callers |
| `FillRecord` | `contracts.py` | State machine internal; stable |
| `ExecutionAuditEvent` | `contracts.py` | Audit contract; append-only semantics |
| `FillEvent` | `fills.py` | Engine output; downstream depends on it |
| `OrderStateMachine` | `state_machine.py` | Tested in isolation; no DB knowledge |
| `OrderMatcher` | `matching.py` | Pure evaluation logic |
| `MatchingEngine` | `engine.py` | Orchestration layer; DB-unaware by design |
| `PnLCalculator` | `pnl.py` | Pure functions; no state |
| `PositionEngine` | `position_engine.py` | In-memory engine; Batch 7D wraps it |
| `TradeLedger` | `trades.py` | In-memory ledger; Batch 7D wraps it |
| All policy classes | `policies.py` | Stable, injectable |

### Classes that will be extended by Batch 7D

| Class | Extension |
|---|---|
| `PositionEngine` | A **persistence adapter** (not subclass) will call `PositionEngine.on_fill()`, then persist the `PositionEngineResult` and updated `PositionSnapshot` via `PositionSnapshotRepository` |
| `OrderStateMachine` | A **persistence adapter** will call `OrderStateMachine.transition()`, then persist `TransitionResult.audit_event` via `AuditEventRepository` and update `ExecutionOrderRepository` |

### New repositories Batch 7D must create

See Section 8.2 for full signatures. Summary:

| Repository | Persists |
|---|---|
| `ExecutionOrderRepository` | `execution_orders` table; order status and fill progress |
| `AuditEventRepository` | `execution_audit_events` table; every transition |
| `FillEventRepository` | `execution_fills` table; fill events from matcher |
| `ExecutionTradeRepository` | `execution_trades` table; position engine trades |
| `PositionSnapshotRepository` | `position_snapshots` table; latest per-instrument position |

### New ORM models Batch 7D must create

See Section 9.2. Five tables:
- `execution_orders`
- `execution_audit_events`
- `execution_fills`
- `execution_trades`
- `position_snapshots`

### Where Batch 7D connects to the running system

The existing `main.py` / FastAPI application has no execution routes. Batch 7D should add:

1. **DB bootstrap** — create the five new tables via SQLAlchemy `metadata.create_all()` or a migration.
2. **Session factory** — expose an `AsyncSession` factory (following the existing pattern from `MinuteBarRepository`).
3. **Persistence adapters** — thin async wrappers around `OrderStateMachine` and `PositionEngine` that call the engine method and then write to DB within a single session/commit.
4. **Recovery path** — on startup, the persistence adapter loads all non-terminal orders from `execution_orders` and all audit events from `execution_audit_events`, then replays them through `OrderStateMachine` to reconstruct in-memory state.
5. **REST routes (optional in 7D)** — `GET /execution/orders`, `GET /execution/positions`, `GET /execution/trades` reading from DB (not from in-memory engine) for durability.

### Existing code that must not be touched

- `src/execution/*.py` — all 10 files are stable
- `tests/unit/execution/*.py` — all 9 test files must continue to pass without modification
- `src/database/repositories/minute_bars.py` — independent; no changes needed
