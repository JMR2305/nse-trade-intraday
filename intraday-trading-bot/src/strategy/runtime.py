"""StrategyRuntime — per-strategy async task.

Manages the lifecycle of one strategy instance: subscribes to market data,
invokes strategy callbacks, emits signals, and tracks fills.

Batch 9D additions (all optional, backward-compatible):
- Signal persistence: signals are written to DB before the routing callback
  fires (write-before-route ordering preserved).
- State snapshot persistence: a snapshot is pushed after each bar
  (fire-and-forget — failures are logged, never raised).
- MetricsCollector integration: per-bar latency, error counts, signal counts.
- FaultIsolator integration: auto-pause on budget breach.

RC-10B additions (all optional, keyword-only, backward-compatible):
- AI forecast gate: ForecastConfidenceGate applied between strategy.on_bar()
  and _emit_signal().  Only active when strategy.config.parameters contains
  "min_forecast_confidence" AND ai_forecast_gate is injected.
- FeatureGenerator: maintains per-instrument close/volume ring buffers;
  update_bar() called on every bar before strategy.on_bar().
- Prefetch lifecycle: asyncio.create_task() prefetch fires between
  build_context() and strategy.on_bar(); awaited with 2 s shield timeout;
  cancelled if the strategy emits no signal.
- ForecastBenchmarkRepository: fire-and-forget record_forecast() after gate
  approves a forecast.  Never raises to the caller.

Backward compatibility guarantee
---------------------------------
StrategyRuntime(config, strategy, context_builder, market_data_service,
                fill_event_bus) — the existing five-positional-argument form —
continues to work without any changes.  All Batch 9D and RC-10B dependencies
are keyword-only optional parameters defaulting to None.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncEngine

from strategy.contracts import (
    Signal,
    StrategyConfig,
    StrategyContext,
    StrategyLifecycleState,
    StrategyStateSnapshot,
    SignalAction,
)
from strategy.strategy_protocol import Strategy
from strategy.state_machine import StrategyStateMachine, TransitionResult
from strategy.context_builder import ContextBuilder
from strategy.fill_tracker import StrategyFillTracker
from strategy.exceptions import StrategyRuntimeError, StrategyError
from market_data.contracts import CompletedBar, Tick
from market_data.service import MarketDataService
from execution.fills import FillEvent
from risk.fill_event_bus import FillEventBus
from strategy.session_context import SessionContext

logger = logging.getLogger(__name__)


class StrategyRuntime:
    """Async runtime for a single strategy instance.

    Each runtime owns:
    - One StrategyStateMachine
    - One market data subscription
    - One StrategyFillTracker
    - A signal emission queue

    The runtime is deterministic: given the same sequence of bars/ticks,
    it produces the same sequence of signals (assuming the strategy is deterministic).
    """

    def __init__(
        self,
        config: StrategyConfig,
        strategy: Strategy,
        context_builder: ContextBuilder,
        market_data_service: MarketDataService,
        fill_event_bus: FillEventBus,
        signal_callback: Optional[Callable[[Signal], None]] = None,
        # --- Batch 9D optional dependencies ---
        persistence: Optional[Any] = None,   # StrategyPersistenceAdapter
        engine: Optional[AsyncEngine] = None,
        metrics: Optional[Any] = None,       # MetricsCollector
        fault_isolator: Optional[Any] = None,  # FaultIsolator
        # --- RC-10B optional AI forecast dependencies ---
        ai_forecast_gate: Optional[Any] = None,    # ForecastConfidenceGate
        feature_generator: Optional[Any] = None,   # FeatureGenerator
        benchmark_repo: Optional[Any] = None,      # ForecastBenchmarkRepository
    ):
        self._config = config
        self._strategy = strategy
        self._context_builder = context_builder
        self._market_data = market_data_service
        self._fill_bus = fill_event_bus
        self._signal_callback = signal_callback

        # Batch 9D
        self._persistence = persistence
        self._engine = engine
        self._metrics = metrics
        self._fault_isolator = fault_isolator

        # RC-10B AI forecast (all optional — None means feature disabled)
        self._ai_forecast_gate = ai_forecast_gate
        self._feature_generator = feature_generator
        self._benchmark_repo = benchmark_repo

        self._state_machine = StrategyStateMachine(StrategyLifecycleState.REGISTERED)
        self._fill_tracker = StrategyFillTracker(config, fill_event_bus)

        self._state = StrategyStateSnapshot(
            strategy_id=config.strategy_id,
            lifecycle_state=StrategyLifecycleState.REGISTERED,
        )

        self._bar_queue: asyncio.Queue[CompletedBar] = asyncio.Queue()
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._signal_queue: asyncio.Queue[Signal] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def strategy_id(self) -> str:
        return self._config.strategy_id

    @property
    def state(self) -> StrategyStateSnapshot:
        return self._state

    @property
    def lifecycle_state(self) -> StrategyLifecycleState:
        return self._state_machine.state

    @property
    def positions(self) -> Dict[str, object]:
        return self._fill_tracker.positions

    @property
    def can_emit_signals(self) -> bool:
        return self._state_machine.can_emit_signals

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> TransitionResult:
        """Start the strategy runtime — REGISTERED → STARTING → ACTIVE."""
        async with self._lock:
            result = await self._state_machine.transition(
                StrategyLifecycleState.STARTING,
                reason="runtime.start() called",
            )
            self._task = asyncio.create_task(self._run_loop())
            result = await self._state_machine.transition(
                StrategyLifecycleState.ACTIVE,
                reason="market data subscription confirmed",
            )
            self._state = StrategyStateSnapshot(
                strategy_id=self._config.strategy_id,
                lifecycle_state=StrategyLifecycleState.ACTIVE,
            )

        for token in self._config.instrument_tokens:
            await self._market_data.subscribe(token, self._on_market_data)
        await self._fill_tracker.subscribe(self._on_fill)

        return result

    async def pause(self) -> TransitionResult:
        """Pause — stops signal generation, maintains subscriptions."""
        async with self._lock:
            result = await self._state_machine.transition(
                StrategyLifecycleState.PAUSED,
                reason="runtime.pause() called",
            )
            self._state = StrategyStateSnapshot(
                strategy_id=self._config.strategy_id,
                lifecycle_state=StrategyLifecycleState.PAUSED,
                current_signals=list(self._state.current_signals),
                pending_orders=list(self._state.pending_orders),
                filled_today=self._state.filled_today,
                rejected_today=self._state.rejected_today,
                last_signal_timestamp=self._state.last_signal_timestamp,
            )
            return result

    async def resume(self) -> TransitionResult:
        """Resume a paused strategy."""
        async with self._lock:
            result = await self._state_machine.transition(
                StrategyLifecycleState.ACTIVE,
                reason="runtime.resume() called",
            )
            self._state = StrategyStateSnapshot(
                strategy_id=self._config.strategy_id,
                lifecycle_state=StrategyLifecycleState.ACTIVE,
                current_signals=list(self._state.current_signals),
                pending_orders=list(self._state.pending_orders),
                filled_today=self._state.filled_today,
                rejected_today=self._state.rejected_today,
                last_signal_timestamp=self._state.last_signal_timestamp,
            )
            return result

    async def stop(self) -> TransitionResult:
        """Stop — STOPPING → cancels task → STOPPED."""
        async with self._lock:
            result = await self._state_machine.transition(
                StrategyLifecycleState.STOPPING,
                reason="runtime.stop() called",
            )
            self._shutdown_event.set()

            if self._task is not None and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

            result = await self._state_machine.transition(
                StrategyLifecycleState.STOPPED,
                reason="cleanup complete",
            )
            self._state = StrategyStateSnapshot(
                strategy_id=self._config.strategy_id,
                lifecycle_state=StrategyLifecycleState.STOPPED,
            )

        for token in self._config.instrument_tokens:
            await self._market_data.unsubscribe(token, self._on_market_data)
        await self._fill_tracker.unsubscribe()

        return result

    # ------------------------------------------------------------------
    # External injection points (tests and recovery)
    # ------------------------------------------------------------------

    async def on_bar(self, bar: CompletedBar) -> None:
        if self._state_machine.can_emit_signals:
            await self._bar_queue.put(bar)

    async def on_tick(self, tick: Tick) -> None:
        if self._state_machine.can_emit_signals:
            await self._tick_queue.put(tick)

    def get_next_signal(self) -> Optional[Signal]:
        try:
            return self._signal_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        try:
            while not self._shutdown_event.is_set():
                try:
                    bar = await asyncio.wait_for(self._bar_queue.get(), timeout=0.1)
                    await self._process_bar(bar)
                    continue
                except asyncio.TimeoutError:
                    pass

                try:
                    tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.1)
                    await self._process_tick(tick)
                    continue
                except asyncio.TimeoutError:
                    pass

                await asyncio.sleep(0)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Runtime error: {str(e)}",
            )
            raise StrategyRuntimeError(
                f"Strategy {self._config.strategy_id} runtime failed: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Bar / tick processing
    # ------------------------------------------------------------------

    async def _process_bar(self, bar: CompletedBar) -> None:
        """Process one bar through the strategy, collect metrics, isolate faults.

        RC-10B forecast injection order:
          1. build_context()
          2. [RC-10B] update_bar() — refresh feature generator buffers
          3. [RC-10B] start prefetch task (if gate configured + strategy opted in)
          4. strategy.on_bar()
          5. [RC-10B] await prefetch, apply forecast gate (suppress or enrich)
          6. _emit_signal() with (possibly enriched) signal
          7. push state snapshot (fire-and-forget)
        """
        if not self._state_machine.can_emit_signals:
            return

        context = await self._context_builder.build_context(
            self._config,
            self._state,
            strategy_positions=self._fill_tracker.positions,
        )

        # RC-10B: update feature generator ring buffers with latest bar
        if self._feature_generator is not None:
            try:
                self._feature_generator.update_bar(
                    bar.instrument_token, bar.close, bar.volume
                )
            except Exception as _fg_err:
                logger.debug("FeatureGenerator.update_bar error (non-fatal): %s", _fg_err)

        # RC-10B: start forecast prefetch task if gate is configured and strategy
        # has opted in via min_forecast_confidence parameter.
        prefetch_task: Optional[asyncio.Task] = None
        _forecast_enabled = (
            self._ai_forecast_gate is not None
            and self._feature_generator is not None
            and self._config.parameters.get("min_forecast_confidence") is not None
        )
        if _forecast_enabled:
            prefetch_task = self._start_forecast_prefetch(bar, context)

        start_ns = time.perf_counter_ns()
        try:
            signal = self._strategy.on_bar(bar, context)
        except Exception as e:
            # Cancel orphaned prefetch to avoid leaking tasks
            if prefetch_task is not None:
                prefetch_task.cancel()
            await self._record_error_and_maybe_isolate()
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Strategy on_bar error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy on_bar failed: {e}") from e

        latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        # Record metrics for this bar
        if self._metrics is not None:
            asyncio.create_task(
                self._metrics.record_bar(self._config.strategy_id, latency_ms)
            )

        if signal is not None:
            # RC-10B: apply forecast gate (may suppress or enrich the signal)
            signal = await self._apply_forecast_gate(signal, context, prefetch_task)
            prefetch_task = None  # ownership transferred / consumed
            if signal is not None:
                await self._emit_signal(signal)
        else:
            # No signal — cancel orphaned prefetch
            if prefetch_task is not None:
                prefetch_task.cancel()
                try:
                    await prefetch_task
                except (asyncio.CancelledError, Exception):
                    pass

        # Push state snapshot (fire-and-forget — never disrupts bar processing)
        if self._persistence is not None and self._engine is not None:
            asyncio.create_task(self._push_state_snapshot_safe())

    async def _process_tick(self, tick: Tick) -> None:
        """Process one tick through the strategy."""
        if not self._state_machine.can_emit_signals:
            return

        context = await self._context_builder.build_context(
            self._config,
            self._state,
            strategy_positions=self._fill_tracker.positions,
        )

        try:
            signal = self._strategy.on_tick(tick, context)
        except Exception as e:
            await self._record_error_and_maybe_isolate()
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Strategy on_tick error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy on_tick failed: {e}") from e

        if self._metrics is not None:
            asyncio.create_task(
                self._metrics.record_tick(self._config.strategy_id)
            )

        if signal is not None:
            await self._emit_signal(signal)

    # ------------------------------------------------------------------
    # RC-10B: AI forecast gate helpers
    # ------------------------------------------------------------------

    def _start_forecast_prefetch(
        self, bar: CompletedBar, context: StrategyContext
    ) -> Optional[asyncio.Task]:
        """Start a background forecast task.

        Returns the Task object (retain to await or cancel later).
        Returns None if prefetch cannot be started (logged at DEBUG).
        """
        from market_intelligence.multi_timeframe_context import MultiTimeframeContext

        try:
            mtf_context = context.market_snapshots.get(bar.instrument_token)
            if mtf_context is None or not isinstance(mtf_context, MultiTimeframeContext):
                return None

            generated_at = datetime.now(timezone.utc).isoformat()
            features = self._feature_generator.generate(
                bar.instrument_token, mtf_context, generated_at
            )
            horizon = self._config.parameters.get("forecast_horizon", "15m")
            return asyncio.create_task(
                self._ai_forecast_gate._adapter.forecast(
                    bar.instrument_token, features, horizon=str(horizon)
                )
            )
        except Exception as exc:
            logger.debug(
                "Forecast prefetch start failed (non-fatal): %s", exc,
                extra={"instrument_token": bar.instrument_token},
            )
            return None

    async def _apply_forecast_gate(
        self,
        signal: Signal,
        context: StrategyContext,
        prefetch_task: Optional[asyncio.Task],
    ) -> Optional[Signal]:
        """Apply the AI forecast gate to an emitted signal.

        Returns:
          - Original signal if gate is not configured or strategy has not
            opted in (fail-open).
          - Enriched signal (metadata["forecast"] attached) if gate approves.
          - None if gate explicitly suppresses (confidence below threshold).

        Never raises: any gate failure returns the original signal (fail-open).
        """
        from ai_forecast.features import FEATURE_SCHEMA_VERSION

        if self._ai_forecast_gate is None:
            return signal

        raw_threshold = self._config.parameters.get("min_forecast_confidence")
        if raw_threshold is None:
            # Strategy has not opted in to forecast gating — pass-through
            return signal

        try:
            min_confidence = Decimal(str(raw_threshold))
        except Exception:
            logger.warning(
                "Invalid min_forecast_confidence value %r — skipping gate (fail-open)",
                raw_threshold,
            )
            return signal

        # Collect prefetched result (2 s shield timeout)
        prefetched_forecast = None
        if prefetch_task is not None:
            try:
                prefetched_forecast = await asyncio.wait_for(
                    asyncio.shield(prefetch_task), timeout=2.0
                )
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as exc:
                logger.debug("Prefetch await failed (will fetch inline): %s", exc)
                prefetched_forecast = None

        try:
            should_route, forecast = await self._ai_forecast_gate.should_route(
                signal, context, min_confidence, prefetched_forecast=prefetched_forecast
            )
        except Exception as exc:
            logger.warning(
                "ForecastConfidenceGate.should_route error (fail-open): %s", exc
            )
            return signal

        if not should_route:
            # Forecast gate suppressed signal
            return None

        if forecast is not None:
            # Enrich signal metadata (frozen Pydantic model — produce a copy)
            forecast_meta: Dict[str, Any] = {
                "direction": forecast.direction,
                "confidence": str(forecast.confidence),
                "model_version": forecast.model_version,
                "forecast_horizon": forecast.forecast_horizon,
                "price_target": (
                    str(forecast.price_target)
                    if forecast.price_target is not None
                    else None
                ),
                "computed_at": forecast.computed_at,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
            }
            signal = signal.model_copy(
                update={"metadata": {**signal.metadata, "forecast": forecast_meta}}
            )

            # Record forecast for benchmarking (fire-and-forget, fail-safe)
            if self._benchmark_repo is not None and self._engine is not None:
                asyncio.create_task(self._record_forecast_safe(forecast))

        return signal

    async def _record_forecast_safe(self, forecast: Any) -> None:
        """Persist a forecast record.  Never raises."""
        try:
            async with SessionContext(self._engine) as session:
                await self._benchmark_repo.record_forecast(session, forecast)
        except Exception as exc:
            logger.debug(
                "ForecastBenchmark.record_forecast failed (non-fatal): %s", exc
            )

    # ------------------------------------------------------------------
    # Market data and fill callbacks
    # ------------------------------------------------------------------

    def _on_market_data(self, data) -> None:
        if isinstance(data, CompletedBar):
            asyncio.create_task(self.on_bar(data))
        elif isinstance(data, Tick):
            asyncio.create_task(self.on_tick(data))

    def _on_fill(self, fill_event: FillEvent) -> None:
        asyncio.create_task(self._process_fill(fill_event))

    async def _process_fill(self, fill_event: FillEvent) -> None:
        """Process a fill.  Only handles fills for orders owned by this runtime."""
        if not self._state_machine.can_emit_signals:
            return

        if fill_event.client_order_id not in self._state.pending_orders:
            return

        context = await self._context_builder.build_context(
            self._config,
            self._state,
            strategy_positions=self._fill_tracker.positions,
        )

        try:
            signal = self._strategy.on_fill(fill_event, context)
        except Exception as e:
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Strategy on_fill error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy on_fill failed: {e}") from e

        if self._metrics is not None:
            asyncio.create_task(
                self._metrics.record_fill(self._config.strategy_id)
            )

        if signal is not None:
            await self._emit_signal(signal)

    # ------------------------------------------------------------------
    # Signal emission (write-before-route)
    # ------------------------------------------------------------------

    async def _emit_signal(self, signal: Signal) -> None:
        """Emit a signal.

        Ordering guarantee
        ------------------
        1. Validate signal ownership.
        2. Persist signal to DB (PENDING routing_status).  Non-fatal — if
           persistence fails the signal is still routed; a warning is logged.
        3. Update in-memory state snapshot.
        4. Put signal on the internal queue.
        5. Invoke the sync routing callback (schedules async routing task).
        """
        if signal.strategy_id != self._config.strategy_id:
            raise StrategyRuntimeError(
                f"Signal strategy_id {signal.strategy_id!r} does not match "
                f"runtime strategy_id {self._config.strategy_id!r}"
            )

        # Step 2: write-before-route persistence (awaited, non-fatal)
        if self._persistence is not None and self._engine is not None:
            await self._persist_signal_safe(signal)

        # Step 3: update in-memory state
        current_signals = list(self._state.current_signals)
        current_signals.append(signal)
        self._state = StrategyStateSnapshot(
            strategy_id=self._config.strategy_id,
            lifecycle_state=self._state.lifecycle_state,
            current_signals=current_signals,
            pending_orders=list(self._state.pending_orders),
            filled_today=self._state.filled_today,
            rejected_today=self._state.rejected_today,
            last_signal_timestamp=signal.timestamp,
        )

        # Step 4: queue for retrieval
        await self._signal_queue.put(signal)

        # Step 5: record metric + invoke routing callback
        if self._metrics is not None:
            asyncio.create_task(
                self._metrics.record_signal(self._config.strategy_id)
            )

        if self._signal_callback is not None:
            self._signal_callback(signal)

    # ------------------------------------------------------------------
    # Persistence helpers (non-fatal wrappers)
    # ------------------------------------------------------------------

    async def _persist_signal_safe(self, signal: Signal) -> None:
        """Persist a signal as PENDING.  Never raises."""
        from src.strategy.persistence import StrategySignalRecord
        record = StrategySignalRecord(
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            account_id=None,
            instrument_token=signal.instrument_token,
            action=signal.action.value,
            side=signal.side.value,
            quantity=signal.quantity,
            order_type=signal.order_type.value,
            limit_price=signal.limit_price,
            trigger_price=signal.trigger_price,
            timestamp=signal.timestamp,
            routing_status="PENDING",
            extra_data=dict(signal.metadata) if signal.metadata else {},
        )
        try:
            async with SessionContext(self._engine) as session:
                await self._persistence.save_signal(session, record)
        except Exception:
            logger.warning(
                "Failed to persist signal %s (routing continues)",
                signal.signal_id,
                exc_info=True,
            )

    async def _push_state_snapshot_safe(self) -> None:
        """Capture and persist a state snapshot.  Never raises."""
        from src.strategy.persistence import StrategyStateSnapshotRecord
        state = self._state
        record = StrategyStateSnapshotRecord(
            strategy_id=self._config.strategy_id,
            lifecycle_state=state.lifecycle_state.value,
            pending_order_ids=list(state.pending_orders),
            latest_signal_timestamp=state.last_signal_timestamp,
            emitted_signal_count=len(state.current_signals),
            rejected_signal_count=state.rejected_today,
            fill_count=self._fill_tracker.fill_count,
            snapshot_timestamp=datetime.now(timezone.utc),
        )
        try:
            async with SessionContext(self._engine) as session:
                await self._persistence.save_state_snapshot(session, record)
        except Exception:
            logger.debug(
                "State snapshot push failed for %s (non-fatal)",
                self._config.strategy_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Fault isolation helper
    # ------------------------------------------------------------------

    async def _record_error_and_maybe_isolate(self) -> None:
        """Record an error in metrics/fault-isolator; pause if budget breached."""
        if self._metrics is not None:
            await self._metrics.record_error(self._config.strategy_id)

        if self._fault_isolator is not None:
            from strategy.fault_isolation import FaultAction  # local to avoid circular at module init
            action = await self._fault_isolator.record_error(self._config.strategy_id)
            if action in (FaultAction.PAUSE, FaultAction.STOP):
                logger.warning(
                    "FaultIsolator triggered %s for strategy %s — pausing",
                    action.value, self._config.strategy_id,
                )
                try:
                    await self._state_machine.transition(
                        StrategyLifecycleState.PAUSED,
                        reason=f"Fault isolation: {action.value}",
                    )
                    self._state = StrategyStateSnapshot(
                        strategy_id=self._config.strategy_id,
                        lifecycle_state=StrategyLifecycleState.PAUSED,
                    )
                except Exception:
                    pass  # state machine may reject if already ERROR — that is fine
