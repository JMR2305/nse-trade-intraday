"""Operator authentication service — separate from broker auth."""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.config import settings
from src.core.exceptions import AuthenticationError, AuthorizationError
from src.core.logging import logger

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class OperatorAuthService:
    """Handles operator authentication for the application/API."""

    def __init__(self) -> None:
        self._secret_key = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._access_ttl = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
        self._refresh_ttl = timedelta(days=settings.jwt_refresh_token_ttl_days)
        self._users: Dict[str, Dict[str, Any]] = {}

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def create_access_token(self, user_id: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
        now = datetime.now(timezone.utc)
        expires = now + self._access_ttl
        payload = {"sub": user_id, "exp": expires, "iat": now, "type": "access"}
        if extra_claims:
            payload.update(extra_claims)
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        logger.info(f"Access token created for {user_id}", extra={"event_type": "AUTH_TOKEN_CREATED", "user_id": user_id})
        return token

    def create_refresh_token(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        expires = now + self._refresh_ttl
        payload = {"sub": user_id, "exp": expires, "iat": now, "type": "refresh"}
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def decode_token(self, token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return payload
        except JWTError as e:
            raise AuthenticationError(f"Invalid token: {e}")

    def verify_token(self, token: str) -> Dict[str, Any]:
        payload = self.decode_token(token)
        token_type = payload.get("type")
        if token_type != "access":
            raise AuthenticationError(f"Invalid token type: {token_type}")
        return payload

    def get_current_user(self, token: str) -> str:
        payload = self.verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Token missing subject")
        return user_id

    def register_user(self, user_id: str, password: str, is_admin: bool = False) -> None:
        self._users[user_id] = {
            "hashed_password": self.hash_password(password),
            "is_admin": is_admin,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def authenticate(self, user_id: str, password: str) -> Optional[str]:
        user = self._users.get(user_id)
        if not user:
            return None
        if not self.verify_password(password, user["hashed_password"]):
            return None
        return self.create_access_token(user_id)


operator_auth_service = OperatorAuthService()
