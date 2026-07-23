# Batch 9D — Implementation Plan
**Project:** Intraday Trading Bot — RC-9 Branch  
**Batch:** 9D — Strategy Coordinator & Runtime Wiring  
**Depends on:** Batch 9C (Strategy Persistence & Recovery Layer) — ✅ MERGED  
**Status:** Awaiting approval

---

## Overview

Batch 9C delivered the persistence layer in isolation: models, repositories, a
persistence adapter, and a recovery manager — none of them wired into the
running system. Batch 9D wires that layer into the live strategy coordinator
and runtime so that every lifecycle transition, every emitted signal, and every
state snapshot is durably recorded, and so that crash recovery is invoked
automatically on coordinator startup.

---

## Objectives

| # | Objective |
|---|---|
| 1 | **Coordinator durability** — `StrategyCoordinator` calls `StrategyPersistenceAdapter` on every lifecycle state transition (register, start, pause, resume, stop, deregister). |
| 2 | **Signal persistence** — signals emitted by `StrategyRuntime` are persisted via the adapter before being handed to the `FillEventBus`. |
| 3 | **Fill-back persistence** — when a fill arrives, the signal routing status is updated to `ROUTED` in the database. |
| 4 | **State snapshot persistence** — `StrategyRuntime` pushes a `StrategyStateSnapshotRecord` to the adapter after every bar, or on a configurable interval. |
| 5 | **Startup recovery** — `StrategyCoordinator.__init__` (or an explicit `coordinator.recover()` call at application startup) invokes `StrategyRecoveryManager` and re-registers any non-terminal strategies found in the database. |
| 6 | **Session scoping** — all database writes in a single coordinator operation share one `AsyncSession`, opened and committed by the coordinator (not the repositories). |
| 7 | **Test coverage** — a new `tests/unit/strategy/test_batch9d.py` suite covering all wiring points with mocked adapters; no real database connections. |

---

## Files to Be Created or Modified

| File | Action | Reason |
|---|---|---|
| `src/strategy/session_context.py` | **Created** | Thin async context-manager that opens an `AsyncSession`, passes it to all adapter calls within a coordinator operation, and commits or rolls back. Keeps transaction ownership out of the coordinator itself and preserves the no-commit-in-repository guarantee from Batch 9C. |
| `src/strategy/coordinator.py` | **Modified** | Inject `StrategyPersistenceAdapter`; add persistence calls on all state transitions; call `StrategyRecoveryManager` at startup. |
| `src/strategy/runtime.py` | **Modified** | Inject `StrategyPersistenceAdapter`; persist signals before routing; push state snapshots on bar completion. |
| `src/strategy/fill_event_bus.py` | **Modified** | After dispatching a fill, call `adapter.update_signal_routing_status(signal_id, ROUTED)` within the same session context. |
| `src/strategy/__init__.py` | **Modified** (minor) | Export `SessionContext` alongside existing exports. |
| `tests/unit/strategy/test_batch9d.py` | **Created** | ~80–100 tests covering all wiring points (see Test Plan below). |

---

## Architecture

### Session Ownership

The coordinator is the transaction owner for coordinator-scoped operations.
The rule from Batch 9C is preserved: repositories and adapters **never** call
`commit`, `rollback`, or `close`. The new `SessionContext` class encapsulates
the open / commit / rollback pattern and is called exclusively by the
coordinator:

```python
# Coordinator usage pattern
async def register_strategy(self, config: StrategyConfig) -> None:
    async with SessionContext(self._engine) as session:
        await self._adapter.upsert_strategy(config, session=session)
        # commit happens automatically in __aexit__
```

For runtime bar-level writes (high frequency), a separate short-lived session
is opened per bar rather than per coordinator operation, to avoid holding a
long-lived connection across market hours.

### Signal Write-Before-Route Ordering

Signals must be persisted before being dispatched to the `FillEventBus`. This
guarantees that a fill-back update can never arrive for a signal that does not
yet exist in the database.

```
StrategyRuntime.on_bar()
  └─ signal = strategy.on_bar(bar, context)
  └─ async with SessionContext(engine) as session:
       await adapter.upsert_signal(signal_record, session=session)
       # commit — signal is now durable
  └─ await fill_event_bus.dispatch(signal)   ← only after commit
```

### State Snapshot Cadence

Snapshots are fire-and-forget (`asyncio.create_task`) with a configurable
interval (default: every bar). Snapshot failures are logged at WARNING level
and do not interrupt bar processing.

### Startup Recovery Flow

```
application startup
  └─ coordinator = StrategyCoordinator(engine=engine, adapter=adapter)
  └─ result = await coordinator.recover()
       └─ StrategyRecoveryManager(adapter).recover(session)
            └─ for each non-terminal strategy in DB:
                 re-register if not already registered
                 collect pending signals for re-routing
       └─ log result.strategies_recovered, result.signals_restored, result.errors
```

Recovery errors are non-fatal: a failed re-registration is appended to
`result.errors` and the loop continues to the next strategy.

---

## Invariants Carried Forward from Batch 9C

| Invariant | Enforcement in 9D |
|---|---|
| Repositories never call `commit`/`rollback`/`close` | `SessionContext.__aexit__` is the only commit site; verified by AST scan test |
| `StrategyRecoveryResult` remains `frozen=True` | Not modified in 9D |
| `list_all_signals()` used in recovery (NF1 fix) | `StrategyRecoveryManager` not modified; wiring calls it unchanged |
| `Base.metadata.create_all` not used in tests | Batch 9D fixture reuses Batch 9C scoped-table pattern |
| Signal persistence before routing | Enforced by ordering in `runtime.py`; verified by `TestRuntimeSignalPersistence` |

---

## Test Plan

| Test class | Tests | Coverage |
|---|---|---|
| `TestSessionContext` | ~8 | Commit on clean exit; rollback on exception; session passed through to adapter; no commit inside adapter or repo |
| `TestCoordinatorPersistence` | ~18 | `upsert_strategy` called on register / start / pause / resume / stop / deregister; correct `lifecycle_state` value passed each time; session opened and closed per operation |
| `TestCoordinatorRecovery` | ~12 | `StrategyRecoveryManager.recover()` called on startup; returned entries re-registered; already-registered strategies skipped; errors logged but non-fatal; result fields correct |
| `TestRuntimeSignalPersistence` | ~15 | Signal `upsert_signal` called before `FillEventBus.dispatch`; correct `StrategySignalRecord` fields (symbol, direction, qty, prices, timestamp, strategy_uuid); routing_status defaults to `PENDING` |
| `TestFillBackPersistence` | ~10 | Fill arrival triggers `update_routing_status(signal_id, ROUTED)`; called once per fill; not called if signal not found |
| `TestStateSnapshotCadence` | ~12 | Snapshot written after each bar; emitted / routed / rejected / fill counts match runtime tallies; configurable interval respected; snapshot failure does not raise |
| `TestNoCommitInCoordinator` | ~3 | AST scan confirms coordinator body does not call `session.commit()` directly; only `SessionContext.__aexit__` does; same check for runtime and fill_event_bus |

**Target:** ≥ 78 tests, ≥ 95% pass rate on first run.  
**Fixture pattern:** Mocked `StrategyPersistenceAdapter` (no real DB); `AsyncMock` for all async adapter methods; `MagicMock` engine passed to `SessionContext`.

---

## Implementation Sequence

```
Step 1 — src/strategy/session_context.py          (no upstream deps — implement first)
Step 2 — src/strategy/coordinator.py wiring       (depends on session_context + adapter)
Step 3 — src/strategy/runtime.py wiring           (depends on session_context + adapter)
Step 4 — src/strategy/fill_event_bus.py wiring    (depends on adapter + session_context)
Step 5 — src/strategy/__init__.py export update   (trivial — after step 1)
Step 6 — tests/unit/strategy/test_batch9d.py      (covers steps 1–4)
Step 7 — Full regression run                      (confirm no new failures)
```

Steps 2, 3, and 4 are independent of each other and can be implemented in
parallel once Step 1 is complete.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Bar-level snapshot writes add latency to the hot path | Snapshot writes are `asyncio.create_task` (fire-and-forget) with a configurable interval; failures are logged at WARNING, never raised |
| Coordinator deadlock on deregister (Batch 9A/9B issue) | `SessionContext` is short-lived per operation; does not hold a session across the deregister wait loop |
| Recovery re-registration collides with already-running strategies | `recover()` deduplicates via `strategies_recovered` set; coordinator checks before re-registering |
| Signal routing race: fill arrives before signal persisted | Write-before-route ordering enforced in `runtime.py`; commit completes before `FillEventBus.dispatch` is called |
| Integration test environment errors (pre-existing bcrypt) contaminating results | Batch 9D tests are unit-level with mocked adapters; no integration test files are modified |

---

## Definition of Done

- [ ] All 6 files created or modified as specified above
- [ ] `SessionContext` opens, commits, and rolls back correctly under test
- [ ] `StrategyCoordinator` persists every lifecycle transition
- [ ] `StrategyCoordinator.recover()` re-registers non-terminal strategies from DB
- [ ] `StrategyRuntime` persists signals before routing
- [ ] `FillEventBus` updates routing status to `ROUTED` on fill
- [ ] `StrategyRuntime` pushes state snapshots after each bar
- [ ] No repository or adapter calls `commit`/`rollback`/`close` (AST-verified)
- [ ] Batch 9D test suite: ≥ 78 tests, all passing
- [ ] Full regression run: zero new failures vs. Batch 9C baseline (260 passing)
- [ ] Batch 9D closure report produced in `intraday-trading-bot/reviews/`

---

*Plan authored: 2026-07-22. Awaiting approval to begin implementation.*
