# Batch 9A/B — Final Package Audit

**Reviewer:** Main Agent  
**Date:** 21 July 2026  
**Package:** `attached_assets/Batch9AB_Final_1784661813624.zip`  
**Against prior reviews:** `Batch9AB_review.md`, `Batch9AB_reviewed_delta.md`  
**Tests run:** Live execution against real RC-8 codebase

---

## Verdict

**Still cannot merge — 22 tests failing across 5 files.**

Good progress: all issues from the original review and all but two from the delta review have been addressed. However, a single unfixed root cause — the `FillEventBus` stub is not active at test time because the real RC-8 module takes precedence — cascades into failures across fill tracking, runtime, coordinator, integration, and SMA tests. One SMA test also remains broken due to insufficient test data for the default window size.

---

## Delta Issues — Status

| # | Severity | Delta Issue | Status |
|---|---|---|---|
| A | 🔴 Blocker | `publish()` 2-arg calls failed because tests still used 1-arg | ✅ **Fixed** — most calls updated to `publish(fill, "test_strat")`; see residual below |
| B | 🔴 Blocker | `test_validate_signal_negative_quantity` still wrong | ✅ **Fixed** — wrapped in `pytest.raises(Exception)` |
| C | 🔴 Blocker | `SmaCrossoverStrategy` never applied config parameters | ✅ **Fixed** — `validate_config` now writes to instance vars with doc comment |
| D | 🟠 Serious | `PortfolioSnapshot` timestamp comparison | ✅ **Fixed** — both test files now compare individual fields (`cash`, `equity`, etc.) |
| E | 🟠 Serious | Background `_run_loop` tasks hung 3 test files | ✅ **Fixed** — `cancel_stray_tasks` autouse fixture added to `conftest.py` |
| 8 | 🟡 Moderate | `SmaCrossoverStrategy` statefulness vs Protocol | ⚠️ **Partially addressed** — doc comment added to `validate_config`; Protocol docstring unchanged |
| 9 | 🟡 Moderate | Integration test private `_subscribers` access | ❌ **Not addressed** — still uses `_subscribers` dict directly |

---

## Live Test Results

| File | Tests | Pass | Fail |
|---|---|---|---|
| `test_contracts.py` | 15 | 15 | 0 |
| `test_state_machine.py` | 14 | 14 | 0 |
| `test_exceptions.py` | 9 | 9 | 0 |
| `test_signal_router.py` | 18 | 18 | 0 |
| `test_context_builder.py` | 6 | 6 | 0 |
| `test_fill_tracker.py` | 8 | 1 | **6** |
| `test_runtime.py` | 11 | 1 | **10** |
| `test_coordinator.py` | 12 | 9 | **3** |
| `test_integration.py` | 3 | 2 | **1** |
| `built_in/test_sma_crossover.py` | 12 | 11 | **1** |
| **Total** | **108** | **86** | **22** |

---

## Remaining Issues

### 🔴 BLOCKER 1 — FillEventBus stub is never active; real RC-8 module wins

This is the root cause of **19 of the 22 failures** (all fill-tracker, runtime, coordinator, and integration failures).

The package ships `src/risk/fill_event_bus.py` as a stub meant to replace the real RC-8 module. However the real RC-8 `fill_event_bus.py` already exists at that path and takes precedence. When tests run `from risk.fill_event_bus import FillEventBus`, they get the real implementation:

| | Real RC-8 FillEventBus | Stub FillEventBus |
|---|---|---|
| `subscribe` | `async def subscribe(name, callback) -> str` | `def subscribe(account_id, callback) -> None` |
| `unsubscribe` | `async def unsubscribe(subscriber_id) -> bool` | `def unsubscribe(account_id, callback) -> None` |
| `publish` | `async def publish(event) -> int` | `def publish(fill_event, account_id) -> None` |

This mismatch cascades into three distinct failure modes:

**Mode 1 — `subscribe` coroutine never awaited (affects all fill tracking and runtime):**

`StrategyFillTracker.subscribe()` calls `self._bus.subscribe(strategy_id, callback)` synchronously. Against the real async `subscribe`, this returns a coroutine that is never awaited, so the subscription is never registered. All subsequent fills are invisible to the tracker.

```
RuntimeWarning: coroutine 'FillEventBus.subscribe' was never awaited
  fill_tracker.py:57: self._bus.subscribe(self._config.strategy_id, self._on_fill)
```

Failing tests: all 6 fill-tracker tracking tests, all 10 runtime tests that depend on fills.

**Mode 2 — `publish` called with 2 positional args against a 1-arg real method:**

Tests updated in the delta review now call `fill_event_bus.publish(fill, "test_strat")` — 2 args. The real `publish(self, event)` accepts only 1. Result: `TypeError: FillEventBus.publish() takes 2 positional arguments but 3 were given`.

Failing tests: `test_buy_fill_creates_long_position`, `test_sell_fill_creates_short_position`, `test_multiple_buys_aggregate`, `test_callback_invoked`.

**Mode 3 — `unsubscribe` called with 2 args against a 1-arg real method:**

`StrategyFillTracker.unsubscribe()` calls `self._bus.unsubscribe(account_id, callback)` — 2 args. Real `unsubscribe(subscriber_id)` takes 1. Result: `TypeError: FillEventBus.unsubscribe() takes 2 positional arguments but 3 were given`.

Failing test: `test_unsubscribe_stops_tracking`.

**Also affected — 3 coordinator tests:** `StrategyRuntime._fill_tracker.subscribe()` is called inside `runtime.start()`. Because the subscription silently fails, runtimes that depend on fill routing fail their assertions.

**Fix — two options (choose one):**

*Option A (preferred):* Do not ship a `fill_event_bus.py` stub at all. Instead, adapt `StrategyFillTracker` to the real RC-8 `FillEventBus` API:
```python
# fill_tracker.py
async def subscribe(self, callback=None) -> None:
    self._callback = callback
    self._subscriber_id = await self._bus.subscribe(
        self._config.strategy_id, self._on_fill
    )

async def unsubscribe(self) -> None:
    if self._subscriber_id:
        await self._bus.unsubscribe(self._subscriber_id)
```
And update `StrategyRuntime.start()` to `await self._fill_tracker.subscribe(self._on_fill)`.

*Option B:* Keep the stub but install it into a test-only namespace that does not overwrite the real module. Use a pytest fixture or conftest import shim to inject the stub FillEventBus into tests only.

---

### 🔴 BLOCKER 2 — `test_golden_cross_signal` still fails (test data too short for default window)

`SmaCrossoverStrategy.__init__` sets `self._long_period = 20` by default. `validate_config` was correctly fixed to apply config parameters. However the test's `base_config` fixture has no `parameters` dict, so defaults (short=5, long=20) are preserved after `validate_config`. The test then feeds only 10 bars:

```python
prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]  # 10 bars
```

The long window requires 20 bars before any SMA can be computed. With 10 bars it never fills, so `on_bar` always returns `None`. The assertion `assert signal is not None` fails.

The fix to `validate_config` was correct but the test was not updated to match. 

**Fix — update `base_config` in `test_golden_cross_signal` and `test_death_cross_signal` to use short periods:**

```python
# In test_sma_crossover.py — tests that check crossover signals
config = StrategyConfig(
    strategy_id="sma_test",
    strategy_type="sma_crossover",
    name="SMA Test",
    instrument_tokens=["RELIANCE"],
    parameters={"short_period": 2, "long_period": 3},  # ← add this
)
strat = SmaCrossoverStrategy()
strat.validate_config(config)  # applies short=2, long=3
```

With `short_period=2, long_period=3`, a crossover can be detected in as few as 4 bars.

---

### 🟡 REMAINING — `test_full_pipeline_sma_strategy` fails and `_subscribers` still accessed privately

The integration test accesses `_subscribers` directly (not fixed from delta issue 9):

```python
subs = base_coordinator._market_data._subscribers.get("RELIANCE", [])
for callback in subs:
    await callback(bar)          # ← awaits a sync function → TypeError
```

`_on_market_data` is `def _on_market_data(self, data) -> None` (sync). `await callback(bar)` returns `None` and then `await None` raises `TypeError`. This is the proximate cause of the `test_full_pipeline_sma_strategy` failure.

**Fix:** Add `publish_bar` to `MarketDataService`:
```python
# market_data/service.py
async def publish_bar(self, instrument_token: str, bar) -> None:
    for callback in self._subscribers.get(instrument_token, []):
        callback(bar)   # sync callbacks: call, don't await
```

And replace the test loop:
```python
await base_coordinator._market_data.publish_bar("RELIANCE", bar)
```

---

## Summary of All Outstanding Fixes

| # | Severity | File(s) to change | Fix |
|---|---|---|---|
| 1a | 🔴 Blocker | `src/strategy/fill_tracker.py` | Make `subscribe()` and `unsubscribe()` async; await the real RC-8 FillEventBus calls |
| 1b | 🔴 Blocker | `src/strategy/runtime.py` | `await self._fill_tracker.subscribe(...)` in `start()` and `await self._fill_tracker.unsubscribe()` in `stop()` |
| 1c | 🔴 Blocker | `tests/unit/strategy/test_fill_tracker.py` | Update `publish(fill, "test_strat")` → `await fill_event_bus.publish(fill)` to match real API; or keep stub and fix the namespace |
| 1d | 🔴 Blocker | `src/risk/fill_event_bus.py` (stub) | Either remove the stub entirely (Option A) or move it to a test-only location so it doesn't conflict with the real module |
| 2 | 🔴 Blocker | `tests/unit/strategy/built_in/test_sma_crossover.py` | Add `parameters={"short_period": 2, "long_period": 3}` to `base_config` in crossover signal tests |
| 3 | 🟡 Moderate | `src/market_data/service.py` + `test_integration.py` | Add `publish_bar()` helper; replace `_subscribers` private access in integration test |

**Fixes 1a–2 are required before merge. Fix 3 (private access) is a design quality issue that should also be addressed in this pass.**

---

## What Is Working Well

- 62 tests pass cleanly with no flakiness (contracts, state machine, exceptions, signal router, context builder, most SMA tests, 9 coordinator tests, 2 integration tests)
- The `cancel_stray_tasks` autouse fixture correctly isolates async background tasks — no more hangs
- `StrategyStateSnapshot` ordering fix, `ConflictResolution`/`StrategyRuntimeError` exports, lock-outside-subscribe, fill ownership check, PortfolioSnapshot field comparison, and both signal quantity tests are all solid
- The SMA `validate_config` parameter-application pattern is the right design; just the test needs to use it
