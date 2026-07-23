---
name: RC-9 strategy engine
description: Durable decisions and constraints for the RC-9 strategy engine, Batches 9A–9D.
---

## Batch 9C frozen API (never modify)
- `StrategyPersistenceAdapter` — session always first arg
- `StrategyRecoveryManager.recover(session)` → `StrategyRecoveryResult`
- All three repositories (`StrategyRepository`, `StrategySignalRepository`, `StrategyStateRepository`) — never commit/rollback/close
- `StrategyConfigRecord`, `StrategySignalRecord`, `StrategyStateSnapshotRecord` — frozen dataclasses

## Batch 9D frozen API
- `SessionContext(engine)` — only commit site in the strategy layer; repos/adapters/coordinator never commit
- `MetricsCollector` — `initialize/remove` sync; all `record_*` async; `get_metrics/get_all_metrics` sync snapshot
- `StrategyHealthMonitor` — derived from MetricsCollector; default thresholds 3/5 consecutive errors, 500/2000 ms latency
- `FaultIsolator` — sticky isolation until `reset_isolation()`; `record_error()` returns `FaultAction` enum
- `ShutdownResult` — frozen dataclass from `coordinator.shutdown(timeout_seconds=30)`

## Key architectural rules
- `SessionContext.__aexit__` is the ONLY site that calls session.commit()/rollback()/close()
- `runtime._emit_signal()` awaits `_persist_signal_safe()` BEFORE the routing callback (write-before-route)
- State snapshots are `asyncio.create_task(_push_state_snapshot_safe())` — fire-and-forget, never block bar processing
- `coordinator.recover()` wraps persistence in `_PersistenceCapture` so `list_non_terminal_strategies` is called exactly once
- `account_id` is persisted as `None` for all 9C/9D records — future batch to wire from session context
- `StrategyCoordinator(mds, feb, cb, sr)` — existing 4-arg form must remain valid forever
- `StrategyRuntime(config, strategy, cb, mds, feb)` — existing 5-arg form must remain valid forever

## Import rules
- `strategy.persistence` and `strategy.recovery` are NOT re-exported from `strategy/__init__.py` (circular import via `src.strategy.persistence`). Import directly from their submodules.
- `SessionContext` IS safe to import at top-level from any strategy submodule (no circular risk)
- `FaultAction` in runtime.py is imported lazily inside `_record_error_and_maybe_isolate` to avoid circular at module init

## Pre-existing failures (not introduced by RC-9)
- `tests/unit/test_kill_switch.py::TestKillSwitch::test_history` — KillSwitch singleton state leak
- 22 integration errors — bcrypt password >72 bytes in conftest
