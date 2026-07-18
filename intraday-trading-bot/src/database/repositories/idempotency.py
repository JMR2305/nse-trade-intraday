"""Idempotency record repository."""

from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from src.database.models import IdempotencyRecord


class IdempotencyRepository:
    """Repository for idempotency_records table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, key: str) -> Optional[IdempotencyRecord]:
        """Get idempotency record by key."""
        result = await self._session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )
        return result.scalar_one_or_none()

    async def create(self, key: str, operation: str, expires_at: datetime) -> IdempotencyRecord:
        """Create a new idempotency record."""
        record = IdempotencyRecord(
            key=key,
            operation=operation,
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def is_duplicate(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        result = await self._session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == key,
                IdempotencyRecord.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none() is not None

    async def cleanup_expired(self) -> int:
        """Delete expired idempotency records. Returns count deleted."""
        result = await self._session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.expires_at <= datetime.now(timezone.utc)
            )
        )
        await self._session.flush()
        return result.rowcount
