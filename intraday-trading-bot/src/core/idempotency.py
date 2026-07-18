"""Idempotency key generation and validation using database."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.core.config import settings
from src.core.logging import logger


class IdempotencyManager:
    """Manages idempotency keys using database storage."""

    def __init__(self, repository=None) -> None:
        self._repository = repository
        self.ttl_seconds = settings.idempotency.key_ttl_seconds

    def generate_key(self, operation: str, entity_type: str, entity_id: str) -> str:
        """Generate a deterministic idempotency key."""
        raw = f"{operation}:{entity_type}:{entity_id}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def generate_uuid_key(self) -> str:
        """Generate a random UUID-based idempotency key."""
        return str(uuid.uuid4())

    async def check_and_store(self, key: str, operation: str) -> bool:
        """
        Check if key exists. If not, store it.
        Returns True if key is new (operation should proceed).
        Returns False if key exists (operation already done).
        """
        if not self._repository:
            logger.warning("No idempotency repository configured, allowing operation")
            return True

        existing = await self._repository.get_by_key(key)
        if existing:
            logger.info(f"Idempotency key already exists: {key}")
            return False

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        await self._repository.create(key=key, operation=operation, expires_at=expires_at)
        logger.info(f"Idempotency key stored: {key}")
        return True

    async def is_duplicate(self, key: str) -> bool:
        """Check if key already exists (without storing)."""
        if not self._repository:
            return False
        existing = await self._repository.get_by_key(key)
        return existing is not None

    def get_key(self, operation: str, **kwargs) -> str:
        """Convenience method to generate key from kwargs."""
        entity_type = kwargs.get("entity_type", "unknown")
        entity_id = kwargs.get("entity_id", str(uuid.uuid4()))
        return self.generate_key(operation, entity_type, entity_id)
