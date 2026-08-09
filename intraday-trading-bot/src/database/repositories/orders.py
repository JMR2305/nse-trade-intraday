"""Order repository."""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc

from src.database.models import Order


class OrderRepository:
    """Repository for orders table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, order_id: int) -> Optional[Order]:
        """Get order by internal ID."""
        result = await self._session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: str) -> Optional[Order]:
        """Get order by broker/paper order ID."""
        result = await self._session.execute(
            select(Order).where(Order.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Optional[Order]:
        """Get order by idempotency key."""
        result = await self._session.execute(
            select(Order).where(Order.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_session(self, session_id: str, status: Optional[str] = None) -> List[Order]:
        """Get orders for a session, optionally filtered by status."""
        query = select(Order).where(Order.session_id == session_id)
        if status:
            query = query.where(Order.status == status)
        query = query.order_by(desc(Order.created_at))
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_open_orders(self, session_id: str) -> List[Order]:
        """Get orders that are not complete/cancelled/rejected."""
        result = await self._session.execute(
            select(Order)
            .where(
                Order.session_id == session_id,
                Order.status.in_(["PENDING", "OPEN", "PARTIAL_FILL"]),
            )
            .order_by(desc(Order.created_at))
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> Order:
        """Create a new order."""
        order = Order(**kwargs)
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def update(self, order_pk: int, **kwargs) -> Optional[Order]:
        """Update order fields.

        Positional arg is the ROW primary key. Named `order_pk` (not
        `order_id`) because Order also has an `order_id` COLUMN (broker
        order id) that callers may pass in kwargs — a same-named parameter
        raised "got multiple values for argument 'order_id'".
        """
        kwargs["updated_at"] = datetime.now(timezone.utc)
        await self._session.execute(
            update(Order).where(Order.id == order_pk).values(**kwargs)
        )
        return await self.get_by_id(order_pk)

    async def update_status(self, order_id: int, status: str, message: Optional[str] = None) -> Optional[Order]:
        """Update order status."""
        kwargs = {"status": status}
        if message:
            kwargs["status_message"] = message
        return await self.update(order_id, **kwargs)
