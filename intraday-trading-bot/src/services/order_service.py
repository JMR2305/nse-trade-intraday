"""Order service — handles order lifecycle with validation and persistence."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.core.kill_switch import kill_switch_manager
from src.core.exceptions import KillSwitchError, OrderValidationError, IdempotencyError
from src.database.repositories.orders import OrderRepository
from src.database.models import Order, OrderEvent


class OrderService:
    """Handles order creation, validation, status updates, and event logging."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._order_repo = OrderRepository(db_session)

    async def create_order(self, session_id: str, instrument_token: int, side: str, order_type: str,
                           quantity: int, price: Optional[Decimal] = None, trigger_price: Optional[Decimal] = None,
                           stop_loss: Optional[Decimal] = None, target: Optional[Decimal] = None,
                           idempotency_key: str = "", created_by: str = "system") -> Order:
        if not kill_switch_manager.state.can_place_orders():
            raise KillSwitchError(f"Trading paused: {kill_switch_manager.state.level.value}")
        if quantity <= 0:
            raise OrderValidationError("Quantity must be positive")
        if order_type != "MARKET" and price is None:
            raise OrderValidationError("Price required for non-market orders")
        if stop_loss is not None and stop_loss <= 0:
            raise OrderValidationError("Stop loss must be positive")
        if target is not None and target <= 0:
            raise OrderValidationError("Target must be positive")
        if idempotency_key:
            existing = await self._order_repo.get_by_idempotency_key(idempotency_key)
            if existing:
                raise IdempotencyError(f"Order with idempotency key {idempotency_key} already exists")

        order = await self._order_repo.create(
            session_id=session_id, instrument_token=instrument_token, side=side, order_type=order_type,
            product="MIS", quantity=quantity, price=price, trigger_price=trigger_price,
            stop_loss=stop_loss, target=target, status="PENDING",
            idempotency_key=idempotency_key or f"auto_{datetime.now(timezone.utc).timestamp()}",
            created_by=created_by,
        )
        await self._log_event(order.id, "CREATED", {"session_id": session_id, "side": side, "quantity": quantity, "price": str(price) if price else None})
        logger.info(f"Order created: {order.id}", extra={"event_type": "ORDER_CREATED", "order_id": order.id, "session_id": session_id, "side": side, "quantity": quantity})
        return order

    async def update_order_status(self, order_id: int, status: str, message: Optional[str] = None,
                                  broker_order_id: Optional[str] = None) -> Order:
        kwargs = {"status": status}
        if broker_order_id:
            kwargs["order_id"] = broker_order_id
        if message:
            kwargs["status_message"] = message
        order = await self._order_repo.update(order_id, **kwargs)
        if not order:
            raise OrderValidationError(f"Order not found: {order_id}")
        await self._log_event(order_id, f"STATUS_{status}", {"status": status, "message": message, "broker_order_id": broker_order_id})
        return order

    async def get_session_orders(self, session_id: str) -> List[Order]:
        return await self._order_repo.get_by_session(session_id)

    async def get_open_orders(self, session_id: str) -> List[Order]:
        return await self._order_repo.get_open_orders(session_id)

    async def _log_event(self, order_id: int, event_type: str, data: Dict[str, Any]) -> None:
        event = OrderEvent(order_id=order_id, event_type=event_type, event_data=data)
        self._db.add(event)
        await self._db.flush()
