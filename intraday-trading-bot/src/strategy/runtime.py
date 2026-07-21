"""StrategyRuntime — per-strategy async task.

Manages the lifecycle of one strategy instance: subscribes to market data,
invokes strategy callbacks, emits signals, and tracks fills.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Optional, Callable, Dict, List
from datetime import datetime

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
    ):
        self._config = config
        self._strategy = strategy
        self._context_builder = context_builder
        self._market_data = market_data_service
        self._fill_bus = fill_event_bus
        self._signal_callback = signal_callback

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
        """True when the runtime is in a state that allows signal emission."""
        return self._state_machine.can_emit_signals

    async def start(self) -> TransitionResult:
        """Start the strategy runtime.

        Transitions REGISTERED -> STARTING -> ACTIVE.
        Subscribes to market data and begins processing.
        """
        async with self._lock:
            # Transition to STARTING
            result = await self._state_machine.transition(
                StrategyLifecycleState.STARTING,
                reason="runtime.start() called",
            )

            # Start the processing task
            self._task = asyncio.create_task(self._run_loop())

            # Transition to ACTIVE
            result = await self._state_machine.transition(
                StrategyLifecycleState.ACTIVE,
                reason="market data subscription confirmed",
            )

            self._state = StrategyStateSnapshot(
                strategy_id=self._config.strategy_id,
                lifecycle_state=StrategyLifecycleState.ACTIVE,
            )

        # Subscribe to market data and fills OUTSIDE the lock
        # to prevent deadlock on slow external calls
        for token in self._config.instrument_tokens:
            await self._market_data.subscribe(token, self._on_market_data)

        await self._fill_tracker.subscribe(self._on_fill)

        return result

    async def pause(self) -> TransitionResult:
        """Pause the strategy.

        Stops signal generation but maintains subscriptions and positions.
        """
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
        """Stop the strategy runtime.

        Transitions to STOPPING, cancels subscriptions, stops the task,
        then transitions to STOPPED.
        """
        async with self._lock:
            result = await self._state_machine.transition(
                StrategyLifecycleState.STOPPING,
                reason="runtime.stop() called",
            )

            self._shutdown_event.set()

            # Cancel task if running
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

        # Unsubscribe from market data and fills OUTSIDE the lock
        for token in self._config.instrument_tokens:
            await self._market_data.unsubscribe(token, self._on_market_data)

        await self._fill_tracker.unsubscribe()

        return result

    async def on_bar(self, bar: CompletedBar) -> None:
        """External entry point for injecting a bar (used by tests and recovery)."""
        if self._state_machine.can_emit_signals:
            await self._bar_queue.put(bar)

    async def on_tick(self, tick: Tick) -> None:
        """External entry point for injecting a tick (used by tests and recovery)."""
        if self._state_machine.can_emit_signals:
            await self._tick_queue.put(tick)

    def get_next_signal(self) -> Optional[Signal]:
        """Non-blocking check for emitted signals."""
        try:
            return self._signal_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _run_loop(self) -> None:
        """Main processing loop."""
        try:
            while not self._shutdown_event.is_set():
                # Process bars with priority
                try:
                    bar = await asyncio.wait_for(self._bar_queue.get(), timeout=0.1)
                    await self._process_bar(bar)
                    continue
                except asyncio.TimeoutError:
                    pass

                # Process ticks
                try:
                    tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.1)
                    await self._process_tick(tick)
                    continue
                except asyncio.TimeoutError:
                    pass

                # Yield control
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Runtime error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy {self._config.strategy_id} runtime failed: {e}") from e

    async def _process_bar(self, bar: CompletedBar) -> None:
        """Process a single bar through the strategy."""
        if not self._state_machine.can_emit_signals:
            return

        context = await self._context_builder.build_context(
            self._config,
            self._state,
            strategy_positions=self._fill_tracker.positions,
        )

        try:
            signal = self._strategy.on_bar(bar, context)
        except Exception as e:
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Strategy on_bar error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy on_bar failed: {e}") from e

        if signal is not None:
            await self._emit_signal(signal)

    async def _process_tick(self, tick: Tick) -> None:
        """Process a single tick through the strategy."""
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
            await self._state_machine.transition(
                StrategyLifecycleState.ERROR,
                reason=f"Strategy on_tick error: {str(e)}",
            )
            raise StrategyRuntimeError(f"Strategy on_tick failed: {e}") from e

        if signal is not None:
            await self._emit_signal(signal)

    def _on_market_data(self, data) -> None:
        """Callback registered with MarketDataService."""
        if isinstance(data, CompletedBar):
            asyncio.create_task(self.on_bar(data))
        elif isinstance(data, Tick):
            asyncio.create_task(self.on_tick(data))

    def _on_fill(self, fill_event: FillEvent) -> None:
        """Callback for fill events."""
        asyncio.create_task(self._process_fill(fill_event))

    async def _process_fill(self, fill_event: FillEvent) -> None:
        """Process a fill and optionally emit follow-up signal.

        Only processes fills for orders submitted by this runtime.
        """
        if not self._state_machine.can_emit_signals:
            return

        # Ownership check: skip fills for orders not submitted by this strategy
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

        if signal is not None:
            await self._emit_signal(signal)

    async def _emit_signal(self, signal: Signal) -> None:
        """Emit a signal to the callback and queue."""
        # Validate signal belongs to this strategy
        if signal.strategy_id != self._config.strategy_id:
            raise StrategyRuntimeError(
                f"Signal strategy_id {signal.strategy_id} does not match "
                f"runtime strategy_id {self._config.strategy_id}"
            )

        # Update state
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

        # Queue for retrieval
        await self._signal_queue.put(signal)

        # Notify callback if registered
        if self._signal_callback is not None:
            self._signal_callback(signal)
