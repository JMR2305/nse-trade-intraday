# Batch 7D — Kimi Design Brief
## Execution Recovery, Persistence & Deterministic Replay

---

## 1. What Is Already Merged (do not modify)

| Batch | Module | Key types |
|---|---|---|
| 7A | `src/execution/contracts.py` | `ExecutionOrder`, `ExecutionAuditEvent`, `FillRecord`, all enums |
| 7A | `src/execution/state_machine.py` | `OrderStateMachine`, `OrderState`, `TransitionResult`, `TRANSITION_GRAPH` |
| 7A | `src/execution/exceptions.py` | Exception hierarchy |
| 7B | `src/execution/fills.py` | `FillEvent` (immutable), `FillEventBuilder` (SHA-256 `fill_id`) |
| 7B | `src/execution/matching.py` | `OrderMatcher`, `MarketSnapshot`, `MatchResult` |
| 7B | `src/execution/engine.py` | `MatchingEngine`, `EngineResult` |
| 7B | `src/execution/policies.py` | `PriceSelectionPolicy`, `SlippagePolicy`, `LiquidityPolicy`, `LatencyPolicy` |
| 7C | `src/execution/pnl.py` | `PnLCalculator` — pure static, all 10 position transitions |
| 7C | `src/execution/portfolio.py` | `PositionSnapshot`, `CashLedger`, `PortfolioSnapshot` |
| 7C | `src/execution/position_engine.py` | `PositionEngine`, `PositionEngineResult` |
| 7C | `src/execution/trades.py` | `ExecutionTrade`, `TradeLedger` |

**Tests:** 214/214 execution tests pass. 271/271 full unit suite.
**Command:** `python -m pytest tests/unit/ -q`
**Root:** `artifacts/api-server/src/python/`

---

## 2. In-Memory State That Must Be Persisted (the 7D problem)

Everything below is lost on restart:

| In-memory object | Idempotency key | Recovery method |
|---|---|---|
| `OrderStateMachine._orders` | `client_order_id` | Replay audit events |
| `OrderState._seen_transitions` | `(client_order_id, action, seq)` | Restore from audit log |
| `MatchingEngine._processed_events` | `(order_id, market_event_id)` | Restore from fill journal |
| `PositionEngine._positions` | `instrument_token` | Replay fills from last snapshot |
| `PositionEngine._seen_fill_ids` | `fill_id` | Restore from trade ledger |
| `PositionEngine._cumulative_realized_pnl` | derived | Sum closed trade P&L from ledger |
| `TradeLedger._trades` | `fill_id` | Restore from trade table |
| `CashLedger.balance` | derived | Starting cash ± trade gross_values |

---

## 3. Key Contracts (signatures only — full source in ZIP)

```python
# FillEvent — identity key used everywhere
fill_id: str  # deterministic SHA-256[:32](order_id:market_event_id:seq)

# ExecutionAuditEvent — generated per transition, NOT stored yet
event_id: UUID; order_id: UUID; sequence_number: int
previous_state / new_state: ExecutionOrderStatus
action: ExecutionOrderAction; fill_record: FillRecord | None

# PositionEngineResult — output of on_fill()
position_impact: str  # OPEN|ADD|REDUCE|CLOSE|REVERSE|DUPLICATE
realized_pnl: Decimal; new_position: PositionSnapshot; trade_recorded: bool

# ExecutionTrade — append-only, idempotent by fill_id
trade_id: str  # f"T-{fill_id}"
cumulative_realized_pnl: Decimal  # running total at time of trade
```

**PnL accumulation rule (important for recovery):**
- `_cumulative_realized_pnl` increments **only on CLOSE or REVERSE**, never on ADD/REDUCE
- `snapshot().realized_pnl` = `_cumulative_realized_pnl` + Σ `open_pos.realized_pnl`

---

## 4. What Does NOT Exist (Batch 7D must create from scratch)

- No ORM models for any execution entity (orders, fills, positions, trades, audit events)
- No execution repositories
- No async SQLAlchemy engine or session factory in `artifacts/api-server/src/python/`
- No Alembic config or migrations
- No recovery manager, replay engine, or snapshot store
- No event journal

The only existing repository is `src/database/repositories/minute_bars.py` (market data only) — included as a pattern reference. Pattern: constructor injects model class; all methods take `AsyncSession`; **no commit inside repositories**.

---

## 5. Repository Pattern Reference

```python
class MinuteBarRepository:
    def __init__(self, model_class=None): self._model = model_class
    async def get_*(self, session: AsyncSession, ...) -> ...: ...
    async def upsert_*(self, session: AsyncSession, ...) -> ...: ...
    # caller commits — no session.commit() inside any method
```

---

## 6. Batch 7D Scope

### May design and implement:
- Execution journal table (append-only: fills + audit events)
- Snapshot tables (position + portfolio, time/trade-count triggered)
- ORM models for all execution entities
- Repository interfaces: orders, fills, positions, trades, audit log, snapshots, idempotency markers
- Recovery manager: replay journal from last snapshot → restore in-memory state
- Replay engine: deterministic re-run of fill stream against `PositionEngine`
- Consistency validator: cross-check in-memory vs persisted
- Recovery coordinator / startup gate (blocks fills until recovery completes)
- Alembic migration(s) for the new tables
- Unit + integration tests (no live DB — use SQLite in-memory or per-test rollback)

### Must NOT:
- Modify `OrderMatcher`, `MatchingEngine` matching semantics
- Modify `TRANSITION_GRAPH` or `OrderStateMachine` transitions
- Modify `PnLCalculator` formulas
- Modify `MarketSnapshot` or any Batch 6 market data contract
- Add live broker order placement (`kiteconnect` order calls)
- Integrate `src/execution/` into `main.py`
- Use float for any monetary value — `Decimal` only
- Bypass repositories (no direct DB calls from engine classes)

---

## 7. Open Design Questions Kimi Must Answer

1. **DB stack** — Define a new SQLAlchemy async stack (engine + session factory) or adopt the `intraday-trading-bot/` conventions (`sqlalchemy[asyncio]==2.0.30`, `asyncpg==0.29.0`, `alembic==1.13.1`)?
2. **Audit persistence** — Append-only `execution_audit_log` table (event-log style) or embed in event-sourced order journal?
3. **Snapshot trigger** — Time-based, trade-count-based, or explicit call?
4. **Recovery scope** — Full replay from t=0, or replay from last snapshot (requires compaction strategy)?
5. **Transaction boundary** — Single `AsyncSession` commit covering state-machine transition + position update + trade record + journal write?
6. **Idempotency constraints** — `fill_id` as `UNIQUE` on fills table; `(order_id, sequence_number)` as `UNIQUE` on audit log?
7. **Test isolation** — Per-test transactions rolled back, SQLite in-memory, or dedicated test schema?
8. **`_cumulative_realized_pnl` recovery** — Recompute from trade ledger (sum of CLOSE/REVERSE trade `realized_pnl`) or snapshot the scalar directly?

---

## 8. Known Pre-existing Debt (do not fix in 7D)

- 11 root-level `test_phase*.py` files crash `pytest` collection (have `sys.exit()` at module level)
- `kiteconnect` not in `pyproject.toml` (lazy import in `src/brokers/`)
- `MarketDataService` not wired into `main.py`
- `instrument_sync.py` never calls `update_refresh_timestamp()`
