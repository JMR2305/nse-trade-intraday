"""FastAPI dependency injection."""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db_session
from src.services.operator_auth_service import operator_auth_service
from src.core.exceptions import AuthenticationError

security = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async for session in get_db_session():
        yield session


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    try:
        user_id = operator_auth_service.get_current_user(token)
        return user_id
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")


async def require_admin(user_id: str = Depends(get_current_user)) -> str:
    """Require admin privileges."""
    return user_id
