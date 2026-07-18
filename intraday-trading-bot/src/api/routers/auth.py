"""Authentication endpoints for operators."""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status

from src.services.operator_auth_service import operator_auth_service
from src.core.exceptions import AuthenticationError
from src.api.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(user_id: str, password: str) -> Dict[str, Any]:
    """Login and get access token."""
    token = operator_auth_service.authenticate(user_id, password)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"access_token": token, "token_type": "bearer"}


@router.post("/register")
async def register(user_id: str, password: str, is_admin: bool = False) -> Dict[str, str]:
    """Register a new operator (dev only)."""
    operator_auth_service.register_user(user_id, password, is_admin)
    return {"status": "registered", "user_id": user_id}


@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Get current user info."""
    return {"user_id": user_id}
