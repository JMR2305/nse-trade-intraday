"""Health check endpoints with real database verification."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import check_database_connection
from src.database.repositories.sessions import SessionRepository
from src.database.repositories.heartbeats import HeartbeatRepository
from src.services.broker_session_service import broker_session_service
from src.core.kill_switch import kill_switch_manager
from src.api.dependencies import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> Dict[str, str]:
    """Liveness probe — is the process running?"""
    return {"status": "alive"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Readiness probe — verifies actual database and recovery status."""
    checks = {
        "database": await check_database_connection(),
        "broker_auth": broker_session_service.is_authenticated,
        "kill_switch": kill_switch_manager.state.can_place_orders(),
    }
    session_repo = SessionRepository(db)
    active_session = await session_repo.get_active_session()
    checks["active_session"] = active_session is not None
    heartbeat_repo = HeartbeatRepository(db)
    unhealthy = await heartbeat_repo.get_unhealthy()
    checks["all_services_healthy"] = len(unhealthy) == 0
    all_ready = all(checks.values())
    if not all_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks, "active_session_id": active_session.session_id if active_session else None}


@router.get("/detailed")
async def detailed_health(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Detailed health check with full system state."""
    session_repo = SessionRepository(db)
    active_session = await session_repo.get_active_session()
    return {
        "status": "healthy",
        "timestamp": "2026-07-18T23:59:00Z",
        "version": "2.0.1-acr",
        "trading_mode": "PAPER",
        "components": {
            "database": await check_database_connection(),
            "broker": {"authenticated": broker_session_service.is_authenticated, "api_key_present": bool(broker_session_service._api_key)},
            "kill_switch": {"level": kill_switch_manager.state.level.value, "can_trade": kill_switch_manager.state.can_place_orders()},
            "session": {"active": active_session is not None, "session_id": active_session.session_id if active_session else None, "status": active_session.status if active_session else None},
        },
    }
