---
name: RC-9 Strategy Engine
description: Key fixes and patterns discovered integrating Batch 9A/B (strategy engine). Critical for any future work touching coordinator, runtime, or FillEventBus integration.
---

## Coordinator deregister deadlock

`deregister()` acquired the per-strategy lock then called `self.stop()` which tried to acquire the same lock — asyncio.Lock is not reentrant, so it deadlocked. Fix: inline the runtime stop logic inside `deregister()` instead of calling `self.stop()`.

**Why:** Any method that holds a per-strategy lock must never call another public method that acquires the same lock.

**How to apply:** If adding new coordinator methods that need to stop/pause/resume while holding a lock, inline the runtime call directly.

## FillEventBus async API contract

RC-8 FillEventBus uses async API: `await bus.subscribe(name, callback) → str` (returns subscriber_id), `await bus.publish(fill) → int`, `await bus.unsubscribe(subscriber_id) → bool`. Tests that call `bus.publish(fill)` without `await` silently create unawaited coroutines.

**Why:** The RC-8 FillEventBus was async from the start; the Batch 9 package was written against a sync stub.

**How to apply:** All FillEventBus call sites must be awaited. Store the subscriber_id returned by subscribe() to use with unsubscribe().

## coordinator._on_signal must schedule a task

`_on_signal` is a sync callback (called from runtime's `_emit_signal`). `SignalRouter.route_signal()` is async. Fix: `asyncio.create_task(self._signal_router.route_signal(signal, signal.strategy_id, config))`. A no-op `pass` means signals never reach the execution callback.

**Why:** The callback boundary between runtime (sync callback) and router (async) requires task scheduling.

## Error propagation: on_bar queues, errors happen in background

`runtime.on_bar(bar)` only queues the bar and returns immediately. Processing happens in `_run_loop` as a background task. Tests using `pytest.raises(StrategyRuntimeError)` around `await runtime.on_bar(bar)` will always fail — the exception is never raised on the calling side. Correct pattern: `await runtime.on_bar(bar); await asyncio.sleep(0.1); assert runtime.lifecycle_state == ERROR`.

## coordinator._final_states for stopped strategy visibility

After `stop()` or `emergency_stop_all()`, the runtime is deleted from `_runtimes`. Without a `_final_states` dict, `get_strategy()` returns REGISTERED for a stopped strategy (falls through to the default). Fix: save `runtime.state` to `_final_states[strategy_id]` before deleting from `_runtimes`, and check `_final_states` in `get_strategy()`.

## SMA crossover golden cross price series

For a golden cross test with short=3, long=5, use a falling-then-rising series (e.g. `[110, 108, 106, 104, 102, 100, 101, 103, 106, 110]`). A monotonically rising series means short SMA is already above long SMA on bar 1, so the crossover condition (`prev_short <= prev_long AND short > long`) never fires. The death cross test uses a monotonically falling series, which works correctly.
