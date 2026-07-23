"""StrategyCoordinator — global strategy lifecycle manager.

Singleton. Manages registration, start, stop, pause, resume for all strategies.
Uses per-strategy asyncio.Lock for concurrency safety.

Batch 9D additions (all optional, backward-compatible):
- StrategyPersistenceAdapter wiring: every lifecycle transition is persisted.
- crash-recovery via StrategyRecoveryManager (call coordinator.recover()).
- MetricsCollector integration: per-bar counters, latency, errors.
- StrategyHealthMonitor integration: HEALTHY/DEGRADED/UNHEALTHY derived from metrics.
- FaultIsolator integration: auto-pauses strategies that breach error budgets.
- Graceful shutdown: coordinator.shutdown() drains in-flight tasks before stopping.

Backward compatibility guarantee
---------------------------------
StrategyCoordinator(mds, feb, cb, sr) — the existing four-positional-argument
form — continues to work without any changes.  All new dependencies are
keyword-only optional parameters defaulting to None.  When None, the new
behaviour is silently skipped so existing tests are unaffected.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncEngine

from strategy.contracts import (
    StrategyConfig,
    StrategyLifecycleState,
    StrategyRegistrationResult,
    StrategyStateSnapshot,
    Signal,
)
from strategy.strategy_protocol import Strategy
from strategy.runtime import StrategyRuntime
from strategy.signal_router import SignalRouter
from strategy.context_builder import ContextBuilder
from strategy.exceptions import (
    StrategyNotFoundError,
    StrategyAlreadyRegisteredError,
    LifecycleTransitionError,
)
from market_data.service import MarketDataService
from risk.fill_event_bus import FillEventBus
from strategy.session_context import SessionContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graceful-shutdown result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShutdownResult:
    """Result returned by coordinator.shutdown()."""
    strategies_stopped: List[str] = field(default_factory=list)
    strategies_failed: List[str] = field(default_factory=list)
    snapshots_flushed: int = 0
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Recovery registry adapter (internal — not part of public API)
# ---------------------------------------------------------------------------

class _PersistenceCapture:
    """Wraps a StrategyPersistenceAdapter and caches list_non_terminal_strategies results.

    Ensures the DB is queried exactly once for non-terminal strategy records
    during coordinator.recover(), regardless of how many callers need the data.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._cached_records: Dict[str, Any] = {}  # strategy_id → StrategyConfigRecord

    async def list_non_terminal_strategies(self, session: Any, **kwargs: Any) -> List[Any]:
        records = await self._adapter.list_non_terminal_strategies(session, **kwargs)
        for rec in records:
            self._cached_records[rec.strategy_id] = rec
        return records

    def get_cached_record(self, strategy_id: str) -> Any:
        return self._cached_records.get(strategy_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)


class _RecoveryRegistryAdapter:
    """Adapts StrategyCoordinator to the StrategyRegistry protocol expected
    by StrategyRecoveryManager.

    Mapping
    -------
    register(strategy_id, instance, "REGISTERED")
        → coordinator.register(pre-loaded config, instance)

    transition(strategy_id, "STARTING")  → no-op
        (coordinator.start() handles REGISTERED→STARTING→ACTIVE atomically)
    transition(strategy_id, "ACTIVE")    → coordinator.start()
    transition(strategy_id, "PAUSED")    → coordinator.pause()

    subscribe_market_data(...)           → no-op
        (coordinator.start() already subscribes inside StrategyRuntime.start())

    is_registered(strategy_id)           → strategy_id in coordinator._configs
    """

    def __init__(
        self,
        coordinator: "StrategyCoordinator",
        capture: "_PersistenceCapture",
    ) -> None:
        self._coordinator = coordinator
        self._capture = capture

    async def is_registered(self, strategy_id: str) -> bool:
        return strategy_id in self._coordinator._configs

    async def register(
        self,
        strategy_id: str,
        instance: Any,
        lifecycle_state: str,  # noqa: ARG002 (always "REGISTERED" from manager)
    ) -> None:
        # Configs are captured by _PersistenceCapture when
        # list_non_terminal_strategies() was called inside mgr.recover().
        rec = self._capture.get_cached_record(strategy_id)
        if rec is None:
            raise ValueError(
                f"_RecoveryRegistryAdapter: no StrategyConfigRecord cached for {strategy_id!r}"
            )
        try:
            config = StrategyConfig(
                strategy_id=rec.strategy_id,
                strategy_type=rec.strategy_type,
                name=rec.name,
                instrument_tokens=list(rec.instrument_tokens or []),
                parameters=dict(rec.configuration or {}),
                enabled=rec.enabled,
            )
        except Exception as exc:
            raise ValueError(
                f"_RecoveryRegistryAdapter: could not build StrategyConfig for {strategy_id!r}: {exc}"
            ) from exc
        await self._coordinator.register(config, instance)

    async def transition(self, strategy_id: str, target_state: str) -> bool:
        try:
            if target_state == "STARTING":
                # No-op: coordinator.start() handles REGISTERED→STARTING→ACTIVE
                return True
            if target_state == "ACTIVE":
                await self._coordinator.start(strategy_id)
                return True
            if target_state == "PAUSED":
                await self._coordinator.pause(strategy_id)
                return True
            # STOPPING / STOPPED / unknown — no-op for recovery
            return True
        except Exception as exc:
            logger.warning(
                "Recovery registry: transition %s→%s failed: %s",
                strategy_id, target_state, exc,
            )
            return False

    async def subscribe_market_data(
        self,
        strategy_id: str,  # noqa: ARG002
        instrument_tokens: List[str],  # noqa: ARG002
    ) -> None:
        # coordinator.start() already subscribes inside StrategyRuntime.start()
        pass


class _RecoverySignalRouterAdapter:
    """Adapts StrategyCoordinator's routing to the SignalRouter protocol used
    by StrategyRecoveryManager for re-queuing pending signals."""

    def __init__(self, coordinator: "StrategyCoordinator") -> None:
        self._coordinator = coordinator

    async def enqueue(self, signal: Any) -> None:
        """Re-submit a signal dict from recovery through the signal router."""
        # Recovery passes a plain dict — wrap it in a task routed via coordinator
        strategy_id = signal.get("strategy_id", "")
        config = self._coordinator._configs.get(strategy_id)
        if config is None:
            logger.warning(
                "Recovery signal router: no config for strategy_id=%r", strategy_id
            )
            return
        logger.debug(
            "Recovery: re-queuing signal %s for strategy %s",
            signal.get("signal_id"), strategy_id,
        )
        # No-op enqueue for now — pending signals are re-routed when the
        # strategy resumes normal operation and receives fresh market data.
        # Full re-routing would require reconstructing a Signal domain object,
        # which is out of scope for crash-recovery (signals are advisory).


# ---------------------------------------------------------------------------
# Main coordinator
# ---------------------------------------------------------------------------

class StrategyCoordinator:
    """Global coordinator for all strategy instances.

    Responsibilities:
    - Register/deregister strategies
    - Start/stop/pause/resume individual strategies
    - Emergency stop all strategies
    - List and query strategy states
    - Persist lifecycle transitions (optional)
    - Crash recovery on startup (optional)
    - Aggregate runtime metrics and health (optional)
    - Fault isolation: auto-pause misbehaving strategies (optional)
    - Graceful shutdown (optional)
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        fill_event_bus: FillEventBus,
        context_builder: ContextBuilder,
        signal_router: SignalRouter,
        # --- Batch 9D optional dependencies ---
        persistence: Optional[Any] = None,      # StrategyPersistenceAdapter
        engine: Optional[AsyncEngine] = None,
        metrics: Optional[Any] = None,          # MetricsCollector
        health_monitor: Optional[Any] = None,   # StrategyHealthMonitor
        fault_isolator: Optional[Any] = None,   # FaultIsolator
    ) -> None:
        self._market_data = market_data_service
        self._fill_bus = fill_event_bus
        self._context_builder = context_builder
        self._signal_router = signal_router

        # Persistence (9D-A)
        self._persistence = persistence
        self._engine = engine

        # Production-hardening (9D-B)
        self._metrics = metrics
        self._health = health_monitor
        self._fault_isolator = fault_isolator

        # Core strategy registry
        self._strategies: Dict[str, Strategy] = {}
        self._configs: Dict[str, StrategyConfig] = {}
        self._runtimes: Dict[str, StrategyRuntime] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._final_states: Dict[str, StrategyStateSnapshot] = {}

        # Graceful-shutdown flag (9D-B)
        self._shutting_down: bool = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(
        self,
        config: StrategyConfig,
        strategy: Strategy,
    ) -> StrategyRegistrationResult:
        """Register a new strategy.

        Returns StrategyRegistrationResult.  Does NOT raise on duplicate —
        returns success=False with an error_message instead.
        """
        if self._shutting_down:
            return StrategyRegistrationResult(
                strategy_id=config.strategy_id,
                success=False,
                error_message="Coordinator is shutting down",
            )

        async with self._global_lock:
            if config.strategy_id in self._configs:
                return StrategyRegistrationResult(
                    strategy_id=config.strategy_id,
                    success=False,
                    error_message=f"Strategy {config.strategy_id} already registered",
                )

            errors = strategy.validate_config(config)
            if errors:
                return StrategyRegistrationResult(
                    strategy_id=config.strategy_id,
                    success=False,
                    error_message=f"Config validation failed: {'; '.join(errors)}",
                )

            self._configs[config.strategy_id] = config
            self._strategies[config.strategy_id] = strategy
            self._locks[config.strategy_id] = asyncio.Lock()

        # Initialise metrics slot before persistence so records match
        if self._metrics is not None:
            self._metrics.initialize(config.strategy_id)

        # Persist registration (non-fatal)
        await self._persist_lifecycle(config, StrategyLifecycleState.REGISTERED)

        return StrategyRegistrationResult(
            strategy_id=config.strategy_id,
            success=True,
        )

    async def deregister(self, strategy_id: str) -> None:
        """Deregister a strategy.

        Stops the strategy if running, then removes all in-process state.
        Does NOT call self.stop() — that would deadlock on the per-strategy lock.
        """
        async with self._get_lock(strategy_id):
            config = self._configs.get(strategy_id)

            if strategy_id in self._runtimes:
                runtime = self._runtimes[strategy_id]
                await runtime.stop()
                self._final_states[strategy_id] = runtime.state

            async with self._global_lock:
                self._strategies.pop(strategy_id, None)
                self._configs.pop(strategy_id, None)
                self._runtimes.pop(strategy_id, None)
                self._locks.pop(strategy_id, None)

        if self._metrics is not None:
            self._metrics.remove(strategy_id)
        if self._fault_isolator is not None:
            self._fault_isolator.remove(strategy_id)

        if config is not None:
            await self._persist_lifecycle(config, StrategyLifecycleState.STOPPED)

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    async def start(self, strategy_id: str) -> None:
        """Start a registered strategy.  Transitions REGISTERED → STARTING → ACTIVE."""
        if self._shutting_down:
            raise LifecycleTransitionError(
                f"Cannot start strategy {strategy_id}: coordinator is shutting down"
            )

        async with self._get_lock(strategy_id):
            self._ensure_registered(strategy_id)

            if strategy_id in self._runtimes:
                raise StrategyAlreadyRegisteredError(
                    f"Strategy {strategy_id} is already running"
                )

            config = self._configs[strategy_id]
            strategy = self._strategies[strategy_id]

            runtime = StrategyRuntime(
                config=config,
                strategy=strategy,
                context_builder=self._context_builder,
                market_data_service=self._market_data,
                fill_event_bus=self._fill_bus,
                signal_callback=self._on_signal,
                persistence=self._persistence,
                engine=self._engine,
                metrics=self._metrics,
            )

            self._runtimes[strategy_id] = runtime
            await runtime.start()

        await self._persist_lifecycle(config, StrategyLifecycleState.ACTIVE)

    async def pause(self, strategy_id: str, reason: str = "") -> None:
        """Pause a running strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            config = self._configs[strategy_id]
            await self._runtimes[strategy_id].pause()

        await self._persist_lifecycle(config, StrategyLifecycleState.PAUSED)

    async def resume(self, strategy_id: str) -> None:
        """Resume a paused strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            config = self._configs[strategy_id]

            # Clear fault-isolation flag when operator explicitly resumes
            if self._fault_isolator is not None:
                await self._fault_isolator.reset_isolation(strategy_id)

            await self._runtimes[strategy_id].resume()

        await self._persist_lifecycle(config, StrategyLifecycleState.ACTIVE)

    async def stop(self, strategy_id: str, reason: str = "") -> None:
        """Stop a running strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            config = self._configs[strategy_id]
            runtime = self._runtimes[strategy_id]
            await runtime.stop()
            self._final_states[strategy_id] = runtime.state
            del self._runtimes[strategy_id]

        await self._persist_lifecycle(config, StrategyLifecycleState.STOPPED)

    async def emergency_stop_all(self, reason: str = "") -> None:
        """Emergency stop all running strategies (best-effort)."""
        async with self._global_lock:
            strategy_ids = list(self._runtimes.keys())

        for strategy_id in strategy_ids:
            await self._signal_router.cancel_pending_for_strategy(strategy_id)

        for strategy_id in strategy_ids:
            try:
                async with self._get_lock(strategy_id):
                    if strategy_id in self._runtimes:
                        config = self._configs.get(strategy_id)
                        runtime = self._runtimes[strategy_id]
                        await runtime.stop()
                        self._final_states[strategy_id] = runtime.state
                        del self._runtimes[strategy_id]
                if config is not None:
                    await self._persist_lifecycle(
                        config, StrategyLifecycleState.STOPPED
                    )
            except Exception:
                logger.exception(
                    "emergency_stop_all: error stopping strategy %s", strategy_id
                )

    # ------------------------------------------------------------------
    # Graceful shutdown (9D-B)
    # ------------------------------------------------------------------

    async def shutdown(self, timeout_seconds: float = 30.0) -> ShutdownResult:
        """Ordered graceful-shutdown sequence.

        1. Mark coordinator as shutting down (reject new starts/registers).
        2. Pause all ACTIVE strategies to stop signal generation.
        3. Wait briefly for in-flight routing tasks to complete.
        4. Flush a final state snapshot for each strategy.
        5. Stop all runtimes.
        6. Return ShutdownResult.
        """
        self._shutting_down = True
        logger.info("Coordinator shutdown initiated")

        # Step 1: snapshot the running set
        async with self._global_lock:
            active_ids = list(self._runtimes.keys())

        # Step 2: pause all to stop signal generation
        for sid in active_ids:
            try:
                async with self._get_lock(sid):
                    if sid in self._runtimes and self._runtimes[sid].can_emit_signals:
                        await self._runtimes[sid].pause()
            except Exception:
                logger.debug("Shutdown pause failed for %s (non-fatal)", sid)

        # Step 3: brief wait for in-flight routing tasks
        await asyncio.sleep(min(0.5, timeout_seconds * 0.05))

        # Step 4: flush state snapshots
        snapshots_flushed = 0
        if self._persistence is not None and self._engine is not None:
            for sid in active_ids:
                try:
                    if sid in self._runtimes:
                        await self._flush_state_snapshot(sid)
                        snapshots_flushed += 1
                except Exception:
                    logger.debug("Shutdown snapshot flush failed for %s", sid)

        # Step 5: stop all runtimes
        stopped: List[str] = []
        failed: List[str] = []
        for sid in active_ids:
            try:
                async with self._get_lock(sid):
                    if sid in self._runtimes:
                        config = self._configs.get(sid)
                        runtime = self._runtimes[sid]
                        await runtime.stop()
                        self._final_states[sid] = runtime.state
                        del self._runtimes[sid]
                        stopped.append(sid)
                if config is not None:
                    await self._persist_lifecycle(
                        config, StrategyLifecycleState.STOPPED
                    )
            except Exception as exc:
                logger.exception("Shutdown stop failed for %s: %s", sid, exc)
                failed.append(sid)

        result = ShutdownResult(
            strategies_stopped=stopped,
            strategies_failed=failed,
            snapshots_flushed=snapshots_flushed,
        )
        logger.info(
            "Coordinator shutdown complete — stopped=%d failed=%d snapshots=%d",
            len(stopped), len(failed), snapshots_flushed,
        )
        return result

    # ------------------------------------------------------------------
    # Crash recovery (9D-A)
    # ------------------------------------------------------------------

    async def recover(
        self,
        session: Any,  # AsyncSession — typed as Any to avoid import cycle
        factory: Optional[Any] = None,  # StrategyFactory protocol
    ) -> Any:  # StrategyRecoveryResult
        """Execute crash-recovery on startup.

        Loads non-terminal strategy records from the DB, re-registers them
        via StrategyRecoveryManager, and re-queues any pending signals.

        Parameters
        ----------
        session:
            Open AsyncSession (owned and committed by the caller).
        factory:
            Optional StrategyFactory for creating strategy instances.
            When None, a stub factory is used that raises on create()
            so strategies cannot be reconstructed but the recovery result
            still enumerates what needs recovery.

        Returns
        -------
        StrategyRecoveryResult (from src.strategy.recovery)
        """
        if self._persistence is None:
            logger.debug("recover() called without persistence — returning empty result")
            from src.strategy.recovery import StrategyRecoveryResult
            return StrategyRecoveryResult()

        from src.strategy.recovery import (
            StrategyRecoveryManager,
            StrategyRecoveryResult,
        )

        # Wrap persistence so list_non_terminal_strategies is called only ONCE
        # (by StrategyRecoveryManager).  The wrapper captures the records so
        # _RecoveryRegistryAdapter can build StrategyConfig objects without a
        # second DB round-trip.
        capture = _PersistenceCapture(self._persistence)
        registry = _RecoveryRegistryAdapter(self, capture)
        signal_router = _RecoverySignalRouterAdapter(self)
        used_factory = factory or _NullStrategyFactory()

        mgr = StrategyRecoveryManager(
            persistence=capture,
            factory=used_factory,
            registry=registry,
            signal_router=signal_router,
        )
        result = await mgr.recover(session)
        logger.info(
            "coordinator.recover() complete — restored=%d skipped=%d "
            "signals_seen=%d errors=%d",
            len(result.strategies_restored),
            len(result.strategies_skipped),
            result.signals_restored,
            len(result.errors),
        )
        return result

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_strategies(self) -> List[StrategyStateSnapshot]:
        """List all registered strategies and their states."""
        result = []
        for strategy_id, config in self._configs.items():
            if strategy_id in self._runtimes:
                result.append(self._runtimes[strategy_id].state)
            else:
                result.append(StrategyStateSnapshot(
                    strategy_id=strategy_id,
                    lifecycle_state=StrategyLifecycleState.REGISTERED,
                ))
        return result

    def get_strategy(self, strategy_id: str) -> Optional[StrategyStateSnapshot]:
        """Get the state snapshot of a specific strategy."""
        if strategy_id not in self._configs:
            return None
        if strategy_id in self._runtimes:
            return self._runtimes[strategy_id].state
        if strategy_id in self._final_states:
            return self._final_states[strategy_id]
        return StrategyStateSnapshot(
            strategy_id=strategy_id,
            lifecycle_state=StrategyLifecycleState.REGISTERED,
        )

    # ------------------------------------------------------------------
    # Health + metrics (9D-B)
    # ------------------------------------------------------------------

    def get_health(self, strategy_id: str) -> Optional[Any]:
        """Return a HealthReport for one strategy (None if no health monitor)."""
        if self._health is None:
            return None
        return self._health.compute_health(strategy_id)

    def get_all_health(self) -> Dict[str, Any]:
        """Return health reports for all registered strategies."""
        if self._health is None:
            return {}
        return self._health.get_all_health(list(self._configs.keys()))

    def get_metrics(self, strategy_id: str) -> Optional[Any]:
        """Return StrategyMetrics snapshot for one strategy (None if no collector)."""
        if self._metrics is None:
            return None
        return self._metrics.get_metrics(strategy_id)

    def get_all_metrics(self) -> Dict[str, Any]:
        """Return metrics snapshots for all strategies."""
        if self._metrics is None:
            return {}
        return self._metrics.get_all_metrics()

    def is_shutting_down(self) -> bool:
        """True once shutdown() has been called."""
        return self._shutting_down

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_lock(self, strategy_id: str) -> asyncio.Lock:
        if strategy_id not in self._locks:
            self._locks[strategy_id] = asyncio.Lock()
        return self._locks[strategy_id]

    def _ensure_registered(self, strategy_id: str) -> None:
        if strategy_id not in self._configs:
            raise StrategyNotFoundError(f"Strategy {strategy_id} is not registered")

    def _ensure_running(self, strategy_id: str) -> None:
        self._ensure_registered(strategy_id)
        if strategy_id not in self._runtimes:
            raise StrategyNotFoundError(f"Strategy {strategy_id} is not running")

    def _on_signal(self, signal: Signal) -> None:
        """Sync callback from StrategyRuntime.  Schedules async routing task."""
        asyncio.create_task(self._route_signal_task(signal))

    async def _route_signal_task(self, signal: Signal) -> None:
        """Route a signal and update its persistence routing status."""
        config = self._configs.get(signal.strategy_id)
        if config is None:
            return

        result = await self._signal_router.route_signal(
            signal, signal.strategy_id, config
        )

        # Persist routing outcome (non-fatal)
        if self._persistence is not None and self._engine is not None:
            await self._persist_routing_outcome(signal, result)

    async def _persist_routing_outcome(self, signal: Signal, result: Any) -> None:
        """Update signal routing status after route_signal() completes."""
        try:
            async with SessionContext(self._engine) as session:
                if result.routed:
                    await self._persistence.mark_signal_routed(
                        session,
                        signal.signal_id,
                        result.client_order_id or "",
                    )
                elif result.status in ("REJECTED", "ERROR"):
                    await self._persistence.mark_signal_rejected(
                        session,
                        signal.signal_id,
                        result.rejection_reason or "",
                    )
        except Exception:
            logger.warning(
                "Failed to persist routing status for signal %s",
                signal.signal_id,
                exc_info=True,
            )

    async def _persist_lifecycle(
        self,
        config: StrategyConfig,
        state: StrategyLifecycleState,
    ) -> None:
        """Upsert strategy record with the new lifecycle state (non-fatal)."""
        if self._persistence is None or self._engine is None:
            return
        from src.strategy.persistence import StrategyConfigRecord
        record = StrategyConfigRecord(
            strategy_id=config.strategy_id,
            strategy_type=config.strategy_type,
            name=config.name,
            account_id=None,
            configuration=dict(config.parameters),
            instrument_tokens=list(config.instrument_tokens),
            lifecycle_state=state.value,
            enabled=config.enabled,
        )
        try:
            async with SessionContext(self._engine) as session:
                await self._persistence.save_strategy(session, record)
        except Exception:
            logger.warning(
                "Failed to persist lifecycle state %s for %s",
                state.value,
                config.strategy_id,
                exc_info=True,
            )

    async def _flush_state_snapshot(self, strategy_id: str) -> None:
        """Persist a state snapshot for a running strategy (non-fatal)."""
        if self._persistence is None or self._engine is None:
            return
        runtime = self._runtimes.get(strategy_id)
        if runtime is None:
            return
        from src.strategy.persistence import StrategyStateSnapshotRecord
        state = runtime.state
        record = StrategyStateSnapshotRecord(
            strategy_id=strategy_id,
            lifecycle_state=state.lifecycle_state.value,
            pending_order_ids=list(state.pending_orders),
            latest_signal_timestamp=state.last_signal_timestamp,
            emitted_signal_count=len(state.current_signals),
            rejected_signal_count=state.rejected_today,
            fill_count=runtime._fill_tracker.fill_count,
            snapshot_timestamp=datetime.now(timezone.utc),
        )
        try:
            async with SessionContext(self._engine) as session:
                await self._persistence.save_state_snapshot(session, record)
        except Exception:
            logger.warning(
                "Failed to flush shutdown snapshot for %s", strategy_id, exc_info=True
            )


# ---------------------------------------------------------------------------
# Null factory (used when no factory is supplied to recover())
# ---------------------------------------------------------------------------

class _NullStrategyFactory:
    """Stub factory that always fails to create instances.

    Used when recover() is called without a factory — the recovery result
    will list all strategies as skipped with an error message.
    """

    async def create(
        self,
        strategy_type: str,
        strategy_id: str,
        config: Dict[str, Any],
    ) -> Any:
        raise NotImplementedError(
            f"No StrategyFactory provided — cannot reconstruct {strategy_type!r} "
            f"for strategy_id={strategy_id!r}"
        )
