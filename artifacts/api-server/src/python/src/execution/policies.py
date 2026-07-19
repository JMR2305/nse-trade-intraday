"""Deterministic paper-execution policies.

Price selection, slippage, liquidity, and latency are modeled as
pure functions for deterministic replay.  No wall-clock sleeps.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from src.execution.contracts import ExecutionOrderSide


# ------------------------------------------------------------------
# Price selection policy
# ------------------------------------------------------------------

class PriceSelectionPolicy(Protocol):
    """Select the executable price for a market order."""

    def select_price(
        self,
        side: ExecutionOrderSide,
        last_traded_price: Decimal,
        bid_price: Decimal | None,
        ask_price: Decimal | None,
    ) -> Decimal:
        """Return the raw executable price before slippage."""
        ...


@dataclass(frozen=True)
class DefaultPriceSelectionPolicy:
    """BUY: prefer ask, fallback to LTP.  SELL: prefer bid, fallback to LTP."""

    def select_price(
        self,
        side: ExecutionOrderSide,
        last_traded_price: Decimal,
        bid_price: Decimal | None,
        ask_price: Decimal | None,
    ) -> Decimal:
        if side == ExecutionOrderSide.BUY:
            if ask_price is not None and ask_price > 0:
                return ask_price
            return last_traded_price
        else:  # SELL
            if bid_price is not None and bid_price > 0:
                return bid_price
            return last_traded_price


# ------------------------------------------------------------------
# Slippage policy
# ------------------------------------------------------------------

class SlippagePolicy(Protocol):
    """Apply deterministic slippage to a fill price."""

    def apply_slippage(
        self,
        side: ExecutionOrderSide,
        price: Decimal,
        tick_size: Decimal,
    ) -> Decimal:
        """Return price after slippage, rounded to tick size."""
        ...


@dataclass(frozen=True)
class BasisPointsSlippagePolicy:
    """Slippage expressed in basis points (1 bp = 0.01%).

    BUY: price worsens upward (more expensive).
    SELL: price worsens downward (less expensive).
    """
    basis_points: Decimal = Decimal("0")  # 0 = no slippage

    def apply_slippage(
        self,
        side: ExecutionOrderSide,
        price: Decimal,
        tick_size: Decimal,
    ) -> Decimal:
        if self.basis_points <= 0:
            return self._round_to_tick(price, tick_size)

        # slippage factor = 1 + (bps / 10000)
        factor = Decimal("1") + (self.basis_points / Decimal("10000"))

        if side == ExecutionOrderSide.BUY:
            slipped = price * factor
        else:
            slipped = price / factor  # SELL: price goes down

        return self._round_to_tick(slipped, tick_size)

    @staticmethod
    def _round_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
        if tick_size <= 0:
            return value
        quantize_str = str(tick_size)
        # Count decimal places in tick_size
        if "." in quantize_str:
            places = len(quantize_str.split(".")[1])
        else:
            places = 0
        quantizer = Decimal("1").scaleb(-places)
        return (value / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size


@dataclass(frozen=True)
class FixedTicksSlippagePolicy:
    """Slippage expressed in whole ticks.

    BUY: price worsens upward by N ticks.
    SELL: price worsens downward by N ticks.
    """
    ticks: int = 0

    def apply_slippage(
        self,
        side: ExecutionOrderSide,
        price: Decimal,
        tick_size: Decimal,
    ) -> Decimal:
        if self.ticks <= 0 or tick_size <= 0:
            return self._round_to_tick(price, tick_size)

        if side == ExecutionOrderSide.BUY:
            slipped = price + (tick_size * self.ticks)
        else:
            slipped = price - (tick_size * self.ticks)

        return self._round_to_tick(slipped, tick_size)

    @staticmethod
    def _round_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
        if tick_size <= 0:
            return value
        quantize_str = str(tick_size)
        if "." in quantize_str:
            places = len(quantize_str.split(".")[1])
        else:
            places = 0
        quantizer = Decimal("1").scaleb(-places)
        return (value / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size


# ------------------------------------------------------------------
# Liquidity policy
# ------------------------------------------------------------------

class LiquidityPolicy(Protocol):
    """Determine how much of an order can be filled given market liquidity."""

    def compute_fill_quantity(
        self,
        order_quantity: int,
        remaining_quantity: int,
        available_liquidity: int | None,
    ) -> int:
        """Return the quantity to fill (0 if not executable)."""
        ...


@dataclass(frozen=True)
class DefaultLiquidityPolicy:
    """Fill up to remaining quantity, capped by available liquidity.

    If no liquidity info is available, fills the full remaining quantity.
    """
    max_fill_ratio: Decimal = Decimal("1.0")  # 1.0 = 100% of available

    def compute_fill_quantity(
        self,
        order_quantity: int,
        remaining_quantity: int,
        available_liquidity: int | None,
    ) -> int:
        if remaining_quantity <= 0:
            return 0

        if available_liquidity is None:
            # No liquidity info: fill full remaining quantity
            return remaining_quantity

        if available_liquidity <= 0:
            return 0

        capped = int(Decimal(available_liquidity) * self.max_fill_ratio)
        return min(remaining_quantity, capped)


# ------------------------------------------------------------------
# Latency policy
# ------------------------------------------------------------------

class LatencyPolicy(Protocol):
    """Deterministic latency model.

    Latency is evaluated by comparing timestamps, not by sleeping.
    """

    def is_eligible(
        self,
        order_timestamp,
        market_event_timestamp,
    ) -> bool:
        """Return True if the market event is eligible for the order."""
        ...


@dataclass(frozen=True)
class ZeroLatencyPolicy:
    """No latency — all events are immediately eligible."""

    def is_eligible(
        self,
        order_timestamp,
        market_event_timestamp,
    ) -> bool:
        return True


@dataclass(frozen=True)
class FixedLatencyPolicy:
    """Fixed latency delay.  Event is eligible only if its timestamp
    is at least ``delay_seconds`` after the order timestamp."""
    delay_seconds: Decimal = Decimal("0")

    def is_eligible(
        self,
        order_timestamp,
        market_event_timestamp,
    ) -> bool:
        if self.delay_seconds <= 0:
            return True
        delta = market_event_timestamp - order_timestamp
        # delta is a timedelta; compare total seconds
        return delta.total_seconds() >= float(self.delay_seconds)
