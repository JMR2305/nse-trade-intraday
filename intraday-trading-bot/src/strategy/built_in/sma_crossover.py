"""Simple Moving Average Crossover — deterministic reference strategy.

Generates BUY signals when short SMA crosses above long SMA.
Generates SELL signals when short SMA crosses below long SMA.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, List, Dict
from collections import deque

from strategy.contracts import Signal, SignalAction, StrategyConfig, StrategyContext
from strategy.strategy_protocol import Strategy
from strategy.exceptions import StrategyError
from execution.contracts import ExecutionOrderSide, ExecutionOrderType
from market_data.contracts import CompletedBar, Tick
from execution.fills import FillEvent


class SmaCrossoverStrategy:
    """Deterministic SMA crossover strategy.

    Parameters (via StrategyConfig.parameters):
        - short_period: int = 5 (bars for short SMA)
        - long_period: int = 20 (bars for long SMA)
        - quantity: Decimal = 100 (order quantity)

    Deterministic: Given the same bar sequence, always produces the same signals.
    """

    def __init__(self):
        self._short_period: int = 5
        self._long_period: int = 20
        self._quantity: Decimal = Decimal("100")
        self._short_window: deque[Decimal] = deque()
        self._long_window: deque[Decimal] = deque()
        self._prev_short_sma: Optional[Decimal] = None
        self._prev_long_sma: Optional[Decimal] = None

    @property
    def strategy_type(self) -> str:
        return "sma_crossover"

    def validate_config(self, config: StrategyConfig) -> List[str]:
        """Validate SMA-specific parameters and apply them to this instance.

        Side-effect: on successful validation, parameters are written to
        instance variables so the strategy runs with the configured values.
        This is intentional — the Protocol allows stateful indicator windows.
        """
        errors = []
        params = config.parameters

        short = params.get("short_period", 5)
        long = params.get("long_period", 20)

        if not isinstance(short, int) or short < 2:
            errors.append(f"short_period must be an integer >= 2, got {short}")
        if not isinstance(long, int) or long < 2:
            errors.append(f"long_period must be an integer >= 2, got {long}")
        if short >= long:
            errors.append(f"short_period ({short}) must be less than long_period ({long})")

        qty = params.get("quantity", 100)
        try:
            qty_dec = Decimal(str(qty))
            if qty_dec <= Decimal("0"):
                errors.append(f"quantity must be positive, got {qty}")
        except Exception:
            errors.append(f"quantity must be a valid number, got {qty}")

        # Apply validated parameters to instance (intentional side-effect)
        if not errors:
            self._short_period = int(short)
            self._long_period = int(long)
            self._quantity = Decimal(str(qty))

        return errors

    def on_bar(
        self,
        bar: CompletedBar,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """Process a bar and emit signal on SMA crossover."""
        # Update windows
        self._short_window.append(bar.close)
        self._long_window.append(bar.close)

        # Maintain window sizes
        while len(self._short_window) > self._short_period:
            self._short_window.popleft()
        while len(self._long_window) > self._long_period:
            self._long_window.popleft()

        # Need enough data
        if len(self._short_window) < self._short_period or len(self._long_window) < self._long_period:
            return None

        # Calculate SMAs
        short_sma = sum(self._short_window) / Decimal(str(self._short_period))
        long_sma = sum(self._long_window) / Decimal(str(self._long_period))

        # Check for crossover (need previous values)
        signal = None
        if self._prev_short_sma is not None and self._prev_long_sma is not None:
            # Golden cross: short crosses above long
            if self._prev_short_sma <= self._prev_long_sma and short_sma > long_sma:
                signal = self._create_signal(
                    context, bar, SignalAction.ENTER_LONG, ExecutionOrderSide.BUY
                )
            # Death cross: short crosses below long
            elif self._prev_short_sma >= self._prev_long_sma and short_sma < long_sma:
                signal = self._create_signal(
                    context, bar, SignalAction.ENTER_SHORT, ExecutionOrderSide.SELL
                )

        self._prev_short_sma = short_sma
        self._prev_long_sma = long_sma

        return signal

    def on_tick(
        self,
        tick: Tick,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """SMA crossover is bar-driven; ticks are ignored."""
        return None

    def on_fill(
        self,
        fill_event: FillEvent,
        context: StrategyContext,
    ) -> Optional[Signal]:
        """No follow-up signals on fill."""
        return None

    def _create_signal(
        self,
        context: StrategyContext,
        bar: CompletedBar,
        action: SignalAction,
        side: ExecutionOrderSide,
    ) -> Signal:
        """Create a Signal for this strategy."""
        return Signal(
            strategy_id=context.strategy_id,
            instrument_token=bar.instrument_token,
            action=action,
            side=side,
            quantity=self._quantity,
            order_type=ExecutionOrderType.MARKET,
            reason=f"SMA crossover: short({self._short_period}) vs long({self._long_period}) "
                   f"at price {bar.close}",
            timestamp=bar.timestamp,
        )
