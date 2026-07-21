"""StrategyCoordinator — global strategy lifecycle manager.

Singleton. Manages registration, start, stop, pause, resume for all strategies.
Uses per-strategy asyncio.Lock for concurrency safety.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, List, Callable
from datetime import datetime

from strategy.contracts import (
    StrategyConfig,
    StrategyStateSnapshot,
    StrategyLifecycleState,
    StrategyRegistrationResult,
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


class StrategyCoordinator:
    """Global coordinator for all strategy instances.

    Responsibilities:
    - Register/deregister strategies
    - Start/stop/pause/resume individual strategies
    - Emergency stop all strategies
    - List and query strategy states
    - Detect cross-strategy conflicts
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        fill_event_bus: FillEventBus,
        context_builder: ContextBuilder,
        signal_router: SignalRouter,
    ):
        self._market_data = market_data_service
        self._fill_bus = fill_event_bus
        self._context_builder = context_builder
        self._signal_router = signal_router

        self._strategies: Dict[str, Strategy] = {}  # strategy_id -> Strategy
        self._configs: Dict[str, StrategyConfig] = {}  # strategy_id -> StrategyConfig
        self._runtimes: Dict[str, StrategyRuntime] = {}  # strategy_id -> StrategyRuntime
        self._locks: Dict[str, asyncio.Lock] = {}  # strategy_id -> Lock
        self._global_lock = asyncio.Lock()
        # Preserves the last known state of stopped runtimes so get_strategy()
        # returns STOPPED (not REGISTERED) after a strategy has been stopped.
        self._final_states: Dict[str, StrategyStateSnapshot] = {}

    async def register(
        self,
        config: StrategyConfig,
        strategy: Strategy,
    ) -> StrategyRegistrationResult:
        """Register a new strategy.

        Args:
            config: Strategy configuration.
            strategy: Strategy implementation satisfying the Strategy Protocol.

        Returns:
            StrategyRegistrationResult.

        Raises:
            StrategyAlreadyRegisteredError: If strategy_id already exists.
        """
        async with self._global_lock:
            if config.strategy_id in self._configs:
                return StrategyRegistrationResult(
                    strategy_id=config.strategy_id,
                    success=False,
                    error_message=f"Strategy {config.strategy_id} already registered",
                )

            # Validate config against strategy
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

            return StrategyRegistrationResult(
                strategy_id=config.strategy_id,
                success=True,
            )

    async def deregister(self, strategy_id: str) -> None:
        """Deregister a strategy.

        Stops the strategy if running, then removes it.

        NOTE: Does NOT call self.stop() — that would deadlock because both
        deregister and stop acquire the same per-strategy lock. Instead, the
        runtime is stopped directly while holding the lock.
        """
        async with self._get_lock(strategy_id):
            if strategy_id in self._runtimes:
                runtime = self._runtimes[strategy_id]
                await runtime.stop()
                self._final_states[strategy_id] = runtime.state

            async with self._global_lock:
                self._strategies.pop(strategy_id, None)
                self._configs.pop(strategy_id, None)
                self._runtimes.pop(strategy_id, None)
                self._locks.pop(strategy_id, None)

    async def start(self, strategy_id: str) -> None:
        """Start a registered strategy.

        Creates a StrategyRuntime and transitions it to ACTIVE.
        """
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
            )

            self._runtimes[strategy_id] = runtime
            await runtime.start()

    async def pause(self, strategy_id: str, reason: str = "") -> None:
        """Pause a running strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            runtime = self._runtimes[strategy_id]
            await runtime.pause()

    async def resume(self, strategy_id: str) -> None:
        """Resume a paused strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            runtime = self._runtimes[strategy_id]
            await runtime.resume()

    async def stop(self, strategy_id: str, reason: str = "") -> None:
        """Stop a running strategy."""
        async with self._get_lock(strategy_id):
            self._ensure_running(strategy_id)
            runtime = self._runtimes[strategy_id]
            await runtime.stop()
            self._final_states[strategy_id] = runtime.state
            del self._runtimes[strategy_id]

    async def emergency_stop_all(self, reason: str = "") -> None:
        """Emergency stop all running strategies.

        Cancels all pending orders and stops all runtimes.
        """
        async with self._global_lock:
            strategy_ids = list(self._runtimes.keys())

        # Cancel all pending orders first
        for strategy_id in strategy_ids:
            await self._signal_router.cancel_pending_for_strategy(strategy_id)

        # Stop all runtimes
        for strategy_id in strategy_ids:
            try:
                async with self._get_lock(strategy_id):
                    if strategy_id in self._runtimes:
                        runtime = self._runtimes[strategy_id]
                        await runtime.stop()
                        self._final_states[strategy_id] = runtime.state
                        del self._runtimes[strategy_id]
            except Exception:
                # Best effort — don't let one failure block others
                pass

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
        """Get the state of a specific strategy."""
        if strategy_id not in self._configs:
            return None

        if strategy_id in self._runtimes:
            return self._runtimes[strategy_id].state

        # Return preserved stopped state if available
        if strategy_id in self._final_states:
            return self._final_states[strategy_id]

        return StrategyStateSnapshot(
            strategy_id=strategy_id,
            lifecycle_state=StrategyLifecycleState.REGISTERED,
        )

    def _get_lock(self, strategy_id: str) -> asyncio.Lock:
        """Get or create the per-strategy lock."""
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
        """Callback invoked when a strategy runtime emits a signal.

        Schedules async routing through SignalRouter as a background task so
        the sync callback can return immediately without blocking the runtime.
        """
        config = self._configs.get(signal.strategy_id)
        if config is None:
            return
        asyncio.create_task(
            self._signal_router.route_signal(signal, signal.strategy_id, config)
        )
