"""Session management endpoints."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.services.session_service import SessionService
from src.core.exceptions import SessionError

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/start")
async def start_session(recovery_mode: str = "auto", db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Start a new trading session (idempotent)."""
    service = SessionService(db)
    session = await service.start_session(recovery_mode=recovery_mode, created_by=user_id)
    return {"session_id": session.session_id, "status": session.status, "trading_mode": session.trading_mode, "started_at": session.started_at.isoformat() if session.started_at else None}


@router.post("/end")
async def end_session(session_id: str, mode: str = "graceful", db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """End a trading session."""
    service = SessionService(db)
    try:
        session = await service.end_session(session_id, mode=mode)
        return {"session_id": session_id, "status": "ended", "mode": mode}
    except SessionError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/active")
async def get_active_session(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Get currently active session."""
    service = SessionService(db)
    session = await service.get_active_session()
    if not session:
        return {"active": False}
    return {"active": True, "session_id": session.session_id, "status": session.status, "trading_mode": session.trading_mode}


@router.get("/{session_id}/state")
async def get_session_state(session_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Get full session state."""
    service = SessionService(db)
    try:
        state = await service.get_session_state(session_id)
        return state
    except SessionError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
