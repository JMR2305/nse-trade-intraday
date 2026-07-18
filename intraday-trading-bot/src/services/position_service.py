"""Position service — manages open positions and P&L."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.database.repositories.positions import PositionRepository
from src.database.models import Position


class PositionService:
    """Manages position lifecycle: open, add, reduce, close."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._repo = PositionRepository(db_session)

    async def update_position_from_fill(self, session_id: str, instrument_token: int, side: str,
                                        quantity: int, price: Decimal) -> Position:
        existing = await self._repo.get_by_session_and_instrument(session_id, instrument_token)
        if existing and existing.side == side:
            updated = await self._repo.add_to_position(existing.id, quantity, price)
            logger.info(f"Added to position: {existing.id} +{quantity} @ {price}", extra={"event_type": "POSITION_ADDED", "position_id": existing.id})
            return updated
        if existing and existing.side != side:
            if quantity >= existing.quantity:
                realized_pnl = self._calculate_pnl(existing.side, existing.quantity, existing.average_price, price)
                closed = await self._repo.close_position(existing.id, price, realized_pnl)
                remaining = quantity - existing.quantity
                if remaining > 0:
                    new_pos = await self._repo.create(session_id=session_id, instrument_token=instrument_token, side=side,
                                                        quantity=remaining, average_price=price, last_price=price, is_open=True)
                    return new_pos
                return closed
            else:
                new_qty = existing.quantity - quantity
                realized_pnl = self._calculate_pnl(existing.side, quantity, existing.average_price, price)
                await self._repo.update(existing.id, quantity=new_qty, last_price=price, realized_pnl=existing.realized_pnl + realized_pnl)
                return await self._repo.get_by_id(existing.id)
        position = await self._repo.create(session_id=session_id, instrument_token=instrument_token, side=side,
                                             quantity=quantity, average_price=price, last_price=price, is_open=True)
        logger.info(f"New position opened: {position.id}", extra={"event_type": "POSITION_OPENED", "position_id": position.id})
        return position

    def _calculate_pnl(self, side: str, quantity: int, entry_price: Decimal, exit_price: Decimal) -> Decimal:
        if side == "BUY":
            return (exit_price - entry_price) * quantity
        else:
            return (entry_price - exit_price) * quantity

    async def get_open_positions(self, session_id: str) -> List[Position]:
        return await self._repo.get_open_positions(session_id)

    async def get_position_summary(self, session_id: str) -> Dict[str, Any]:
        positions = await self._repo.get_open_positions(session_id)
        total_unrealized = sum(p.unrealized_pnl for p in positions)
        total_realized = sum(p.realized_pnl for p in positions)
        return {
            "open_positions": len(positions),
            "total_unrealized_pnl": float(total_unrealized),
            "total_realized_pnl": float(total_realized),
            "positions": [{"id": p.id, "instrument_token": p.instrument_token, "side": p.side, "quantity": p.quantity,
                           "average_price": float(p.average_price), "last_price": float(p.last_price) if p.last_price else None,
                           "unrealized_pnl": float(p.unrealized_pnl)} for p in positions],
        }
