"""Fill repository."""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from decimal import Decimal

from src.database.models import Fill


class FillRepository:
    """Repository for fills table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, fill_id: int) -> Optional[Fill]:
        """Get fill by internal ID."""
        result = await self._session.execute(
            select(Fill).where(Fill.id == fill_id)
        )
        return result.scalar_one_or_none()

    async def get_by_order(self, order_id: int) -> List[Fill]:
        """Get all fills for an order."""
        result = await self._session.execute(
            select(Fill).where(Fill.order_id == order_id).order_by(Fill.created_at)
        )
        return list(result.scalars().all())

    async def get_total_filled_quantity(self, order_id: int) -> int:
        """Get total filled quantity for an order."""
        result = await self._session.execute(
            select(func.sum(Fill.quantity)).where(Fill.order_id == order_id)
        )
        total = result.scalar()
        return total or 0

    async def get_total_cost(self, order_id: int) -> Decimal:
        """Get total cost for an order."""
        result = await self._session.execute(
            select(func.sum(Fill.total_cost)).where(Fill.order_id == order_id)
        )
        total = result.scalar()
        return total or Decimal("0")

    async def create(self, **kwargs) -> Fill:
        """Create a new fill."""
        fill = Fill(**kwargs)
        self._session.add(fill)
        await self._session.flush()
        await self._session.refresh(fill)
        return fill
