"""Broker session service — manages Zerodha OAuth, separate from operator auth."""

from typing import Optional, Dict, Any

from src.core.config import settings
from src.core.logging import logger
from src.core.exceptions import AuthenticationError


class BrokerSessionService:
    """Manages Zerodha broker session authentication."""

    def __init__(self) -> None:
        self._api_key = settings.zerodha_api_key
        self._api_secret = settings.zerodha_api_secret
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._user_id: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    @property
    def access_token(self) -> Optional[str]:
        return self._access_token

    def get_login_url(self) -> str:
        if not self._api_key:
            raise AuthenticationError("ZERODHA_API_KEY not configured")
        return f"https://kite.zerodha.com/connect/login?api_key={self._api_key}&v=3"

    async def generate_session(self, request_token: str) -> Dict[str, Any]:
        if not self._api_key or not self._api_secret:
            raise AuthenticationError("Zerodha credentials not configured")
        logger.warning("Broker session generation is a placeholder", extra={"event_type": "BROKER_SESSION_PLACEHOLDER"})
        self._access_token = "mock_access_token"
        self._user_id = "mock_user"
        return {"access_token": self._access_token, "user_id": self._user_id, "login_time": "2026-07-18T09:15:00Z"}

    async def invalidate_session(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._user_id = None
        logger.info("Broker session invalidated", extra={"event_type": "BROKER_SESSION_INVALIDATED"})

    async def refresh_access_token(self) -> Optional[str]:
        if not self._refresh_token:
            return None
        return self._access_token


broker_session_service = BrokerSessionService()
