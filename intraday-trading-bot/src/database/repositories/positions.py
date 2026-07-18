"""Position repository."""

from typing import Optional, List
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.database.models import Position


class PositionRepository:
    """Repository for positions table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by internal ID."""
        result = await self._session.execute(
            select(Position).where(Position.id == position_id)
        )
        return result.scalar_one_or_none()

    async def get_by_session_and_instrument(
        self, session_id: str, instrument_token: int
    ) -> Optional[Position]:
        """Get open position for session + instrument."""
        result = await self._session.execute(
            select(Position).where(
                Position.session_id == session_id,
                Position.instrument_token == instrument_token,
                Position.is_open == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_open_positions(self, session_id: str) -> List[Position]:
        """Get all open positions for a session."""
        result = await self._session.execute(
            select(Position).where(
                Position.session_id == session_id,
                Position.is_open == True,
            )
        )
        return list(result.scalars().all())

    async def get_all_positions(self, session_id: str) -> List[Position]:
        """Get all positions for a session."""
        result = await self._session.execute(
            select(Position).where(Position.session_id == session_id)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> Position:
        """Create a new position."""
        position = Position(**kwargs)
        self._session.add(position)
        await self._session.flush()
        await self._session.refresh(position)
        return position

    async def update(self, position_id: int, **kwargs) -> Optional[Position]:
        """Update position fields."""
        kwargs["updated_at"] = datetime.now(timezone.utc)
        await self._session.execute(
            update(Position).where(Position.id == position_id).values(**kwargs)
        )
        return await self.get_by_id(position_id)

    async def close_position(
        self, position_id: int, exit_price: Decimal, realized_pnl: Decimal
    ) -> Optional[Position]:
        """Close a position with exit details."""
        return await self.update(
            position_id,
            is_open=False,
            last_price=exit_price,
            realized_pnl=realized_pnl,
            unrealized_pnl=Decimal("0"),
            closed_at=datetime.now(timezone.utc),
        )

    async def add_to_position(
        self, position_id: int, additional_qty: int, new_price: Decimal
    ) -> Optional[Position]:
        """Add quantity to existing position (average price update)."""
        position = await self.get_by_id(position_id)
        if not position:
            return None

        total_value = (position.quantity * position.average_price) + (additional_qty * new_price)
        new_quantity = position.quantity + additional_qty
        new_avg = total_value / new_quantity if new_quantity > 0 else Decimal("0")

        return await self.update(
            position_id,
            quantity=new_quantity,
            average_price=new_avg,
        )
