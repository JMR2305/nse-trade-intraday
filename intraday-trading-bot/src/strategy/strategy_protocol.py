"""Strategy Protocol definition.

All strategy implementations must satisfy this Protocol.
The engine manages state; implementations provide logic.
"""
from __future__ import annotations

from typing import Protocol, Optional, List, runtime_checkable

from strategy.contracts import Signal, StrategyConfig, StrategyContext
from market_data.contracts import CompletedBar, Tick
from execution.fills import FillEvent


@runtime_checkable
class Strategy(Protocol):
    """Protocol for all trading strategy implementations.

    Implementations are logic containers. Strategy-level mutable state
    (position tracking, indicator windows, etc.) may be stored on the
    instance, but the StrategyRuntime owns the lifecycle and guarantees
    one instance per active strategy. All state must be reconstructible
    from the StrategyContext for deterministic replay.

    Determinism requirement: Given the same sequence of bars/ticks/fills
    and the same StrategyContext, a strategy must produce the same
    sequence of signals.
    """

    @property
    def strategy_type(self) -> str:
        """Return the registered type identifier for this strategy.

        Must match the strategy_type field in StrategyConfig.
        """
        ...

    def on_bar(
        self,
        bar: CompletedBar,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """Process a completed bar and optionally emit a signal.

        Called by StrategyRuntime for bar-driven strategies.

        Args:
            bar: The completed OHLCV bar.
            context: Current market, portfolio, and strategy state.

        Returns:
            A Signal if the strategy wants to trade, or None.
        """
        ...

    def on_tick(
        self,
        tick: Tick,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """Process a market tick and optionally emit a signal.

        Called by StrategyRuntime for tick-driven strategies.

        Args:
            tick: The market tick data.
            context: Current market, portfolio, and strategy state.

        Returns:
            A Signal if the strategy wants to trade, or None.
        """
        ...

    def on_fill(
        self,
        fill_event: FillEvent,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """Process a fill event and optionally emit a follow-up signal.

        Called by StrategyRuntime when a fill occurs for an order
        that this strategy submitted.

        Args:
            fill_event: The fill event from the execution engine.
            context: Current market, portfolio, and strategy state.

        Returns:
            A Signal if the strategy wants to follow up (e.g., trailing stop),
            or None.
        """
        ...

    def validate_config(self, config: StrategyConfig) -> List[str]:
        """Validate a StrategyConfig for this strategy type.

        Args:
            config: The configuration to validate.

        Returns:
            A list of validation error messages. Empty list means valid.
        """
        ...
