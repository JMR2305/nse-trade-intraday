"""
Fill Event Bus — pub/sub delivery of fill events to risk state and other subscribers.

The FillEventBus decouples the execution engine from risk state updates.
After a fill, the execution layer publishes a FillEvent; the risk engine
subscribes to update daily P&L, turnover, and peak equity.

All delivery is in-process (asyncio tasks). Cross-process or persistent
delivery is outside scope.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

from .exceptions import FillDeliveryError

logger = logging.getLogger(__name__)


@dataclass
class FillEvent:
    """Immutable record of a fill (trade execution) event.

    Published after every successful order fill.
    """

    fill_id: str
    account_id: str
    instrument_token: str
    side: str                       # "BUY" | "SELL"
    quantity: Decimal
    fill_price: Decimal
    realized_pnl: Decimal           # May be zero for entry fills
    turnover: Decimal               # abs(quantity * fill_price)
    current_equity: Decimal         # Portfolio equity after fill
    fill_timestamp: datetime

    # Optional metadata
    order_id: Optional[str] = None
    broker_fill_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


FillSubscriber = Callable[[FillEvent], Awaitable[None]]


class FillEventBus:
    """Asynchronous pub/sub bus for fill events.

    Subscribers are async callables that receive FillEvent objects.
    Delivery is sequential within a single publish call to maintain
    ordering guarantees required by the risk engine.

    Thread-safe: asyncio.Lock protects the subscriber list.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, FillSubscriber] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._delivered_fills: Dict[str, int] = {}  # fill_id -> delivery count

    async def subscribe(self, name: str, callback: FillSubscriber) -> str:
        """Register a subscriber.

        Args:
            name: Human-readable subscriber name (for logging).
            callback: Async callable that receives FillEvent.

        Returns:
            Subscriber ID (use to unsubscribe).
        """
        subscriber_id = f"{name}:{uuid4().hex[:8]}"
        async with self._lock:
            self._subscribers[subscriber_id] = callback
        logger.debug(f"FillEventBus: subscribed {subscriber_id!r}")
        return subscriber_id

    async def unsubscribe(self, subscriber_id: str) -> bool:
        """Remove a subscriber.

        Args:
            subscriber_id: ID returned by subscribe().

        Returns:
            True if the subscriber was found and removed, False otherwise.
        """
        async with self._lock:
            if subscriber_id in self._subscribers:
                del self._subscribers[subscriber_id]
                logger.debug(f"FillEventBus: unsubscribed {subscriber_id!r}")
                return True
        return False

    async def publish(self, event: FillEvent) -> int:
        """Publish a fill event to all subscribers.

        Delivery is sequential. If any subscriber raises, a FillDeliveryError
        is raised after attempting delivery to remaining subscribers (best-effort).

        Args:
            event: The fill event to publish.

        Returns:
            Number of subscribers notified.

        Raises:
            FillDeliveryError: If any subscriber failed to process the event.
        """
        async with self._lock:
            subscribers = dict(self._subscribers)

        errors: List[str] = []
        notified = 0

        for subscriber_id, callback in subscribers.items():
            try:
                await callback(event)
                notified += 1
            except Exception as exc:
                errors.append(f"{subscriber_id}: {exc}")
                logger.error(
                    f"FillEventBus delivery error for subscriber {subscriber_id!r}: {exc}",
                    exc_info=True,
                )

        # Track delivery count for observability
        self._delivered_fills[event.fill_id] = (
            self._delivered_fills.get(event.fill_id, 0) + notified
        )

        if errors:
            raise FillDeliveryError(
                fill_id=event.fill_id,
                reason="; ".join(errors),
            )

        logger.debug(
            f"FillEventBus: published fill_id={event.fill_id!r} "
            f"to {notified} subscriber(s)"
        )
        return notified

    async def publish_nowait(self, event: FillEvent) -> None:
        """Publish a fill event in the background (fire-and-forget).

        Does NOT raise on subscriber failures — errors are logged only.
        Use when the caller cannot await delivery.
        """
        try:
            await self.publish(event)
        except FillDeliveryError as exc:
            logger.warning(f"Background fill delivery error: {exc}")

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered subscribers."""
        return len(self._subscribers)

    def get_delivery_count(self, fill_id: str) -> int:
        """Return how many times a fill was successfully delivered."""
        return self._delivered_fills.get(fill_id, 0)

    @classmethod
    def build_fill_event(
        cls,
        fill_id: str,
        account_id: str,
        instrument_token: str,
        side: str,
        quantity: Decimal,
        fill_price: Decimal,
        current_equity: Decimal,
        fill_timestamp: Optional[datetime] = None,
        realized_pnl: Optional[Decimal] = None,
        order_id: Optional[str] = None,
        broker_fill_id: Optional[str] = None,
    ) -> FillEvent:
        """Factory helper to build a FillEvent with computed turnover."""
        if not isinstance(quantity, Decimal):
            quantity = Decimal(str(quantity))
        if not isinstance(fill_price, Decimal):
            fill_price = Decimal(str(fill_price))
        if not isinstance(current_equity, Decimal):
            current_equity = Decimal(str(current_equity))
        if realized_pnl is None:
            realized_pnl = Decimal("0")
        elif not isinstance(realized_pnl, Decimal):
            realized_pnl = Decimal(str(realized_pnl))

        turnover = abs(quantity * fill_price)
        ts = fill_timestamp or datetime.now(timezone.utc)

        return FillEvent(
            fill_id=fill_id,
            account_id=account_id,
            instrument_token=str(instrument_token),
            side=side.upper(),
            quantity=quantity,
            fill_price=fill_price,
            realized_pnl=realized_pnl,
            turnover=turnover,
            current_equity=current_equity,
            fill_timestamp=ts,
            order_id=order_id,
            broker_fill_id=broker_fill_id,
        )
