"""Risk management endpoints."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.services.risk_service import RiskService
from src.services.session_service import SessionService
from src.core.kill_switch import kill_switch_manager, KillSwitchLevel

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/status")
async def get_risk_status(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Get current risk status."""
    session_service = SessionService(db)
    session = await session_service.get_active_session()
    if not session:
        return {"error": "No active session"}
    risk_service = RiskService(db)
    portfolio_risk = await risk_service.check_portfolio_risk(session.session_id)
    return {"kill_switch": {"level": kill_switch_manager.state.level.value, "can_trade": kill_switch_manager.state.can_place_orders(), "reason": kill_switch_manager.state.reason}, "portfolio": portfolio_risk}


@router.post("/kill_switch")
async def trigger_kill_switch(level: str, reason: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Manually trigger or reset kill switch."""
    if level == "RESET":
        kill_switch_manager.reset(reason, triggered_by=user_id)
        return {"status": "reset", "level": "NORMAL", "reason": reason}
    try:
        ks_level = KillSwitchLevel[level.upper()]
        kill_switch_manager.escalate(ks_level, reason, triggered_by=user_id)
        return {"status": "escalated", "level": ks_level.value, "reason": reason, "triggered_by": user_id}
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid level. Use: PAUSE, CANCEL_PENDING, FLATTEN_ALL, RESET")
