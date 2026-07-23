# Batch 9D — Closure Report

**Date:** 2026-07-23  
**Scope:** Strategy Coordinator & Runtime Wiring (9D-A) + Production Hardening (9D-B)  
**Status:** ✅ COMPLETE — 89/89 new tests pass, 0 regressions

---

## Summary

Batch 9D wires the Batch 9C persistence and recovery layer into the strategy engine's runtime and coordinator, adds production-hardening primitives (metrics, health monitoring, fault isolation), and implements graceful shutdown.

All implementations are backward-compatible.  The existing four-positional-argument form of `StrategyCoordinator(mds, feb, cb, sr)` and `StrategyRuntime(config, strategy, cb, mds, feb)` continue to work without modification.

---

## Files Produced / Modified

### New files

| File | Lines | Purpose |
|------|-------|---------|
| `src/strategy/session_context.py` | 60 | Async context manager: commit on clean exit, rollback + close on exception. Only commit site in the strategy layer. |
| `src/strategy/metrics.py` | 170 | `StrategyMetrics` frozen dataclass + `MetricsCollector`; tracks bars, ticks, signals, fills, errors, latency. Lock-protected. |
| `src/strategy/health.py` | 175 | `StrategyHealthStatus` enum + `HealthReport` frozen dataclass + `StrategyHealthMonitor`; derives health from `MetricsCollector`. |
| `src/strategy/fault_isolation.py` | 205 | `FaultAction` enum + `FaultBudget` + `FaultIsolator`; per-strategy consecutive-error and per-minute rate budgets; auto-pause on breach. |
| `tests/unit/strategy/test_batch9d_a.py` | 500+ | 35 tests: SessionContext, coordinator persistence wiring, recovery, runtime signal persistence, routing status, state snapshots. |
| `tests/unit/strategy/test_batch9d_b.py` | 500+ | 54 tests: metrics, health monitor, fault isolator, coordinator health/metrics integration, graceful shutdown. |

### Modified files

| File | Changes |
|------|---------|
| `src/strategy/coordinator.py` | Added: `SessionContext` top-level import, `_PersistenceCapture` wrapper, `_RecoveryRegistryAdapter` (now uses capture), `_NullStrategyFactory`, `ShutdownResult`, `persist_lifecycle`, `persist_routing_outcome`, `flush_state_snapshot`, `recover()`, `shutdown()`, `get_health()`, `get_metrics()`, `is_shutting_down()`. Optional kwargs: `persistence`, `engine`, `metrics`, `health_monitor`, `fault_isolator`. |
| `src/strategy/runtime.py` | Added: `SessionContext` top-level import, `_persist_signal_safe()` (write-before-route), `_push_state_snapshot_safe()` (fire-and-forget), `_record_error_and_maybe_isolate()`, metrics recording in `_process_bar`/`_process_tick`/`_process_fill`. Optional kwargs: `persistence`, `engine`, `metrics`, `fault_isolator`. |
| `src/strategy/__init__.py` | Added exports: `SessionContext`, `MetricsCollector`, `StrategyMetrics`, `StrategyHealthMonitor`, `StrategyHealthStatus`, `HealthReport`, `FaultIsolator`, `FaultAction`, `FaultBudget`, `FaultIsolationStatus`, `ShutdownResult`. Circular-import note for persistence/recovery (imported directly from submodule). |

---

## Design Decisions

### Backward compatibility
All new dependencies on coordinator and runtime are optional keyword arguments defaulting to `None`. When `None`, the new behaviour is skipped silently. No existing test required modification.

### Transaction ownership — SessionContext is the sole commit site
Repositories, adapters, coordinator, and runtime methods **never** call `session.commit()`, `session.rollback()`, or `session.close()`. Only `SessionContext.__aexit__` may do so. An AST audit test (`TestNoCommitInCoordinator`) enforces this.

### Write-before-route signal ordering
`StrategyRuntime._emit_signal()` awaits `_persist_signal_safe()` before invoking the signal routing callback. This guarantees the signal record exists in the DB before any fill-back update can reference it. If persistence fails, a warning is logged and routing continues — signals are never dropped due to a DB failure.

### State snapshots — fire-and-forget
`_push_state_snapshot_safe()` is scheduled as `asyncio.create_task(...)` after each bar. Snapshot failures are logged at DEBUG level and never interrupt bar processing.

### `_PersistenceCapture` — single DB round-trip during recovery
`coordinator.recover()` wraps the persistence adapter in a `_PersistenceCapture` that intercepts `list_non_terminal_strategies()` and caches results. `StrategyRecoveryManager` calls this method once; `_RecoveryRegistryAdapter.register()` reads from the cache to build `StrategyConfig` objects without a second query.

### Graceful shutdown sequence
`coordinator.shutdown(timeout_seconds=30)` follows a strict order:
1. Set `_shutting_down = True` (new registrations/starts rejected)
2. Pause all active runtimes (stop signal generation)
3. Brief drain wait (in-flight routing tasks)
4. Flush final state snapshots (best-effort)
5. Stop all runtimes
6. Return `ShutdownResult`

### Fault isolation — sticky, operator-cleared
Once a strategy breaches its error budget, it is `isolated` until `reset_isolation()` is explicitly called (e.g. by `coordinator.resume()`). Isolation is sticky: further `record_error()` calls return `PAUSE` immediately without re-evaluating the budget.

### Health thresholds (default)
| Condition | DEGRADED | UNHEALTHY |
|-----------|----------|-----------|
| Consecutive errors | ≥ 3 | ≥ 5 |
| Last bar latency | ≥ 500 ms | ≥ 2000 ms |

Thresholds are constructor-overridable for production tuning.

---

## Test Results

```
tests/unit/strategy/test_batch9d_a.py  35/35  PASS
tests/unit/strategy/test_batch9d_b.py  54/54  PASS
Full unit suite                       445/446 PASS
Pre-existing failures                 1 (test_kill_switch::test_history — singleton leak, unrelated to RC-9)
New failures introduced by Batch 9D   0
```

---

## Pre-existing Failures (not introduced by this batch)

| Test | Root cause |
|------|-----------|
| `tests/unit/test_kill_switch.py::TestKillSwitch::test_history` | KillSwitch singleton state leaks between tests due to module-level global. Predates RC-9. |

---

## Frozen API Surface (do not modify in subsequent batches)

### SessionContext
```python
SessionContext(engine: AsyncEngine)
async with SessionContext(engine) as session: ...  # commit on success, rollback on exception
```

### MetricsCollector
```python
mc.initialize(strategy_id)              # sync
mc.remove(strategy_id)                  # sync
await mc.record_bar(sid, latency_ms)
await mc.record_tick(sid)
await mc.record_signal(sid)
await mc.record_signal_rejected(sid)
await mc.record_fill(sid)
await mc.record_error(sid)
await mc.record_success(sid)
mc.get_metrics(sid) -> Optional[StrategyMetrics]
mc.get_all_metrics() -> Dict[str, StrategyMetrics]
```

### StrategyHealthMonitor
```python
monitor.compute_health(sid) -> HealthReport
monitor.get_all_health(sids) -> Dict[str, HealthReport]
monitor.is_healthy(sid) -> bool
monitor.any_unhealthy(sids) -> bool
```

### FaultIsolator
```python
fi.configure_budget(sid, budget: FaultBudget)
fi.remove(sid)
await fi.record_error(sid) -> FaultAction
await fi.record_success(sid)
await fi.reset_isolation(sid)          # operator action
fi.is_isolated(sid) -> bool
fi.get_isolation_reason(sid) -> Optional[str]
fi.get_status(sid) -> FaultIsolationStatus
```

### ShutdownResult (frozen dataclass)
```python
ShutdownResult(strategies_stopped, strategies_failed, snapshots_flushed, completed_at)
```

---

## Next Steps (Batch 9E candidates)

- Wire `account_id` from session context into `StrategyConfigRecord` and `StrategySignalRecord` (currently persisted as `None`)
- Health-check HTTP endpoint (`GET /api/strategies/health`) using `coordinator.get_all_health()`
- Metrics export to Prometheus or JSON summary endpoint
- Fault-isolator integration tests against real DB (integration test suite)
- `_NullStrategyFactory` replacement: wire a real `StrategyFactory` registry for recovery
