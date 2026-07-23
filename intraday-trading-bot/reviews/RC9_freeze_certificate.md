# RC-9 — Freeze Certificate

**Tag:** `RC-9-complete`  
**Date:** 2026-07-23  
**Status:** FROZEN ❄️

---

## What RC-9 covers

RC-9 is the complete strategy engine for the intraday trading bot, spanning four implementation batches and one persistence/recovery sub-batch:

| Batch | Scope | Tests |
|-------|-------|-------|
| 9A | Strategy contracts, state machine, coordinator skeleton | 44 |
| 9B | StrategyRuntime, fill tracker, SMA crossover strategy, FillEventBus | 62 |
| 9C | Persistence adapter, recovery manager, all three repositories, Alembic models | 97 |
| 9D-A | SessionContext, runtime wiring (write-before-route), coordinator lifecycle persistence, recovery wiring | 35 |
| 9D-B | MetricsCollector, StrategyHealthMonitor, FaultIsolator, graceful shutdown | 54 |

**Total strategy-engine tests: 292**  
**Full unit suite at freeze: 445 passed, 1 pre-existing failure (kill-switch singleton leak, unrelated to RC-9)**

---

## Frozen API surface

### Contracts (`src/strategy/contracts.py`)
`Signal`, `SignalType`, `StrategyConfig`, `StrategyState`, `StrategyLifecycleEvent` — immutable.

### Session management
```python
SessionContext(engine: AsyncEngine)
async with SessionContext(engine) as session:
    ...  # commit on success, rollback + close on exception
```
`SessionContext.__aexit__` is the **only** site in the strategy layer that calls `session.commit()`, `session.rollback()`, or `session.close()`. This constraint must be enforced in all future batches.

### Persistence (Batch 9C — frozen)
- `StrategyPersistenceAdapter` — session always first positional arg
- `StrategySignalRepository`, `StrategyRepository`, `StrategyStateRepository` — never commit/rollback/close
- `StrategyConfigRecord`, `StrategySignalRecord`, `StrategyStateSnapshotRecord` — frozen dataclasses
- `StrategyRecoveryManager.recover(session)` → `StrategyRecoveryResult`

### Coordinator & Runtime (Batch 9D — frozen)
- `StrategyCoordinator(mds, feb, cb, sr)` — 4-arg form is permanent; new deps are optional kwargs
- `StrategyRuntime(config, strategy, cb, mds, feb)` — 5-arg form is permanent; new deps are optional kwargs
- `coordinator.shutdown(timeout_seconds=30)` → `ShutdownResult`
- `coordinator.get_health(strategy_id)` → `HealthReport`
- `coordinator.get_metrics(strategy_id)` → `StrategyMetrics`

### Metrics & health
- `MetricsCollector` — `initialize/remove` sync; all `record_*` async; no external deps
- `StrategyHealthMonitor` — derived from `MetricsCollector`; default thresholds: ≥3/≥5 consecutive errors, ≥500ms/≥2000ms latency (constructor-overridable)
- `FaultIsolator` — sticky isolation until explicit `reset_isolation()`; `record_error()` → `FaultAction` enum

---

## Known deferred items (not defects)

| Item | Deferred to |
|------|------------|
| `account_id` always `None` in persistence records | Batch 10+ (session context wiring) |
| `strategy.persistence` / `strategy.recovery` not re-exported from `__init__` | Permanent — circular import; callers import directly |
| `_NullStrategyFactory` placeholder in `coordinator.recover()` | Batch 10+ (real factory registry) |
| Health/metrics HTTP endpoints (`GET /api/strategies/health`) | Batch 10+ |

---

## Files frozen under RC-9

```
src/strategy/__init__.py
src/strategy/contracts.py
src/strategy/state_machine.py
src/strategy/context_builder.py
src/strategy/fill_tracker.py
src/strategy/signal_router.py
src/strategy/coordinator.py
src/strategy/runtime.py
src/strategy/session_context.py
src/strategy/persistence.py
src/strategy/recovery.py
src/strategy/metrics.py
src/strategy/health.py
src/strategy/fault_isolation.py
src/strategy/strategies/sma_crossover.py
src/database/models.py            (strategy tables)
src/database/repositories/strategy.py
src/database/repositories/strategy_signal.py
src/database/repositories/strategy_state.py
alembic/versions/0003_strategy_tables.py
```

Modifications to frozen files in future batches require:
1. A written justification in the batch closure report
2. Confirmation that all 292 strategy-engine tests still pass
3. A new freeze certificate entry

---

## Review artifacts

| Document | Location |
|----------|----------|
| Batch 9A/B final audit | `reviews/Batch9AB_final_audit.md` |
| Batch 9C audit (v2) | `reviews/Batch9C_v2_audit.md` |
| Batch 9C final audit | `reviews/Batch9C_final_audit.md` |
| Batch 9D closure | `reviews/Batch9D_closure.md` |
| This document | `reviews/RC9_freeze_certificate.md` |
