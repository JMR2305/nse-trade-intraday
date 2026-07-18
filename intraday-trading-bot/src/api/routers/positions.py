"""Position management endpoints."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.services.position_service import PositionService
from src.services.session_service import SessionService

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/")
async def get_positions(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Get all open positions for active session."""
    session_service = SessionService(db)
    session = await session_service.get_active_session()
    if not session:
        return {"positions": []}
    position_service = PositionService(db)
    summary = await position_service.get_position_summary(session.session_id)
    return summary


@router.get("/{position_id}")
async def get_position(position_id: int, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Get specific position details."""
    position_service = PositionService(db)
    position = await position_service._repo.get_by_id(position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"id": position.id, "instrument_token": position.instrument_token, "side": position.side, "quantity": position.quantity,
            "average_price": float(position.average_price), "last_price": float(position.last_price) if position.last_price else None,
            "unrealized_pnl": float(position.unrealized_pnl), "realized_pnl": float(position.realized_pnl), "is_open": position.is_open}
