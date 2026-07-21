# Batch 9A/B — Reviewed Package Delta Audit

**Reviewer:** Main Agent  
**Date:** 21 July 2026  
**Package:** `attached_assets/Batch9AB_Reviewed_1784660500461.zip`  
**Against:** Original review `reviews/Batch9AB_review.md`  
**Tests run:** Live execution against real RC-8 codebase

---

## Verdict

**Still cannot merge.** 8 of the 11 original issues were resolved, but the fix for issue #7 introduced a signature mismatch that broke 7 tests, and 5 additional test failures were discovered that were not present in the original review. Net result: **12 distinct test failures** across 5 test files, plus the runtime/coordinator/integration suite hanging the test runner.

---

## Original Issues — Status

| # | Severity | Original Issue | Status |
|---|---|---|---|
| 1 | 🔴 Blocker | Risk stubs would overwrite real RC-8 modules | ✅ **Fixed** — `risk/contracts.py`, `risk/engine.py`, `risk/integration_layer.py` removed |
| 2 | 🔴 Blocker | Missing `__init__.py` for `execution/` and `market_data/` | ✅ **Fixed** — both added |
| 3 | 🔴 Blocker | `test_validate_signal_zero_quantity` wrong assertion pattern | ✅ **Fixed** — wrapped in `pytest.raises(Exception)` |
| 4 | 🟠 Serious | `conftest.py` conflicts with `asyncio_mode = "auto"` | ✅ **Fixed** — file removed entirely |
| 5 | 🟠 Serious | `StrategyContext` forward-references `StrategyStateSnapshot` | ✅ **Fixed** — `StrategyStateSnapshot` moved above `StrategyContext` (now line 94 vs 111) |
| 6 | 🟠 Serious | `__init__.py` missing `ConflictResolution` and `StrategyRuntimeError` | ✅ **Fixed** — both added to imports and `__all__` |
| 7 | 🟡 Moderate | `FillEventBus` stub broadcasts to all subscribers | ⚠️ **Partially fixed — introduced regression** (see new issue A) |
| 8 | 🟡 Moderate | `SmaCrossoverStrategy` is stateful vs "stateless" Protocol claim | ❌ **Not addressed** |
| 9 | 🟡 Moderate | Integration test accesses private `_subscribers` dict | ❌ **Not addressed** |
| 10 | 🟡 Minor | `StrategyRuntime.start()` holds lock during external `subscribe()` | ✅ **Fixed** — subscription moved outside lock with comment |
| 11 | 🟡 Minor | `_process_fill` has no fill-ownership check | ✅ **Fixed** — `client_order_id not in pending_orders` guard added |

---

## New Issues Found (Reviewed Package Only)

### 🔴 NEW BLOCKER A — `FillEventBus.publish()` signature change broke 7 tests

The fix for original issue #7 changed `publish()` from:

```python
# old stub (broadcasts to all)
def publish(self, fill_event: FillEvent) -> None:
```

to:

```python
# new stub (routes by account_id)
def publish(self, fill_event: FillEvent, account_id: str) -> None:
```

This is the correct routing behaviour, but **every test call to `publish` was left unchanged** — all still pass only one argument:

```python
fill_event_bus.publish(fill)   # ← TypeError: missing required argument 'account_id'
```

7 tests fail as a result:

```
FAILED test_fill_tracker.py::test_buy_fill_creates_long_position    — position never created
FAILED test_fill_tracker.py::test_sell_fill_creates_short_position  — position never created
FAILED test_fill_tracker.py::test_multiple_buys_aggregate           — position never created
FAILED test_fill_tracker.py::test_buy_then_sell_flattens            — fill_count == 0
FAILED test_fill_tracker.py::test_unsubscribe_stops_tracking        — TypeError on unsubscribe
FAILED test_fill_tracker.py::test_callback_invoked                  — callback never fires
```

**Root cause for the 7th failure (`test_unsubscribe_stops_tracking`):** `FillEventBus.unsubscribe()` was similarly changed to `unsubscribe(self, account_id, callback)` but `StrategyFillTracker.unsubscribe()` still calls:

```python
self._bus.unsubscribe(self._config.strategy_id, self._on_fill)
```

which now passes 2 args to a method that expects 2 positional args — **this one actually matches** — but `subscribe()` in the real RC-8 module (`async def subscribe(self, name: str, callback) -> str:`) returns a `subscriber_id` string that must be passed to `unsubscribe`. The stub `unsubscribe(account_id, callback)` mixes those two APIs.

**Fix — all test calls to `publish` must include the account_id:**

```python
fill_event_bus.publish(fill, "test_strat")   # account_id = strategy_id used at subscribe time
```

---

### 🔴 NEW BLOCKER B — `test_validate_signal_negative_quantity` still fails

The fix for Blocker 3 (zero-quantity) correctly wrapped Signal construction in `pytest.raises`. The companion test for **negative** quantity was not fixed and still has the same problem:

```python
async def test_validate_signal_negative_quantity(self, router, strategy_config):
    signal = Signal(             # ← raises ValidationError here
        ...
        quantity=Decimal("-10"),
    )
    with pytest.raises(Exception):    # ← never reached
        await router.route_signal(signal, ...)
```

`Signal.quantity = Field(..., gt=Decimal("0"))` rejects `-10` at construction. The `pytest.raises` wraps the wrong statement.

**Fix:** Same pattern as the zero-quantity fix:
```python
async def test_validate_signal_negative_quantity(self, router, strategy_config):
    with pytest.raises(Exception):
        Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("-10"),
        )
```

---

### 🔴 NEW BLOCKER C — `SmaCrossoverStrategy` never reads parameters from `StrategyConfig`

`SmaCrossoverStrategy.__init__` hard-codes its parameters:

```python
def __init__(self):
    self._short_period: int = 5
    self._long_period: int = 20
    self._quantity: Decimal = Decimal("100")
```

`validate_config()` checks parameter values for validity but **never assigns them to instance variables**. The strategy always runs with `short_period=5, long_period=20` regardless of what's in `StrategyConfig.parameters`.

This causes two test failures:

```
FAILED test_sma_crossover.py::test_golden_cross_signal
FAILED test_sma_crossover.py::test_death_cross_signal
```

Both tests call `strat.validate_config(base_config)` expecting it to configure the strategy, then feed 10 bars. With `long_period=20` hard-coded, the long window never fills in 10 bars and the strategy always returns `None`.

The integration test (`test_integration.py`) passes `parameters={"short_period": 3, "long_period": 5, "quantity": 50}` in the config and expects a signal to fire, but the strategy ignores these values and uses 5/20 instead — so signals depend entirely on whether 50+ bars happen to trigger a crossover.

**Fix:** Apply config parameters at strategy initialisation — either in `validate_config` (as a side-effect, with a note that this is intentional), or add an explicit `configure(config: StrategyConfig) -> None` method to the Protocol:

```python
def validate_config(self, config: StrategyConfig) -> List[str]:
    errors = []
    params = config.parameters
    short = params.get("short_period", 5)
    long_ = params.get("long_period", 20)
    # ... validation ...
    if not errors:                      # apply only if valid
        self._short_period = int(short)
        self._long_period = int(long_)
        self._quantity = Decimal(str(params.get("quantity", 100)))
    return errors
```

---

### 🟠 NEW SERIOUS D — `PortfolioSnapshot` timestamp comparison causes 2 test failures

`PortfolioSnapshot` is a `@dataclass(frozen=True)` with:

```python
timestamp: datetime = field(default_factory=datetime.utcnow)
```

Two separate `PortfolioSnapshot()` constructions made microseconds apart produce instances with different `timestamp` values, so `==` comparison fails:

```
FAILED test_contracts.py::TestStrategyContext::test_context_creation
AssertionError: assert ctx.portfolio == PortfolioSnapshot()
  Differing attributes: ['timestamp']
  timestamp: datetime(2026, 7, 21, 19, 14, 39, 360536) != datetime(2026, 7, 21, 19, 14, 39, 360572)

FAILED test_context_builder.py::TestContextBuilder::test_build_context_basic
AssertionError: assert ctx.portfolio == PortfolioSnapshot()
  Differing attributes: ['timestamp']
```

This was always latent (the original package had the same code) but is now exposed because `StrategyStateSnapshot` is no longer masking the issue via earlier failures.

**Fix (two options):**

Option A — Compare only the meaningful fields, not timestamp:
```python
assert ctx.portfolio.cash == Decimal("0")
assert ctx.portfolio.equity == Decimal("0")
# etc.
```

Option B — Use `dataclasses.replace` to freeze the timestamp for comparison:
```python
empty = PortfolioSnapshot()
assert dataclasses.replace(ctx.portfolio, timestamp=empty.timestamp) == empty
```

---

### 🟠 NEW SERIOUS E — Runtime/coordinator/integration tests hang the test runner

`StrategyRuntime.start()` creates a permanent background task:

```python
self._task = asyncio.create_task(self._run_loop())
```

`_run_loop()` runs until `self._shutdown_event.is_set()`. When a test ends without calling `await runtime.stop()` (or when stop fails), the task keeps running and the event loop never closes.

In practice:
- `test_runtime.py` (11 tests) — **entire file hangs**
- `test_coordinator.py` (12 tests) — **entire file hangs**
- `test_integration.py` (3 tests) — **entire file hangs**

Together this is **26 tests that never complete**. The OS `timeout 30` kills the runner; pytest reports no results for these files.

Root causes observed:
1. Tests that call `runtime.start()` without a matching `runtime.stop()` (even if the test passes the assertion).
2. `runtime.stop()` cancels the task but `_run_loop` may have an in-flight `_process_bar` await — if that coroutine itself awaits `_context_builder.build_context`, the cancel propagation can stall.
3. `test_integration.py` injects bars via `base_coordinator._market_data._subscribers["RELIANCE"][0](bar)` which fires `asyncio.create_task(self.on_bar(data))` — these tasks are never awaited and linger past test teardown.

**Fix (minimum viable):** Add a module-level `autouse` fixture that cancels all lingering tasks after each test:

```python
# in tests/unit/strategy/conftest.py
import asyncio
import pytest

@pytest.fixture(autouse=True)
async def cancel_stray_tasks():
    yield
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

This is the standard pytest-asyncio pattern for test isolation when strategies create background tasks.

---

## Full Test Results (Reviewed Package)

| File | Tests | Passed | Failed | Hung |
|---|---|---|---|---|
| `test_contracts.py` | 15 | 14 | 1 (D) | — |
| `test_state_machine.py` | 14 | 14 | 0 | — |
| `test_exceptions.py` | 9 | 9 | 0 | — |
| `test_signal_router.py` | 18 | 17 | 1 (B) | — |
| `test_context_builder.py` | 6 | 5 | 1 (D) | — |
| `test_fill_tracker.py` | 8 | 1 | 7 (A) | — |
| `test_runtime.py` | 11 | — | — | ✗ hangs (E) |
| `test_coordinator.py` | 12 | — | — | ✗ hangs (E) |
| `test_integration.py` | 3 | — | — | ✗ hangs (E) |
| `built_in/test_sma_crossover.py` | 12 | 10 | 2 (C) | — |
| **Total** | **108** | **70** | **12** | **26 not run** |

---

## Issues Remaining — Consolidated

| # | Severity | Issue | Fix Required |
|---|---|---|---|
| A | 🔴 Blocker | `FillEventBus.publish()` new 2-arg signature broke 7 fill-tracker tests | Update all 7 test `publish(fill)` calls to `publish(fill, "test_strat")` |
| B | 🔴 Blocker | `test_validate_signal_negative_quantity` still fails | Wrap Signal construction in `pytest.raises` |
| C | 🔴 Blocker | `SmaCrossoverStrategy` never applies config parameters; 2 tests fail | Apply config params inside `validate_config` or a new `configure()` method |
| D | 🟠 Serious | `PortfolioSnapshot` timestamp comparison fails across 2 test files | Compare individual fields, not the whole object |
| E | 🟠 Serious | Background task from `_run_loop` hangs 3 test files (26 tests) | Add autouse `cancel_stray_tasks` fixture to `conftest.py` |
| 8 | 🟡 Moderate | `SmaCrossoverStrategy` is stateful vs "stateless" Protocol claim | Clarify docs or key state by `instrument_token` |
| 9 | 🟡 Moderate | Integration test accesses private `_subscribers` dict | Add `publish_bar()` helper to `MarketDataService` stub |

**Items A–E must be fixed before the package can be merged.** Items 8–9 are design concerns carried over from the original review.
