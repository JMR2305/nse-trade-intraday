# ARCHITECTURE REFERENCE
### NSE Paper Trading Platform — `intraday-trading-bot`
**Version:** RC-8  
**Date:** 21 July 2026  
**Status:** ✅ Risk Engine actively integrated into ExecutionService

---

## Quick-Reference Status Table

| Package | Status | Since | Tests |
|---|---|---|---|
| `src/market_data/` | ✅ Integrated | RC-6 (Batch 6) | 57 pass |
| `src/execution/` | ✅ Integrated | RC-7 (Batch 7A–7D) | 279 pass |
| `src/risk/` | ✅ **Actively integrated** | **RC-8 (Batch 8)** | **128 pass** |
| `src/brokers/` | ✅ Integrated | RC-6 | — |
| `src/database/` | ✅ Integrated | RC-7 | — |
| **Total unit tests** | | | **464 / 464** |

> **RC-8 promotion:** The Risk Engine was delivered as an isolated package in Batch 8 but previously wired
> only as a stub. As of RC-8, `RiskIntegrationLayer` gates every `ExecutionService.execute_order()` call
> before the order reaches the paper broker. The engine is **not dormant** — it is on the live path.

---

## Package Map

```
intraday-trading-bot/src/
│
├── brokers/
│   └── zerodha_market_data.py        ZerodhaMarketDataProvider (read-only, Kite Connect)
│
├── core/
│   └── config.py                     Settings (Pydantic v2 BaseSettings)
│
├── database/
│   ├── models/
│   │   ├── base.py                   Shared declarative_base — ALL models import from here
│   │   ├── audit_event.py            execution_audit_events
│   │   ├── execution_order.py        execution_orders
│   │   ├── execution_trade.py        execution_trades
│   │   ├── fill_event.py             execution_fills
│   │   ├── position_snapshot.py      position_snapshots
│   │   └── risk_state.py             risk_state_snapshots  ← RC-8 addition
│   └── repositories/
│       ├── minute_bars.py
│       ├── audit_event.py
│       ├── execution_order.py
│       ├── execution_trade.py
│       ├── fill_event.py
│       ├── position_snapshot.py
│       └── risk_state.py             RiskStateRepository  ← RC-8 addition
│
├── execution/                        RC-7 — FROZEN API (see §Frozen Components)
│   ├── contracts.py
│   ├── exceptions.py
│   ├── state_machine.py
│   ├── matching.py
│   ├── fills.py
│   ├── policies.py
│   ├── engine.py
│   ├── pnl.py
│   ├── portfolio.py
│   ├── trades.py
│   ├── position_engine.py
│   └── recovery/
│       ├── journal.py
│       ├── snapshot.py
│       ├── replay_engine.py
│       ├── recovery_manager.py
│       ├── consistency_checker.py
│       └── persistence_adapter.py
│
├── market_data/                      RC-6 — FROZEN API
│   ├── contracts.py
│   ├── provider.py
│   ├── service.py
│   ├── subscription_manager.py
│   ├── bar_builder.py
│   ├── quality.py
│   ├── backfill.py
│   └── instrument_sync.py
│
├── risk/                             RC-8 — ACTIVELY INTEGRATED ← KEY CHANGE
│   ├── __init__.py                   58 public exports
│   ├── contracts.py                  Pydantic v2 domain types (frozen, Literal[] pattern)
│   ├── exceptions.py                 Typed exception hierarchy incl. FillDeliveryError
│   ├── state.py                      RiskState — per-account mutable counters + safety flags
│   ├── kill_switch.py                Async KillSwitch with full audit trail
│   ├── rules.py                      20 rules in RULE_REGISTRY (Protocol-based)
│   ├── engine.py                     RiskEngine — per-account state, fill dedup, throttle
│   ├── fill_event_bus.py             FillEvent + FillEventBus pub/sub
│   ├── integration_layer.py          RiskIntegrationLayer + ExecutionEnginePort ABC
│   ├── execution_adapter.py          ProjectExecutionAdapter (bridges to project repos)
│   └── persistence.py                RiskEnginePersistenceAdapter (session-injected)
│
└── services/
    └── execution_service.py          ExecutionService — entry point; gated by RiskIntegrationLayer
```

---

## Live Request Path (RC-8)

Every inbound order now passes through the Risk Engine before reaching the paper broker:

```
API caller
    │
    ▼
ExecutionService.execute_order(session_id, order_dict)
    │
    ├─► RiskIntegrationLayer.submit_order(account_id, order)
    │        │
    │        ├─► RiskEngine.evaluate(account_id, request, context)
    │        │        │  (runs all 20 RULE_REGISTRY rules in priority order)
    │        │        ▼
    │        │   RiskResult { approved, violations, check_timestamp }
    │        │
    │        ├─ [BLOCKED] → return RiskIntegrationResult(approved=False, violations=[...])
    │        │
    │        └─ [APPROVED] → ExecutionEnginePort.submit_order()
    │                              │
    │                              ▼
    │                    ProjectExecutionAdapter.submit_order()
    │                              │
    │                              ▼
    │                    ExecutionService._submit_approved_order()
    │                              │
    │                              ▼
    │                    PaperBrokerClient  (RC-7 matching engine path)
    │
    └─► [On fill] RiskEngine.record_fill(account_id, fill_event)
                  FillEventBus.publish(fill_event)
```

**Key invariant:** `_submit_approved_order()` is only ever reached after the Risk Engine approves. The two execution paths (risk gate → approved path) are separated by the `ExecutionEnginePort` abstraction. There is no way to skip the risk gate without explicitly calling `layer.disable()`.

---

## Risk Engine — Rule Registry (20 rules)

| Rule | Check Type | Phase | Blocks on |
|---|---|---|---|
| `KillSwitchRule` | `KILL_SWITCH` | pre-trade | Kill switch active |
| `EmergencyHaltRule` | `EMERGENCY_HALT` | pre-trade | Emergency halt active |
| `CircuitBreakerRule` | `CIRCUIT_BREAKER` | pre-trade | Circuit breaker triggered |
| `OrderQuantityRule` | `ORDER_QUANTITY` | pre-trade | qty > max_quantity |
| `OrderValueRule` | `ORDER_VALUE` | pre-trade | notional > max_value |
| `TickSizeRule` | `TICK_SIZE` | pre-trade | price not multiple of tick |
| `PriceBandRule` | `PRICE_BAND` | pre-trade | price > band% from LTP |
| `MaxPositionSizeRule` | `MAX_POSITION_SIZE` | pre-trade | projected qty > limit |
| `InstrumentExposureRule` | `INSTRUMENT_EXPOSURE` | pre-trade | projected exposure > limit |
| `NetExposureRule` | `NET_EXPOSURE` | pre-trade | net long/short > limit |
| `ConcentrationRule` | `CONCENTRATION_LIMIT` | pre-trade | instrument % > limit |
| `CashAvailabilityRule` | `CASH_AVAILABILITY` | pre-trade | cash < order cost |
| `BuyingPowerRule` | `BUYING_POWER` | pre-trade | buying power insufficient |
| `PortfolioExposureRule` | `PORTFOLIO_EXPOSURE` | pre-trade | exposure% > limit |
| `MarginAvailabilityRule` | `MARGIN_AVAILABILITY` | pre-trade | margin insufficient |
| `DailyLossLimitRule` | `DAILY_LOSS_LIMIT` | pre-trade | loss ≥ hard limit (FATAL) |
| `DailyProfitTargetLockRule` | `DAILY_PROFIT_TARGET_LOCK` | pre-trade | profit ≥ target |
| `MaxTradesPerDayRule` | `MAX_TRADES_PER_DAY` | pre-trade | trade count ≥ limit |
| `MaxOrdersPerMinuteRule` | `MAX_ORDERS_PER_MINUTE` | pre-trade | orders in window ≥ limit |
| `DrawdownRule` | `DRAWDOWN` | pre-trade | drawdown% ≥ limit |

Rules evaluate in RULE_REGISTRY order. `KillSwitchRule` is evaluated first and short-circuits immediately on FATAL.

---

## Risk Engine — Domain Types (RC-8B vocabulary)

All types are in `src/risk/contracts.py`. All are Pydantic v2 models with `frozen=True`.

| Type | Role |
|---|---|
| `RiskRequest` | Input to a risk evaluation (account_id + order) |
| `RiskResult` | Output: `approved`, `violations`, `check_timestamp` |
| `RiskContext` | Market + portfolio state at evaluation time |
| `RiskViolation` | A single breached limit (check_type, severity, message, rule_id) |
| `RiskSeverity` | `INFO / WARNING / CRITICAL / FATAL` |
| `RiskCheckType` | Enum of all 20+ check categories |
| `RiskConfiguration` | Base config for a single rule |
| `RiskStateSnapshot` | Point-in-time snapshot for persistence |
| `RiskAudit` | Immutable audit record of every decision |
| `OrderQuantityLimit` | Config for ORDER_QUANTITY rule |
| `DailyLossLimit` | Config for DAILY_LOSS_LIMIT rule |
| `KillSwitchLimit` | Config for KILL_SWITCH rule |
| *(17 more limit config types)* | One per RiskCheckType |

**Pydantic v2 pattern used for frozen `check_type` fields:**
```python
# Each limit config class narrows its check_type with Literal:
class OrderQuantityLimit(RiskConfiguration, frozen=True):
    check_type: Literal[RiskCheckType.ORDER_QUANTITY] = RiskCheckType.ORDER_QUANTITY
```

---

## Database Schema (RC-8 additions)

### `risk_state_snapshots` (new in RC-8)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `account_id` | TEXT | Indexed with snapshot_timestamp |
| `snapshot_timestamp` | TIMESTAMPTZ | |
| `daily_realized_pnl` | NUMERIC(20,8) | |
| `daily_turnover` | NUMERIC(20,8) | |
| `trade_count` | INTEGER | ← RC-8B addition |
| `order_count` | INTEGER | ← RC-8B addition |
| `peak_equity` | NUMERIC(20,8) | |
| `kill_switch_active` | BOOLEAN | |
| `kill_switch_reason` | TEXT | nullable |
| `emergency_halt_active` | BOOLEAN | ← RC-8B addition |
| `circuit_breaker_triggered` | BOOLEAN | ← RC-8B addition |
| `message_counts` | JSONB | throttle state |
| `extra_metadata` | JSONB | |

**Migration:** `migrations/versions/0002_rc8b_risk_state_fields.py` — apply with `alembic upgrade head` on any environment where `risk_state_snapshots` already existed (fresh installs create the full schema via ORM auto-create).

---

## Frozen Components — Do Not Modify

The following are production-verified and locked. Any change requires a full regression run and explicit justification.

| Component | Locked Since | Why Frozen |
|---|---|---|
| `execution/contracts.py` — enum values | RC-7 | Stored in DB as strings; renaming breaks existing records and replay |
| `execution/state_machine.py` | RC-7 | Idempotency dedup and per-order lock pattern are safety-critical |
| `execution/matching.py`, `engine.py` | RC-7 | Matching logic and policy protocols are the determinism guarantee |
| `execution/pnl.py` — FIFO algorithm | RC-7 | Any change invalidates all historical P&L records |
| `execution/fills.py`, `position_engine.py` | RC-7 | FillEvent field names referenced by audit trail and persistence |
| `execution/recovery/replay_engine.py` | RC-7 | Idempotent replay contract is the crash-recovery guarantee |
| `database/models/*.py` — column names | RC-7 | Recovery layer reads columns by name; renaming requires migration + replay re-validation |
| `database/repositories/` — method signatures | RC-7 | Persistence adapters depend on these signatures |

---

## Design Principles

Principles established through RC-7 and upheld in RC-8:

1. **Deterministic behaviour** — identical input → identical output regardless of restart history.
2. **Idempotent processing** — every replayable operation (fills, transitions, risk snapshots) is safe to apply twice.
3. **Decimal for all monetary values** — `decimal.Decimal` mandatory; `float` prohibited.
4. **Repository-only persistence** — DB access only through `src/database/repositories/`; no ORM in domain or engine code.
5. **Async-first** — all I/O is `async def`; per-resource `asyncio.Lock` for shared state.
6. **Immutable events** — all domain events are `frozen=True` Pydantic models or frozen dataclasses.
7. **Session injection / caller-owned transactions** — no function below the service layer creates or commits a session.
8. **Layered architecture — no upward dependencies** — `contracts.py` → `rules/state/kill_switch` → `engine` → `integration_layer` → `execution_adapter` → `ExecutionService`. No layer imports from a layer above it.
9. **Backward compatibility** — new batches add capabilities; existing engine behaviour is never altered.
10. **Explicit failure** — exceptions propagate unless caught with documented intent; recovery errors are collected in structured result objects.
11. **Type safety** — full type annotations on all public signatures; Pydantic enforces field types at construction.
12. **Paper trading boundary** — the engine never constructs or submits a real broker order; the broker package is read-only.
13. **Risk gate is non-bypassable** — `ExecutionService._submit_approved_order()` is only reachable via `ProjectExecutionAdapter`, which is only called on `RiskResult.approved == True`. There is no code path that skips the gate without an explicit `layer.disable()` call.

---

## What RC-8 Changed

| Area | Before RC-8 | After RC-8 |
|---|---|---|
| Risk Engine vocabulary | RC-8A stub (`OrderSizeLimit`, `RiskDecision`, etc.) | RC-8B production (`OrderQuantityLimit`, `RiskResult`, etc.) |
| `contracts.py` Pydantic compat | `const=True` (Pydantic v1 only) | `Literal[EnumVal]` (Pydantic v2) |
| `ExecutionService` wiring | Called `RiskService.check_trade_risk()` (stub) | Calls `RiskIntegrationLayer.submit_order()` (live gate) |
| Risk gate on execute path | Dormant / bypassed | **Active — every order is checked** |
| `RiskStateModel` columns | 8 columns | 12 columns (+ trade_count, order_count, emergency_halt_active, circuit_breaker_triggered) |
| Unit tests | 336 (execution + market_data) | **464 (+ 128 risk engine tests)** |
| Git tag | `RC-7` | **`RC-8`** |

---

## What Batch 9 Should Assume

### The Risk Engine Is Production-Ready and Active

As of RC-8, the following are stable and must be treated as a fixed foundation:

- `RiskEngine` — per-account state, 20-rule evaluation, fill dedup, throttle recording ✅
- `RiskIntegrationLayer` — async order gate with per-account serialization ✅
- `KillSwitch` — async activate/deactivate with full audit trail ✅
- `FillEventBus` — pub/sub fill notification; subscribers can hook here ✅
- `ProjectExecutionAdapter` — RC-7 bridge; `get_market_price()` returns `None` (paper) ✅
- `RiskStateRepository` — save/restore via `risk_state_snapshots` table ✅

### account_id == session_id

Throughout the risk engine, `account_id` maps to the project's `session_id`. This is enforced in `ProjectExecutionAdapter` and must be maintained in any future integration.

### PriceBandRule Skips in Paper Mode

`ProjectExecutionAdapter.get_market_price()` returns `None` because there is no real-time LTP in paper mode. `PriceBandRule.evaluate()` skips gracefully when LTP is `None`. If real-time pricing is added later, this adapter method must be updated.

### layer.disable() for Testing

`RiskIntegrationLayer(enabled=False)` or `layer.disable()` bypasses all risk checks. Use this in tests that exercise the execution path without wanting risk semantics.

### Alembic Required on Existing Environments

Any environment where `risk_state_snapshots` was created before RC-8B needs `alembic upgrade head` to add the 4 new columns. Fresh environments auto-create the full schema via ORM.

---

*Document version: RC-8*  
*Last updated: 21 July 2026*  
*Execution tests: 279 / 279 ✅*  
*Risk engine tests: 128 / 128 ✅*  
*Total unit tests: 464 / 464 ✅*  
*Pre-existing failure: `tests/unit/test_kill_switch.py::test_history` (KillSwitchManager, unrelated to RC-8)*
