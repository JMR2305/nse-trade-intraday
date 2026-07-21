"""StrategyFillTracker — per-strategy fill tracking via FillEventBus.

Subscribes to fill events and maintains per-strategy position state.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Dict, Optional, Callable
from datetime import datetime

from strategy.contracts import StrategyConfig
from execution.fills import FillEvent
from execution.portfolio import PositionSnapshot
from execution.contracts import ExecutionOrderSide
from risk.fill_event_bus import FillEventBus


class StrategyFillTracker:
    """Tracks fills for a single strategy and maintains virtual positions.

    Each strategy has its own fill tracker that subscribes to the
    global FillEventBus and filters for fills belonging to that strategy.
    """

    def __init__(self, config: StrategyConfig, fill_event_bus: FillEventBus):
        self._config = config
        self._bus = fill_event_bus
        self._lock = asyncio.Lock()
        self._positions: Dict[str, PositionSnapshot] = {}
        self._fill_count = 0
        self._realized_pnl = Decimal("0")
        self._callback: Optional[Callable[[FillEvent], None]] = None
        self._subscriber_id: Optional[str] = None

    @property
    def positions(self) -> Dict[str, PositionSnapshot]:
        """Copy of current virtual positions."""
        return dict(self._positions)

    @property
    def fill_count(self) -> int:
        """Number of fills processed."""
        return self._fill_count

    @property
    def realized_pnl(self) -> Decimal:
        """Cumulative realized P&L from tracked fills."""
        return self._realized_pnl

    async def subscribe(self, callback: Optional[Callable[[FillEvent], None]] = None) -> None:
        """Subscribe to fill events on the bus.

        Uses the real RC-8 FillEventBus async API:
          subscribe(name, callback) -> subscriber_id (str)
        The subscriber_id is stored for clean unsubscription.

        Args:
            callback: Optional callback to invoke on each fill.
        """
        self._callback = callback
        self._subscriber_id = await self._bus.subscribe(
            self._config.strategy_id, self._on_fill
        )

    async def unsubscribe(self) -> None:
        """Unsubscribe from fill events using the stored subscriber_id."""
        if self._subscriber_id is not None:
            await self._bus.unsubscribe(self._subscriber_id)
            self._subscriber_id = None

    async def _on_fill(self, fill_event: FillEvent) -> None:
        """Handle an incoming fill event.

        Must be async because FillSubscriber = Callable[[FillEvent], Awaitable[None]].
        Schedules the locking handler as a background task to avoid blocking the bus.
        """
        asyncio.create_task(self._handle_fill(fill_event))

    async def _handle_fill(self, fill_event: FillEvent) -> None:
        """Process fill with locking."""
        async with self._lock:
            self._fill_count += 1

            token = fill_event.instrument_token

            # Update or create position
            if token in self._positions:
                pos = self._positions[token]
                new_pos = self._update_position(pos, fill_event)
            else:
                new_pos = self._create_position(fill_event)

            if new_pos.net_quantity == Decimal("0"):
                # Flat position — remove from tracking
                del self._positions[token]
            else:
                self._positions[token] = new_pos

            # Notify callback if registered
            if self._callback is not None:
                self._callback(fill_event)

    def _create_position(self, fill_event: FillEvent) -> PositionSnapshot:
        """Create a new position from a fill."""
        if fill_event.side == ExecutionOrderSide.BUY:
            return PositionSnapshot(
                instrument_token=fill_event.instrument_token,
                net_quantity=fill_event.quantity,
                direction="LONG",
                average_buy_price=fill_event.price,
                total_buy_quantity=fill_event.quantity,
                total_buy_value=fill_event.price * fill_event.quantity,
                position_timestamp=fill_event.fill_timestamp,
            )
        else:
            return PositionSnapshot(
                instrument_token=fill_event.instrument_token,
                net_quantity=fill_event.quantity,
                direction="SHORT",
                average_sell_price=fill_event.price,
                total_sell_quantity=fill_event.quantity,
                total_sell_value=fill_event.price * fill_event.quantity,
                position_timestamp=fill_event.fill_timestamp,
            )

    def _update_position(
        self,
        pos: PositionSnapshot,
        fill_event: FillEvent,
    ) -> PositionSnapshot:
        """Update an existing position with a new fill."""
        if fill_event.side == ExecutionOrderSide.BUY:
            new_buy_qty = pos.total_buy_quantity + fill_event.quantity
            new_buy_val = pos.total_buy_value + (fill_event.price * fill_event.quantity)
            new_net = pos.net_quantity + fill_event.quantity

            avg_buy = new_buy_val / new_buy_qty if new_buy_qty > Decimal("0") else Decimal("0")
            direction: str = "LONG" if new_net > Decimal("0") else ("FLAT" if new_net == Decimal("0") else "SHORT")

            return PositionSnapshot(
                instrument_token=pos.instrument_token,
                net_quantity=new_net,
                direction=direction,
                average_buy_price=avg_buy,
                average_sell_price=pos.average_sell_price,
                total_buy_quantity=new_buy_qty,
                total_sell_quantity=pos.total_sell_quantity,
                total_buy_value=new_buy_val,
                total_sell_value=pos.total_sell_value,
                realized_pnl=pos.realized_pnl,
                position_timestamp=fill_event.fill_timestamp,
            )
        else:
            new_sell_qty = pos.total_sell_quantity + fill_event.quantity
            new_sell_val = pos.total_sell_value + (fill_event.price * fill_event.quantity)
            new_net = pos.net_quantity - fill_event.quantity

            avg_sell = new_sell_val / new_sell_qty if new_sell_qty > Decimal("0") else Decimal("0")
            direction = "LONG" if new_net > Decimal("0") else ("FLAT" if new_net == Decimal("0") else "SHORT")

            return PositionSnapshot(
                instrument_token=pos.instrument_token,
                net_quantity=new_net,
                direction=direction,
                average_buy_price=pos.average_buy_price,
                average_sell_price=avg_sell,
                total_buy_quantity=pos.total_buy_quantity,
                total_sell_quantity=new_sell_qty,
                total_buy_value=pos.total_buy_value,
                total_sell_value=new_sell_val,
                realized_pnl=pos.realized_pnl,
                position_timestamp=fill_event.fill_timestamp,
            )
