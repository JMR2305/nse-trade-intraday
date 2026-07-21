"""SignalRouter — validates signals, maps to ExecutionOrder, routes to execution.

Singleton. Receives signals from all strategy runtimes and processes them
through validation, conflict detection, and order submission.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Set
from datetime import datetime, timedelta

from strategy.contracts import (
    Signal,
    SignalAction,
    StrategyConfig,
    SignalRoutingResult,
    ConflictResolution,
)
from strategy.exceptions import (
    InvalidSignalError,
    SignalValidationError,
    StrategyConflictError,
    OrderMappingError,
    PositionLimitExceededError,
)
from execution.contracts import (
    ExecutionOrder,
    ExecutionOrderSide,
    ExecutionOrderType,
)
from execution.fills import FillEvent


class SignalRouter:
    """Routes strategy signals to execution orders.

    Responsibilities:
    1. Validate incoming signals
    2. Detect and resolve conflicts between strategies
    3. Map valid signals to ExecutionOrder objects
    4. Submit orders via the execution service callback
    5. Track pending orders for cancellation support
    """

    def __init__(
        self,
        execution_callback: Optional[Callable[[str, ExecutionOrder], None]] = None,
    ):
        self._execution_callback = execution_callback
        self._lock = asyncio.Lock()
        self._pending_orders: Dict[str, Signal] = {}  # client_order_id -> Signal
        self._strategy_signals: Dict[str, List[datetime]] = {}  # strategy_id -> timestamps
        self._signal_window = timedelta(minutes=1)

    async def route_signal(
        self,
        signal: Signal,
        session_id: str,
        strategy_config: Optional[StrategyConfig] = None,
    ) -> SignalRoutingResult:
        """Route a signal through validation and order submission.

        Args:
            signal: The trading signal to route.
            session_id: The account/session ID for order submission.
            strategy_config: Optional config for position limit checks.

        Returns:
            SignalRoutingResult indicating success or failure.
        """
        # Step 1: Validate signal
        try:
            self._validate_signal(signal)
        except (InvalidSignalError, SignalValidationError) as e:
            return SignalRoutingResult(
                signal_id=signal.signal_id,
                routed=False,
                status="REJECTED",
                rejection_reason=str(e),
            )

        # Step 2: Check rate limits
        if strategy_config is not None:
            try:
                await self._check_rate_limit(signal, strategy_config)
            except SignalValidationError as e:
                return SignalRoutingResult(
                    signal_id=signal.signal_id,
                    routed=False,
                    status="REJECTED",
                    rejection_reason=str(e),
                )

        # Step 3: Check position limits
        if strategy_config is not None:
            try:
                self._check_position_limits(signal, strategy_config)
            except PositionLimitExceededError as e:
                return SignalRoutingResult(
                    signal_id=signal.signal_id,
                    routed=False,
                    status="REJECTED",
                    rejection_reason=str(e),
                )

        # Step 4: Map to ExecutionOrder
        try:
            order = self._map_signal_to_order(signal)
        except OrderMappingError as e:
            return SignalRoutingResult(
                signal_id=signal.signal_id,
                routed=False,
                status="ERROR",
                rejection_reason=str(e),
            )

        # Step 5: Submit via callback
        async with self._lock:
            self._pending_orders[order.client_order_id] = signal

            # Track for rate limiting
            if signal.strategy_id not in self._strategy_signals:
                self._strategy_signals[signal.strategy_id] = []
            self._strategy_signals[signal.strategy_id].append(signal.timestamp)

        if self._execution_callback is not None:
            try:
                await self._execution_callback(session_id, order)
            except Exception as e:
                async with self._lock:
                    self._pending_orders.pop(order.client_order_id, None)
                return SignalRoutingResult(
                    signal_id=signal.signal_id,
                    routed=False,
                    status="ERROR",
                    rejection_reason=f"Execution callback failed: {e}",
                )

        return SignalRoutingResult(
            signal_id=signal.signal_id,
            routed=True,
            client_order_id=order.client_order_id,
            status="ROUTED",
        )

    async def cancel_pending_for_strategy(self, strategy_id: str) -> int:
        """Cancel all pending orders for a strategy.

        Returns:
            Number of orders cancelled.
        """
        async with self._lock:
            to_cancel = [
                (cid, sig) for cid, sig in self._pending_orders.items()
                if sig.strategy_id == strategy_id
            ]
            count = len(to_cancel)
            for cid, _ in to_cancel:
                del self._pending_orders[cid]
            return count

    def _validate_signal(self, signal: Signal) -> None:
        """Validate a signal's fields."""
        if signal.quantity <= Decimal("0"):
            raise InvalidSignalError(f"Signal quantity must be positive, got {signal.quantity}")

        if not signal.instrument_token:
            raise InvalidSignalError("Signal instrument_token cannot be empty")

        if signal.action == SignalAction.HOLD:
            raise SignalValidationError("HOLD signals should not be routed")

        if signal.order_type == ExecutionOrderType.LIMIT and signal.limit_price is None:
            raise InvalidSignalError("LIMIT orders require limit_price")

        if signal.order_type in (ExecutionOrderType.SL, ExecutionOrderType.SL_M) and signal.trigger_price is None:
            raise InvalidSignalError(f"{signal.order_type.value} orders require trigger_price")

    async def _check_rate_limit(self, signal: Signal, config: StrategyConfig) -> None:
        """Check if strategy has exceeded orders per minute."""
        async with self._lock:
            now = signal.timestamp
            window_start = now - self._signal_window

            timestamps = self._strategy_signals.get(signal.strategy_id, [])
            recent = [t for t in timestamps if t > window_start]

            if len(recent) >= config.max_orders_per_minute:
                raise SignalValidationError(
                    f"Rate limit exceeded: {len(recent)} orders in the last minute "
                    f"(limit: {config.max_orders_per_minute})"
                )

            self._strategy_signals[signal.strategy_id] = recent

    def _check_position_limits(self, signal: Signal, config: StrategyConfig) -> None:
        """Check if signal would exceed strategy position limits."""
        if signal.quantity > config.max_position_quantity:
            raise PositionLimitExceededError(
                f"Signal quantity {signal.quantity} exceeds max_position_quantity "
                f"{config.max_position_quantity}"
            )

    def _map_signal_to_order(self, signal: Signal) -> ExecutionOrder:
        """Map a Signal to an ExecutionOrder.

        This is a 1:1 mapping as specified in the architecture.
        """
        client_order_id = f"{signal.strategy_id}_{signal.signal_id}_{uuid.uuid4().hex[:8]}"

        return ExecutionOrder(
            client_order_id=client_order_id,
            instrument_token=signal.instrument_token,
            side=signal.side,
            order_type=signal.order_type,
            quantity=signal.quantity,
            limit_price=signal.limit_price,
            trigger_price=signal.trigger_price,
            metadata={
                "signal_id": str(signal.signal_id),
                "strategy_id": signal.strategy_id,
                "action": signal.action.value,
                "reason": signal.reason,
            },
        )

    def detect_conflict(self, signals: List[Signal]) -> ConflictResolution:
        """Detect conflicts among a batch of signals.

        Basic conflict detection:
        - Opposing signals for same instrument from different strategies
        - Signals that would exceed some global limit

        Args:
            signals: List of signals to check.

        Returns:
            ConflictResolution indicating if/how to resolve.
        """
        if len(signals) <= 1:
            return ConflictResolution(has_conflict=False)

        # Group by instrument
        by_instrument: Dict[str, List[Signal]] = {}
        for sig in signals:
            by_instrument.setdefault(sig.instrument_token, []).append(sig)

        for instrument, instrument_signals in by_instrument.items():
            if len(instrument_signals) <= 1:
                continue

            # Check for opposing directions
            buys = [s for s in instrument_signals if s.side == ExecutionOrderSide.BUY]
            sells = [s for s in instrument_signals if s.side == ExecutionOrderSide.SELL]

            if buys and sells:
                # Opposing signals detected
                return ConflictResolution(
                    has_conflict=True,
                    conflict_reason=f"Opposing signals for {instrument}: "
                                   f"{len(buys)} BUY vs {len(sells)} SELL",
                    rejected_signals=instrument_signals,
                )

        return ConflictResolution(has_conflict=False)
