# Batch 9A/B — Code Review

**Reviewer:** Main Agent  
**Date:** 21 July 2026  
**Package:** `attached_assets/Batch9AB_Complete_1784649793540.zip`  
**Scope:** `src/strategy/` (11 source files) + stubs for `execution/`, `market_data/`, `risk/` + `tests/unit/strategy/` (11 test files)

---

## Verdict

**Do not merge as-is.** Three blockers prevent the package from being installed or its tests from running. Three serious issues will cause silent test failures or corrupt the runtime. Five moderate/minor issues are design concerns for Batch 9 to resolve.

---

## Files Delivered (from manifests)

### Source (`src/`)

| File | Size | Purpose |
|---|---|---|
| `src/strategy/contracts.py` | 6,253 B | Domain types: Signal, StrategyConfig, StrategyContext, etc. |
| `src/strategy/exceptions.py` | 1,264 B | 9 typed exception classes |
| `src/strategy/strategy_protocol.py` | 2,932 B | Strategy Protocol (on_bar/on_tick/on_fill/validate_config) |
| `src/strategy/state_machine.py` | 5,049 B | Lifecycle state machine with 7 states |
| `src/strategy/runtime.py` | 13,220 B | Per-strategy async task |
| `src/strategy/signal_router.py` | 9,827 B | Signal validation, order mapping, conflict detection |
| `src/strategy/coordinator.py` | 8,748 B | Global lifecycle manager |
| `src/strategy/context_builder.py` | 3,240 B | Immutable StrategyContext builder |
| `src/strategy/fill_tracker.py` | 6,514 B | Per-strategy fill tracking via FillEventBus |
| `src/strategy/__init__.py` | 1,803 B | Public exports (58 symbols) |
| `src/strategy/built_in/sma_crossover.py` | 5,212 B | Deterministic SMA crossover reference strategy |
| `src/execution/contracts.py` | 2,120 B | RC-7 stub: ExecutionOrder, FillRecord, enums |
| `src/execution/exceptions.py` | 398 B | RC-7 stub: Execution exception hierarchy |
| `src/execution/fills.py` | 530 B | RC-7 stub: FillEvent |
| `src/execution/portfolio.py` | 1,457 B | RC-7 stub: PositionSnapshot, PortfolioSnapshot |
| `src/market_data/contracts.py` | 1,722 B | RC-6 stub: Tick, CompletedBar, Quote |
| `src/market_data/service.py` | 1,191 B | RC-6 stub: MarketDataService |
| `src/risk/contracts.py` | 3,052 B | RC-8 stub: RiskResult, RiskViolation, RiskStateSnapshot |
| `src/risk/engine.py` | 682 B | RC-8 stub: RiskEngine |
| `src/risk/fill_event_bus.py` | 1,092 B | RC-8 stub: FillEventBus |
| `src/risk/integration_layer.py` | 1,381 B | RC-8 stub: RiskIntegrationLayer |

### Tests (`tests/unit/strategy/`)

| File | Tests | Coverage |
|---|---|---|
| `test_contracts.py` | 15 | Signal, Config, Context, Snapshot |
| `test_state_machine.py` | 14 | All lifecycle transitions |
| `test_signal_router.py` | 18 | Validation, routing, conflicts |
| `test_runtime.py` | 11 | Start/stop/pause/signals/fills |
| `test_coordinator.py` | 12 | Register/start/stop/emergency |
| `test_context_builder.py` | 6 | Context assembly |
| `test_fill_tracker.py` | 8 | Fill tracking, positions |
| `test_exceptions.py` | 9 | Exception hierarchy |
| `test_integration.py` | 3 | End-to-end pipeline |
| `built_in/test_sma_crossover.py` | 12 | SMA strategy validation |
| `conftest.py` + `__init__.py` files | — | Shared fixtures |

---

## Issues

### 🔴 BLOCKER 1 — Stubs will destroy the real RC-8 Risk Engine

The zip ships minimal replacement stubs for 4 files that **already exist** as complete, tested RC-8 implementations in the repo:

| File | Real (lines) | Stub (lines) | What's lost |
|---|---|---|---|
| `src/risk/contracts.py` | 456 | ~80 | `RiskConfiguration`, all 20 limit config types, `RiskAudit`, `ConcentrationLimitConfig`, field validators, etc. |
| `src/risk/engine.py` | 284 | ~30 | All rule evaluation logic, throttle tracking, fill recording |
| `src/risk/fill_event_bus.py` | 213 | ~30 | All routing, per-account filtering, subscription management |
| `src/risk/integration_layer.py` | 374 | ~50 | All pre-trade gating, session injection, port wiring |

Merging these as-is would overwrite 1,327 lines of RC-8 code with hollow stubs and break every existing RC-8 test (128 passing today).

Additionally, the stub `risk/contracts.py` adds a `DRAWDOWN = "DRAWDOWN"` value to `RiskCheckType` that does not exist in the real module and has no corresponding rule — it would corrupt the enum.

**Fix:** Exclude all 4 risk stub files from the merge. The strategy package must import the real RC-8 modules, not replacements. The stubs are only useful in an isolated test environment where RC-8 doesn't yet exist.

---

### 🔴 BLOCKER 2 — `execution/` and `market_data/` packages are missing `__init__.py`

The zip introduces two brand-new packages:

```
src/execution/contracts.py
src/execution/fills.py
src/execution/portfolio.py
src/execution/exceptions.py
src/market_data/contracts.py
src/market_data/service.py
```

Neither `src/execution/__init__.py` nor `src/market_data/__init__.py` is present in the zip. Without them Python will not recognise these directories as packages, and every `from execution.contracts import ...` statement in the strategy source will fail with `ModuleNotFoundError`. All 98 tests will error at import time before a single test runs.

**Fix:** Add `src/execution/__init__.py` and `src/market_data/__init__.py` (empty files are sufficient).

---

### 🔴 BLOCKER 3 — `test_validate_signal_zero_quantity` will error, not assert

`Signal.quantity` is declared `Field(..., gt=Decimal("0"))` (strictly greater than zero), so constructing:

```python
Signal(
    strategy_id="test_strat",
    instrument_token="RELIANCE",
    action=SignalAction.ENTER_LONG,
    side=ExecutionOrderSide.BUY,
    quantity=Decimal("0"),   # ← raises ValidationError here
)
```

raises `ValidationError` at construction — before `route_signal` is ever called. The test expects `route_signal` to return a `SignalRoutingResult(routed=False, status="REJECTED")`. That return value is never produced.

Compare the adjacent test `test_validate_signal_negative_quantity`, which correctly wraps the Signal construction in `pytest.raises(Exception)`. This test must follow the same pattern.

**Fix:**
```python
async def test_validate_signal_zero_quantity(self, router, strategy_config):
    with pytest.raises(Exception):
        Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("0"),
        )
```

---

### 🟠 SERIOUS 4 — `conftest.py` custom `event_loop` fixture conflicts with `asyncio_mode = "auto"`

The project already has in `pyproject.toml`:

```toml
asyncio_mode = "auto"
```

with `pytest-asyncio==0.23.7`. The new `conftest.py` adds:

```python
@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

In `pytest-asyncio` 0.23.x, redefining `event_loop` when `asyncio_mode = "auto"` is already active triggers:

```
DeprecationWarning: There is no current event loop
```

and in strict configurations this is promoted to an error. The custom fixture is entirely redundant — `asyncio_mode = "auto"` already provides a fresh event loop per test.

**Fix:** Delete `tests/unit/strategy/conftest.py` entirely.

---

### 🟠 SERIOUS 5 — `StrategyContext` forward-references `StrategyStateSnapshot` before it is defined

In `contracts.py`:

```python
class StrategyContext(BaseModel, frozen=True):          # line 94
    ...
    strategy_state: StrategyStateSnapshot = Field(      # ← type not yet defined
        default_factory=lambda: StrategyStateSnapshot(  # ← lambda captures by name
            strategy_id="",
            lifecycle_state=StrategyLifecycleState.REGISTERED,
        )
    )

class StrategyStateSnapshot(BaseModel, frozen=True):    # line 114  ← defined here
    ...
```

With `from __future__ import annotations`, Pydantic v2 stores annotations as strings and defers schema construction until first use, so this works at runtime. However, any code path that triggers `StrategyContext.model_rebuild()` before `StrategyStateSnapshot` is in the module scope (e.g. a third-party tool, early import, or a future `__init_subclass__` hook) will raise `PydanticUserError: NameError: name 'StrategyStateSnapshot' is not defined`. It is also a clear readability hazard.

**Fix:** Move `StrategyStateSnapshot` above `StrategyContext` in `contracts.py`. No other changes are needed.

---

### 🟠 SERIOUS 6 — `__init__.py` omits `ConflictResolution` and `StrategyRuntimeError`

Both are part of the public API surface of this package:

- `ConflictResolution` is the return type of `SignalRouter.detect_conflict()` — the primary cross-strategy conflict API.
- `StrategyRuntimeError` is the public error type raised by `StrategyRuntime`.

Neither appears in `src/strategy/__init__.py`'s import list or `__all__`. Tests currently import them directly from sub-modules (`from strategy.contracts import ConflictResolution`) which works, but any consumer of `from strategy import ConflictResolution` will get an `ImportError`.

**Fix:** Add both to `__init__.py`:

```python
from strategy.contracts import ConflictResolution
from strategy.exceptions import StrategyRuntimeError

__all__ = [
    ...
    "ConflictResolution",
    "StrategyRuntimeError",
]
```

---

### 🟡 MODERATE 7 — `FillEventBus` stub broadcasts to ALL subscribers regardless of `account_id`

The stub's `publish()`:

```python
def publish(self, fill_event: FillEvent) -> None:
    # For stub, we broadcast to all
    for account_id, callbacks in self._subscribers.items():
        for callback in callbacks:
            callback(fill_event)
```

The comment acknowledges this. In a multi-strategy test, every `StrategyFillTracker` (each subscribing under its own `strategy_id`) receives every fill from every strategy. Position tracking across strategies will be inflated and incorrect.

The real RC-8 `FillEventBus` (213 lines) routes fills by account ID. The stub inverts this: it routes to everyone. This means the multi-strategy integration test (`test_multi_strategy_no_conflict`) passes only because no fills are published in that test, masking the bug.

**Fix:** The stub should at minimum filter by the `account_id` key used at subscription time. A minimal correct implementation:

```python
def publish(self, fill_event: FillEvent, account_id: str) -> None:
    for callback in self._subscribers.get(account_id, []):
        callback(fill_event)
```

This requires either adding `account_id` to `FillEvent`, or having the caller specify it at publish time — consistent with how the real RC-8 bus works.

---

### 🟡 MODERATE 8 — `SmaCrossoverStrategy` is stateful, contradicting the Protocol's "stateless" requirement

The `Strategy` Protocol docstring states:

> *"Implementations are stateless logic containers. All mutable state (position tracking, indicator values, etc.) is managed by the StrategyRuntime and passed via StrategyContext."*

`SmaCrossoverStrategy` stores indicator state as instance variables:

```python
self._short_window: deque[Decimal]
self._long_window: deque[Decimal]
self._prev_short_sma: Optional[Decimal]
self._prev_long_sma: Optional[Decimal]
```

Consequences:
1. If the same strategy instance is reused across multiple instruments, SMA windows get mixed.
2. Recovery / replay from a checkpoint produces different signals from original execution (non-deterministic under recovery).
3. The `test_determinism` test creates two fresh instances — it would fail if both used the same instance.

**Fix (pick one):**
- **Option A:** Change the Protocol docstring to acknowledge that indicator state is an implementation concern, and document that the strategy instance must be single-use per instrument token.
- **Option B:** Move `_short_window`, `_long_window`, etc. into `StrategyContext.extra_metadata` (keyed by `instrument_token`) so state round-trips through the context and the instance truly holds no mutable state.

---

### 🟡 MODERATE 9 — Integration test accesses private internals of `MarketDataService`

In `test_integration.py`:

```python
await base_coordinator._market_data._subscribers["RELIANCE"][0](bar)
```

This reaches into `_subscribers`, a private dict, and calls the raw callback directly. Any internal refactor of `MarketDataService` (even of the stub) silently breaks this test. It also assumes the callback is the zeroth subscriber, which is fragile in multi-strategy tests.

**Fix:** Add a `publish_bar(instrument_token, bar)` helper to the `MarketDataService` stub for testing, and use that in the integration test.

---

### 🟡 MINOR 10 — `StrategyRuntime.start()` holds `self._lock` across external async calls

```python
async def start(self) -> TransitionResult:
    async with self._lock:                                    # lock acquired
        ...
        for token in self._config.instrument_tokens:
            await self._market_data.subscribe(token, ...)    # external async call while locked
        ...
```

`stop()`, `pause()`, and `resume()` all also acquire `self._lock`. If `subscribe()` is slow or raises mid-loop (e.g. network failure), the lock remains held and all other lifecycle operations deadlock until the lock is eventually released by exception propagation. This is particularly dangerous if a strategy subscribes to many instruments.

**Fix:** Perform the state-machine transition inside the lock, then release it before awaiting external services:

```python
async with self._lock:
    result = await self._state_machine.transition(STARTING, ...)
    self._task = asyncio.create_task(self._run_loop())
    result = await self._state_machine.transition(ACTIVE, ...)

# Subscribe outside the lock
for token in self._config.instrument_tokens:
    await self._market_data.subscribe(token, self._on_market_data)
```

---

### 🟡 MINOR 11 — `_process_fill` does not verify the fill belongs to this runtime's orders

In `StrategyRuntime._process_fill`:

```python
async def _process_fill(self, fill_event: FillEvent) -> None:
    if not self._state_machine.can_emit_signals:
        return
    context = await self._context_builder.build_context(...)
    signal = self._strategy.on_fill(fill_event, context)   # ← no ownership check
    ...
```

There is no check that `fill_event.client_order_id` matches an order submitted by this runtime. Given that the `FillEventBus` stub broadcasts to all (issue 7), a fill from strategy B reaches strategy A's `_process_fill` and causes it to call `on_fill` on the wrong strategy with an unrelated fill event.

**Fix:** Track submitted `client_order_id` values in the runtime (already partially done via `_state.pending_orders`). In `_process_fill`, skip fills whose `client_order_id` is not in that set.

---

## Summary

| # | Severity | Area | Fix required before merge |
|---|---|---|---|
| 1 | 🔴 Blocker | Risk stubs | Remove the 4 risk stub files; use real RC-8 modules |
| 2 | 🔴 Blocker | Package structure | Add `execution/__init__.py` and `market_data/__init__.py` |
| 3 | 🔴 Blocker | Test | Fix `test_validate_signal_zero_quantity` to use `pytest.raises` |
| 4 | 🟠 Serious | Test config | Delete `conftest.py` — conflicts with `asyncio_mode = "auto"` |
| 5 | 🟠 Serious | contracts.py | Move `StrategyStateSnapshot` above `StrategyContext` |
| 6 | 🟠 Serious | `__init__.py` | Add `ConflictResolution` and `StrategyRuntimeError` to exports |
| 7 | 🟡 Moderate | FillEventBus stub | Stub must filter by `account_id`, not broadcast to all |
| 8 | 🟡 Moderate | Design | Clarify/fix `SmaCrossoverStrategy` statefulness vs Protocol contract |
| 9 | 🟡 Moderate | Test | Replace `_subscribers` private access with a `publish_bar()` helper |
| 10 | 🟡 Minor | StrategyRuntime | Release lock before awaiting external subscribe calls |
| 11 | 🟡 Minor | StrategyRuntime | Add `client_order_id` ownership check in `_process_fill` |

**Blockers 1–3 must be resolved before any merge.** Issues 4–6 will cause test failures or silent incorrect behaviour and should be fixed in the same pass. Issues 7–11 are design/robustness concerns that Batch 9 should address before Batch 10 begins building on top of this layer.
