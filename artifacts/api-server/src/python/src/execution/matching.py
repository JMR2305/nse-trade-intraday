"""Order matching logic.

Determines whether an order is executable against a market snapshot,
and computes the fill price and quantity.  Stateless — all inputs are
passed as arguments; no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderSide,
    ExecutionOrderStatus,
    ExecutionOrderType,
)
from src.execution.fills import FillEvent, FillEventBuilder
from src.execution.policies import (
    DefaultLiquidityPolicy,
    DefaultPriceSelectionPolicy,
    LiquidityPolicy,
    PriceSelectionPolicy,
    SlippagePolicy,
)


# ------------------------------------------------------------------
# MarketSnapshot
# ------------------------------------------------------------------

@dataclass(frozen=True)
class MarketSnapshot:
    """Normalized market data snapshot consumed by the matching engine.

    Adapted from Batch 6 Tick/Quote contracts for execution use.
    All prices are Decimal.  Timestamps are timezone-aware.
    """
    instrument_token: int
    timestamp: datetime
    last_traded_price: Decimal
    event_id: str
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    bid_quantity: int | None = None
    ask_quantity: int | None = None
    traded_volume: int | None = None
    tick_size: Decimal = Decimal("0.05")  # NSE default tick size
    metadata: dict[str, Any] | None = None


# ------------------------------------------------------------------
# MatchResult
# ------------------------------------------------------------------

@dataclass(frozen=True)
class MatchResult:
    """Result of evaluating an order against a market snapshot."""
    executable: bool
    fill_event: FillEvent | None = None
    reason: str | None = None


# ------------------------------------------------------------------
# TriggerStateTracker
# ------------------------------------------------------------------

class TriggerStateTracker:
    """Tracks sticky trigger activation for stop orders.

    Once a stop order's trigger condition is met, it remains triggered
    for all subsequent evaluations.
    """

    def __init__(self) -> None:
        self._triggered: set = set()

    def is_triggered(self, order_id) -> bool:
        return order_id in self._triggered

    def mark_triggered(self, order_id) -> None:
        self._triggered.add(order_id)

    def reset(self) -> None:
        self._triggered.clear()


# ------------------------------------------------------------------
# OrderMatcher
# ------------------------------------------------------------------

class OrderMatcher:
    """Deterministic order matcher.

    Evaluates whether an order is executable against a market snapshot.
    Stateless except for the trigger tracker (which is required for sticky
    stop-order semantics).
    """

    def __init__(
        self,
        price_policy: PriceSelectionPolicy | None = None,
        slippage_policy: SlippagePolicy | None = None,
        liquidity_policy: LiquidityPolicy | None = None,
        trigger_tracker: TriggerStateTracker | None = None,
    ) -> None:
        self._price_policy = price_policy or DefaultPriceSelectionPolicy()
        self._slippage_policy = slippage_policy
        self._liquidity_policy = liquidity_policy or DefaultLiquidityPolicy()
        self._trigger_tracker = trigger_tracker or TriggerStateTracker()
        self._fill_builder = FillEventBuilder()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def match(
        self,
        order: ExecutionOrder,
        status: ExecutionOrderStatus,
        filled_quantity: int,
        remaining_quantity: int,
        snapshot: MarketSnapshot,
    ) -> MatchResult:
        """Evaluate an order against a market snapshot.

        Returns MatchResult with executable flag and optional FillEvent.
        """
        # 1. State filter — only OPEN and PARTIALLY_FILLED are executable
        if status not in (ExecutionOrderStatus.OPEN, ExecutionOrderStatus.PARTIALLY_FILLED):
            return MatchResult(
                executable=False,
                reason=f"Order in non-executable state: {status.value}",
            )

        # 2. Instrument filter
        if order.instrument_token != snapshot.instrument_token:
            return MatchResult(
                executable=False,
                reason="Instrument token mismatch",
            )

        # 3. Order-type-specific evaluation
        if order.order_type == ExecutionOrderType.MARKET:
            return self._match_market(order, filled_quantity, remaining_quantity, snapshot)

        if order.order_type == ExecutionOrderType.LIMIT:
            return self._match_limit(order, filled_quantity, remaining_quantity, snapshot)

        if order.order_type == ExecutionOrderType.STOP_MARKET:
            return self._match_stop_market(order, filled_quantity, remaining_quantity, snapshot)

        if order.order_type == ExecutionOrderType.STOP_LIMIT:
            return self._match_stop_limit(order, filled_quantity, remaining_quantity, snapshot)

        return MatchResult(executable=False, reason=f"Unsupported order type: {order.order_type.value}")

    def reset(self) -> None:
        """Reset internal state for deterministic replay."""
        self._trigger_tracker.reset()
        self._fill_builder.reset()

    # ------------------------------------------------------------------
    # MARKET order matching
    # ------------------------------------------------------------------
    def _match_market(
        self,
        order: ExecutionOrder,
        filled_quantity: int,
        remaining_quantity: int,
        snapshot: MarketSnapshot,
    ) -> MatchResult:
        raw_price = self._price_policy.select_price(
            side=order.side,
            last_traded_price=snapshot.last_traded_price,
            bid_price=snapshot.bid_price,
            ask_price=snapshot.ask_price,
        )

        fill_price = self._apply_slippage(order.side, raw_price, snapshot.tick_size)

        # Determine available liquidity
        available_liquidity = self._available_liquidity(order.side, snapshot)

        fill_qty = self._liquidity_policy.compute_fill_quantity(
            order_quantity=order.quantity,
            remaining_quantity=remaining_quantity,
            available_liquidity=available_liquidity,
        )

        if fill_qty <= 0:
            return MatchResult(executable=False, reason="Insufficient liquidity")

        if fill_qty > remaining_quantity:
            fill_qty = remaining_quantity

        new_cumulative = filled_quantity + fill_qty
        new_remaining = remaining_quantity - fill_qty

        fill_event = self._fill_builder.build(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            instrument_token=order.instrument_token,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            market_event_id=snapshot.event_id or str(snapshot.timestamp),
            market_timestamp=snapshot.timestamp,
            cumulative_filled_quantity=new_cumulative,
            remaining_quantity=new_remaining,
            slippage_bps=self._slippage_bps(),
            metadata={"order_type": "MARKET"},
        )

        return MatchResult(executable=True, fill_event=fill_event)

    # ------------------------------------------------------------------
    # LIMIT order matching
    # ------------------------------------------------------------------
    def _match_limit(
        self,
        order: ExecutionOrder,
        filled_quantity: int,
        remaining_quantity: int,
        snapshot: MarketSnapshot,
    ) -> MatchResult:
        if order.limit_price is None:
            return MatchResult(executable=False, reason="LIMIT order missing limit_price")

        ltp = snapshot.last_traded_price

        # Eligibility check
        if order.side == ExecutionOrderSide.BUY:
            if ltp > order.limit_price:
                return MatchResult(
                    executable=False,
                    reason=f"LTP {ltp} > limit {order.limit_price}",
                )
            # Fill price = limit price (never worse than limit)
            fill_price = order.limit_price
        else:  # SELL
            if ltp < order.limit_price:
                return MatchResult(
                    executable=False,
                    reason=f"LTP {ltp} < limit {order.limit_price}",
                )
            fill_price = order.limit_price

        # Apply slippage but guard against exceeding limit
        slipped = self._apply_slippage(order.side, fill_price, snapshot.tick_size)
        if order.side == ExecutionOrderSide.BUY and slipped > order.limit_price:
            slipped = order.limit_price
        if order.side == ExecutionOrderSide.SELL and slipped < order.limit_price:
            slipped = order.limit_price

        fill_price = slipped

        available_liquidity = self._available_liquidity(order.side, snapshot)
        fill_qty = self._liquidity_policy.compute_fill_quantity(
            order_quantity=order.quantity,
            remaining_quantity=remaining_quantity,
            available_liquidity=available_liquidity,
        )

        if fill_qty <= 0:
            return MatchResult(executable=False, reason="Insufficient liquidity")

        if fill_qty > remaining_quantity:
            fill_qty = remaining_quantity

        new_cumulative = filled_quantity + fill_qty
        new_remaining = remaining_quantity - fill_qty

        fill_event = self._fill_builder.build(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            instrument_token=order.instrument_token,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            market_event_id=snapshot.event_id or str(snapshot.timestamp),
            market_timestamp=snapshot.timestamp,
            cumulative_filled_quantity=new_cumulative,
            remaining_quantity=new_remaining,
            slippage_bps=self._slippage_bps(),
            metadata={"order_type": "LIMIT", "limit_price": str(order.limit_price)},
        )

        return MatchResult(executable=True, fill_event=fill_event)

    # ------------------------------------------------------------------
    # STOP_MARKET order matching
    # ------------------------------------------------------------------
    def _match_stop_market(
        self,
        order: ExecutionOrder,
        filled_quantity: int,
        remaining_quantity: int,
        snapshot: MarketSnapshot,
    ) -> MatchResult:
        if order.trigger_price is None:
            return MatchResult(executable=False, reason="STOP_MARKET order missing trigger_price")

        ltp = snapshot.last_traded_price
        triggered = self._trigger_tracker.is_triggered(order.order_id)

        if not triggered:
            # Check trigger condition
            if order.side == ExecutionOrderSide.BUY:
                if ltp < order.trigger_price:
                    return MatchResult(
                        executable=False,
                        reason=f"BUY stop not triggered: LTP {ltp} < trigger {order.trigger_price}",
                    )
            else:  # SELL
                if ltp > order.trigger_price:
                    return MatchResult(
                        executable=False,
                        reason=f"SELL stop not triggered: LTP {ltp} > trigger {order.trigger_price}",
                    )
            # Trigger activated
            self._trigger_tracker.mark_triggered(order.order_id)

        # Once triggered, behave as market order
        return self._match_market(
            order, filled_quantity, remaining_quantity, snapshot
        )

    # ------------------------------------------------------------------
    # STOP_LIMIT order matching
    # ------------------------------------------------------------------
    def _match_stop_limit(
        self,
        order: ExecutionOrder,
        filled_quantity: int,
        remaining_quantity: int,
        snapshot: MarketSnapshot,
    ) -> MatchResult:
        if order.trigger_price is None or order.limit_price is None:
            return MatchResult(executable=False, reason="STOP_LIMIT order missing trigger_price or limit_price")

        ltp = snapshot.last_traded_price
        triggered = self._trigger_tracker.is_triggered(order.order_id)

        if not triggered:
            # Check trigger condition
            if order.side == ExecutionOrderSide.BUY:
                if ltp < order.trigger_price:
                    return MatchResult(
                        executable=False,
                        reason=f"BUY stop not triggered: LTP {ltp} < trigger {order.trigger_price}",
                    )
            else:  # SELL
                if ltp > order.trigger_price:
                    return MatchResult(
                        executable=False,
                        reason=f"SELL stop not triggered: LTP {ltp} > trigger {order.trigger_price}",
                    )
            self._trigger_tracker.mark_triggered(order.order_id)

        # Once triggered, behave as limit order
        return self._match_limit(
            order, filled_quantity, remaining_quantity, snapshot
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _apply_slippage(self, side: ExecutionOrderSide, price: Decimal, tick_size: Decimal) -> Decimal:
        if self._slippage_policy is None:
            return price
        return self._slippage_policy.apply_slippage(side, price, tick_size)

    def _slippage_bps(self) -> Decimal:
        if hasattr(self._slippage_policy, "basis_points"):
            return self._slippage_policy.basis_points
        return Decimal("0")

    @staticmethod
    def _available_liquidity(side: ExecutionOrderSide, snapshot: MarketSnapshot) -> int | None:
        if side == ExecutionOrderSide.BUY:
            return snapshot.ask_quantity
        return snapshot.bid_quantity
